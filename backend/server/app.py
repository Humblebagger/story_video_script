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
  GET                 /novels/{nid}/style-image   取小说的风格参考图
  PUT                 /novels/{nid}/style-image   上传（原始图片体，PNG / JPEG / WebP，≤ 8MB，替换删旧）
  DELETE              /novels/{nid}/style-image   删（没有也成功）
出片（视频生成，状态在 chapters/<cid>/render/<vid>/session.json，后台线程提交/轮询/下载）：
  POST/GET/PATCH      …/versions/{vid}/render/session           建立（过验证门）/ 查询（标过期）/ 改设置
  POST                …/versions/{vid}/render/clips/{clip}/run  出这一段（试段或重做）
  POST                …/versions/{vid}/render/run               批量出剩余各段（带确认金额，不一致 409）
  PUT / PATCH         …/render/clips/{clip}/chosen、…/clips/{clip}   采用某次 / 原声静音
  GET                 …/versions/{vid}/render/files/{path}      取片段与尾帧
  GET                 …/versions/{vid}/render/export.zip        导出剪辑工程（FCPXML + 素材 + 字幕 + 说明；成片已合成且未过期才可）

助手（spec docs/specs/2026-11-01-assistant-panel-design.md）：
  GET/DELETE  /novels/{nid}/assistant            历史 / 清空
  POST        /novels/{nid}/assistant/messages   发消息（SSE）；有待确认的卡时先按取消处理
  POST        /novels/{nid}/assistant/resume     确认卡上点了确认或取消，接着跑（SSE）
  POST        /novels/{nid}/assistant/undo       撤销助手的一次修改（不调模型）

以上全部需要登录，且只能看到自己的数据：
  POST /auth/register / POST /auth/login → {"token": ...}；GET /auth/me
