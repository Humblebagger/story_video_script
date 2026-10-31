"""HTTP 服务：小说 → 章节 → 版本的会话管理，后台转换，取分镜 IR。

启动：uvicorn server.app:app --host 0.0.0.0 --port 8000

小说级会话（总会话 = 小说，长期记忆；二级会话 = 章节；每次转换 = 一个版本，短期记忆）。
首次访问时自动把旧的转换记录（runs/）与资产库（library.json）迁到这套结构下（旧文件保留）：
  GET/POST            /novels                                   小说列表 / 新建
  GET/PATCH/DELETE    /novels/{nid}                             详情（含章节摘要与长期记忆）/ 改 / 删
  POST                /novels/{nid}/chapters                    新建章节
  GET/PATCH/DELETE    /novels/{nid}/chapters/{cid}              详情（含版本列表）/ 改 / 删
  POST                /novels/{nid}/chapters/{cid}/versions     转换本章 → {"job_id"}（进度走 /jobs）
  GET/PUT/DELETE      /novels/{nid}/chapters/{cid}/versions/{vid}        取 / 人工编辑并复验 / 删
  POST                /novels/{nid}/chapters/{cid}/versions/{vid}/adopt  采用 → 写入长期记忆
  POST                /novels/{nid}/chapters/{cid}/digest       重跑章后整理（采用后自动跑一次）
  GET                 /novels/{nid}/memory                      长期记忆
  PUT/DELETE          /novels/{nid}/memory/assets/{kind}/{id}   资产卡增改删
  POST                /novels/{nid}/memory/lifecycle            手动添加人物生命周期（死亡/永久伤病/下线）
  POST/DELETE         /novels/{nid}/memory/lifecycle/{lid}      确认 / 驳回 / 修改；删
  PUT                 /novels/{nid}/memory/plot                 全书梗概
  PUT                 /novels/{nid}/memory/plot/chapters/{cid}  改某章摘要
  POST                /novels/{nid}/memory/constraints          新增创作限制；PATCH/DELETE …/{kid}

转换耗时为分钟级（LLM 长输出），故采用异步任务模型：
  GET  /jobs             → 本人在跑/刚结束的任务摘要（关掉页面后靠它重新接上）
  GET  /jobs/{job_id}    → {"status": queued|running|succeeded|completed_with_warnings|failed,
                            "result": 分镜JSON, "quality_report": 降级交付时的质量报告, "log": [...]}
  GET  /jobs/{job_id}/partial → 已完成批次的合并结果（只读预览）
completed_with_warnings：软质量门（旁白密度/评审分）重试耗尽，产物结构合法、
逐字保真但质量未达阈值，已择优交付历次尝试中最优一版（请求置 strict=true 改为直接失败）。
任务表在内存中（进程重启后实时日志会清空），但状态与产物都落进版本记录。

渲染任务包（下游消费入口，只读、不落盘、不改 IR）：
  POST /render/plan        → 分镜 IR → 机器可读渲染任务清单 + 人读版生产包 + 费用估算
  POST /render/keyframes   → 分镜 IR → 每镜一条关键帧出图提示词（静帧预演用）

静帧预演的关键帧图（在别处出图后上传，挂在版本上、不进 IR）：
  GET                 /novels/{nid}/chapters/{cid}/versions/{vid}/keyframes            已有关键帧的镜头
  GET/PUT/DELETE      /novels/{nid}/chapters/{cid}/versions/{vid}/keyframes/{shot_id}  取图 / 上传（原始图片体）/ 删
出片（视频生成，状态在 chapters/<cid>/render/<vid>/session.json，后台线程提交/轮询/下载）：
  POST/GET/PATCH      …/versions/{vid}/render/session           建立（过验证门）/ 查询（标过期）/ 改设置
  POST                …/versions/{vid}/render/clips/{clip}/run  出这一段（试段或重做）
  POST                …/versions/{vid}/render/run               批量出剩余各段（带确认金额，不一致 409）
  PUT / PATCH         …/render/clips/{clip}/chosen、…/clips/{clip}   采用某次 / 原声静音
  GET                 …/versions/{vid}/render/files/{path}      取片段与尾帧

以上全部需要登录，且只能看到自己的数据：
  POST /auth/register / POST /auth/login → {"token": ...}；GET /auth/me
"""
import os
import copy
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import __version__
from pipeline.config import load_settings
from pipeline.convert import ConversionError, ConvertParams, convert_text
from pipeline import novel_memory, verification
from pipeline.chat import ChatInvoker
from render import keyframes as keyframes_mod
from render import plan as render_plan_mod
from render import compose as render_compose
from render import providers as render_providers
from render import runner as render_runner
from render import session as render_session
from pipeline.manifest import sum_usage
from server import admin as admin_mod
from server import audit, auth, library, novels, pricing, store, usage
# 人读版生产包（Markdown）与机器可读清单共用 render/plan.py 的提示词组装
from adapters import seedance

app = FastAPI(title="小说 → 分镜 IR 转换服务", version=__version__)

# 前端（frontend/）独立部署，跨源直连本服务；限定来源用 STORYBOARD_CORS_ORIGINS（逗号分隔）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in
                   os.environ.get("STORYBOARD_CORS_ORIGINS", "*").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

_executor = ThreadPoolExecutor(
    max_workers=int(os.environ.get("STORYBOARD_SERVER_WORKERS", "1")))
_jobs: dict = {}
_lock = threading.Lock()

_D = ConvertParams()


# ---------- 认证 ----------

