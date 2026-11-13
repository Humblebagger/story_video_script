#!/usr/bin/env python3
"""小说级会话（小说 → 章节 → 版本）的测试。用法: python3 tests/server/test_novels.py

全程使用临时数据目录，不碰真实 data/。
"""
import copy
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "pipeline"))     # fakes.FakeChat

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前

# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None

from server import library, novels, store  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao"
U = "a" * 12          # 用户 ID 须为 12 位十六进制（auth.user_dir 的规则）


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def batch_doc(n: int) -> dict:
    return json.loads((YAO / f"output_batch{n}.json").read_text(encoding="utf-8"))


def succeed(nid, cid, vid, doc, status="succeeded"):
    novels.update_version_state(U, nid, cid, vid, status, result=doc)


def digest_and_version_errors(app_mod, HTTPException) -> None:
    """章后整理失败带编号、可预期失败不带；关闭开关的提示不含变量名；版本记录可存 error_msg。"""
    import logging
    from server import error_refs
    uid = "e" * 12
    nid = novels.create_novel(uid, "书")["id"]
    cid = novels.create_chapter(uid, nid, "一", text="原文")["id"]
    novels.create_version(uid, nid, cid, "s1", {}, "原文")
    novels.update_version_state(uid, nid, cid, "s1", "succeeded", result=batch_doc(1))
    novels.adopt_version(uid, nid, cid, "s1")
    A = {"id": uid}

    class Grab(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record)

    real = app_mod._digest_chat
    errs = Grab()
    logging.getLogger("server.errors").addHandler(errs)
    SECRET = "zz-synthetic-anthropic-key-0123456789"
    old_key = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = SECRET
    try:
        def boom():
            raise RuntimeError(f"model exploded key={SECRET}")
        app_mod._digest_chat = boom
        app_mod._run_digest(uid, nid, cid)
        d = novels.get_chapter(uid, nid, cid)["digest"]
        assert d["status"] == "failed"
        assert d["error_msg"]["code"] == "chapter.digest.failed" and d["error_msg"]["params"] == {}
        ref = d["error_msg"]["ref"]
        assert len(ref) == 8
        assert d["error"].startswith("没有完成，可以稍后重跑；仍失败请联系管理员") and ref in d["error"]
        assert "RuntimeError" not in d["error"]
        assert SECRET not in json.dumps(novels.get_chapter(uid, nid, cid), ensure_ascii=False), "章节数据里没有密钥"
        row = error_refs.find(ref)
        assert "RuntimeError" in row["detail"] and row["where"].startswith("digest ")
        assert row["user_id"] == uid
        assert SECRET not in json.dumps(row, ensure_ascii=False), "错误记录里没有密钥"
        fmt = logging.Formatter("%(levelname)s %(message)s")
        out = "\n".join(fmt.format(r) for r in errs.records if ref in r.getMessage())
        assert out and "RuntimeError" in out and SECRET not in out, "日志有编号与异常类型、没有密钥"

        # 可预期的失败（章节整理中途被删）：原因本身清楚，不记编号
        before = len(error_refs.recent(1000))

        def gone():
            raise novels.NotFound.of("chapter.not_found")
        app_mod._digest_chat = gone
        app_mod._run_digest(uid, nid, cid)
        d = novels.get_chapter(uid, nid, cid)["digest"]
        assert d["error_msg"] == {"code": "chapter.not_found", "params": {}}
        assert len(error_refs.recent(1000)) == before
    finally:
        if old_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = old_key
        app_mod._digest_chat = real
        logging.getLogger("server.errors").removeHandler(errs)

    # 开关关闭：422 消息对象不含变量名，变量名只进日志
    real_ls = app_mod.load_settings
    app_log = Grab()
    logging.getLogger("render.app").addHandler(app_log)
    app_mod.load_settings = lambda: type("S", (), {"chapter_digest": False})()
    try:
        e = must_raise(HTTPException, app_mod.chapters_digest, nid, cid, A)
        assert e.status_code == 422 and e.detail["code"] == "chapter.digest.off"
        assert "STORYBOARD_CHAPTER_DIGEST" not in json.dumps(e.detail, ensure_ascii=False)
        assert any(r.levelno == logging.WARNING and "STORYBOARD_CHAPTER_DIGEST" in r.getMessage()
                   for r in app_log.records)
    finally:
        app_mod.load_settings = real_ls
        logging.getLogger("render.app").removeHandler(app_log)

    # 版本记录：error_msg 字段
    v = novels.create_version(uid, nid, cid, "f9", {}, "原文")
    assert "error_msg" in v and v["error_msg"] is None
    m = {"code": "common.internal", "params": {}}
    novels.update_version_state(uid, nid, cid, "f9", "failed", error="x", error_msg=m)
    got = novels.get_version(uid, nid, cid, "f9")
    assert got["error"] == "x" and got["error_msg"] == m
    novels.update_version_state(uid, nid, cid, "f9", "failed", error="y")
    assert novels.get_version(uid, nid, cid, "f9")["error_msg"] == m, "不传 error_msg 时不动它"
    print("持久化失败: 章后整理带编号 / 可预期失败不记编号 / 关闭开关无变量名 / 版本 error_msg ✓")