"""
import hashlib
import logging
import os
import re
import copy
import json
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from typing import Optional

import anyio
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import iterate_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import __version__
from pipeline.config import load_settings
from pipeline.convert import ConversionError, ConvertParams, convert_text
from pipeline import novel_memory, verification
from pipeline.chat import ChatInvoker, UsageCallback, build_chat_model, replace_thinking
from assistant import events as assistant_events, graph as assistant_graph, store as assistant_store
from assistant import tools as assistant_tools
from assistant import actions as assistant_actions
from assistant import edits as assistant_edits
from langgraph.types import Command
from render import keyframes as keyframes_mod
from render import plan as render_plan_mod
from render import compose as render_compose
from render import providers as render_providers
from render import runner as render_runner
from render import session as render_session
from render import free as render_free
from render import mix as render_mix
from render import export_fcpxml as render_export_fcpxml
from render import voice as render_voice
from render.providers import base as render_video_base
from pipeline.manifest import sum_usage
from server import admin as admin_mod
from server import audit, auth, library, novels, pricing, store, summary, usage
from server.messages import compact, money, msg, render_zh, to_detail
# 人读版生产包（Markdown）与机器可读清单共用 render/plan.py 的提示词组装
from adapters import seedance

log = logging.getLogger("render.app")

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


def _jobs_view(user_id: str) -> list:
    """在跑任务的摘要（与 /jobs 同形），给助手的 jobs_running 工具用。"""
    with _lock:
        jobs = [j for j in _jobs.values() if j.get("user_id") == user_id]
    return [{"id": j["id"], "status": j["status"], "novel_id": j.get("novel_id"), "chapter": j.get("chapter"),
             "progress": _progress_view(j), "last_log": j["log"][-1] if j["log"] else None} for j in jobs]


assistant_tools.jobs_source = _jobs_view


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
    except novels.Busy as e:
        raise HTTPException(409, str(e))
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


@app.get("/novels/{nid}/summary")
def novels_summary(nid: str, user: dict = Depends(novel_user)):
    """概览、费用表、左栏章节卡片用：花费与各章进度汇总（只读，读会话不重算指纹）。"""
    return _novel_call(summary.novel_summary, user["id"], nid)


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


def _start_version(user: dict, nid: str, cid: str, overrides: dict, strict: bool) -> dict:
    """转换本章 → 新版本（接口与助手共用）。返回 job_id（即版本 id），进度/分批预览照旧走 /jobs。"""
    novel = _novel_call(novels.get_novel, user["id"], nid)
    chapter = _novel_call(novels.get_chapter, user["id"], nid, cid)
    text = chapter.get("text") or ""
    if not text.strip():
        raise HTTPException(422, "本章还没有原文")
    raw = auth.get_user_raw(user["id"])
    cap = raw.get("monthly_cap_usd") if raw else None
    if cap is not None and usage.month_spent(user["id"], pricing.load()) >= cap:
        raise HTTPException(429, "本月用量已达上限，请联系管理员")
    merged = {**_clean_params(novel.get("params")), **_clean_params(overrides)}
    params = ConvertParams(**{**merged, "work_title": novel["title"],
                              "chapter": chapter["title"]})
    job_id = uuid.uuid4().hex[:12]
    _novel_call(novels.create_version, user["id"], nid, cid, job_id,
                {**merged, "strict": strict}, text)
    job = {"id": job_id, "user_id": user["id"], "status": "queued", "log": [],
           "result": None, "quality_report": None, "error": None, "persisted": True,
           "created_at": store.now_iso(), "work_title": novel["title"],
           "chapter": chapter["title"], "chars": len(text), "progress": {},
           "partial": None, "novel_id": nid, "chapter_id": cid, "version_id": job_id}
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_run_version_job, job, user["id"], nid, cid, text, params, strict)
    return {"job_id": job_id, "version_id": job_id, "status_url": f"/jobs/{job_id}"}


@app.post("/novels/{nid}/chapters/{cid}/versions")
def versions_create(nid: str, cid: str, req: VersionRequest,
                    user: dict = Depends(novel_user)):
    """转换本章 → 新版本。返回 job_id（即版本 id），进度/分批预览照旧走 /jobs。"""
    return _start_version(user, nid, cid, req.overrides, req.strict)


@app.get("/novels/{nid}/chapters/{cid}/versions/{vid}")
def versions_get(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    return _novel_call(novels.get_version, user["id"], nid, cid, vid)


def _check_version_doc(user: dict, nid: str, cid: str, vid: str, doc: dict) -> dict:
    """人工编辑后的整份复验，不保存（助手出对比卡时预先告诉用户）：{ok, warnings（最多 5 条，隐去服务器目录）}。"""
    existing = _novel_call(novels.get_version, user["id"], nid, cid, vid)
    context = _novel_call(novels.novel_context, user["id"], nid, cid)
    _doc, report, _status, _frozen = _reverify(existing, doc, context)
    return {"ok": report.ok,
            "warnings": [_hide_root(f"{f.object_path}: {f.message}", auth.DATA_DIR) for f in report.errors][:5]}


def _save_version_doc(user: dict, nid: str, cid: str, vid: str, doc: dict) -> dict:
    """人工编辑 + 整份复验后保存（接口与助手共用）。不合格标 draft_invalid 但照样保存；采用版被改了，长期记忆随之更新。"""
    existing = _novel_call(novels.get_version, user["id"], nid, cid, vid)
    context = _novel_call(novels.novel_context, user["id"], nid, cid)
    doc, report, status, frozen = _reverify(existing, doc, context)
    v = _novel_call(novels.update_version_result, user["id"], nid, cid, vid, doc,
                    verification=report.to_dict(), status=status, frozen_units=frozen)
    return {"id": vid, "edited_at": v["edited_at"], "status": status,
            "verification": report.to_dict()}


@app.put("/novels/{nid}/chapters/{cid}/versions/{vid}")
def versions_update(nid: str, cid: str, vid: str,
                    result: dict = Body(..., embed=False),
                    user: dict = Depends(novel_user)):
    """人工编辑 + 整份复验。采用版被改了，长期记忆随之按改后的产物更新。"""
    return _save_version_doc(user, nid, cid, vid, result)


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


_STYLE = "/novels/{nid}/style-image"


@app.get(_STYLE)
def style_image_get(nid: str, user: dict = Depends(novel_user)):
    path, kind = _novel_call(novels.style_image_file, user["id"], nid)
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "no-store"})


@app.put(_STYLE)
async def style_image_put(nid: str, request: Request, user: dict = Depends(novel_user)):
    return _novel_call(novels.save_style_image, user["id"], nid,
                       request.headers.get("content-type", ""), await request.body())


@app.delete(_STYLE)
def style_image_delete(nid: str, user: dict = Depends(novel_user)):
    _novel_call(novels.delete_style_image, user["id"], nid)
    return {"deleted": True}


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
            raise HTTPException(422, detail=msg("film.session.no_storyboard"))
        _render_gate(copy.deepcopy(doc), record)
    owner = {"user_id": uid, "nid": nid, "cid": cid, "vid": vid}
    return root, doc, _keyframe_paths(uid, nid, cid, vid), owner


def _render_call(fn, *args, **kwargs):
    """把出片会话的业务异常翻成 HTTP 状态码；带代码的给消息对象（spec §3.2）。"""
    try:
        return fn(*args, **kwargs)
    except render_session.NotFound as e:
        raise HTTPException(404, detail=to_detail(e))
    except render_session.Conflict as e:
        raise HTTPException(409, detail=to_detail(e, expected_cny=e.expected_cny))
    except render_session.Corrupt:
        raise HTTPException(500, detail=msg("film.session.corrupt_admin"))
    except render_session.SessionError as e:
        raise HTTPException(422, detail=to_detail(e))


def _style_for(uid: str, nid: str) -> Optional[dict]:
    """这部小说当前的风格参考图（data URI + 哈希）。

    以小说记录里的元数据为准（没有元数据即没有图，哪怕目录里有残留文件）；
    哈希按实际读到的字节算，data URI 也用这同一份字节，记下的就是发出去的。
    """
    try:
        path, _ = novels.style_image_file(uid, nid)
        data = path.read_bytes()
    except (novels.NotFound, OSError):
        return None
    return {"source": render_compose.data_uri_bytes(data, path), "hash": hashlib.sha256(data).hexdigest()}


def _render_request(root, s: dict, clip: dict):
    """出片线程提交前：剧本段按已保存的分镜与关键帧重建厂商请求；自由节点按它存的正文与参考组装。"""
    o = s["owner"]
    record = novels.get_version(o["user_id"], o["nid"], o["cid"], o["vid"])
    provider = render_providers.get_video(s["provider"])
    kfs = _keyframe_paths(o["user_id"], o["nid"], o["cid"], o["vid"])
    style = _style_for(o["user_id"], o["nid"])
    if render_session.is_free(clip["id"]):
        return render_compose.request_for_free(
            record.get("result") or {}, s, clip, keyframes=kfs, tail_frame=render_free.tail_frame(root, s, clip),
            caps=provider.caps(s["model"]), rewrite=provider.rewrite_prompt, style=style)
    return render_compose.request_for(
        record.get("result") or {}, s, clip,
        keyframes=kfs, relay_frame=render_session.relay_frame(root, s, clip),
        caps=provider.caps(s["model"]), rewrite=provider.rewrite_prompt, style=style)


_render_runner = render_runner.Runner(
    _render_request,
    poll_sec=float(os.environ.get("STORYBOARD_RENDER_POLL_SEC", "10")),
    max_parallel=int(os.environ.get("STORYBOARD_RENDER_PARALLEL", "2")))


@app.on_event("startup")
def _start_render_runner():
    """出片线程随服务启动，续上重启前没跑完的段。STORYBOARD_RENDER_RUNNER=0 关闭（测试里手动 tick）。"""
    if os.environ.get("STORYBOARD_RENDER_RUNNER", "1") == "0":
        for path in Path(auth.DATA_DIR).glob(render_runner.SESSIONS_GLOB):   # 中断的合成照样收尾
            render_session.recover_compose(path.parent)
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
    s = _render_call(render_session.build, root, doc, owner=owner, patch=patch, keyframes=kfs,
                     style=_style_for(owner["user_id"], owner["nid"]))
    return _render_call(render_session.view, s)


def _gate_status(user: dict, nid: str, cid: str, vid: str) -> dict:
    """出片页签的前置检查：验证门结果。读取时只报告不拦（建会话、出片照旧过门）。"""
    record = _novel_call(novels.get_version, user["id"], nid, cid, vid)
    doc = record.get("result") or {}
    if not doc.get("episodes"):
        return {"ok": False, "message": "这个版本还没有分镜产物"}  # i18n: todo(4)
    try:
        _render_gate(copy.deepcopy(doc), record)
    except HTTPException as e:
        d = e.detail
        return {"ok": False, "message": d.get("message") if isinstance(d, dict) else str(d)}
    return {"ok": True, "message": None}


@app.get(_R + "/session")
def render_session_get(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    """查询；按当前已保存的分镜重算指纹并标过期（在跑的段不动），附验证门结果（只报告）。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid, gate=False)
    if render_session.load(root) is None:
        raise HTTPException(404, detail=msg("film.session.none"))
    s = _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                     allow_in_flight=True, style=_style_for(owner["user_id"], owner["nid"]))
    out = _render_call(render_session.view, s)
    out["gate"] = _gate_status(user, nid, cid, vid)
    return out