def current_user(authorization: str = Header(default="")) -> dict:
    """所有业务接口的守门人：没有合法 token 就看不到任何数据。"""
    token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    user = auth.verify_token(token)
    if user is None:
        raise HTTPException(401, "未登录或登录已过期")
    auth.touch_seen(user["id"])
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    """管理接口的守门人：前端隐藏入口只是体验，权限以这里为准。"""
    if user.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


class Credentials(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


@app.post("/auth/register")
def register(body: Credentials):
    try:
        user = auth.register(body.username, body.password)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    # 首个用户会接管单用户时代的历史记录，这些旧产物的资产卡也要一并进库，
    # 否则新账号打开资产库页会是空的（迁移只搬了历史文件）
    try:
        filled = library.backfill_from_runs(user["id"])
        if filled:
            print(f"[library] 已从接管的历史记录补齐资产库：{filled}", flush=True)
    except (OSError, ValueError) as e:
        print(f"[library] 资产库回填失败（可在资产库页手动补齐）：{e!r}", flush=True)
    return {"token": auth.issue_token(user["id"]), "user": user}


@app.post("/auth/login")
def login(body: Credentials):
    try:
        user = auth.authenticate(body.username, body.password)
    except auth.AuthError as e:
        raise HTTPException(401, str(e))
    return {"token": auth.issue_token(user["id"]), "user": user}


@app.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return user


# ---------- 转换 ----------

def _record_usage(job: dict, manifest: dict, ok: bool, settings=None) -> None:
    """一次转换落一行用量（成功、失败都记；一次模型调用都没有就不记）。

    评审与转换共用一个用量回调，分不出模型：评审换了模型时整笔记在转换模型名下，
    并标 mixed_models，后台据此提示「金额按转换模型估算」。
    """
    try:
        totals = sum_usage((manifest or {}).get("attempts") or [])
        if not totals.get("calls"):
            return
        model = ((manifest or {}).get("contracts") or {}).get("model") \
            or (settings.model if settings else load_settings().model)
        mixed = None
        if settings is not None and settings.review_enabled and settings.review_model \
                and settings.review_model != model:
            mixed = [model, settings.review_model]
        usage.record(user_id=job["user_id"], purpose="convert", model=model, usage=totals,
                     ok=ok, chars=((manifest or {}).get("input") or {}).get("normalized_chars")
                     or job.get("chars") or 0,
                     novel_id=job.get("novel_id"), chapter_id=job.get("chapter_id"),
                     version_id=job.get("version_id") or job.get("id"), mixed_models=mixed)
    except Exception as e:  # 落账失败绝不能拖垮转换/整理本身
        print(f"[usage] 落账失败：{e!r}", flush=True)


def _record_chat_usage(user_id: str, nid: str, cid: str, chat, ok: bool) -> None:
    totals_fn = getattr(chat, "usage_totals", None)
    if totals_fn is None:
        return
    totals = totals_fn()
    if not totals.get("calls"):
        return
    try:
        usage.record(user_id=user_id, purpose="digest", model=load_settings().model,
                     usage=totals, ok=ok, novel_id=nid, chapter_id=cid)
    except Exception as e:  # 落账失败绝不能拖垮转换/整理本身
        print(f"[usage] 落账失败：{e!r}", flush=True)


def _execute(job: dict, text: str, params: ConvertParams, strict: bool,
             seed: Optional[dict], persist, after_success,
             numbering: Optional[dict] = None,
             context: Optional[novel_memory.NovelContext] = None) -> None:
    """跑一次转换并把状态/产物写回。persist(status, **fields) 把状态落到章节的
    版本记录；after_success(job, log) 做成功后的长期记忆动作（首个成功版本自动采用）。"""
    job["status"] = "running"

    def save(status, **fields):
        try:
            persist(status, **fields)
            return True
        except OSError as e:
            log(f"警告：记录落盘失败（产物仍可从本次响应取走）：{e!r}")
            return False

    def log(msg):
        job["log"].append(str(msg))

    save("running")
    settings = load_settings()
    settings.strict = settings.strict or strict

    warnings: list = []
    manifest: dict = {}
    try:
        job["result"] = convert_text(text, params, settings=settings,
                                     log=log, warnings_out=warnings,
                                     seed_assets=seed, manifest_out=manifest,
                                     progress_out=job["progress"],
                                     on_partial=lambda d, k, n: _on_partial(job, d, k, n),
                                     start_numbering=numbering,
                                     novel_context=context)
        job["manifest"] = manifest
        job["verification"] = manifest.get("verification")
        job["partial"] = None    # 整章已出，预览作废；失败时则保留，已通过的批次照样能看
        if warnings:
            job["quality_report"] = "\n\n".join(warnings)
            job["status"] = "completed_with_warnings"
        else:
            job["status"] = "succeeded"
        # 转换慢且花钱，产物必须落盘——内存任务表重启即清空
        job["persisted"] = save(
            job["status"], result=job["result"], quality_report=job["quality_report"],
            manifest=manifest, verification=job["verification"], error=None)
        _record_usage(job, manifest, True, settings)
        try:
            after_success(job, log)
        except (OSError, ValueError, LookupError) as e:
            log(f"警告：写入长期记忆失败：{e!r}")
    except ConversionError as e:
        job["status"] = "failed"
        job["error"] = f"{e}\n{e.report}"
        job["manifest"] = manifest
        if manifest:
            manifest["state"] = "failed"
        job["verification"] = manifest.get("verification")
        save("failed", error=job["error"], manifest=manifest,
             verification=job["verification"])
        _record_usage(job, manifest, False, settings)
    except Exception as e:  # LLM/网络等运行期错误
        job["status"] = "failed"
        job["error"] = repr(e)
        job["manifest"] = manifest
        if manifest:
            manifest["state"] = "failed"
        save("failed", error=job["error"], manifest=manifest)
        _record_usage(job, manifest, False, settings)


def _on_partial(job: dict, doc: dict, done: int, total: int) -> None:
    """转换线程回调：已完成批次的合并结果，供整章跑完前先审阅。"""
    job["partial"] = {"doc": doc, "batches_done": done, "batches": total}


def _progress_view(job: dict) -> Optional[dict]:
    """进度快照 + 服务端算好的已用/预计剩余秒数（不让浏览器拿自己的时钟去减）。

    预计剩余按已完成字数线性外推：第一批跑完之前没有依据，宁可不给也不瞎猜。
    """
    p = dict(job.get("progress") or {})
    if not p:
        return None
    started = p.pop("started_at", None)
    elapsed = time.time() - started if started else None
    p["elapsed_sec"] = round(elapsed) if elapsed is not None else None
    done, total = p.get("done_chars") or 0, p.get("total_chars") or 0
    running = job.get("status") in ("queued", "running") and p.get("phase") != "done"
    p["eta_sec"] = (round(elapsed / done * (total - done))
                    if running and elapsed and done and total > done else None)
    return p


@app.get("/jobs")
def list_jobs(user: dict = Depends(current_user)):
    """本人在跑/刚结束的任务摘要（不含分镜正文与日志）。

    转换是分钟级任务，前端关掉页面后转换仍在后台继续；靠这个接口重新接上，
    不必守着页面等。
    """
    with _lock:
        jobs = [j for j in _jobs.values() if j.get("user_id") == user["id"]]
    return {"jobs": [{
        "id": j["id"], "status": j["status"], "created_at": j.get("created_at"),
        "work_title": j.get("work_title"), "chapter": j.get("chapter"),
        "novel_id": j.get("novel_id"), "chapter_id": j.get("chapter_id"),
        "chars": j.get("chars"), "log_lines": len(j["log"]),
        "last_log": j["log"][-1] if j["log"] else None,
        "progress": _progress_view(j),
    } for j in sorted(jobs, key=lambda x: x.get("created_at") or "", reverse=True)]}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, user: dict = Depends(current_user)):
    with _lock:
        job = _jobs.get(job_id)
    if job is None or job.get("user_id") != user["id"]:
        raise HTTPException(404, "job 不存在（服务重启会清空任务表）")
    # 部分产物有几百 KB，轮询每 1.5 秒一次，只带批数；要看再走 /partial 取
    out = {k: v for k, v in job.items() if k not in ("user_id", "partial")}
    out["progress"] = _progress_view(job)
    out["partial_batches"] = (job.get("partial") or {}).get("batches_done", 0)
    return out


