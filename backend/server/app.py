"""HTTP 服务：POST 小说文本 → 后台转换 → GET 取分镜 JSON。

启动：uvicorn server.app:app --host 0.0.0.0 --port 8000
转换耗时为分钟级（LLM 长输出），故采用异步任务模型：
  POST /convert          → {"job_id": ...}
  GET  /jobs             → 本人在跑/刚结束的任务摘要（关掉页面后靠它重新接上）
  GET  /jobs/{job_id}    → {"status": queued|running|succeeded|completed_with_warnings|failed,
                            "result": 分镜JSON, "quality_report": 降级交付时的质量报告, "log": [...]}
completed_with_warnings：软质量门（旁白密度/评审分）重试耗尽，产物结构合法、
逐字保真但质量未达阈值，已择优交付历次尝试中最优一版（请求置 strict=true 改为直接失败）。

任务表在内存中（进程重启后实时日志会清空），但 queued/running/成功/失败状态与产物均会落盘：
  GET    /history         → 历史记录摘要列表
  GET    /history/{id}    → 单条完整记录（含分镜 JSON）
  PUT    /history/{id}    → 保存人工编辑后的分镜
  DELETE /history/{id}    → 删除记录

资产库（独立于任何一次转换的一等实体，可增删改，转换时可注入、转换后可入库）：
  GET    /library                      → 按作品列出
  POST   /library/{work}               → 新建一部空作品
  GET    /library/{work}               → 某作品的全部资产卡
  PUT    /library/{work}/{kind}/{id}   → 新建或覆盖一张卡
  DELETE /library/{work}/{kind}/{id}   → 删除一张卡
  POST   /library/{work}/import        → 把一次转换的 assets 并入库
  DELETE /library/{work}               → 删除整部作品的资产库

小说级会话（总会话 = 小说，长期记忆；二级会话 = 章节；每次转换 = 一个版本，短期记忆）。
首次访问时自动把上面的旧记录与资产库迁到这套结构下（旧文件保留）：
  GET/POST            /novels                                   小说列表 / 新建
  GET/PATCH/DELETE    /novels/{nid}                             详情（含章节摘要与长期记忆）/ 改 / 删
  POST                /novels/{nid}/chapters                    新建章节
  GET/PATCH/DELETE    /novels/{nid}/chapters/{cid}              详情（含版本列表）/ 改 / 删
  POST                /novels/{nid}/chapters/{cid}/versions     转换本章 → {"job_id"}（进度照旧走 /jobs）
  GET/PUT/DELETE      /novels/{nid}/chapters/{cid}/versions/{vid}        取 / 人工编辑并复验 / 删
  POST                /novels/{nid}/chapters/{cid}/versions/{vid}/adopt  采用 → 写入长期记忆
  GET                 /novels/{nid}/memory                      长期记忆
  PUT/DELETE          /novels/{nid}/memory/assets/{kind}/{id}   资产卡增改删

渲染任务包（下游消费入口，只读、不落盘、不改 IR）：
  POST /render/plan        → 分镜 IR → 机器可读渲染任务清单 + 人读版生产包 + 费用估算

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

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import __version__
from pipeline.config import load_settings
from pipeline.convert import ConversionError, ConvertParams, convert_text
from pipeline import verification
from render import plan as render_plan_mod
from server import auth, library, novels, store
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

class ConvertRequest(BaseModel):
    text: str = Field(..., min_length=1, description="小说原文（纯文本）")
    work_title: str = _D.work_title
    chapter: str = _D.chapter
    style_prefix: str = _D.style_prefix
    art_style: str = _D.art_style
    color_tone: str = _D.color_tone
    aspect_ratio: str = _D.aspect_ratio
    target_platform: str = _D.target_platform
    narration_mode: str = _D.narration_mode
    tts_voice: str = _D.tts_voice
    strict: bool = False   # True：软质量门重试耗尽直接失败（默认择优降级交付）
    # 沿用资产库：默认自动取本人该作品的资产库（没有则为空），
    # 也可显式传一份覆盖。续写下一章时角色/场景 ID 与描述保持一致，防跨章漂移
    use_library: bool = True
    seed_assets: Optional[dict] = None
    # 转换成功后把产物里的资产卡并回库（新 ID 新增，同 ID 按追加规则合并）
    import_assets: bool = True


def _execute(job: dict, text: str, params: ConvertParams, strict: bool,
             seed: Optional[dict], persist, after_success,
             numbering: Optional[dict] = None) -> None:
    """跑一次转换并把状态/产物写回。persist(status, **fields) 决定落到哪
    （旧的转换记录，或小说章节的某个版本）；after_success(job, log) 做成功后的
    长期记忆动作（旧路径：资产入库；新路径：首个成功版本自动采用）。"""
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
                                     start_numbering=numbering)
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
    except Exception as e:  # LLM/网络等运行期错误
        job["status"] = "failed"
        job["error"] = repr(e)
        job["manifest"] = manifest
        if manifest:
            manifest["state"] = "failed"
        save("failed", error=job["error"], manifest=manifest)


def _run_job(job: dict, req: ConvertRequest, user_id: str) -> None:
    """旧接口 /convert：扁平转换记录 + 按作品名的资产库。"""
    params = ConvertParams(
        work_title=req.work_title, chapter=req.chapter,
        style_prefix=req.style_prefix, art_style=req.art_style,
        color_tone=req.color_tone, aspect_ratio=req.aspect_ratio,
        target_platform=req.target_platform, narration_mode=req.narration_mode,
        tts_voice=req.tts_voice)
    seed = req.seed_assets
    if seed is None and req.use_library:
        seed = library.seed_for(user_id, req.work_title)
        if seed:
            n = sum(len(v) for v in seed.values())
            job["log"].append(f"沿用资产库《{req.work_title}》共 {n} 张卡（模型须复用其 ID 与描述）")

    def after_success(job, log):
        if req.import_assets:
            r = library.import_assets(user_id, req.work_title,
                                      job["result"].get("assets") or {})
            log(f"资产入库《{req.work_title}》：新增 {r['added']} 张，"
                f"合并 {r['merged']} 张（可在资产库页管理）")

    _execute(job, req.text, params, req.strict, seed,
             lambda status, **f: store.update_state(user_id, job["id"], status, **f),
             after_success)


@app.post("/convert")
def submit(req: ConvertRequest, user: dict = Depends(current_user)):
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "user_id": user["id"], "status": "queued", "log": [],
           "result": None, "quality_report": None, "error": None, "persisted": False,
           "created_at": store.now_iso(),
           "work_title": req.work_title, "chapter": req.chapter,
           "chars": len(req.text), "progress": {}, "partial": None}
    params = {name: getattr(req, name) for name in ConvertParams.__dataclass_fields__}
    try:
        store.save(user["id"], job_id, "queued", params, None)
        job["persisted"] = True
    except OSError as e:
        raise HTTPException(500, f"无法建立持久化任务记录：{e}")
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_run_job, job, req, user["id"])
    return {"job_id": job_id, "status_url": f"/jobs/{job_id}"}


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


# ---------- 历史记录 ----------

@app.get("/history")
def history(user: dict = Depends(current_user)):
    """历史记录摘要（不含分镜正文，列表要轻）。"""
    return {"runs": store.list_runs(user["id"])}


@app.get("/history/{run_id}")
def history_get(run_id: str, user: dict = Depends(current_user)):
    try:
        record = store.get(user["id"], run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if record is None:
        raise HTTPException(404, "历史记录不存在")
    return record


def _frozen_of(record: dict) -> Optional[list]:
    """一条记录的冻结证据：清单里的冻结句单元；旧记录没有清单，就用它当时产物里的句单元。"""
    frozen = ((record.get("manifest") or {}).get("scope") or {}).get("units")
    if not frozen:
        frozen = [{k: unit.get(k) for k in ("id", "text", "para")}
                  for unit in ((record.get("result") or {}).get("source") or {})
                  .get("units") or []]
    return frozen or None


def _reverify(existing: dict, result: dict):
    """人工编辑后的整份复验。不合格标 draft_invalid 但照样保存（不丢人的工作）。"""
    doc = copy.deepcopy(result)
    frozen = _frozen_of(existing)
    probe = verification.verify_document(doc, frozen_units=frozen)
    verification.recompute_coverage_field(doc, probe.coverage)
    report = verification.verify_document(doc, frozen_units=frozen)
    previous_status = existing.get("status")
    status = ((previous_status if previous_status in
               ("succeeded", "completed_with_warnings") else "succeeded")
              if report.ok else "draft_invalid")
    return doc, report, status, frozen


@app.put("/history/{run_id}")
def history_update(run_id: str, result: dict = Body(..., embed=False),
                   user: dict = Depends(current_user)):
    """保存人工编辑后的分镜。

    只覆盖 result；创建时间与制作参数保持原样，另记 edited_at。
    """
    try:
        existing = store.get(user["id"], run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if existing is None:
        raise HTTPException(404, "历史记录不存在")

    doc, report, status, frozen = _reverify(existing, result)
    record = store.update_result(user["id"], run_id, doc,
                                 verification=report.to_dict(), status=status,
                                 frozen_units=frozen or None)
    return {"id": run_id, "edited_at": record["edited_at"], "status": status,
            "verification": report.to_dict()}


@app.delete("/history/{run_id}")
def history_delete(run_id: str, user: dict = Depends(current_user)):
    try:
        ok = store.delete(user["id"], run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "历史记录不存在")
    return {"deleted": run_id}


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

    def after_success(job, log):
        chapter = novels.get_chapter(user_id, nid, cid)
        if chapter.get("adopted_version"):
            log("本章已有采用版，这一版仅存档；要用它请在版本列表里点「采用」")
            return
        r = novels.adopt_version(user_id, nid, cid, job["id"])
        log(f"已自动采用为本章首个成功版本：资产库新增 {r['added']} 张、"
            f"合并 {r['merged']} 张")

    _execute(job, text, params, strict, seed,
             lambda status, **f: novels.update_version_state(
                 user_id, nid, cid, job["id"], status, **f),
             after_success, numbering)


@app.post("/novels/{nid}/chapters/{cid}/versions")
def versions_create(nid: str, cid: str, req: VersionRequest,
                    user: dict = Depends(novel_user)):
    """转换本章 → 新版本。返回 job_id（即版本 id），进度/分批预览照旧走 /jobs。"""
    novel = _novel_call(novels.get_novel, user["id"], nid)
    chapter = _novel_call(novels.get_chapter, user["id"], nid, cid)
    text = chapter.get("text") or ""
    if not text.strip():
        raise HTTPException(422, "本章还没有原文")
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
    doc, report, status, frozen = _reverify(existing, result)
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
    return _novel_call(novels.adopt_version, user["id"], nid, cid, vid)


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
    frozen = None
    if req.run_id:
        try:
            record = (store.get(user["id"], req.run_id)
                      or novels.find_version(user["id"], req.run_id))
        except ValueError as e:
            raise HTTPException(400, str(e))
        if record is None:
            raise HTTPException(404, "历史记录不存在")
        frozen = _frozen_of(record)
    probe = verification.verify_document(doc, frozen_units=frozen or None)
    verification.recompute_coverage_field(doc, probe.coverage)
    report = verification.verify_document(doc, frozen_units=frozen or None)
    if not report.ok:
        raise HTTPException(422, detail={
            "message": "分镜未通过独立验证，禁止进入付费渲染",
            "verification": report.to_dict(),
        })
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


# ---------- 资产库 ----------

@app.get("/library")
def library_list(user: dict = Depends(current_user)):
    return {"works": library.list_works(user["id"])}


@app.post("/library/backfill")
def library_backfill(user: dict = Depends(current_user)):
    """从本人的历史记录补齐资产库。

    早于「自动入库」的转换、以及关掉 import_assets 的转换，资产都不在库里。
    同 ID 走追加式合并，不覆盖人工编辑，因此重复点是安全的。
    """
    return {"works": library.backfill_from_runs(user["id"])}


@app.post("/library/{work}")
def library_create_work(work: str, user: dict = Depends(current_user)):
    """建一部空作品，供「先设定人物场景、再去转换」的用法。"""
    try:
        created = library.create_work(user["id"], work)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not created:
        raise HTTPException(409, f"《{work}》已在资产库中")
    return {"work_title": work, "created": True}


@app.get("/library/{work}")
def library_get(work: str, user: dict = Depends(current_user)):
    got = library.get_work(user["id"], work)
    if got is None:
        raise HTTPException(404, "资产库里没有这部作品")
    return got


@app.put("/library/{work}/{kind}/{card_id}")
def library_upsert(work: str, kind: str, card_id: str,
                   card: dict = Body(..., embed=False),
                   user: dict = Depends(current_user)):
    if card.get("id") != card_id:
        raise HTTPException(422, f"卡片 id 与路径不一致：{card.get('id')!r} != {card_id!r}")
    try:
        return library.upsert_card(user["id"], work, kind, card)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.delete("/library/{work}/{kind}/{card_id}")
def library_delete_card(work: str, kind: str, card_id: str,
                        user: dict = Depends(current_user)):
    try:
        ok = library.delete_card(user["id"], work, kind, card_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not ok:
        raise HTTPException(404, "资产卡不存在")
    return {"deleted": card_id}


@app.post("/library/{work}/import")
def library_import(work: str, assets: dict = Body(..., embed=False),
                   user: dict = Depends(current_user)):
    return library.import_assets(user["id"], work, assets)


@app.delete("/library/{work}")
def library_delete_work(work: str, user: dict = Depends(current_user)):
    if not library.delete_work(user["id"], work):
        raise HTTPException(404, "资产库里没有这部作品")
    return {"deleted": work}


# ---------- 探针 ----------

@app.get("/healthz")
def healthz():
    s = load_settings()
    return {"status": "ok", "model": s.model,
            "api_key_configured": bool(s.api_key),
            "users": auth.user_count()}