@app.patch(_R + "/session")
def render_session_patch(nid: str, cid: str, vid: str, body: RenderSettingsBody,
                         user: dict = Depends(novel_user)):
    """改设置（厂商、档位、分辨率、声音模式、上限）。有段在跑时 409。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    if render_session.load(root) is None:
        raise HTTPException(404, detail=msg("film.session.none"))
    s = _render_call(render_session.build, root, doc, owner=owner,
                     patch=body.model_dump(exclude_none=True), keyframes=kfs,
                     style=_style_for(owner["user_id"], owner["nid"]))
    return _render_call(render_session.view, s)


def _film_quote(user: dict, nid: str, cid: str, vid: str, clip_ids: Optional[list]) -> dict:
    """出片确认卡的预估：要出哪几段、合计多少元（不改段状态）。厂商与档位由用户在出片那一步选，所以要求已有会话。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    if render_session.load(root) is None:
        raise HTTPException(404, detail=msg("film.session.none_pick"))
    s = _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                     allow_in_flight=True, style=_style_for(owner["user_id"], owner["nid"]))
    targets, total = _render_call(render_session.run_quote, s, clip_ids)
    return {"amount": total, "clips": [c["id"] for c in targets]}


def _film_run(user: dict, nid: str, cid: str, vid: str, clip_ids: Optional[list],
              expected_cny: Optional[float]) -> dict:
    """排队出片（接口与助手共用）：按已保存的分镜刷新会话再排队；确认金额由 queue_run 校验。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                 allow_in_flight=True, style=_style_for(owner["user_id"], owner["nid"]))
    s = _render_call(render_session.queue_run, root, clip_ids, expected_cny)
    _render_runner.watch(root)
    return _render_call(render_session.view, s)


@app.post(_R + "/clips/{clip_id}/run")
def render_clip_run(nid: str, cid: str, vid: str, clip_id: str,
                    body: Optional[RenderRunBody] = None, user: dict = Depends(novel_user)):
    """出这一段（试段或重做）。超过确认线时要带 expected_cny。"""
    return _film_run(user, nid, cid, vid, [clip_id], body.expected_cny if body else None)


@app.post(_R + "/run")
def render_run_all(nid: str, cid: str, vid: str, body: RenderRunBody,
                   user: dict = Depends(novel_user)):
    """批量出剩余各段：必须带用户确认的预估金额，服务端重算不一致 409。"""
    return _film_run(user, nid, cid, vid, None, body.expected_cny)


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


class FreeCreateBody(BaseModel):
    from_clip: Optional[str] = None


class FreePatchBody(BaseModel):
    prompt: Optional[str] = Field(None, max_length=2000)
    refs: Optional[list[str]] = Field(None, max_length=20)
    first_frame: Optional[str] = None
    duration: Optional[float] = Field(None, gt=0, le=600)
    target: Optional[str] = None


def _free_ctx(user: dict, nid: str, cid: str, vid: str, gate: bool = False) -> tuple:
    """自由节点接口的前置：要有会话；按已保存的分镜刷新一次（挂靠段、时长、预估跟着走）；
    返回 (会话目录, 校验用的分镜 / 关键帧 / 有无风格图)。生成时 gate=True 过验证门。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid, gate=gate)
    if render_session.load(root) is None:
        raise HTTPException(404, detail=msg("film.session.none"))
    style = _style_for(owner["user_id"], owner["nid"])
    _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                 allow_in_flight=True, style=style)
    return root, render_free.Ctx(doc, kfs, style is not None)


@app.post(_R + "/free")
def render_free_create(nid: str, cid: str, vid: str, body: Optional[FreeCreateBody] = None,
                       user: dict = Depends(novel_user)):
    """新建自由节点；带 from_clip 时从这一段派生（预填正文、参考、时长，挂靠这一段）。不花钱。"""
    root, ctx = _free_ctx(user, nid, cid, vid)
    s = _render_call(render_free.create, root, ctx, body.from_clip if body else None)
    return _render_call(render_session.view, s)


@app.patch(_R + "/free/{fid}")
def render_free_patch(nid: str, cid: str, vid: str, fid: str, body: FreePatchBody,
                      user: dict = Depends(novel_user)):
    """改正文、参考、首帧、时长、挂靠：只改传了的字段（显式传 null 为清掉）。在跑 409，校验不过 422。"""
    root, ctx = _free_ctx(user, nid, cid, vid)
    s = _render_call(render_free.update, root, ctx, fid, body.model_dump(exclude_unset=True))
    return _render_call(render_session.view, s)