@app.get("/jobs/{job_id}/partial")
def get_job_partial(job_id: str, user: dict = Depends(current_user)):
    """已完成批次的合并结果（只读预览）。整章成功后不再提供，失败时保留。"""
    with _lock:
        job = _jobs.get(job_id)
    if job is None or job.get("user_id") != user["id"]:
        raise HTTPException(404, "job 不存在（服务重启会清空任务表）")
    if not job.get("partial"):
        raise HTTPException(404, "暂无已完成的批次可预览")
    return job["partial"]


def _frozen_of(record: dict) -> Optional[list]:
    """一条记录的冻结证据：清单里的冻结句单元；旧记录没有清单，就用它当时产物里的句单元。"""
    frozen = ((record.get("manifest") or {}).get("scope") or {}).get("units")
    if not frozen:
        frozen = [{k: unit.get(k) for k in ("id", "text", "para")}
                  for unit in ((record.get("result") or {}).get("source") or {})
                  .get("units") or []]
    return frozen or None


def _reverify(existing: dict, result: dict,
              context: Optional[novel_memory.NovelContext] = None):
    """人工编辑后的整份复验。不合格标 draft_invalid 但照样保存（不丢人的工作）。
    小说章节的版本另带长期记忆软核查（只记 MEDIUM，不影响状态）。"""
    doc = copy.deepcopy(result)
    frozen = _frozen_of(existing)
    probe = verification.verify_document(doc, frozen_units=frozen)
    verification.recompute_coverage_field(doc, probe.coverage)
    report = verification.verify_document(doc, frozen_units=frozen)
    report.findings.extend(novel_memory.soft_findings(doc, context))
    previous_status = existing.get("status")
    status = ((previous_status if previous_status in
               ("succeeded", "completed_with_warnings") else "succeeded")
              if report.ok else "draft_invalid")
    return doc, report, status, frozen


# ---------- 小说级会话：小说 → 章节 → 版本 ----------

_migrated_users: set = set()


def novel_user(user: dict = Depends(current_user)) -> dict:
    """小说接口的守门人：在 current_user 之上，首次访问时把旧数据迁到小说结构下。"""
    if user["id"] not in _migrated_users:
        try:
            r = novels.migrate_legacy(user["id"])
            if r.get("migrated") and (r.get("novels") or r.get("chapters")):
                print(f"[novels] 旧数据已迁移：{r}", flush=True)
        except OSError as e:
            print(f"[novels] 旧数据迁移失败（旧接口仍可用）：{e!r}", flush=True)
        _migrated_users.add(user["id"])
    return user


def _novel_call(fn, *args, **kwargs):
    """把存储层的业务异常翻成 HTTP 状态码。"""
    try:
        return fn(*args, **kwargs)
    except novels.NotFound as e:
        raise HTTPException(404, str(e))
    except novels.NovelError as e:
        raise HTTPException(422, str(e))


class NovelBody(BaseModel):
    title: Optional[str] = None
    # 小说级默认制作参数（ConvertParams 的字段，作品名/章节名除外）
    params: Optional[dict] = None


