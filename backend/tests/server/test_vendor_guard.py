#!/usr/bin/env python3
"""响应守卫：普通用户能调到的接口，响应里没有厂商或模型名、没有禁止的字段（视频地址、计费快照、厂商与档位名等）。
用真实的厂商名注册桩（名字是真的、行为是假的），再往会话文件里投毒（带厂商词的错误原文、签名地址、用量、旧错误代码），
逐个接口检查；最后核对路由清单：新增接口必须登记进守卫（调用它，或写明豁免理由）。
全程临时数据目录 + 桩，不联网、不花钱。用法: python3 tests/server/test_vendor_guard.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前

import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "minimax"      # 用真实的厂商名注册桩：守卫要在最像线上的条件下查
os.environ["STORYBOARD_TTS_PROVIDER"] = "volc"
os.environ["MINIMAX_API_KEY"] = "k-test-not-real"        # 假值，只为让档位表把它当成已配置；桩不联网
os.environ.pop("ARK_API_KEY", None)
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
import re  # noqa: E402
from render import mix as render_mix, plan as render_plan, providers, session as render_session, tiers  # noqa: E402
from render.providers.fake import FakeTts, FakeVideo  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402
from server import public as P  # noqa: E402


class StubMiniMax(FakeVideo):
    name = "minimax"
    default_model = "minimax-h3"

    def __init__(self):
        super().__init__(polls_to_finish=1)
        self.models = {k: {"label": f"MiniMax {k}"} for k in ("minimax-h3", "minimax-h3-highspeed", "minimax-h3-lite")}


class StubVolc(FakeTts):
    name = "volc"


VIDEO = StubMiniMax()
providers.register("minimax", lambda: VIDEO)
providers.register_tts("volc", lambda: StubVolc())
FORBIDDEN_KEYS = ("video_url", "last_frame_url", "billing", "known_cost_cny", "provider", "providers", "models", "default_note")
# usage 不在禁止名单里：转换清单的尝试记录里有同名的用量字段（合法）。出片尝试里的 usage 在第 5 步单独断言。
DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))
SEEN_ROUTES: set = set()      # (方法, 路径模板)：clean 按实际请求的方法登记
TASK_KEY = re.compile(r"t[0-9a-f]{16}")
RT = "/novels/{nid}/chapters/{cid}/versions/{vid}/render"




def _blank(v, path):
    """扫词前把用户内容字段的字符串值换成空串：只按明确的字段路径（$.a.b[].c，[] 是列表里每一项），
    键名与结构保留，路径上必须真的是字符串（形状变了就报错，不会静默放过）。"""
    return _blank_walk(v, path.split("."), 1)


def _blank_walk(v, parts, i):
    if i == len(parts):
        assert isinstance(v, str), ("豁免路径上应是字符串", parts, v)
        return ""
    part = parts[i]
    many = part.endswith("[]")
    key = part[:-2] if many else part
    assert isinstance(v, dict) and key in v, ("豁免路径不存在", parts, part)
    out = dict(v)
    child = v[key]
    if many:
        assert isinstance(child, list), ("豁免路径上应是列表", parts, part)
        out[key] = [_blank_walk(x, parts, i + 1) for x in child]
    else:
        out[key] = _blank_walk(child, parts, i + 1)
    return out


def _pieces(v):
    """请求体里的所有值（含整体与各层子值）。"""
    out = [v]
    if isinstance(v, dict):
        for x in v.values():
            out += _pieces(x)
    elif isinstance(v, list):
        for x in v:
            out += _pieces(x)
    return out


def _echo_free(body, sent):
    """422 会把请求里的输入（整体或其中某个值）回显进 input 字段；只去掉能证明来自请求的那些，其余照扫。"""
    if isinstance(body, dict):
        return {k: _echo_free(x, sent) for k, x in body.items() if not (k == "input" and x in _pieces(sent))}
    if isinstance(body, list):
        return [_echo_free(x, sent) for x in body]
    return body


def clean(label, resp, status, *, route, user_fields=(), models_at=None, sent=None):
    """响应状态码精确等于 status；整份响应没有厂商词（user_fields：这几条字段路径上的用户字符串值先清空再扫，键名与结构仍检查）、没有禁止的键；
    登记 (方法, 路径模板)。models_at：{字段路径: 允许的取值}，只有这些位置的 model 字符串放行。"""
    assert resp.status_code == status, (label, resp.status_code, status, resp.text[:300])
    body = resp.json()
    scan = body
    for path in user_fields:
        scan = _blank(scan, path)
    if sent is not None:
        scan = _echo_free(scan, sent)
    assert not P.find_vendor_words(scan), (label, P.find_vendor_words(scan))
    models_at = models_at or {}

    def walk(v, path="$"):
        if isinstance(v, dict):
            for k, x in v.items():
                assert k not in FORBIDDEN_KEYS, (label, f"{path}.{k}")
                if k == "model" and isinstance(x, str):
                    assert x in models_at.get(f"{path}.model", ()), (label, f"{path}.model", x)
                walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
    walk(scan if sent is None else _echo_free(body, sent))
    SEEN_ROUTES.add((resp.request.method, route))
    return body


def film_shape(label, body):
    """会话视图的形状：clips / free / orphaned 三个容器里都有带毒的非空尝试，逐个断言白名单、短键与错误归一。"""
    allowed = set(P.ATTEMPT_KEYS) | {"task_id", "error", "error_msg"}
    for cont in ("clips", "free", "orphaned"):
        atts = [(h["id"], at) for h in body[cont] for at in h["attempts"]]
        assert len(atts) >= 2, (label, cont, "带毒的尝试应还在", len(atts))
        for hid, at in atts:
            assert set(at) <= allowed, (label, cont, hid, sorted(set(at) - allowed))
            assert at["task_id"] is None or TASK_KEY.fullmatch(at["task_id"]), (label, cont, at["task_id"])
        rej = [at for _h, at in atts if (at.get("error_msg") or {}).get("code")]
        assert rej and all(at["error_msg"]["code"] == "film.vendor.rejected" for at in rej), (label, cont, rej)
    assert "tier" in body and "provider" not in body and "model" not in body, label
    byid = {c["id"]: c for c in body["clips"]}
    if byid[D]["state"] == "failed":
        assert byid[D]["error_msg"]["code"] == "film.vendor.balance", (label, byid[D]["error_msg"])
    if byid[E]["state"] == "failed":
        assert byid[E]["error_msg"]["code"] == "common.failed_generic", (label, byid[E]["error_msg"])
    SEEN_FILM.add(label)


def drain(limit=400):
    runner = app_mod._render_runner
    for _ in range(limit):
        if not runner.watching():
            return
        runner.tick()
    raise AssertionError("出片线程没跑完")


def pick(s, iid):
    return next(x for x in s["clips"] + s["free"] if x["id"] == iid)


SIGN = "https://x.volces.com/v.mp4?X-Tos-Signature=zz"
A = D = E = None
SEEN_FILM: set = set()
REAL: dict = {}


def bad_attempts(tag):
    """两次带毒的尝试：被拒（带厂商原话、签名地址、计费快照、用量、一个服务端以后可能新增的字段）；迟到成功。"""
    return [
        {"task_id": f"cgt-{tag}-1", "state": "failed", "video_url": SIGN, "last_frame_url": SIGN,
         "usage": {"model": "doubao-seedance-2-0"}, "vendor_note": "MiniMax internal",
         "billing": {"provider": "minimax", "model": "minimax-h3", "resolution": "768P", "duration": 5, "estimate_cny": 2.5},
         "known_cost_cny": 2.5, "cost_cny": 0,
         "error_msg": {"code": "film.provider.rejected", "params": {"detail": {"t": "vendor", "text": "MiniMax: prompt rejected"}}},
         "error": "MiniMax: prompt rejected"},
        {"task_id": f"cgt-doubao-seedance-{tag}", "state": "succeeded", "late": True, "settled_at": render_session._now(),
         "cost_cny": 1.0, "video_url": SIGN, "vendor_note": "Seedance"},
    ]


def poison(root):
    """把带厂商词的原始数据写进会话文件（可重复调用：每次把这几处重置成同样的带毒状态）。"""
    now = render_session._now()
    with render_session.mutate(root) as s:
        byid = {x["id"]: x for x in s["clips"]}
        a, d, e = byid[A], byid[D], byid[E]
        d.update(state="failed", error="视频服务（MiniMax）账户余额不足，暂时无法出片，请联系管理员",
                 error_msg={"code": "film.minimax.insufficient_balance", "params": {}}, ended_at=now, ended_as="failed")
        e.update(state="failed", error="KeyError: 'video_url' Seedance sk-live-12345 " + SIGN, error_msg=None,
                 ended_at=now, ended_as="failed")
        a["attempts"] = [REAL["clip"]] + bad_attempts("c")
        f1 = next(n for n in s["free"] if n["id"] == "F01")
        f1["attempts"] = [REAL["free"]] + bad_attempts("f")
        s["orphaned"] = [{"id": "E77-C77", "shots": [], "attempts": bad_attempts("o"), "chosen": None}]
        s["final"] = {"state": "failed", "started_at": now, "finished_at": now, "step": "配音", "step_msg": None,
                      "error": "豆包语音拒绝了请求（45000）：Doubao TTS quota",
                      "error_msg": {"code": "tts.volc.rejected",
                                    "params": {"code": "45000", "detail": {"t": "vendor", "text": "Doubao TTS quota"}}},
                      "detail": "ffmpeg … volc", "fingerprint": "x", "files": {"E01": "final/E01.mp4"},
                      "report": "final/mix_report.json"}


def write_report(root):
    rep = {"notes": [], "episodes": [{"episode": "E01", "notes": [{"shot": "SH001", "kind": "speedup", "speed": 1.1}]}],
           "lines_failed": [{"line": "L1", "error": "豆包语音拒绝了请求（45000）：Doubao TTS quota",
                             "error_msg": {"code": "tts.volc.rejected",
                                           "params": {"code": "45000", "detail": {"t": "vendor", "text": "Doubao TTS quota"}}}}],
           "detail": "MiniMax volc"}
    d = Path(root) / "final"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mix_report.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    (d / "E01.mp4").write_bytes(b"x")


def main() -> int:
    global D, E, A
    assert P.find_vendor_words(DOC) == [], "夹具里不应含词表里的词（换了夹具要重新审）"
    app_mod._render_runner.sleep = lambda _s: None
    c = TestClient(app_mod.app)
    alice = auth.register("alice", "secret1")["id"]
    boss = auth.register("boss", "secret2")["id"]
    auth.update_user(boss, role="admin")
    H = {"Authorization": f"Bearer {auth.issue_token(alice)}"}
    HA = {"Authorization": f"Bearer {auth.issue_token(boss)}"}
    nid = novels.create_novel(alice, "药")["id"]
    cid = novels.create_chapter(alice, nid, "第一章", text="原文")["id"]
    novels.create_version(alice, nid, cid, "v1", {}, "原文")
    novels.update_version_state(alice, nid, cid, "v1", "succeeded", result=copy.deepcopy(DOC))
    R = f"/novels/{nid}/chapters/{cid}/versions/v1/render"
    root = novels.render_dir(alice, nid, cid, "v1")
    RTP = RT                                      # 路径模板

    # ---- 准备：会话、出一段、自由节点出一次（真实形状的尝试），再投毒 ----
    s = c.post(R + "/session", headers=H, json={"budget_cny": 100000}).json()
    ids = [x["id"] for x in s["clips"]]
    assert len(ids) >= 5, ids
    A, D, E, C1 = ids[0], ids[1], ids[2], ids[3]
    assert c.post(R + f"/clips/{A}/run", headers=H, json={}).status_code == 200
    drain()
    assert c.post(R + "/free", headers=H, json={}).status_code == 200
    assert c.patch(R + "/free/F01", headers=H, json={"prompt": "空镜：河面"}).status_code == 200
    assert c.post(R + "/free/F01/run", headers=H, json={}).status_code == 200
    drain()
    s0 = render_session.load(root)
    REAL["clip"] = copy.deepcopy(next(x for x in s0["clips"] if x["id"] == A)["attempts"][0])
    REAL["free"] = copy.deepcopy(next(x for x in s0["free"] if x["id"] == "F01")["attempts"][0])
    assert REAL["clip"]["state"] == "succeeded" and REAL["free"]["state"] == "succeeded"
    fake_file = Path(root) / "clips" / "late.mp4"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_bytes(b"x")
    write_report(root)
    poison(root)
    raw = (Path(root) / "session.json").read_text(encoding="utf-8")
    assert "Seedance" in raw and "volces" in raw and "vendor_note" in raw, "投毒确实写进去了"
    print("1. 会话与投毒 ✓")

    # ---- 出片会话的每个返回出口，各查一次带毒的成功响应（每次调用前重新投毒），再查错误分支 ----
    def film(label, method, path, route, status=200, **kw):
        poison(root)
        resp = c.request(method, path, headers=H, **kw)
        body = clean(label, resp, status, route=route)
        if status == 200:
            film_shape(label, body)
        return body

    film("session.get", "GET", R + "/session", RTP + "/session")
    film("session.post", "POST", R + "/session", RTP + "/session", json={})
    film("session.patch", "PATCH", R + "/session", RTP + "/session", json={"tier": "a-fast"})
    poison(root)
    r = c.patch(R + "/session", headers=H, json={"tier": "nope"})
    clean("session.patch.422", r, 422, route=RTP + "/session")
    poison(root)
    sent = {"provider": "minimax"}
    r = c.patch(R + "/session", headers=H, json=sent)
    clean("session.patch.vendor-input", r, 422, route=RTP + "/session", sent=sent)
    # 回显豁免只限 input：若把豁免用在不是请求回显的内容上，守卫自己要能红（自检）
    assert P.find_vendor_words(r.json()), "反向对照：422 原文里应有被回显的厂商词（豁免确实在起作用）"
    film("run.single", "POST", R + f"/clips/{C1}/run", RTP + "/clips/{clip_id}/run", json={})
    film("cancel.queued", "POST", R + f"/clips/{C1}/cancel", RTP + "/clips/{clip_id}/cancel")
    poison(root)
    clean("cancel.409", c.post(R + f"/clips/{C1}/cancel", headers=H), 409, route=RTP + "/clips/{clip_id}/cancel")
    # 批量出剩余各段：先不带金额（409 附重算金额），再带上
    poison(root)
    r = c.post(R + "/run", headers=H, json={})
    b = clean("run.all.409", r, 409, route=RTP + "/run")
    amount = b["detail"]["expected_cny"] if "expected_cny" in b.get("detail", {}) else None
    if amount is None:
        amount = render_session.run_quote(render_session.load(root), None)[1]
    film("run.all", "POST", R + "/run", RTP + "/run", json={"expected_cny": amount})
    drain()
    film("chosen", "PUT", R + f"/clips/{A}/chosen", RTP + "/clips/{clip_id}/chosen", json={"attempt": 0})
    poison(root)
    clean("chosen.422", c.put(R + f"/clips/{A}/chosen", headers=H, json={"attempt": 1}), 422, route=RTP + "/clips/{clip_id}/chosen")
    film("clip.patch", "PATCH", R + f"/clips/{A}", RTP + "/clips/{clip_id}", json={"mute_native": True})
    film("free.post", "POST", R + "/free", RTP + "/free", json={})
    film("free.patch", "PATCH", R + "/free/F02", RTP + "/free/{fid}", json={"prompt": "空镜：夜"})
    film("free.run", "POST", R + "/free/F02/run", RTP + "/free/{fid}/run", json={})
    film("free.cancel", "POST", R + "/free/F02/cancel", RTP + "/free/{fid}/cancel")
    poison(root)
    clean("free.cancel.409", c.post(R + "/free/F02/cancel", headers=H), 409, route=RTP + "/free/{fid}/cancel")
    film("free.chosen", "PUT", R + "/free/F01/chosen", RTP + "/free/{fid}/chosen", json={"attempt": 0})
    film("free.delete", "DELETE", R + "/free/F02", RTP + "/free/{fid}")
    print("2. 出片会话的各个出口（带毒的成功响应与错误分支）✓")

    # ---- 合成：入口桩化执行器（不起线程、不需要 ffmpeg），成功响应也是会话视图 ----
    app_mod._compose_worker = lambda *a, **k: None
    render_mix.tools = lambda: ("ffmpeg", "ffprobe")
    miss = c.get(R + "/voices", headers=H).json()["missing"]
    assert c.put(R + "/voices", headers=H, json={"voices": {k: "fake-male" for k in miss}}).status_code == 200
    poison(root)
    r = c.post(R + "/compose", headers=H, json={"draft": True})
    if r.status_code == 409:
        amt = r.json()["detail"]["expected_cny"]
        clean("compose.409", r, 409, route=RTP + "/compose")
        film("compose.post", "POST", R + "/compose", RTP + "/compose", json={"draft": True, "expected_cny": amt})
    else:
        clean("compose.post", r, 200, route=RTP + "/compose")
        film_shape("compose.post", r.json())
    poison(root)
    write_report(root)
    cp = clean("compose.get", c.get(R + "/compose", headers=H), 200, route=RTP + "/compose")
    assert cp["report"] is not None and cp["final"]["error_msg"]["code"] == "tts.vendor.rejected", (cp["report"], cp["final"])
    assert cp["report"]["lines_failed"][0]["error_msg"]["code"] == "tts.vendor.rejected", cp["report"]
    rf = c.get(R + "/files/final/mix_report.json", headers=H)
    rb = clean("files.report", rf, 200, route=RTP + "/files/{path:path}")
    # 与预览同一个公共视图：旧码归一成中性码、旧原话参数去掉、detail 打码，而不是逐字符串替换
    assert rb["lines_failed"] == cp["report"]["lines_failed"], (rb["lines_failed"], cp["report"]["lines_failed"])
    lf = rb["lines_failed"][0]["error_msg"]
    assert lf == {"code": "tts.vendor.rejected", "params": {}} and rb["detail"] == "*** ***", (lf, rb["detail"])
    assert "tts.***" not in json.dumps(rb), rb
    clean("files.404", c.get(R + "/files/session.json", headers=H), 404, route=RTP + "/files/{path:path}")
    print("3. 合成与报告 ✓")

    # ---- 其余接口 ----
    clean("openapi", c.get("/openapi.json"), 200, route="/openapi.json")
    clean("healthz", c.get("/healthz"), 200, route="/healthz")
    clean("me", c.get("/auth/me", headers=H), 200, route="/auth/me")
    poison(root)
    tasks_body = clean("tasks", c.get("/render/tasks", headers=H), 200, route="/render/tasks")
    clean("voices", c.get(R + "/voices", headers=H), 200, route=RTP + "/voices")
    clean("voices.put.422", c.put(R + "/voices", headers=H, json={"voices": {"x": "nope"}}), 422, route=RTP + "/voices")
    clean("voices.put", c.put(R + "/voices", headers=H, json={"voices": {}}), 200, route=RTP + "/voices")
    clean("bgm.put.422", c.put(R + "/bgm/E01", headers={**H, "content-type": "text/plain"}, content=b"x"), 422, route=RTP + "/bgm/{episode}")
    clean("bgm.delete", c.delete(R + "/bgm/E01", headers=H), 200, route=RTP + "/bgm/{episode}")
    app_mod._jobs["jvg"] = {"id": "jvg", "user_id": alice, "status": "failed", "log": [], "debug_log": [], "result": None,
                            "quality_report": None, "quality_msg": None, "error": "转换失败", "error_msg": None,
                            "persisted": True, "created_at": "2026-01-01T00:00:00", "work_title": "药", "chapter": "第一章",
                            "chars": 2, "progress": {}, "partial": {"batches_done": 1}, "novel_id": nid,
                            "chapter_id": cid, "version_id": "jvg", "finished_at": "2026-01-01T00:01:00"}
    # 转换的旧失败记录：无代码的系统错误、旧厂商错误码、清单里带厂商词的诊断报告；用户内容（result）不动
    POISON_REPORT = "MiniMax says boom deepseek https://api.minimax.cn/v1 sk-live-1"
    app_mod._jobs["jvg"].update(
        error="Anthropic claude 调用失败 api.anthropic.com",
        manifest={"contracts": {"model": "deepseek-x", "review_model": "claude-x", "schema": "s1"},
                  "attempts": [{"n": 1, "report": POISON_REPORT}]})
    app_mod._jobs["jvg2"] = {**app_mod._jobs["jvg"], "id": "jvg2", "version_id": "jvg2",
                             "error": "旧", "error_msg": {"code": "film.minimax.no_key", "params": {}}}
    novels.create_version(alice, nid, cid, "v2", {}, "原文")
    novels.update_version_state(alice, nid, cid, "v2", "failed", error="Anthropic claude 调用失败",
                                error_msg={"code": "tts.volc.no_key", "params": {}},
                                manifest={"contracts": {"model": "deepseek-x"}, "attempts": [{"report": POISON_REPORT}]})
    clean("jobs", c.get("/jobs", headers=H), 200, route="/jobs")
    j1 = clean("job", c.get("/jobs/jvg", headers=H), 200, route="/jobs/{job_id}")
    assert j1["error_msg"]["code"] == "common.failed_generic" and "claude" not in j1["error"].lower(), j1
    assert j1["manifest"]["attempts"][0]["report"] == "*** says boom *** https://api.***.cn/v1 sk-live-1", j1["manifest"]
    assert j1["manifest"]["contracts"] == {"schema": "s1"}, j1["manifest"]
    j2 = clean("job2", c.get("/jobs/jvg2", headers=H), 200, route="/jobs/{job_id}")
    assert j2["error_msg"]["code"] == "film.vendor.no_key" and j2["error"] == "视频生成服务还没有配置，请联系管理员", j2
    v2 = clean("version.err", c.get(f"/novels/{nid}/chapters/{cid}/versions/v2", headers=H), 200,
               route="/novels/{nid}/chapters/{cid}/versions/{vid}")
    assert v2["error_msg"]["code"] == "tts.vendor.no_key" and v2["error"] == "配音服务还没有配置，请联系管理员", v2
    assert "***" in v2["manifest"]["attempts"][0]["report"], v2["manifest"]
    clean("job.partial", c.get("/jobs/jvg/partial", headers=H), 200, route="/jobs/{job_id}/partial")
    clean("job.404", c.get("/jobs/nope", headers=H), 404, route="/jobs/{job_id}")
    # 生产包与估价：夹具不含厂商词，整份响应全文扫（含 packs[].markdown）；estimate.model 只放行中性费率档
    plan = clean("plan", c.post("/render/plan", headers=H, json={"result": DOC}), 200, route="/render/plan",
                 models_at={"$.plan.estimate.model": tuple(render_plan.TIERS)})
    assert plan["plan"]["estimate"]["model"] in render_plan.TIERS and plan["packs"], plan["plan"]["estimate"]
    clean("novels", c.get("/novels", headers=H), 200, route="/novels")
    clean("summary", c.get(f"/novels/{nid}/summary", headers=H), 200, route="/novels/{nid}/summary")
    clean("novel", c.get(f"/novels/{nid}", headers=H), 200, route="/novels/{nid}")
    clean("chapter", c.get(f"/novels/{nid}/chapters/{cid}", headers=H), 200, route="/novels/{nid}/chapters/{cid}")
    clean("version", c.get(f"/novels/{nid}/chapters/{cid}/versions/v1", headers=H), 200,
          route="/novels/{nid}/chapters/{cid}/versions/{vid}")
    clean("memory", c.get(f"/novels/{nid}/memory", headers=H), 200, route="/novels/{nid}/memory")
    clean("assistant", c.get(f"/novels/{nid}/assistant", headers=H), 200, route="/novels/{nid}/assistant")
    # 助手历史里的旧工具记录：升级前存下的厂商错误码、无代码的厂商文字、film_status 结果里的错误字段；
    # 对话正文（用户提问与回答，含「方舟」这种常用词）原样，其余全部过出口
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from assistant import actions as a_actions, events as a_events, graph as a_graph, store as a_store
    act = a_actions.ACTIONS[0]
    fs_old = json.dumps({"session": {"pending": [{"id": "E01-C01", "error": "视频服务（MiniMax）账户余额不足 seedance"}]}},
                        ensure_ascii=False)
    old_msgs = [HumanMessage("方舟是什么"),
                AIMessage("", tool_calls=[{"name": act, "args": {}, "id": "c1"}, {"name": act, "args": {}, "id": "c2"},
                                          {"name": "film_status", "args": {}, "id": "c3"},
                                          {"name": "plot_get", "args": {}, "id": "c4"},
                                          {"name": "film_status", "args": {}, "id": "c5"},
                                          {"name": "plot_get", "args": {}, "id": "c6"}]),
                ToolMessage("视频服务（MiniMax）还没有配置 minimax", name=act, tool_call_id="c1", status="error",
                            artifact={"error": {"code": "film.minimax.no_key", "params": {}, "message": "视频服务（MiniMax）还没有配置"}}),
                ToolMessage("doubao 豆包语音出错 volc", name=act, tool_call_id="c2", status="error"),
                ToolMessage(fs_old, name="film_status", tool_call_id="c3"),
                ToolMessage("Anthropic claude 出错", name="plot_get", tool_call_id="c4", status="error",
                            artifact={"error": {"code": "tts.volc.no_key", "params": {}, "ref": "AB12CD34"}}),
                ToolMessage("{\"session\": {\"pending\": [{\"id\": \"E01-C01\", \"error\": \"视频服务（MiniMax）账户余额不足 seedance " + "x" * 400 + "（已截断）",
                            name="film_status", tool_call_id="c5"),
                ToolMessage("坏了 MiniMax", name="plot_get", tool_call_id="c6", status="error",
                            artifact={"error": {"params": {}, "ref": "ZX98YW76"}}),
                AIMessage("方舟是一艘船。")]
    with a_store.saver(alice, nid) as cp:
        ag = a_graph.build_agent(a_graph.NullModel(), cp)
        ag.update_state(a_graph.run_config(alice, nid, {}, "zh"), {"messages": old_msgs}, as_node="tools")
    hb = clean("assistant.old", c.get(f"/novels/{nid}/assistant", headers=H), 200, route="/novels/{nid}/assistant",
               user_fields=("$.messages[].text",))
    assert hb["messages"][0]["text"] == "方舟是什么" and hb["messages"][-1]["text"] == "方舟是一艘船。", hb["messages"]
    ent = hb["messages"][1]
    cards = {x["tool_call_id"]: x for x in ent["cards"]}
    assert cards["c1"]["error_msg"]["code"] == "film.vendor.no_key" and cards["c1"]["error"] == "视频生成服务还没有配置，请联系管理员", cards["c1"]
    assert cards["c2"]["error_msg"]["code"] == "common.failed_generic", cards["c2"]
    tl = {x["id"]: x for x in ent["tools"]}
    assert tl["c4"]["msg"]["code"] == "tts.vendor.no_key" and tl["c4"]["msg"]["ref"] == "AB12CD34" and "AB12CD34" in tl["c4"]["summary"], tl["c4"]
    assert "***" in tl["c3"]["summary"] and "MiniMax" not in tl["c3"]["summary"], tl["c3"]
    # 截断得无法解析的旧 film_status 结果：不回退原文，给登记过的中性摘要；无代码但带结构化 ref 的工具错误保留 ref
    assert tl["c5"]["summary"] == "（结果过长，已省略）" and tl["c5"]["msg"]["code"] == "assistant.tool.truncated", tl["c5"]
    assert tl["c6"]["msg"] == {"code": "common.failed_generic", "params": {}, "ref": "ZX98YW76"} and "ZX98YW76" in tl["c6"]["summary"], tl["c6"]
    assert a_events.tool_end_data(old_msgs[6], None)["msg"]["code"] == "assistant.tool.truncated"
    assert a_events.tool_end_data(old_msgs[7], None)["msg"]["ref"] == "ZX98YW76"
    # SSE：工具结束与操作事件走同一个序列化；系统错误事件也过出口
    ev_end = a_events.tool_end_data(old_msgs[5], None)
    assert not P.find_vendor_words(ev_end) and ev_end["msg"]["code"] == "tts.vendor.no_key", ev_end
    ev_err = a_events.error_msg(RuntimeError("MiniMax boom https://api.minimax.cn"), alice, "w")
    assert not P.find_vendor_words(ev_err) and ev_err["code"] in ("assistant.crashed", "common.failed_generic"), ev_err
    from render.providers.base import ProviderError as _PE
    legacy_err = _PE("视频服务（MiniMax）还没有配置")
    legacy_err.code, legacy_err.params = "film.minimax.no_key", {}
    real_llm_error, a_events.llm_error = a_events.llm_error, lambda e: legacy_err      # 模型错误映射给出旧码
    try:
        ev_old = a_events.error_msg(RuntimeError("x"), alice, "w")
    finally:
        a_events.llm_error = real_llm_error
    assert ev_old["code"] == "film.vendor.no_key" and not P.find_vendor_words(ev_old), ev_old
    clean("keyframes", c.get(f"/novels/{nid}/chapters/{cid}/versions/v1/keyframes", headers=H), 200,
          route="/novels/{nid}/chapters/{cid}/versions/{vid}/keyframes")
    # R12：用户内容里的「方舟」不打码；系统文案与键名照扫
    nid2 = novels.create_novel(alice, "方舟纪事")["id"]
    cid2 = novels.create_chapter(alice, nid2, "方舟之行", text="他登上方舟。")["id"]
    title2, ch_title2, text2 = "方舟纪事", "方舟之行", "他登上方舟。"
    lst = clean("novels.user", c.get("/novels", headers=H), 200, route="/novels", user_fields=("$.novels[].title",))
    mine = next(x for x in lst["novels"] if x["id"] == nid2)
    assert mine["title"] == title2, mine
    r1 = c.get(f"/novels/{nid2}", headers=H)
    nv = clean("novel.user", r1, 200, route="/novels/{nid}", user_fields=("$.title", "$.chapters[].title"))
    assert nv["title"] == title2 and [x["title"] for x in nv["chapters"]] == [ch_title2], nv
    r2 = c.get(f"/novels/{nid2}/chapters/{cid2}", headers=H)
    cv = clean("chapter.user", r2, 200, route="/novels/{nid}/chapters/{cid}", user_fields=("$.title", "$.text"))
    assert (cv["title"], cv["text"]) == (ch_title2, text2), cv
    assert "***" not in lst.__repr__() + nv.__repr__() + cv.__repr__(), "用户内容不打码"
    print("4. 其余接口 ✓")

    # ---- 具体断言 ----
    poison(root)
    tasks = c.get("/render/tasks", headers=H).json()["tasks"]
    late = [t for t in tasks if t["state"] == "late" and t["item_id"] == A]
    assert any(t["id"].endswith(P.task_key("cgt-doubao-seedance-c")) for t in late), late
    comp = [t for t in tasks if t["kind"] == "compose"]
    assert len(comp) == 1 and comp[0]["state"] == "failed" and comp[0]["step"] is None
    assert comp[0]["error"]["code"] == "tts.vendor.rejected", comp[0]["error"]
    legal = {t for t, _, _ in tiers.TIERS} | {None}
    assert tasks and all(t["tier"] in legal for t in tasks), [t["tier"] for t in tasks]
    print("5. 具体断言 ✓")

    # ---- 反向对照：管理员接口里有厂商词，普通用户拿不到 ----
    adm = c.get("/admin/service", headers=HA)
    assert adm.status_code == 200 and P.find_vendor_words(adm.json()), "反向对照：/admin/service 里应有厂商词"
    assert all(row.get("vendor_label") for row in adm.json()["film"]["tiers"])
    assert c.get("/admin/service", headers=H).status_code == 403
    print("6. 反向对照 ✓")

    # ---- 路由清单：(方法, 路径) 逐条登记 ----
    ui = "响应是用户自己的内容或只回显用户的输入，没有服务端生成的错误文字、出片会话、任务"
    bin_ = "二进制文件"
    EXEMPT = {
        ("GET", RT + "/export.zip"): bin_,
        ("POST", "/auth/register"): "认证：只回账号字段，错误是登记过的认证消息，不涉及出片",
        ("POST", "/auth/login"): "同上",
        ("POST", "/novels"): "新建小说：" + ui,
        ("PATCH", "/novels/{nid}"): "改小说：" + ui,
        ("DELETE", "/novels/{nid}"): "删小说：" + ui,
        ("POST", "/novels/{nid}/chapters"): "新建章节：" + ui,
        ("PATCH", "/novels/{nid}/chapters/{cid}"): "改章节：" + ui,
        ("DELETE", "/novels/{nid}/chapters/{cid}"): "删章节：" + ui,
        ("POST", "/novels/{nid}/chapters/{cid}/versions"): "新建转换版本：只回任务号；转换任务本身在 /jobs 与 /jobs/{job_id} 里查",
        ("PUT", "/novels/{nid}/chapters/{cid}/versions/{vid}"): "保存用户编辑后的分镜：" + ui,
        ("DELETE", "/novels/{nid}/chapters/{cid}/versions/{vid}"): "删版本：" + ui,
        ("POST", "/novels/{nid}/chapters/{cid}/versions/{vid}/adopt"): "采纳版本：" + ui,
        ("POST", "/novels/{nid}/chapters/{cid}/digest"): "章节摘要：调大模型，输出是用户内容",
        ("PUT", "/novels/{nid}/memory/assets/{kind}/{card_id}"): "资产卡增改：" + ui,
        ("DELETE", "/novels/{nid}/memory/assets/{kind}/{card_id}"): "资产卡删除：" + ui,
        ("POST", "/render/keyframes"): "关键帧批量生成：按分镜出图，响应是图片清单，不含出片会话与厂商字段",
        ("PUT", "/novels/{nid}/chapters/{cid}/versions/{vid}/keyframes/{shot_id}"): "关键帧上传：二进制入，回清单",
        ("GET", "/novels/{nid}/chapters/{cid}/versions/{vid}/keyframes/{shot_id}"): "关键帧下载：" + bin_,
        ("DELETE", "/novels/{nid}/chapters/{cid}/versions/{vid}/keyframes/{shot_id}"): "关键帧删除：只回清单",
        ("GET", "/novels/{nid}/style-image"): "风格图下载：" + bin_,
        ("PUT", "/novels/{nid}/style-image"): "风格图上传：二进制入，回元数据",
        ("DELETE", "/novels/{nid}/style-image"): "风格图删除：只回元数据",
        ("POST", "/novels/{nid}/memory/lifecycle"): "记忆增删改：" + ui,
        ("POST", "/novels/{nid}/memory/lifecycle/{lid}"): "同上",
        ("DELETE", "/novels/{nid}/memory/lifecycle/{lid}"): "同上",
        ("PUT", "/novels/{nid}/memory/plot"): "同上",
        ("PUT", "/novels/{nid}/memory/plot/chapters/{cid}"): "同上",
        ("POST", "/novels/{nid}/memory/constraints"): "同上",
        ("PATCH", "/novels/{nid}/memory/constraints/{kid}"): "同上",
        ("DELETE", "/novels/{nid}/memory/constraints/{kid}"): "同上",
        ("DELETE", "/novels/{nid}/assistant"): "清空助手对话：" + ui,
        ("POST", "/novels/{nid}/assistant/messages"): "助手：流式输出（SSE），内容是模型对用户说的话",
        ("POST", "/novels/{nid}/assistant/resume"): "助手：流式输出",
        ("POST", "/novels/{nid}/assistant/undo"): "助手：撤销，回用户内容",
    }
    overlap = SEEN_ROUTES & set(EXEMPT)
    assert not overlap, ("已调用的接口不应再写豁免", overlap)
    expected = set()
    for r in app_mod.app.routes:
        path = getattr(r, "path", "")
        if not path or path == "/admin" or path.startswith("/admin/") or path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
            continue
        for m in sorted((getattr(r, "methods", None) or set()) - {"HEAD", "OPTIONS"}):
            expected.add((m, path))
            assert (m, path) in SEEN_ROUTES or (m, path) in EXEMPT, f"新接口 {m} {path} 没有登记：加进守卫的调用，或写明豁免理由"
    stale = (SEEN_ROUTES | set(EXEMPT)) - expected
    assert not stale, ("登记了不存在的接口", stale)
    # 出片会话的返回出口都查过带毒的成功响应
    need = {"session.get", "session.post", "session.patch", "run.single", "cancel.queued", "run.all", "chosen", "clip.patch",
            "free.post", "free.patch", "free.run", "free.cancel", "free.chosen", "free.delete", "compose.post"}
    assert need <= SEEN_FILM, need - SEEN_FILM
    print("7. 路由清单 ✓")
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