@app.delete(_R + "/free/{fid}")
def render_free_delete(nid: str, cid: str, vid: str, fid: str, user: dict = Depends(novel_user)):
    """删节点与只属于它的文件。在跑或被别的节点当尾帧来源时 409。"""
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid)
    s = _render_call(render_free.delete, root, fid)
    return _render_call(render_session.view, s)


@app.post(_R + "/free/{fid}/run")
def render_free_run(nid: str, cid: str, vid: str, fid: str, body: Optional[RenderRunBody] = None,
                    user: dict = Depends(novel_user)):
    """生成一次（与单段出片同一套确认线与上限）。过验证门；超过确认线要带 expected_cny。"""
    root, ctx = _free_ctx(user, nid, cid, vid, gate=True)
    s = _render_call(render_free.queue, root, ctx, fid, body.expected_cny if body else None)
    _render_runner.watch(root)
    return _render_call(render_session.view, s)


@app.put(_R + "/free/{fid}/chosen")
def render_free_chosen(nid: str, cid: str, vid: str, fid: str, body: RenderChosenBody,
                       user: dict = Depends(novel_user)):
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid)
    s = _render_call(render_free.set_chosen, root, fid, body.attempt)
    return _render_call(render_session.view, s)


@app.get(_R + "/files/{path:path}")
def render_file(nid: str, cid: str, vid: str, path: str, user: dict = Depends(novel_user)):
    """取本版本出片目录下的文件（片段、尾帧）。拒绝路径穿越。"""
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, detail=msg("film.file.not_found"))
    return FileResponse(target)


# ---------- 配音与合成：音色存在 session.json 的 voices，成片在 final/ ----------

BGM_TYPES = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
             "audio/wave": ".wav", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".aac"}
BGM_MAX_BYTES = 30 * 1024 * 1024
_compose_threads: dict = {}


class RenderVoicesBody(BaseModel):
    voices: dict[str, str]          # 说话人 → 音色 id；空串为清除


class RenderComposeBody(BaseModel):
    expected_cny: Optional[float] = Field(None, ge=0)
    draft: bool = True


def _tts():
    try:
        return render_providers.get_tts()
    except KeyError as e:
        raise HTTPException(422, detail=to_detail(e))
    except render_video_base.ProviderError as e:
        raise HTTPException(422, detail=to_detail(e))


def _bgm_files(root) -> dict:
    d = Path(root) / "audio" / "bgm"
    return ({p.stem: p for p in sorted(d.iterdir()) if p.is_file() and not p.name.startswith(".")}
            if d.is_dir() else {})


def _session_or_404(root) -> dict:
    s = render_session.load(root)
    if s is None:
        raise HTTPException(404, detail=msg("film.session.none"))
    return s


@app.get(_R + "/voices")
def render_voices(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    """配音厂商的音色表、各说话人当前用的音色（选的或默认）、缺音色的说话人。"""
    root, doc, _kfs, _owner = _render_ctx(user, nid, cid, vid, gate=False)
    s = _session_or_404(root)
    lines = render_voice.tts_lines(render_voice.speech_lines(doc), s["audio_mode"])
    if not lines:       # 这个声音模式不配音：不取配音厂商，没配密钥也能看
        return {"provider": None, "rate_note": "", "voices": [], "speakers": [], "missing": []}
    tts = _tts()
    voices, missing = render_voice.resolve_voices(doc, lines, s.get("voices") or {}, tts.caps)
    info = render_voice.speakers(doc)
    chosen = s.get("voices") or {}
    return {"provider": tts.name, "rate_note": tts.rate_note,
            "voices": [{"id": x.id, "name": x.name, "gender": x.gender} for x in tts.caps.voices],
            "speakers": [{"key": k, "name": (info.get(k) or {}).get("name") or k or compact(msg("voice.unlabeled")),
                          "hint": (info.get(k) or {}).get("hint"), "voice": voices.get(k), "chosen": chosen.get(k)}
                         for k in dict.fromkeys(x["speaker"] for x in lines)],
            "missing": missing}


@app.put(_R + "/voices")
def render_voices_put(nid: str, cid: str, vid: str, body: RenderVoicesBody,
                      user: dict = Depends(novel_user)):
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid)
    ids = {x.id for x in _tts().caps.voices}
    bad = [v for v in body.voices.values() if v and v not in ids]
    if bad:
        raise HTTPException(422, detail=msg("tts.unknown_voice_list", voices=bad))
    _render_call(render_session.set_voices, root, body.voices)
    return render_voices(nid, cid, vid, user)


def _compose_preview(user: dict, nid: str, cid: str, vid: str, draft: bool) -> tuple:
    root, doc, kfs, _owner = _render_ctx(user, nid, cid, vid, gate=False)
    s = _session_or_404(root)
    bgm = _bgm_files(root)
    lines = render_voice.tts_lines(render_voice.speech_lines(doc), s["audio_mode"])
    p = render_mix.preview(root, doc, s, tts=_tts() if lines else None, bgm=bgm, draft=draft, keyframes=kfs)
    f = s.get("final")
    if f:
        stale = False
        if f.get("files"):                      # 现有成片出自哪次合成（之后的失败不改它）就跟哪次比
            fp, made = p["fingerprint"], f.get("files_draft", f.get("draft", draft))
            if made != draft:                   # 按成片当时的草稿设置比，不随预览参数变
                fp = render_mix.compose_fingerprint(root, doc, s, p["voices"], bgm, made, kfs)
            stale = f.get("files_fingerprint", f.get("fingerprint")) != fp
        p["final"] = dict(f, stale=stale)
    else:
        p["final"] = None
    fin = p["final"]
    if fin and fin.get("state") in render_session.COMPOSE_BUSY:
        reason = "busy"
    elif not fin or not fin.get("files"):
        reason = "none"
    elif fin["stale"]:
        reason = "stale"
    elif not (Path(root) / "final" / "timeline.json").is_file():
        reason = "no_timeline"
    else:
        reason = None
    p["exportable"], p["export_reason"] = reason is None, reason
    rep = Path(root) / f["report"] if f and f.get("files") and f.get("report") else None
    try:
        p["report"] = json.loads(rep.read_text(encoding="utf-8")) if rep and rep.is_file() else None
    except (OSError, ValueError):
        p["report"] = None      # 报告坏了不影响预览
    p["bgm"] = sorted(bgm)
    p["tools"] = render_mix.tools() is not None
    p["music"] = {ep["id"]: ep.get("music") or {} for ep in doc.get("episodes") or []}
    return root, doc, kfs, s, p