class ChapterBody(BaseModel):
    title: Optional[str] = None
    text: Optional[str] = None
    order: Optional[int] = None


class VersionRequest(BaseModel):
    # 本次转换对小说默认参数的覆写（只存在本版本里）
    overrides: dict = Field(default_factory=dict)
    strict: bool = False


_PARAM_FIELDS = set(ConvertParams.__dataclass_fields__) - {"work_title", "chapter"}


def _clean_params(params: Optional[dict]) -> dict:
    unknown = set(params or {}) - _PARAM_FIELDS
    if unknown:
        raise HTTPException(422, f"未知的制作参数：{sorted(unknown)}")
    return dict(params or {})


@app.get("/novels")
def novels_list(user: dict = Depends(novel_user)):
    return {"novels": novels.list_novels(user["id"])}


@app.post("/novels")
def novels_create(body: NovelBody, user: dict = Depends(novel_user)):
    return _novel_call(novels.create_novel, user["id"], body.title or "",
                       _clean_params(body.params))


@app.get("/novels/{nid}")
def novels_get(nid: str, user: dict = Depends(novel_user)):
    return _novel_call(novels.get_novel, user["id"], nid)


@app.patch("/novels/{nid}")
def novels_update(nid: str, body: NovelBody, user: dict = Depends(novel_user)):
    params = _clean_params(body.params) if body.params is not None else None
    return _novel_call(novels.update_novel, user["id"], nid, title=body.title,
                       params=params)


@app.delete("/novels/{nid}")
def novels_delete(nid: str, user: dict = Depends(novel_user)):
    _novel_call(novels.delete_novel, user["id"], nid)
    return {"deleted": nid}


@app.post("/novels/{nid}/chapters")
def chapters_create(nid: str, body: ChapterBody, user: dict = Depends(novel_user)):
    return _novel_call(novels.create_chapter, user["id"], nid, body.title or "",
                       body.text or "", body.order)


@app.get("/novels/{nid}/chapters/{cid}")
def chapters_get(nid: str, cid: str, user: dict = Depends(novel_user)):
    return _novel_call(novels.get_chapter, user["id"], nid, cid)


@app.patch("/novels/{nid}/chapters/{cid}")
def chapters_update(nid: str, cid: str, body: ChapterBody,
                    user: dict = Depends(novel_user)):
    return _novel_call(novels.update_chapter, user["id"], nid, cid,
                       title=body.title, text=body.text, order=body.order)


@app.delete("/novels/{nid}/chapters/{cid}")
def chapters_delete(nid: str, cid: str, user: dict = Depends(novel_user)):
    _novel_call(novels.delete_chapter, user["id"], nid, cid)
    return {"deleted": cid}


def _run_version_job(job: dict, user_id: str, nid: str, cid: str, text: str,
                     params: ConvertParams, strict: bool) -> None:
    """新接口：转换某章，产物落成该章的一个版本；本章还没有采用版时自动采用。"""
    seed = novels.seed_assets(user_id, nid)
    if seed:
        n = sum(len(v) for v in seed.values())
        job["log"].append(f"沿用《{params.work_title}》的资产库共 {n} 张卡"
                          "（模型须复用其 ID 与描述）")
    numbering = novels.start_numbering(user_id, nid, cid)
    if numbering:
        job["log"].append(f"编号接续本书此前章节：句子从 u{numbering['next_unit']:04d}、"
                          f"分集从 E{numbering['next_episode']:02d} 起")
    context = novels.novel_context(user_id, nid, cid)
    if not context.empty():
        job["log"].append(
            f"注入长期记忆：人物状态 {len(context.lifecycle)} 条、此前章节摘要 "
            f"{len(context.synopses)} 章{'、全书梗概' if context.outline else ''}、"
            f"创作限制 {len(context.constraints)} 条")

    def after_success(job, log):
        chapter = novels.get_chapter(user_id, nid, cid)
        if chapter.get("adopted_version"):
            log("本章已有采用版，这一版仅存档；要用它请在版本列表里点「采用」")
            return
        r = novels.adopt_version(user_id, nid, cid, job["id"])
        log(f"已自动采用为本章首个成功版本：资产库新增 {r['added']} 张、"
            f"合并 {r['merged']} 张")
        if _schedule_digest(user_id, nid, cid):
            log("章后整理已排队：提取人物生命周期提议与本章摘要（待人工确认）")

    _execute(job, text, params, strict, seed,
             lambda status, **f: novels.update_version_state(
                 user_id, nid, cid, job["id"], status, **f),
             after_success, numbering, context)


def _digest_chat():
    """章后整理用的模型（测试替换成 FakeChat）。"""
    return ChatInvoker(load_settings())


def _run_digest(user_id: str, nid: str, cid: str) -> None:
    """采用版本后的一次小调用：生命周期提议 + 本章摘要。失败只记在章节上，
    不影响已经采用的版本——这是锦上添花，人可以手动补。"""
    chat, ok = None, False
    try:
        vid, units, characters = novels.digest_input(user_id, nid, cid)
        chat = _digest_chat()
        proposals, synopsis, dropped = novel_memory.run_digest(chat, units, characters)
        novels.record_digest(user_id, nid, cid, vid, proposals, synopsis, dropped)
        ok = True
    except Exception as e:  # 网络/解析/章节被删——都只是这一步没做成
        try:
            novels.set_digest_state(user_id, nid, cid, "failed", error=repr(e)[:300])
        except (OSError, ValueError, LookupError):
            pass
    finally:
        if chat is not None:
            _record_chat_usage(user_id, nid, cid, chat, ok)