def codes_and_api(app_mod, HTTPException) -> None:
    """报错带代码：存储层异常带 code/params，接口层 detail 是消息对象。"""
    uid = "b" * 12

    def E(exc, code, fn, *a, **kw):
        """断言抛出 exc 且带指定代码，返回异常供继续检查。"""
        error = must_raise(exc, fn, *a, **kw)
        assert error.code == code, (code, error.code)
        return error

    E(novels.NovelError, "novel.empty_title", novels.create_novel, uid, " ")
    E(novels.NotFound, "novel.not_found", novels.get_novel, uid, "nope")
    e = E(novels.NovelError, "novel.bad_id", novels.get_novel, uid, "../x")
    assert e.params == {"id": "../x"} and str(e) == "非法的 ID：../x"
    nid = novels.create_novel(uid, "书")["id"]
    E(novels.NovelError, "chapter.empty_title", novels.create_chapter, uid, nid, " ")
    E(novels.NotFound, "chapter.not_found", novels.get_chapter, uid, nid, "c_nope")
    cid = novels.create_chapter(uid, nid, "一", text="原文")["id"]
    E(novels.NotFound, "chapter.version.not_found", novels.get_version, uid, nid, cid, "nope")
    E(novels.NotFound, "chapter.version.not_found", novels.delete_version, uid, nid, cid, "nope")
    E(novels.NovelError, "chapter.no_adopted", novels.digest_input, uid, nid, cid)
    novels.create_version(uid, nid, cid, "f1", {}, "原文")
    novels.update_version_state(uid, nid, cid, "f1", "failed")
    e = E(novels.NovelError, "chapter.version.not_adoptable", novels.adopt_version, uid, nid, cid, "f1")
    assert e.params == {} and "failed" not in str(e)
    novels.create_version(uid, nid, cid, "s1", {}, "原文")
    novels.update_version_state(uid, nid, cid, "s1", "succeeded", result=batch_doc(1))
    novels.adopt_version(uid, nid, cid, "s1")
    E(novels.NovelError, "chapter.version.adopted_delete", novels.delete_version, uid, nid, cid, "s1")
    c2 = novels.create_chapter(uid, nid, "二", text="原文二")["id"]
    novels.create_version(uid, nid, c2, "s2", {}, "原文二")
    novels.update_version_state(uid, nid, c2, "s2", "succeeded", result=batch_doc(2))
    novels.adopt_version(uid, nid, c2, "s2")
    novels.create_version(uid, nid, cid, "s3", {}, "原文")
    novels.update_version_state(uid, nid, cid, "s3", "succeeded", result=batch_doc(1))
    e = E(novels.NovelError, "chapter.version.later_adopted", novels.adopt_version, uid, nid, cid, "s3")
    assert e.params["names"] == ["二"] and "二" in str(e)
    E(novels.NovelError, "novel.asset.unknown_kind", novels.upsert_asset, uid, nid, "x", {"id": "a", "name": "n"})
    E(novels.NovelError, "novel.asset.no_id", novels.upsert_asset, uid, nid, "characters", {"name": "n"})
    E(novels.NovelError, "novel.asset.no_name", novels.upsert_asset, uid, nid, "characters", {"id": "a"})
    E(novels.NotFound, "novel.asset.not_found", novels.delete_asset, uid, nid, "characters", "zz")
    E(novels.NovelError, "novel.lifecycle.unknown_character", novels.add_lifecycle, uid, nid,
      character_id="ghost", type="deceased")
    novels.upsert_asset(uid, nid, "characters", {"id": "C90", "name": "甲"})
    e = E(novels.NovelError, "novel.lifecycle.unknown_type", novels.add_lifecycle, uid, nid,
          character_id="C90", type="bogus")
    assert isinstance(e.params["options"], list) and "（可选 deceased、permanent_condition、departed）" in str(e)
    E(novels.NovelError, "novel.lifecycle.unknown_status", novels.update_lifecycle, uid, nid, "zz",
      status="weird")
    E(novels.NotFound, "novel.lifecycle.not_found", novels.delete_lifecycle, uid, nid, "zz")
    E(novels.NotFound, "novel.lifecycle.not_found", novels.update_lifecycle, uid, nid, "zz", detail="x")
    e = E(novels.NovelError, "chapter.synopsis_too_long", novels.set_synopsis, uid, nid, cid, "字" * 500)
    assert set(e.params) == {"max", "len"}
    E(novels.NovelError, "novel.constraint.no_text", novels.add_constraint, uid, nid, {"text": " "})
    E(novels.NotFound, "novel.constraint.not_found", novels.delete_constraint, uid, nid, "zz")
    # 版本还有片段在出：Busy 带代码，仍是 NovelError
    from render import session as rs
    novels.create_version(uid, nid, c2, "s4", {}, "原文二")
    rdir = novels._chapter_dir(uid, nid, c2) / "render" / "s4"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "session.json").write_text("{}", encoding="utf-8")
    real_load, real_fly = rs.load, rs.any_in_flight
    rs.load, rs.any_in_flight = (lambda d: {"x": 1}), (lambda s: True)
    try:
        e = must_raise(novels.Busy, novels.delete_version, uid, nid, c2, "s4")
        assert e.code == "chapter.version.busy" and isinstance(e, novels.NovelError)
    finally:
        rs.load, rs.any_in_flight = real_load, real_fly
    # 旧资产库：仍是 ValueError
    e = must_raise(ValueError, library.create_work, uid, " ")
    assert isinstance(e, library.LibraryError) and e.code == "library.empty_title"
    assert must_raise(ValueError, library.upsert_card, uid, "w", "x", {"id": "a", "name": "n"}).code == "novel.asset.unknown_kind"
    assert must_raise(ValueError, library.upsert_card, uid, "w", "characters", {"name": "n"}).code == "novel.asset.no_id"
    assert must_raise(ValueError, library.upsert_card, uid, "w", "characters", {"id": "a"}).code == "novel.asset.no_name"
    assert must_raise(ValueError, library.delete_card, uid, "w", "x", "a").code == "novel.asset.unknown_kind"

    # 接口层：404 / 409 / 422 的 detail 都是消息对象
    A = {"id": uid}
    e = must_raise(HTTPException, app_mod.novels_get, "nope", A)
    assert e.status_code == 404 and e.detail["code"] == "novel.not_found"
    e = must_raise(HTTPException, app_mod._novel_call, lambda: (_ for _ in ()).throw(novels.Busy.of("chapter.version.busy")))
    assert e.status_code == 409 and e.detail["code"] == "chapter.version.busy"
    e = must_raise(HTTPException, app_mod.novels_create, app_mod.NovelBody(title=" "), A)
    assert e.status_code == 422 and e.detail["code"] == "novel.empty_title"
    e = must_raise(HTTPException, app_mod._clean_params, {"bogus": 1, "zzz": 2})
    assert e.status_code == 422 and e.detail["code"] == "novel.unknown_params" and e.detail["params"]["keys"] == ["bogus", "zzz"]
    e = must_raise(HTTPException, app_mod.memory_asset_upsert, nid, "characters", "C1", {"id": "C2", "name": "n"}, A)
    assert e.status_code == 422 and e.detail["code"] == "novel.asset.id_mismatch"
    empty = novels.create_chapter(uid, nid, "空章")["id"]
    e = must_raise(HTTPException, app_mod._start_version, A, nid, empty, {}, False)
    assert e.status_code == 422 and e.detail["code"] == "chapter.no_text"
    req = lambda rid: app_mod.RenderPlanRequest(result=batch_doc(1), run_id=rid)  # noqa: E731
    e = must_raise(HTTPException, app_mod.render_plan, req("../x"), A)
    assert e.status_code == 400 and e.detail["code"] == "novel.bad_id"
    e = must_raise(HTTPException, app_mod.render_plan, req("nope"), A)
    assert e.status_code == 404 and e.detail["code"] == "chapter.version.not_found"
    print("报错带代码: 存储层 code/params / Busy 仍是 NovelError / 旧资产库仍是 ValueError / 接口 detail 为消息对象 ✓")