_EXPORT_REASONS = {"none": "export.none", "stale": "export.stale",
                   "no_timeline": "export.no_timeline", "busy": "export.busy"}


def _compose_blockers(p: dict, draft: bool) -> None:
    """合成前提：有 ffmpeg、说话人都有音色、非草稿时每段都有视频。"""
    if render_mix.tools() is None:
        raise HTTPException(422, detail=msg("compose.no_ffmpeg"))
    if p["missing_voices"]:
        raise HTTPException(422, detail=msg("compose.missing_voices", speakers=[
            k or compact(msg("voice.unlabeled")) for k in p["missing_voices"]]))
    if p["no_video"] and not draft:
        raise HTTPException(422, detail=msg("compose.no_video_count", n=len(p["no_video"])))


def _compose_quote(user: dict, nid: str, cid: str, vid: str, draft: bool) -> dict:
    """合成确认卡的预估：未缓存配音的字数与金额（元）。过验证门与合成前提；合成中 409。"""
    _render_ctx(user, nid, cid, vid)          # 过验证门
    _root, _doc, _kfs, _s, p = _compose_preview(user, nid, cid, vid, draft)
    if (p.get("final") or {}).get("state") in render_session.COMPOSE_BUSY:
        raise HTTPException(409, detail=msg("compose.busy"))
    _compose_blockers(p, draft)
    return {"amount": p["tts_cny"], "chars": p["tts_chars"]}


def _compose_start(user: dict, nid: str, cid: str, vid: str, draft: bool,
                   expected_cny: Optional[float]) -> dict:
    """合成整章（后台线程，接口与助手共用）。配音金额大于 0 时必须带确认金额。"""
    _render_ctx(user, nid, cid, vid)          # 过验证门
    root, doc, kfs, s, p = _compose_preview(user, nid, cid, vid, draft)
    _compose_blockers(p, draft)
    if p["tts_cny"] > 0 and (expected_cny is None or abs(expected_cny - p["tts_cny"]) > 1e-6):
        raise HTTPException(409, detail={**msg("compose.confirm_cny", cost=money(p["tts_cny"])),
                                         "expected_cny": p["tts_cny"]})
    s = _render_call(render_session.begin_compose, root, fingerprint=p["fingerprint"],
                     tts_cny=p["tts_cny"], draft=draft, voices=s.get("voices") or {})
    t = threading.Thread(target=_compose_worker, args=(root, doc, s, kfs, draft, render_mix.tools()),
                         name=f"compose-{vid}", daemon=True)
    _compose_threads[str(root)] = t
    t.start()
    return _render_call(render_session.view, s)


def _export_check(user: dict, nid: str, cid: str, vid: str) -> tuple:
    """能否导出剪辑工程：成片已合成、没过期、有 ffmpeg。返回 (会话目录, ffmpeg 工具)。"""
    root, _doc, _kfs, _s, p = _compose_preview(user, nid, cid, vid, True)
    reason = p.get("export_reason")
    if reason:
        raise HTTPException(409, detail=msg(_EXPORT_REASONS[reason]))
    tools = render_mix.tools()
    if not tools:
        raise HTTPException(503, detail=msg("export.no_ffmpeg"))
    return root, tools


@app.get(_R + "/compose")
def render_compose_get(nid: str, cid: str, vid: str, draft: bool = True, user: dict = Depends(novel_user)):
    """合成预览（配音条数、未缓存字数与费用、缺音色、缺视频的段、BGM、选曲参考）、当前成片状态与合成报告。"""
    return _compose_preview(user, nid, cid, vid, draft)[4]


@app.get(_R + "/export.zip")
def render_export(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    """导出剪辑工程（FCPXML + 素材 + 字幕 + 说明）。只读本地文件、跑本地 ffmpeg，不花钱。"""
    root, tools = _export_check(user, nid, cid, vid)
    novel = _novel_call(novels.get_novel, user["id"], nid)
    chapter = next((c for c in novel["chapters"] if c["id"] == cid), {})
    title = f"{novel['title']}-{chapter.get('title', cid)}-{vid[:8]}"
    try:
        path = render_export_fcpxml.export(root, title=title, tools=tools)
    except render_export_fcpxml.ExportError as e:
        raise HTTPException(409, _hide_root(str(e), root))
    # 不让 Starlette 按名字猜：任何名字都同时给 ASCII 兜底的 filename= 和 UTF-8 的 filename*=
    ascii_name = path.name.encode("ascii", "replace").decode("ascii").replace('"', "").replace("\\", "").replace("?", "_")
    cd = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(path.name)}"
    return FileResponse(path, media_type="application/zip", headers={"Content-Disposition": cd})


def _hide_root(text: str, root) -> str:
    """存进会话的报错里隐去服务器上的目录。"""
    for r in {str(root), str(Path(root).resolve())}:
        text = text.replace(r, "…")
    return text


def _hide_root_deep(v, root):
    """消息对象（含 params 里的嵌套消息、列表）里的字符串一律隐去服务器目录。"""
    if isinstance(v, str):
        return _hide_root(v, root)
    if isinstance(v, list):
        return [_hide_root_deep(x, root) for x in v]
    if isinstance(v, dict):
        return {k: _hide_root_deep(x, root) for k, x in v.items()}
    return v