def _schedule_digest(user_id: str, nid: str, cid: str) -> bool:
    if not load_settings().chapter_digest:
        novels.set_digest_state(user_id, nid, cid, "off")
        return False
    novels.set_digest_state(user_id, nid, cid, "running")
    _executor.submit(_run_digest, user_id, nid, cid)
    return True


@app.post("/novels/{nid}/chapters/{cid}/versions")
def versions_create(nid: str, cid: str, req: VersionRequest,
                    user: dict = Depends(novel_user)):
    """转换本章 → 新版本。返回 job_id（即版本 id），进度/分批预览照旧走 /jobs。"""
    novel = _novel_call(novels.get_novel, user["id"], nid)
    chapter = _novel_call(novels.get_chapter, user["id"], nid, cid)
    text = chapter.get("text") or ""
    if not text.strip():
        raise HTTPException(422, "本章还没有原文")
    raw = auth.get_user_raw(user["id"])
    cap = raw.get("monthly_cap_usd") if raw else None
    if cap is not None and usage.month_spent(user["id"], pricing.load()) >= cap:
        raise HTTPException(429, "本月用量已达上限，请联系管理员")
    merged = {**_clean_params(novel.get("params")), **_clean_params(req.overrides)}
    params = ConvertParams(**{**merged, "work_title": novel["title"],
                              "chapter": chapter["title"]})
    job_id = uuid.uuid4().hex[:12]
    _novel_call(novels.create_version, user["id"], nid, cid, job_id,
                {**merged, "strict": req.strict}, text)
    job = {"id": job_id, "user_id": user["id"], "status": "queued", "log": [],
           "result": None, "quality_report": None, "error": None, "persisted": True,
           "created_at": store.now_iso(), "work_title": novel["title"],
           "chapter": chapter["title"], "chars": len(text), "progress": {},
           "partial": None, "novel_id": nid, "chapter_id": cid, "version_id": job_id}
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_run_version_job, job, user["id"], nid, cid, text, params,
                     req.strict)
    return {"job_id": job_id, "version_id": job_id, "status_url": f"/jobs/{job_id}"}