def main() -> int:
    # 1. 小说：建、重名拦截、列表、改
    n = novels.create_novel(U, "药", {"narration_mode": "selective"})
    nid = n["id"]
    must_raise(novels.NovelError, novels.create_novel, U, " 药 ")
    must_raise(novels.NovelError, novels.create_novel, U, "")
    assert [x["title"] for x in novels.list_novels(U)] == ["药"]
    novels.update_novel(U, nid, params={"narration_mode": "original_text"})
    assert novels.get_novel(U, nid)["params"] == {"narration_mode": "original_text"}
    assert novels.get_novel(U, nid)["memory"]["numbering"] == {
        "next_unit": 1, "next_para": 1, "next_episode": 1}
    print("小说: 新建 / 同名拦截 / 列表 / 改参数 ✓")

    # 2. 章节：顺序自动续、采用前原文可改
    c1 = novels.create_chapter(U, nid, "一", "原文一")
    c2 = novels.create_chapter(U, nid, "二", "原文二")
    assert (c1["order"], c2["order"]) == (1, 2)
    novels.update_chapter(U, nid, c1["id"], text="原文一（改）")
    assert novels.get_chapter(U, nid, c1["id"])["text"] == "原文一（改）"
    print("章节: 顺序自动续 / 采用前原文可改 ✓")

    # 3. 版本与采用：资产进长期记忆、编号接续、原文锁定
    v1_doc = batch_doc(1)
    extra = copy.deepcopy(v1_doc["assets"]["characters"][0])
    extra.update({"id": "C98", "name": "只在 v1 出现的人"})
    edited = copy.deepcopy(extra)
    edited.update({"id": "C97", "name": "v1 带来、后被人改过"})
    v1_doc["assets"]["characters"] += [extra, edited]
    novels.create_version(U, nid, c1["id"], "v1", {}, "原文一（改）")
    must_raise(novels.NovelError, novels.adopt_version, U, nid, c1["id"], "v1")  # 还在 queued
    succeed(nid, c1["id"], "v1", v1_doc)
    r = novels.adopt_version(U, nid, c1["id"], "v1")
    assert r["added"] == len(v1_doc["assets"]["characters"]) + sum(
        len(v1_doc["assets"].get(k) or []) for k in ("locations", "props", "creatures"))
    mem = novels.get_memory(U, nid)
    assert "asset_origin" not in mem, "来源标记是内部账，不外露"
    assert {"C97", "C98"} <= {c["id"] for c in mem["assets"]["characters"]}
    units = v1_doc["source"]["units"]
    assert mem["numbering"]["next_unit"] == max(int(u["id"][1:]) for u in units) + 1
    assert mem["numbering"]["next_episode"] == max(
        int(e["id"][1:]) for e in v1_doc["episodes"]) + 1
    e = must_raise(novels.NovelError, novels.update_chapter, U, nid, c1["id"], text="再改")
    assert e.code == "chapter.text_locked" and "锁定" in str(e)
    assert novels.seed_assets(U, nid)["characters"], "长期记忆的资产就是下一次转换的种子"
    print("采用: 资产进长期记忆 / 编号接续 = 最大编号 +1 / 原文锁定 ✓")

    # 4. 换采用版：撤回旧版新建且没被人改过的卡；人改过的留下
    novels.upsert_asset(U, nid, "characters", {**edited, "name": "人工改名"})
    novels.create_version(U, nid, c1["id"], "v2", {}, "原文一（改）")
    succeed(nid, c1["id"], "v2", batch_doc(1))
    r = novels.adopt_version(U, nid, c1["id"], "v2")
    ids = {c["id"] for c in novels.get_memory(U, nid)["assets"]["characters"]}
    assert "C98" not in ids, "v1 独有、没人改过的卡应随换采用版撤回"
    assert "C97" in ids, "人改过的卡不能被撤回"
    assert r["retracted"] >= 1
    assert novels.get_chapter(U, nid, c1["id"])["adopted_version"] == "v2"
    must_raise(novels.NovelError, novels.delete_version, U, nid, c1["id"], "v2")
    novels.delete_version(U, nid, c1["id"], "v1")
    print("换采用版: 撤回旧版独有卡 / 人工改过的保留 / 采用版不可删 ✓")

    # 5. 后面的章节接着编号转过，前面的章节就不能再换采用版
    novels.create_version(U, nid, c2["id"], "w1", {}, "原文二")
    succeed(nid, c2["id"], "w1", batch_doc(2))
    novels.adopt_version(U, nid, c2["id"], "w1")
    novels.create_version(U, nid, c1["id"], "v3", {}, "原文一（改）")
    succeed(nid, c1["id"], "v3", batch_doc(1))
    e = must_raise(novels.NovelError, novels.adopt_version, U, nid, c1["id"], "v3")
    assert "二" in str(e), "要点名是哪一章挡着"
    b2_units = batch_doc(2)["source"]["units"]
    assert novels.get_memory(U, nid)["numbering"]["next_unit"] == \
        max(int(u["id"][1:]) for u in b2_units) + 1
    print("采用限制: 后续章节已采用时，前面的章节不能换采用版 ✓")

    # 6. 人工编辑：改坏了不能采用；改采用版会刷新长期记忆
    novels.create_version(U, nid, c2["id"], "w2", {}, "原文二")
    succeed(nid, c2["id"], "w2", batch_doc(2))
    novels.update_version_result(U, nid, c2["id"], "w2", batch_doc(2),
                                 verification={"status": "failed"}, status="draft_invalid")
    must_raise(novels.NovelError, novels.adopt_version, U, nid, c2["id"], "w2")
    trimmed = batch_doc(2)
    trimmed["episodes"] = trimmed["episodes"][:1]
    novels.update_version_result(U, nid, c2["id"], "w1", trimmed,
                                 verification={"status": "passed"}, status="succeeded")
    assert novels.get_memory(U, nid)["numbering"]["next_episode"] == \
        int(trimmed["episodes"][0]["id"][1:]) + 1, "采用版改了，编号接续按改后的算"
    print("编辑: 改坏的版本不能采用 / 改采用版刷新长期记忆 ✓")

    # 7. 删章节：撤回它的资产、编号回退
    novels.delete_chapter(U, nid, c2["id"])
    assert novels.get_memory(U, nid)["numbering"]["next_unit"] == \
        max(int(u["id"][1:]) for u in batch_doc(1)["source"]["units"]) + 1
    must_raise(novels.NotFound, novels.get_chapter, U, nid, c2["id"])
    must_raise(novels.NovelError, novels.get_chapter, U, nid, "../x")
    print("删章节: 编号回退 / 非法 ID 拦截 ✓")

    # 8. 旧数据迁移：按作品名归小说、按章节名归章节，每条记录成一个版本
    L = "b" * 12
    b1, b2 = batch_doc(1), batch_doc(2)
    # 迁移按产物里记的章节名归章（与旧历史列表同口径），参数里的只作后备
    b1["source"]["chapter"], b2["source"]["chapter"] = "上", "下"
    store.save(L, "r1", "succeeded", {"work_title": "药", "chapter": "上"}, b1)
    time.sleep(1.1)   # created_at 精确到秒，拉开先后
    store.save(L, "r2", "draft_invalid", {"work_title": "药", "chapter": "上"}, b1)
    store.save(L, "r3", "completed_with_warnings",
               {"work_title": "药", "chapter": "下", "narration_mode": "selective"}, b2)
    library.create_work(L, "只有资产库的作品")
    library.upsert_card(L, "只有资产库的作品", "characters",
                        {"id": "C01", "name": "甲"})
    library.import_assets(L, "药", {"characters": [{"id": "C55", "name": "库里人工建的"}]})
    r = novels.migrate_legacy(L)
    assert r["migrated"] and r["novels"] == 2 and r["chapters"] == 2 and r["versions"] == 3, r
    by_title = {x["title"]: x for x in novels.list_novels(L)}
    yao = novels.get_novel(L, by_title["药"]["id"])
    chs = {c["title"]: c for c in yao["chapters"]}
    assert chs["上"]["adopted_version"] == "r1", "draft_invalid 不能当采用版"
    assert chs["下"]["adopted_version"] == "r3"
    assert all(c["legacy_numbering"] for c in yao["chapters"])
    up = novels.get_chapter(L, yao["id"], chs["上"]["id"])
    assert up["text"].replace("\n", "") == "".join(u["text"] for u in b1["source"]["units"]), \
        "旧记录没存原文，要用句单元拼回"
    assert yao["params"] == {"narration_mode": "selective"}
    assert "C55" in {c["id"] for c in yao["memory"]["assets"]["characters"]}, \
        "旧资产库是人维护过的，要整体迁进长期记忆"
    only = novels.get_novel(L, by_title["只有资产库的作品"]["id"])
    assert only["chapters"] == [] and only["memory"]["assets"]["characters"][0]["id"] == "C01"
    assert novels.migrate_legacy(L) == {"migrated": False}, "迁移应幂等"
    assert store.get(L, "r1") is not None and library.get_work(L, "药"), "旧文件原样保留"
    # 迁移来的章节编号本不接续：前面的章节照样能换采用版
    novels.adopt_version(L, yao["id"], chs["上"]["id"], "r1")
    print("迁移: 按作品/章节归档 / 采用最近成功版 / 原文用句单元拼回 / 资产库整体迁入 / 幂等 ✓")

    # 9. 接口：转换落成版本、首个成功版本自动采用、复验、渲染按版本 id 取证据
    import server.app as app_mod
    from fastapi import HTTPException

    calls = []

    def fake_convert(text, params, settings=None, log=print, warnings_out=None,
                     seed_assets=None, manifest_out=None, progress_out=None,
                     on_partial=None, start_numbering=None, novel_context=None):
        calls.append({"text": text, "params": params, "seed": seed_assets,
                      "numbering": start_numbering, "context": novel_context})
        log("（假转换）")
        if manifest_out is not None:
            manifest_out.update({"verification": {"status": "passed"}})
        return batch_doc(1)

    # 章后整理的模型替身：每次调用新给一个，提议「小栓」在其出场的第一句发生永久状态变化
    b1units = batch_doc(1)["source"]["units"]
    quote_unit = next(u for u in b1units if "小栓" in u["text"])
    digests = []

    def fake_digest_chat():
        from fakes import FakeChat
        from pipeline.chat import ChatInvoker
        from pipeline.config import Settings
        chat = FakeChat(responses=[json.dumps({"lifecycle": [
            {"character_id": "C03", "type": "permanent_condition", "detail": "痨病",
             "unit_ref": quote_unit["id"], "evidence_quote": "小栓"},
            {"character_id": "C03", "type": "deceased", "unit_ref": quote_unit["id"],
             "evidence_quote": "小栓死了"}],
            "synopsis": f"第{len(digests) + 1}次整理的摘要。"}, ensure_ascii=False)])
        digests.append(chat)
        return ChatInvoker(Settings(), chat=chat)

    def wait_digest(nid, cid, vid=None):
        for _ in range(500):
            d = app_mod.chapters_get(nid, cid, A).get("digest") or {}
            # 只认终态 done：还没开始（没有 digest 记录）或 failed 都不算跑完，继续等到超时
            if d.get("status") == "done" and (vid is None or d.get("version_id") == vid):
                return d
            time.sleep(0.02)
        raise AssertionError(f"章后整理没跑完：{d}")

    real_convert, real_digest = app_mod.convert_text, app_mod._digest_chat
    app_mod.convert_text = fake_convert
    app_mod._digest_chat = fake_digest_chat
    try:
        A = {"id": "c" * 12}
        app_mod.novel_user(A)
        created = app_mod.novels_create(app_mod.NovelBody(
            title="药", params={"narration_mode": "selective"}), A)
        e = must_raise(HTTPException, app_mod.novels_create,
                       app_mod.NovelBody(title="药", params={"bogus": 1}), A)
        assert e.status_code == 422
        e = must_raise(HTTPException, app_mod.novels_create, app_mod.NovelBody(title="药"), A)
        assert e.status_code == 422 and e.detail["code"] == "novel.title_taken" and e.detail["params"] == {"title": "药"}
        anid = created["id"]
        ch = app_mod.chapters_create(anid, app_mod.ChapterBody(title="第一章", text="他推门。"), A)
        e = must_raise(HTTPException, app_mod.versions_create, anid, "c_nope",
                       app_mod.VersionRequest(), A)
        assert e.status_code == 404

        def run(overrides=None):
            r = app_mod.versions_create(anid, ch["id"],
                                        app_mod.VersionRequest(overrides=overrides or {}), A)
            for _ in range(200):
                if app_mod._jobs[r["job_id"]]["status"] not in ("queued", "running"):
                    break
                time.sleep(0.02)
            return r["version_id"]

        va = run()
        job = app_mod.get_job(va, user=A)
        assert job["status"] == "succeeded" and job["chapter_id"] == ch["id"]
        assert calls[0]["params"].work_title == "药" and calls[0]["params"].chapter == "第一章"
        assert calls[0]["params"].narration_mode == "selective", "小说默认参数要带进转换"
        assert calls[0]["seed"] is None, "空库不注入"
        assert any("自动采用" in line for line in job["log"])
        chapter = app_mod.chapters_get(anid, ch["id"], A)
        assert chapter["adopted_version"] == va
        d = wait_digest(anid, ch["id"])
        assert d["status"] == "done" and d["proposed"] == 1 and len(d["dropped"]) == 1, \
            "证据不是原文子串的提议要丢"
        mem = app_mod.memory_get(anid, A)
        (prop,) = mem["lifecycle"]
        assert prop["status"] == "proposed" and prop["origin"] == "model"
        assert prop["since"] == {"chapter_id": ch["id"], "unit_ref": quote_unit["id"]}
        assert prop["written_by"] == {"chapter_id": ch["id"], "version_id": va}
        assert mem["plot"]["chapters"] == [
            {"chapter_id": ch["id"], "synopsis": "第1次整理的摘要。", "origin": "model"}]

        vb = run({"narration_mode": "original_text"})
        assert calls[1]["params"].narration_mode == "original_text", "本次覆写优先"
        assert calls[1]["seed"], "第二次转换要带上长期记忆里的资产库"
        assert app_mod.chapters_get(anid, ch["id"], A)["adopted_version"] == va, \
            "已有采用版时新版本只存档"
        stored = app_mod.versions_get(anid, ch["id"], vb, A)
        assert stored["input_text"] == "他推门。" and stored["params"]["narration_mode"] == \
            "original_text"

        bad = copy.deepcopy(stored["result"])
        bad["source"]["units"][0]["text"] += "（篡改）"
        r = app_mod.versions_update(anid, ch["id"], vb, bad, A)
        assert r["status"] == "draft_invalid", "冻结证据被改，复验不过"
        e = must_raise(HTTPException, app_mod.versions_adopt, anid, ch["id"], vb, A)
        assert e.status_code == 422
        r = app_mod.versions_update(anid, ch["id"], vb, stored["result"], A)
        assert r["status"] == "succeeded"
        # 换采用版：未确认的模型提议与模型摘要撤回，按新版本重新整理；人写的摘要不覆盖
        app_mod.plot_synopsis(anid, ch["id"], app_mod.SynopsisBody(synopsis="人写的摘要。"), A)
        r = app_mod.versions_adopt(anid, ch["id"], vb, A)
        assert r["changed"] and r["digest"] == "running"
        d = wait_digest(anid, ch["id"], vb)
        assert d["synopsis_kept_user"] and d["version_id"] == vb
        mem = app_mod.memory_get(anid, A)
        assert [e["written_by"]["version_id"] for e in mem["lifecycle"]] == [vb]
        assert mem["plot"]["chapters"][0]["synopsis"] == "人写的摘要。"
        assert app_mod.versions_adopt(anid, ch["id"], vb, A)["changed"] is False
        assert len(digests) == 2, "重复采用同一版不重跑整理"
        lid = mem["lifecycle"][0]["id"]
        e = must_raise(HTTPException, app_mod.lifecycle_update, anid, lid,
                       app_mod.LifecyclePatch(status="maybe"), A)
        assert e.status_code == 422
        app_mod.lifecycle_update(anid, lid, app_mod.LifecyclePatch(status="confirmed"), A)
        e = must_raise(HTTPException, app_mod.lifecycle_add, anid,
                       app_mod.LifecycleBody(character_id="C77", type="deceased"), A)
        assert e.status_code == 422, "资产库里没有的角色不能记"
        manual = app_mod.lifecycle_add(anid, app_mod.LifecycleBody(
            character_id="C01", type="departed", detail="远走"), A)
        assert manual["status"] == "confirmed" and manual["origin"] == "user"
        app_mod.plot_outline(anid, app_mod.OutlineBody(outline="全书梗概。"), A)
        k = app_mod.constraints_add(anid, app_mod.ConstraintBody(
            text="不出现血腥画面", negative_prompt="血迹", keywords=["血"]), A)
        e = must_raise(HTTPException, app_mod.constraints_add, anid,
                       app_mod.ConstraintBody(text="  "), A)
        assert e.status_code == 422
        off = app_mod.constraints_add(anid, app_mod.ConstraintBody(text="不吸烟"), A)
        app_mod.constraints_update(anid, off["id"], app_mod.ConstraintBody(enabled=False), A)

        assert calls[0]["numbering"] is None, "第一章前面没有采用章节，从 1 起编"
        # 第二章：接着第一章采用版的编号往下排；重转第一章不接在它自己后面
        ch2 = app_mod.chapters_create(anid, app_mod.ChapterBody(title="第二章", text="她走了。"), A)
        r2 = app_mod.versions_create(anid, ch2["id"], app_mod.VersionRequest(), A)
        for _ in range(200):
            if app_mod._jobs[r2["job_id"]]["status"] not in ("queued", "running"):
                break
            time.sleep(0.02)
        b1u = batch_doc(1)["source"]["units"]
        assert calls[-1]["numbering"] == {
            "next_unit": max(int(u["id"][1:]) for u in b1u) + 1,
            "next_para": max(u["para"] for u in b1u) + 1,
            "next_episode": max(int(e["id"][1:]) for e in batch_doc(1)["episodes"]) + 1}
        assert any("编号接续本书此前章节" in line
                   for line in app_mod._jobs[r2["job_id"]]["log"])
        assert any("注入长期记忆" in line for line in app_mod._jobs[r2["job_id"]]["log"])
        ctx = calls[-1]["context"]
        assert {e["character_id"] for e in ctx.lifecycle} == {"C03", "C01"}, "只注入已确认的"
        assert ctx.lifecycle[0]["since"]["chapter_title"] == "第一章"
        assert ctx.outline == "全书梗概。" and ctx.synopses == [("第一章", "人写的摘要。")]
        assert [c["text"] for c in ctx.constraints] == ["不出现血腥画面"], "停用的不注入"
        assert novels.start_numbering(A["id"], anid, ch["id"]) is None
        # 重转第一章：看不到它自己与后面章节的生命周期和摘要
        ctx1 = novels.novel_context(A["id"], anid, ch["id"])
        assert [e["character_id"] for e in ctx1.lifecycle] == ["C01"] and not ctx1.synopses
        # 人工编辑时软核查照跑：C01 已下线却出现在镜头里
        v2 = app_mod._jobs[r2["job_id"]]["id"]
        r = app_mod.versions_update(anid, ch2["id"], v2,
                                    app_mod.versions_get(anid, ch2["id"], v2, A)["result"], A)
        assert r["status"] == "succeeded"
        assert any(f["rule_id"] == "NOVEL-LIFECYCLE-001"
                   for f in r["verification"]["findings"])
        wait_digest(anid, ch2["id"])
        assert any(s["chapter_id"] == ch2["id"]
                   for s in app_mod.memory_get(anid, A)["plot"]["chapters"])
        app_mod.chapters_delete(anid, ch2["id"], A)
        mem = app_mod.memory_get(anid, A)
        assert all(s["chapter_id"] != ch2["id"] for s in mem["plot"]["chapters"]) and all(
            (e["since"] or {}).get("chapter_id") != ch2["id"] for e in mem["lifecycle"]), \
            "删章节连带撤掉它的摘要与生命周期"
        app_mod.constraints_delete(anid, k["id"], A)
        app_mod.lifecycle_delete(anid, manual["id"], A)
        e = must_raise(HTTPException, app_mod.lifecycle_delete, anid, manual["id"], A)
        assert e.status_code == 404

        plan = app_mod.render_plan(app_mod.RenderPlanRequest(
            result=stored["result"], run_id=vb, include_markdown=False), A)
        assert plan["plan"]["clips"], "渲染任务包要能按版本 id 取冻结证据"
        assert app_mod.memory_get(anid, A)["assets"]["characters"]
        e = must_raise(HTTPException, app_mod.memory_asset_upsert, anid, "characters", "C01",
                       {"id": "C02", "name": "x"}, A)
        assert e.status_code == 422
        app_mod.memory_asset_upsert(anid, "characters", "C99", {"id": "C99", "name": "新人"}, A)
        assert "C99" in {c["id"] for c in app_mod.memory_get(anid, A)["assets"]["characters"]}
        e = must_raise(HTTPException, app_mod.novels_get, anid, {"id": "d" * 12})
        assert e.status_code == 404, "别人的小说看不到"
    finally:
        app_mod.convert_text, app_mod._digest_chat = real_convert, real_digest
    print("接口: 转换落成版本 / 首个成功版本自动采用 / 覆写优先 / 编号接续前章 / 复验 / 渲染按版本取证据 / 用户隔离 ✓")
    print("长期记忆: 章后整理核证据 / 换采用版撤回重整 / 人写摘要不覆盖 / 确认后才注入 / "
          "只注入前面章节 / 限制启停 / 编辑时软核查 / 删章节连带撤回 ✓")

    codes_and_api(app_mod, HTTPException)
    digest_and_version_errors(app_mod, HTTPException)
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        _TMP.cleanup()
    sys.exit(code)