_LOG_KEY_ENVS = ("ARK_API_KEY", "MINIMAX_API_KEY", "VOLC_TTS_API_KEY", "VOLC_TTS_ACCESS_KEY")


def _scrub_log(text: str) -> str:
    """日志文字脱敏：Bearer 凭据加环境里配置的厂商密钥（不设最短长度）。"""
    out = render_video_base.scrub(text)
    for name in _LOG_KEY_ENVS:
        k = os.environ.get(name, "").strip()
        if k:
            out = out.replace(k, "***")
    return out


def _compose_worker(root, doc: dict, s: dict, kfs: dict, draft: bool, tools: tuple) -> None:
    def failed(err, detail: str = "") -> None:
        m = err.as_msg() if hasattr(err, "as_msg") else err
        if isinstance(m, dict) and m.get("code"):
            m = _hide_root_deep({"code": m["code"], "params": m.get("params") or {},
                                 "message": m.get("message") or render_zh(m["code"], m.get("params") or {})}, root)
        else:
            m = _hide_root(str(err), root)
        render_session.compose_failed(root, m, _hide_root(detail or "", root))

    try:
        lines = render_voice.tts_lines(render_voice.speech_lines(doc), s["audio_mode"])
        tts = render_providers.get_tts() if lines else None     # 没有要配音的语音条就不需要配音密钥
        out = render_mix.compose(root, doc, s, tts=tts, keyframes=kfs,
                                 bgm=_bgm_files(root), draft=draft, tools=tools,
                                 on_cost=lambda cny: render_session.add_spent(root, cny),
                                 progress=lambda step: render_session.compose_progress(root, step))
        render_session.compose_done(root, out["files"], out["report"])
    except render_mix.MixError as e:
        failed(e, e.stderr)
    except Exception as e:  # noqa: BLE001  任何意外都要落到失败，不能卡在「合成中」
        # 不把原始 exc_info 交给日志：堆栈文字（含 __cause__/__context__ 链）先脱敏再写
        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        log.error("合成异常 root=%s\n%s", root, _scrub_log(tb))  # i18n: internal
        try:
            failed(msg("compose.crashed"))
        except Exception as e2:  # noqa: BLE001
            tb2 = "".join(traceback.format_exception(type(e2), e2, e2.__traceback__))
            log.error("合成失败状态写回失败 root=%s\n%s", root, _scrub_log(tb2))  # i18n: internal


@app.post(_R + "/compose")
def render_compose_post(nid: str, cid: str, vid: str, body: RenderComposeBody,
                        user: dict = Depends(novel_user)):
    """合成整章（后台线程）。过验证门；配音金额（未缓存的字数 × 单价）大于 0 时必须带确认金额。"""
    return _compose_start(user, nid, cid, vid, body.draft, body.expected_cny)


@app.put(_R + "/bgm/{episode}")
async def render_bgm_put(nid: str, cid: str, vid: str, episode: str, request: Request,
                         user: dict = Depends(novel_user)):
    """每集一段 BGM（mp3 / wav / m4a / aac，≤ 30MB）；合成时循环铺满，有人声时自动压低。"""
    root, doc, _kfs, _owner = _render_ctx(user, nid, cid, vid, gate=False)
    _session_or_404(root)
    if episode not in {ep["id"] for ep in doc.get("episodes") or []}:
        raise HTTPException(404, detail=msg("compose.bgm.no_episode", episode=episode))
    ext = BGM_TYPES.get(request.headers.get("content-type", "").split(";")[0].strip().lower())
    if ext is None:
        raise HTTPException(422, detail=msg("compose.bgm.bad_type"))
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > BGM_MAX_BYTES:
        raise HTTPException(422, detail=msg("compose.bgm.too_big"))
    d = Path(root) / "audio" / "bgm"
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{episode}{ext}.{uuid.uuid4().hex}.part"     # 同一集并发上传各写各的
    total = 0
    try:
        with open(tmp, "wb") as fh:
            async for chunk in request.stream():
                total += len(chunk)
                if total > BGM_MAX_BYTES:
                    break
                fh.write(chunk)
        if total == 0 or total > BGM_MAX_BYTES:
            raise HTTPException(422, detail=msg("compose.bgm.too_big"))
        tmp.replace(d / f"{episode}{ext}")
    finally:
        tmp.unlink(missing_ok=True)
    for old in d.glob(f"{episode}.*"):
        if old.name != f"{episode}{ext}":
            old.unlink()
    return {"episode": episode, "bytes": total}


@app.delete(_R + "/bgm/{episode}")
def render_bgm_delete(nid: str, cid: str, vid: str, episode: str, user: dict = Depends(novel_user)):
    root, doc, _kfs, _owner = _render_ctx(user, nid, cid, vid, gate=False)
    if episode not in {ep["id"] for ep in doc.get("episodes") or []}:
        raise HTTPException(404, detail=msg("compose.bgm.no_episode", episode=episode))
    old = _bgm_files(root).get(episode)
    if old:
        old.unlink()
    return {"deleted": episode}


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


# ---------- 助手 ----------

# 操作工具调这些（与接口同一份）；assistant 包不能反过来导入 app
assistant_actions.ops.update(start_version=_start_version, film_quote=_film_quote, film_run=_film_run,
                             compose_quote=_compose_quote, compose_start=_compose_start,
                             export_check=_export_check, version_check=_check_version_doc,
                             version_save=_save_version_doc)

_ASSISTANT_STEPS = ("import", "storyboard", "review", "render", "compose", "download")
_ASSISTANT_MAX = 2000


def _assistant_model():
    """助手用的聊天模型：关掉 thinking（工具循环里不处理 thinking 块）。测试里替换成假模型。

    build_chat_model 故意设 max_retries=0（流水线的重试交给 with_retry）；助手不能套 with_retry——
    create_react_agent 要在模型上 bind_tools，RunnableRetry 没有这个方法——所以改回让 SDK 自己重试
    瞬时故障（529 过载、网关抖动、连接断开），否则一次抖动整轮就失败。"""
    return build_chat_model(replace_thinking(load_settings())).model_copy(update={"max_retries": 2})