@app.get("/novels/{nid}/chapters/{cid}/versions/{vid}")
def versions_get(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    return _novel_call(novels.get_version, user["id"], nid, cid, vid)


@app.put("/novels/{nid}/chapters/{cid}/versions/{vid}")
def versions_update(nid: str, cid: str, vid: str,
                    result: dict = Body(..., embed=False),
                    user: dict = Depends(novel_user)):
    """人工编辑 + 整份复验。采用版被改了，长期记忆随之按改后的产物更新。"""
    existing = _novel_call(novels.get_version, user["id"], nid, cid, vid)
    context = _novel_call(novels.novel_context, user["id"], nid, cid)
    doc, report, status, frozen = _reverify(existing, result, context)
    v = _novel_call(novels.update_version_result, user["id"], nid, cid, vid, doc,
                    verification=report.to_dict(), status=status, frozen_units=frozen)
    return {"id": vid, "edited_at": v["edited_at"], "status": status,
            "verification": report.to_dict()}


@app.delete("/novels/{nid}/chapters/{cid}/versions/{vid}")
def versions_delete(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    _novel_call(novels.delete_version, user["id"], nid, cid, vid)
    return {"deleted": vid}


@app.post("/novels/{nid}/chapters/{cid}/versions/{vid}/adopt")
def versions_adopt(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    r = _novel_call(novels.adopt_version, user["id"], nid, cid, vid)
    if r.get("changed"):
        r["digest"] = "running" if _schedule_digest(user["id"], nid, cid) else "off"
    return r


@app.post("/novels/{nid}/chapters/{cid}/digest")
def chapters_digest(nid: str, cid: str, user: dict = Depends(novel_user)):
    """手动重跑章后整理（上次失败、或关着开关时采用的）。"""
    _novel_call(novels.digest_input, user["id"], nid, cid)
    if not load_settings().chapter_digest:
        raise HTTPException(422, "章后整理已关闭（STORYBOARD_CHAPTER_DIGEST=0）")
    _schedule_digest(user["id"], nid, cid)
    return {"digest": "running"}


@app.get("/novels/{nid}/memory")
def memory_get(nid: str, user: dict = Depends(novel_user)):
    return _novel_call(novels.get_memory, user["id"], nid)


@app.put("/novels/{nid}/memory/assets/{kind}/{card_id}")
def memory_asset_upsert(nid: str, kind: str, card_id: str,
                        card: dict = Body(..., embed=False),
                        user: dict = Depends(novel_user)):
    if card.get("id") != card_id:
        raise HTTPException(422, f"卡片 id 与路径不一致：{card.get('id')!r} != {card_id!r}")
    return _novel_call(novels.upsert_asset, user["id"], nid, kind, card)


@app.delete("/novels/{nid}/memory/assets/{kind}/{card_id}")
def memory_asset_delete(nid: str, kind: str, card_id: str,
                        user: dict = Depends(novel_user)):
    _novel_call(novels.delete_asset, user["id"], nid, kind, card_id)
    return {"deleted": card_id}


# ---------- 渲染任务包 ----------

def _render_gate(doc: dict, record: Optional[dict]):
    """分镜未通过独立验证禁止进入付费渲染（渲染任务包与出片共用）。会改写 doc 的覆盖率字段。"""
    frozen = _frozen_of(record) if record else None
    probe = verification.verify_document(doc, frozen_units=frozen or None)
    verification.recompute_coverage_field(doc, probe.coverage)
    report = verification.verify_document(doc, frozen_units=frozen or None)
    if not report.ok:
        raise HTTPException(422, detail={
            "message": "分镜未通过独立验证，禁止进入付费渲染",
            "verification": report.to_dict(),
        })
    return report


class RenderPlanRequest(BaseModel):
    """要渲染的分镜。传当前屏幕上的产物而不是只按 run_id 取，
    这样人工编辑还没保存也能先导出来看提示词与费用。"""
    result: dict
    max_clip_seconds: float = Field(15.0, gt=0, le=60)
    run_id: Optional[str] = None
    include_markdown: bool = True
    # 费率档位；cny_per_second 显式覆盖（拿真实账单标定后填这里最准）
    model: str = render_plan_mod.DEFAULT_TIER
    cny_per_second: Optional[float] = Field(None, gt=0, le=1000)


@app.post("/render/plan")
def render_plan(req: RenderPlanRequest, user: dict = Depends(current_user)):
    """分镜 IR → 渲染任务清单（+ 人读版生产包）。

    只读操作，不碰 IR 也不落盘：这一步的价值是让人在花钱之前，先逐条核对
    提示词、看清楚要出几张图、以及这一章大概要烧多少钱。
    """
    doc = copy.deepcopy(req.result)
    record = None
    if req.run_id:
        try:
            record = novels.find_version(user["id"], req.run_id)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if record is None:
            raise HTTPException(404, "版本不存在")
    report = _render_gate(doc, record)
    try:
        plan = render_plan_mod.build_plan(doc, req.max_clip_seconds, req.run_id,
                                          req.model, req.cny_per_second)
    except (KeyError, TypeError) as e:
        raise HTTPException(422, f"分镜结构不完整，无法组装渲染任务：{e}")

    packs = []
    if req.include_markdown:
        for ep in doc.get("episodes") or []:
            packs.append({"episode": ep.get("id"),
                          "title": ep.get("title", ""),
                          "markdown": seedance.render_episode(
                              doc, ep, req.max_clip_seconds)})
    return {"plan": plan, "packs": packs, "verification": report.to_dict()}


class KeyframesRequest(BaseModel):
    result: dict


@app.post("/render/keyframes")
def render_keyframes(req: KeyframesRequest, user: dict = Depends(current_user)):
    """每镜一条关键帧出图提示词。传屏幕上的产物（可能还没保存），改完镜头立刻能看到变化。"""
    try:
        return {"keyframes": keyframes_mod.keyframe_plan(req.result)}
    except (KeyError, TypeError, AttributeError) as e:
        raise HTTPException(422, f"分镜结构不完整，无法组装关键帧提示词：{e}")


_KF = "/novels/{nid}/chapters/{cid}/versions/{vid}/keyframes"


@app.get(_KF)
def keyframes_list(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    return {"shots": _novel_call(novels.list_keyframes, user["id"], nid, cid, vid)}


@app.put(_KF + "/{shot_id}")
async def keyframes_put(nid: str, cid: str, vid: str, shot_id: str, request: Request,
                        user: dict = Depends(novel_user)):
    data = await request.body()
    return _novel_call(novels.save_keyframe, user["id"], nid, cid, vid, shot_id,
                       request.headers.get("content-type", ""), data)


@app.get(_KF + "/{shot_id}")
def keyframes_get(nid: str, cid: str, vid: str, shot_id: str,
                  user: dict = Depends(novel_user)):
    path, kind = _novel_call(novels.keyframe_file, user["id"], nid, cid, vid, shot_id)
    return FileResponse(path, media_type=kind)


@app.delete(_KF + "/{shot_id}")
def keyframes_delete(nid: str, cid: str, vid: str, shot_id: str,
                     user: dict = Depends(novel_user)):
    _novel_call(novels.delete_keyframe, user["id"], nid, cid, vid, shot_id)
    return {"deleted": shot_id}


# ---------- 出片（视频生成）：会话在 chapters/<cid>/render/<vid>/，不进 IR ----------

_R = "/novels/{nid}/chapters/{cid}/versions/{vid}/render"


def _keyframe_paths(uid: str, nid: str, cid: str, vid: str) -> dict:
    return {sid: novels.keyframe_file(uid, nid, cid, vid, sid)[0]
            for sid in novels.list_keyframes(uid, nid, cid, vid)}


def _render_ctx(user: dict, nid: str, cid: str, vid: str, gate: bool = True) -> tuple:
    """(会话目录, 已保存的分镜, 关键帧, 归属)。出片只用已保存的版本内容；gate 时过验证门。"""
    uid = user["id"]
    record = _novel_call(novels.get_version, uid, nid, cid, vid)
    root = _novel_call(novels.render_dir, uid, nid, cid, vid)
    doc = record.get("result") or {}
    if gate:
        if not doc.get("episodes"):
            raise HTTPException(422, "这个版本还没有分镜产物")
        _render_gate(copy.deepcopy(doc), record)
    owner = {"user_id": uid, "nid": nid, "cid": cid, "vid": vid}
    return root, doc, _keyframe_paths(uid, nid, cid, vid), owner


def _render_call(fn, *args, **kwargs):
    """把出片会话的业务异常翻成 HTTP 状态码。"""
    try:
        return fn(*args, **kwargs)
    except render_session.NotFound as e:
        raise HTTPException(404, str(e))
    except render_session.Conflict as e:
        raise HTTPException(409, detail={"message": str(e), "expected_cny": e.expected_cny})
    except render_session.Corrupt:
        raise HTTPException(500, "出片记录文件已损坏，原文件已备份，请联系管理员处理")
    except render_session.SessionError as e:
        raise HTTPException(422, str(e))


def _render_request(root, s: dict, clip: dict):
    """出片线程提交前：按已保存的分镜与关键帧重建这一段的厂商请求。"""
    o = s["owner"]
    record = novels.get_version(o["user_id"], o["nid"], o["cid"], o["vid"])
    provider = render_providers.get_video(s["provider"])
    return render_compose.request_for(
        record.get("result") or {}, s, clip,
        keyframes=_keyframe_paths(o["user_id"], o["nid"], o["cid"], o["vid"]),
        relay_frame=render_session.relay_frame(root, s, clip),
        caps=provider.caps(s["model"]), rewrite=provider.rewrite_prompt)


_render_runner = render_runner.Runner(
    _render_request,
    poll_sec=float(os.environ.get("STORYBOARD_RENDER_POLL_SEC", "10")),
    max_parallel=int(os.environ.get("STORYBOARD_RENDER_PARALLEL", "2")))


@app.on_event("startup")
def _start_render_runner():
    """出片线程随服务启动，续上重启前没跑完的段。STORYBOARD_RENDER_RUNNER=0 关闭（测试里手动 tick）。"""
    if os.environ.get("STORYBOARD_RENDER_RUNNER", "1") == "0":
        return
    n = _render_runner.recover(auth.DATA_DIR)
    if n:
        print(f"[render] 续上 {n} 个出片会话", flush=True)
    _render_runner.start()


class RenderSettingsBody(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    resolution: Optional[str] = None
    audio_mode: Optional[str] = None
    budget_cny: Optional[float] = Field(None, gt=0, le=100000)
    confirm_over_cny: Optional[float] = Field(None, ge=0, le=100000)


class RenderRunBody(BaseModel):
    expected_cny: Optional[float] = Field(None, ge=0)


class RenderChosenBody(BaseModel):
    attempt: int = Field(ge=0)


class RenderClipBody(BaseModel):
    mute_native: bool


@app.post(_R + "/session")
def render_session_post(nid: str, cid: str, vid: str, body: Optional[RenderSettingsBody] = None,
                        user: dict = Depends(novel_user)):
    """过验证门、按设置切段，生成或重建会话（不花钱）。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    patch = body.model_dump(exclude_none=True) if body else {}
    s = _render_call(render_session.build, root, doc, owner=owner, patch=patch, keyframes=kfs)
    return _render_call(render_session.view, s)


@app.get(_R + "/session")
def render_session_get(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    """查询；按当前已保存的分镜重算指纹并标过期（在跑的段不动）。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid, gate=False)
    if render_session.load(root) is None:
        raise HTTPException(404, "还没有出片会话")
    s = _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                     allow_in_flight=True)
    return _render_call(render_session.view, s)


@app.patch(_R + "/session")
def render_session_patch(nid: str, cid: str, vid: str, body: RenderSettingsBody,
                         user: dict = Depends(novel_user)):
    """改设置（厂商、档位、分辨率、声音模式、上限）。有段在跑时 409。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    if render_session.load(root) is None:
        raise HTTPException(404, "还没有出片会话")
    s = _render_call(render_session.build, root, doc, owner=owner,
                     patch=body.model_dump(exclude_none=True), keyframes=kfs)
    return _render_call(render_session.view, s)


@app.post(_R + "/clips/{clip_id}/run")
def render_clip_run(nid: str, cid: str, vid: str, clip_id: str,
                    body: Optional[RenderRunBody] = None, user: dict = Depends(novel_user)):
    """出这一段（试段或重做）。超过确认线时要带 expected_cny。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                 allow_in_flight=True)
    s = _render_call(render_session.queue_run, root, [clip_id], body.expected_cny if body else None)
    _render_runner.watch(root)
    return _render_call(render_session.view, s)


@app.post(_R + "/run")
def render_run_all(nid: str, cid: str, vid: str, body: RenderRunBody,
                   user: dict = Depends(novel_user)):
    """批量出剩余各段：必须带用户确认的预估金额，服务端重算不一致 409。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                 allow_in_flight=True)
    s = _render_call(render_session.queue_run, root, None, body.expected_cny)
    _render_runner.watch(root)
    return _render_call(render_session.view, s)


@app.put(_R + "/clips/{clip_id}/chosen")
def render_clip_chosen(nid: str, cid: str, vid: str, clip_id: str, body: RenderChosenBody,
                       user: dict = Depends(novel_user)):
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid)
    s = _render_call(render_session.set_chosen, root, clip_id, body.attempt)
    return _render_call(render_session.view, s)


@app.patch(_R + "/clips/{clip_id}")
def render_clip_patch(nid: str, cid: str, vid: str, clip_id: str, body: RenderClipBody,
                      user: dict = Depends(novel_user)):
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid)
    s = _render_call(render_session.set_mute, root, clip_id, body.mute_native)
    return _render_call(render_session.view, s)


@app.get(_R + "/files/{path:path}")
def render_file(nid: str, cid: str, vid: str, path: str, user: dict = Depends(novel_user)):
    """取本版本出片目录下的文件（片段、尾帧）。拒绝路径穿越。"""
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target)


# ---------- 长期记忆：人物生命周期、主线剧情、创作限制 ----------

class LifecycleBody(BaseModel):
    character_id: str
    type: str
    detail: str = ""
    chapter_id: Optional[str] = None
    unit_ref: Optional[str] = None
    evidence_quote: str = ""


class LifecyclePatch(BaseModel):
    status: Optional[str] = None
    type: Optional[str] = None
    detail: Optional[str] = None


class OutlineBody(BaseModel):
    outline: str = ""


class SynopsisBody(BaseModel):
    synopsis: str = ""


class ConstraintBody(BaseModel):
    text: Optional[str] = None
    negative_prompt: Optional[str] = None
    keywords: Optional[list] = None
    enabled: Optional[bool] = None


@app.post("/novels/{nid}/memory/lifecycle")
def lifecycle_add(nid: str, body: LifecycleBody, user: dict = Depends(novel_user)):
    return _novel_call(novels.add_lifecycle, user["id"], nid, **body.model_dump())


@app.post("/novels/{nid}/memory/lifecycle/{lid}")
def lifecycle_update(nid: str, lid: str, body: LifecyclePatch,
                     user: dict = Depends(novel_user)):
    return _novel_call(novels.update_lifecycle, user["id"], nid, lid, **body.model_dump())


@app.delete("/novels/{nid}/memory/lifecycle/{lid}")
def lifecycle_delete(nid: str, lid: str, user: dict = Depends(novel_user)):
    _novel_call(novels.delete_lifecycle, user["id"], nid, lid)
    return {"deleted": lid}


@app.put("/novels/{nid}/memory/plot")
def plot_outline(nid: str, body: OutlineBody, user: dict = Depends(novel_user)):
    return _novel_call(novels.set_outline, user["id"], nid, body.outline)


@app.put("/novels/{nid}/memory/plot/chapters/{cid}")
def plot_synopsis(nid: str, cid: str, body: SynopsisBody,
                  user: dict = Depends(novel_user)):
    return _novel_call(novels.set_synopsis, user["id"], nid, cid, body.synopsis)


@app.post("/novels/{nid}/memory/constraints")
def constraints_add(nid: str, body: ConstraintBody, user: dict = Depends(novel_user)):
    return _novel_call(novels.add_constraint, user["id"], nid,
                       body.model_dump(exclude_none=True))


@app.patch("/novels/{nid}/memory/constraints/{kid}")
def constraints_update(nid: str, kid: str, body: ConstraintBody,
                       user: dict = Depends(novel_user)):
    return _novel_call(novels.update_constraint, user["id"], nid, kid,
                       body.model_dump(exclude_none=True))


@app.delete("/novels/{nid}/memory/constraints/{kid}")
def constraints_delete(nid: str, kid: str, user: dict = Depends(novel_user)):
    _novel_call(novels.delete_constraint, user["id"], nid, kid)
    return {"deleted": kid}


# ---------- 探针 ----------

# ---------- 管理后台 ----------

class AdminPatch(BaseModel):
    disabled: Optional[bool] = None
    role: Optional[str] = None
    monthly_cap_usd: Optional[float] = None


class AdminPassword(BaseModel):
    password: str = Field(..., min_length=1)


def _admin_call(fn, *args):
    try:
        return fn(*args)
    except admin_mod.NotFound as e:
        raise HTTPException(404, str(e))
    except admin_mod.AdminError as e:
        raise HTTPException(400, str(e))


def _running_jobs() -> list:
    with _lock:
        return [dict(j) for j in _jobs.values()]


@app.get("/admin/overview")
def admin_overview(user: dict = Depends(admin_user)):
    running = sum(1 for j in _running_jobs() if j.get("status") in ("queued", "running"))
    return admin_mod.overview(pricing.load(), running)


@app.get("/admin/users")
def admin_users(user: dict = Depends(admin_user)):
    return {"users": admin_mod.user_rows(pricing.load())}


@app.get("/admin/users/{uid}")
def admin_user_detail(uid: str, user: dict = Depends(admin_user)):
    return _admin_call(admin_mod.user_detail, uid, pricing.load())


@app.patch("/admin/users/{uid}")
def admin_patch_user(uid: str, body: AdminPatch, user: dict = Depends(admin_user)):
    # 只取请求里真正带了的字段：「设为不限」要传 null，不能和「没传」混为一谈
    fields = body.model_dump(exclude_unset=True)
    return _admin_call(admin_mod.patch_user, user, uid, fields)


@app.post("/admin/users/{uid}/password")
def admin_reset_password(uid: str, body: AdminPassword, user: dict = Depends(admin_user)):
    _admin_call(admin_mod.reset_password, user, uid, body.password)
    return {"ok": True}


@app.get("/admin/usage")
def admin_usage(group: str = "user", days: int = Query(30),
                user: dict = Depends(admin_user)):
    if days not in (7, 30, 90):
        raise HTTPException(422, "days 只能是 7、30、90")
    return _admin_call(admin_mod.usage_report, group, days, pricing.load())


@app.get("/admin/usage.csv")
def admin_usage_csv(days: int = Query(30), user: dict = Depends(admin_user)):
    if days not in (7, 30, 90):
        raise HTTPException(422, "days 只能是 7、30、90")
    return Response(admin_mod.usage_csv(days, pricing.load()), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="usage-{days}d.csv"'})


@app.get("/admin/jobs")
def admin_jobs(user: dict = Depends(admin_user)):
    return admin_mod.jobs_view(_running_jobs())


@app.get("/admin/audit")
def admin_audit(limit: int = Query(200, ge=1, le=1000), user: dict = Depends(admin_user)):
    return {"audit": audit.read(limit)}


@app.get("/admin/pricing")
def admin_pricing(user: dict = Depends(admin_user)):
    return pricing.load()


@app.put("/admin/pricing")
def admin_pricing_put(table: dict = Body(...), user: dict = Depends(admin_user)):
    before = pricing.load()
    try:
        saved = pricing.save(table)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.write(user, "update_pricing", None, {"models": before.get("models")},
                {"models": saved["models"]})
    return saved


@app.get("/healthz")
def healthz():
    s = load_settings()
    return {"status": "ok", "model": s.model,
            "api_key_configured": bool(s.api_key),
            "users": auth.user_count()}