def _assistant_db(user: dict, nid: str):
    try:
        return novels.assistant_db(user["id"], nid)
    except novels.NotFound:
        raise HTTPException(404, "小说不存在")


_VERSION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")   # 用 fullmatch：$ 会放过结尾的换行


def _assistant_where(user_id: str, nid: str, raw: dict) -> dict:
    """只留可信的位置：chapter_id 须是这部小说的章；version_id 须形如编号且章节留下了；step 已校验。
    where 每次模型调用都进系统提示，不收原样的长串。"""
    where: dict = {}
    if isinstance(raw.get("step"), str):
        where["step"] = raw["step"]
    cid = raw.get("chapter_id")
    if isinstance(cid, str) and any(c["id"] == cid for c in novels.get_novel(user_id, nid)["chapters"]):
        where["chapter_id"] = cid
        vid = raw.get("version_id")
        if isinstance(vid, str) and _VERSION_ID.fullmatch(vid):
            where["version_id"] = vid
    return where


@app.get("/novels/{nid}/assistant")
def assistant_history(nid: str, user: dict = Depends(novel_user)):
    _assistant_db(user, nid)
    if not assistant_store.exists(user["id"], nid):
        return {"messages": []}
    with assistant_store.saver(user["id"], nid) as cp:
        agent = assistant_graph.build_agent(assistant_graph.NullModel(), cp)
        cfg = assistant_graph.run_config(user["id"], nid, {}, "zh")
        return {"messages": assistant_events.history(agent, cfg, hide=str(auth.DATA_DIR),
                                                     undone=assistant_store.undone(user["id"], nid))}


@app.delete("/novels/{nid}/assistant")
def assistant_clear(nid: str, user: dict = Depends(novel_user)):
    _assistant_db(user, nid)
    token = assistant_store.try_begin(user["id"], nid)
    if not token:
        raise HTTPException(409, "助手正在回答，等它说完再清空")
    try:
        assistant_store.clear(user["id"], nid)
    finally:
        assistant_store.end(user["id"], nid, token)
    return {"ok": True}


def _assistant_ctx(user: dict, nid: str, body: dict) -> tuple:
    """(lang, where)：语言只收 zh / en；where 校验 step 后消毒（见 _assistant_where）。"""
    lang = body.get("lang") if body.get("lang") in ("zh", "en") else "zh"
    raw = body.get("where") or {}
    if not isinstance(raw, dict):
        raise HTTPException(422, "where 不合法")
    if raw.get("step") is not None and raw.get("step") not in _ASSISTANT_STEPS:
        raise HTTPException(422, "where.step 不合法")
    return lang, _assistant_where(user["id"], nid, raw)


def _assistant_begin(user: dict, nid: str) -> float:
    """每日上限（429）与并发锁（409）；返回锁凭据。"""
    if assistant_store.used_today(user["id"]) >= assistant_store.daily_limit():
        raise HTTPException(429, "今天的助手消息已用完，明天再来")
    token = assistant_store.try_begin(user["id"], nid)
    if not token:
        raise HTTPException(409, "上一条还在回答")
    return token


def _assistant_pending(user_id: str, nid: str) -> dict:
    """存档里待确认的卡：中断编号 → 卡（中断的原值）。"""
    if not assistant_store.exists(user_id, nid):
        return {}
    with assistant_store.saver(user_id, nid) as cp:
        agent = assistant_graph.build_agent(assistant_graph.NullModel(), cp)
        cfg = assistant_graph.run_config(user_id, nid, {}, "zh")
        return {it.id: it.value for it in assistant_graph.pending(agent, cfg)}


def _assistant_stream(user: dict, nid: str, where: dict, lang: str, payload, token: float, model,
                      before=None, resume_tool_call: Optional[str] = None) -> StreamingResponse:
    """跑一轮（发消息或确认卡恢复）→ SSE 响应。payload：用户文字或 Command。
    before(agent, cfg)：开跑前在同一份存档上做的事（发新消息时取消待确认的卡）。
    resume_tool_call：恢复时被恢复的那次工具调用（工具据此不管金额都先取回答）。"""
    root = str(auth.DATA_DIR)   # 整个数据根：用户目录、密钥文件等任何服务器路径都隐去

    def gen():
        cb = UsageCallback()
        ok = False
        try:
            with assistant_store.saver(user["id"], nid) as cp:
                agent = assistant_graph.build_agent(model, cp)
                cfg = assistant_graph.run_config(user["id"], nid, where, lang, [cb], resume_tool_call)
                try:
                    if before:
                        before(agent, cfg)
                except Exception as e:  # 存档读写出错：给一条报错，不开新一轮
                    yield assistant_events.sse({"event": "error", "data": {
                        "message": assistant_events._hide(f"助手出错：{e}", root)[:300]}})
                    return
                for ev in assistant_events.stream(agent, cfg, payload, hide=root):
                    if ev["event"] == "done":
                        ok = True
                    yield assistant_events.sse(ev)
        finally:
            assistant_store.end(user["id"], nid, token)
            try:
                usage.record(user_id=user["id"], purpose=assistant_store.PURPOSE, model=load_settings().model,
                             usage=cb.usage_totals(), ok=ok, novel_id=nid, chapter_id=where.get("chapter_id"))
            except Exception as e:  # 落账失败不影响对话
                print(f"[usage] 助手落账失败：{e!r}", flush=True)

    class _Body:
        """包一层异步迭代器：客户端提前断开（含 gen 还没开始）时 aclose 也保证释放锁。
        不用 async 生成器：没开始的异步生成器 aclose 时不会进 finally。"""

        def __init__(self):
            self._it = gen()
            self._aiter = iterate_in_threadpool(self._it)
            self._closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self._aiter.__anext__()

        async def aclose(self):
            if self._closed:
                return
            self._closed = True
            # 先放锁（已裁定）：下一条消息不必排在旧回答后面；凭据保证迟到的 end 不误放新锁
            assistant_store.end(user["id"], nid, token)
            # 关生成器会等 LangGraph 正在跑的模型节点结束（可能几十秒），放到线程里，别卡住事件循环；
            # shield：请求被取消时也把关闭做完（gen 的 finally 要落账）
            with anyio.CancelScope(shield=True):
                try:
                    await anyio.to_thread.run_sync(self._it.close)
                except ValueError:   # 模型还在线程里跑：gen 自己的 finally 会在它结束时落账
                    pass

    class _Resp(StreamingResponse):
        async def __call__(self, scope, receive, send):
            try:
                await super().__call__(scope, receive, send)
            finally:   # 断开、取消、正常结束都走这里；aclose 幂等
                await self.body_iterator.aclose()

    return _Resp(_Body(), media_type="text/event-stream",
                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _assistant_model_or_503(user: dict, nid: str, token: float):
    try:
        return _assistant_model()
    except Exception as e:
        assistant_store.end(user["id"], nid, token)
        raise HTTPException(503, assistant_events._hide(f"助手暂不可用：{e}", str(auth.DATA_DIR)))


@app.post("/novels/{nid}/assistant/messages")
def assistant_send(nid: str, body: dict = Body(...), user: dict = Depends(novel_user)):
    _assistant_db(user, nid)
    text = str(body.get("text") or "").strip()
    if not text or len(text) > _ASSISTANT_MAX:
        raise HTTPException(422, f"消息不能为空，且不超过 {_ASSISTANT_MAX} 字")
    lang, where = _assistant_ctx(user, nid, body)
    token = _assistant_begin(user, nid)
    model = _assistant_model_or_503(user, nid, token)
    # 有待确认的卡：先按「取消」处理（spec §7.2），再开新的一轮
    return _assistant_stream(user, nid, where, lang, text, token, model, before=assistant_graph.cancel_pending)


# 已接受过恢复的中断 (user_id, nid, 中断编号)：第一次恢复中途断开时存档里卡还待确认，再点一次也不能再跑
_assistant_resumed: set = set()
_assistant_resumed_lock = threading.Lock()


@app.post("/novels/{nid}/assistant/resume")
def assistant_resume(nid: str, body: dict = Body(...), user: dict = Depends(novel_user)):
    """点了确认卡上的按钮：接着跑被中断的那一轮（spec §7.2）。卡以存档为准，不收前端传来的卡。"""
    _assistant_db(user, nid)
    iid, decision = body.get("id"), body.get("decision")
    if not isinstance(iid, str) or decision not in ("approve", "reject"):
        raise HTTPException(422, "id 或 decision 不合法")
    lang, where = _assistant_ctx(user, nid, body)
    token = _assistant_begin(user, nid)
    try:
        card = _assistant_pending(user["id"], nid).get(iid)
    except Exception:
        assistant_store.end(user["id"], nid, token)
        raise
    key = (user["id"], nid, iid)
    with _assistant_resumed_lock:
        done = key in _assistant_resumed
    if card is None or done:
        assistant_store.end(user["id"], nid, token)
        raise HTTPException(409, "这张确认卡已经处理过")
    model = _assistant_model_or_503(user, nid, token)
    cmd = Command(resume={iid: {"decision": decision, "card": card}})
    with _assistant_resumed_lock:   # 校验都过了才记：校验失败（503 等）的还能再点
        _assistant_resumed.add(key)
    return _assistant_stream(user, nid, where, lang, cmd, token, model, resume_tool_call=card["tool_call_id"])


def _assistant_undo_data(user_id: str, nid: str, tool_call_id: str) -> Optional[dict]:
    """存档里这次修改的撤销数据：应用成功的改内容工具结果才有。"""
    if not assistant_store.exists(user_id, nid):
        return None
    with assistant_store.saver(user_id, nid) as cp:
        agent = assistant_graph.build_agent(assistant_graph.NullModel(), cp)
        msgs = agent.get_state(assistant_graph.run_config(user_id, nid, {}, "zh")).values.get("messages") or []
    # 取最后一条匹配的：按约定 tool_call_id 在一次会话里唯一，但有的网关会复用编号，以最近的为准
    for m in reversed(msgs):
        if getattr(m, "tool_call_id", None) == tool_call_id and m.name in assistant_edits.EDITS:
            a = m.artifact if m.status != "error" else None
            return a["undo"] if a and a.get("outcome") == "approved" and a.get("undo") else None
    return None


@app.post("/novels/{nid}/assistant/undo")
def assistant_undo(nid: str, body: dict = Body(...), user: dict = Depends(novel_user)):
    """对比卡上点了「撤销」：把那次应用的改动写回去（spec §8.2）。不调模型、不记用量；之后被别处改过 409。"""
    _assistant_db(user, nid)
    tcid = body.get("tool_call_id")
    if not isinstance(tcid, str) or not tcid:
        raise HTTPException(422, "tool_call_id 不合法")
    token = assistant_store.try_begin(user["id"], nid)
    if not token:
        raise HTTPException(409, "助手正在回答，等它说完再撤销")
    try:
        if tcid in assistant_store.undone(user["id"], nid):
            raise HTTPException(409, "这次修改已经撤销过了")
        data = _assistant_undo_data(user["id"], nid, tcid)
        if data is None:
            raise HTTPException(404, "找不到这次修改")
        try:
            message = assistant_edits.undo(user["id"], nid, data)
        except (assistant_edits.UndoError, novels.NovelError, novels.NotFound) as e:
            raise HTTPException(409, _hide_root(str(e), auth.DATA_DIR))
        assistant_store.mark_undone(user["id"], nid, tcid)
        return {"ok": True, "message": message,
                "task": {"kind": "edit", "chapter_id": data.get("chapter_id"), "version_id": data.get("version_id")}}
    finally:
        assistant_store.end(user["id"], nid, token)


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

