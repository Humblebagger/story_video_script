"""HTTP 服务：POST 小说文本 → 后台转换 → GET 取分镜 JSON。

启动：uvicorn server.app:app --host 0.0.0.0 --port 8000
转换耗时为分钟级（LLM 长输出），故采用异步任务模型：
  POST /convert          → {"job_id": ...}
  GET  /jobs             → 本人在跑/刚结束的任务摘要（关掉页面后靠它重新接上）
  GET  /jobs/{job_id}    → {"status": queued|running|succeeded|completed_with_warnings|failed,
                            "result": 分镜JSON, "quality_report": 降级交付时的质量报告, "log": [...]}
completed_with_warnings：软质量门（旁白密度/评审分）重试耗尽，产物结构合法、
逐字保真但质量未达阈值，已择优交付历次尝试中最优一版（请求置 strict=true 改为直接失败）。

任务表在内存中（进程重启即清空），但**完成的转换会落盘**，经历史接口取用：
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

渲染任务包（下游消费入口，只读、不落盘、不改 IR）：
  POST /render/plan        → 分镜 IR → 机器可读渲染任务清单 + 人读版生产包 + 费用估算

以上全部需要登录，且只能看到自己的数据：
  POST /auth/register / POST /auth/login → {"token": ...}；GET /auth/me
"""
import os
import sys
import threading
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
from render import plan as render_plan_mod
from server import auth, library, store
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


def _run_job(job: dict, req: ConvertRequest, user_id: str) -> None:
    job["status"] = "running"

    def log(msg):
        job["log"].append(str(msg))

    params = ConvertParams(
        work_title=req.work_title, chapter=req.chapter,
        style_prefix=req.style_prefix, art_style=req.art_style,
        color_tone=req.color_tone, aspect_ratio=req.aspect_ratio,
        target_platform=req.target_platform, narration_mode=req.narration_mode,
        tts_voice=req.tts_voice)
    settings = load_settings()
    settings.strict = settings.strict or req.strict

    seed = req.seed_assets
    if seed is None and req.use_library:
        seed = library.seed_for(user_id, req.work_title)
        if seed:
            n = sum(len(v) for v in seed.values())
            log(f"沿用资产库《{req.work_title}》共 {n} 张卡（模型须复用其 ID 与描述）")

    warnings: list = []
    try:
        job["result"] = convert_text(req.text, params, settings=settings,
                                     log=log, warnings_out=warnings,
                                     seed_assets=seed)
        if warnings:
            job["quality_report"] = "\n\n".join(warnings)
            job["status"] = "completed_with_warnings"
        else:
            job["status"] = "succeeded"
        # 转换慢且花钱，产物必须落盘——内存任务表重启即清空
        try:
            store.save(user_id, job["id"], job["status"], params.__dict__,
                       job["result"], job["quality_report"])
            job["persisted"] = True
        except OSError as e:
            log(f"警告：历史记录落盘失败（产物仍可从本次响应取走）：{e!r}")
        if req.import_assets:
            try:
                r = library.import_assets(user_id, req.work_title,
                                          job["result"].get("assets") or {})
                log(f"资产入库《{req.work_title}》：新增 {r['added']} 张，"
                    f"合并 {r['merged']} 张（可在资产库页管理）")
            except (OSError, ValueError) as e:
                log(f"警告：资产入库失败：{e!r}")
    except ConversionError as e:
        job["status"] = "failed"
        job["error"] = f"{e}\n{e.report}"
    except Exception as e:  # LLM/网络等运行期错误
        job["status"] = "failed"
        job["error"] = repr(e)


@app.post("/convert")
def submit(req: ConvertRequest, user: dict = Depends(current_user)):
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "user_id": user["id"], "status": "queued", "log": [],
           "result": None, "quality_report": None, "error": None, "persisted": False,
           "created_at": store.now_iso(),
           "work_title": req.work_title, "chapter": req.chapter,
           "chars": len(req.text)}
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_run_job, job, req, user["id"])
    return {"job_id": job_id, "status_url": f"/jobs/{job_id}"}


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
    } for j in sorted(jobs, key=lambda x: x.get("created_at") or "", reverse=True)]}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, user: dict = Depends(current_user)):
    with _lock:
        job = _jobs.get(job_id)
    if job is None or job.get("user_id") != user["id"]:
        raise HTTPException(404, "job 不存在（服务重启会清空任务表）")
    return {k: v for k, v in job.items() if k != "user_id"}


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


@app.put("/history/{run_id}")
def history_update(run_id: str, result: dict = Body(..., embed=False),
                   user: dict = Depends(current_user)):
    """保存人工编辑后的分镜。

    只覆盖 result；创建时间与制作参数保持原样，另记 edited_at。
    """
    if not result.get("meta") or not result.get("episodes"):
        raise HTTPException(422, "不是分镜 IR：缺少 meta / episodes")
    try:
        record = store.update_result(user["id"], run_id, result)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if record is None:
        raise HTTPException(404, "历史记录不存在")
    return {"id": run_id, "edited_at": record["edited_at"]}


@app.delete("/history/{run_id}")
def history_delete(run_id: str, user: dict = Depends(current_user)):
    try:
        ok = store.delete(user["id"], run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "历史记录不存在")
    return {"deleted": run_id}


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
    doc = req.result
    if not doc.get("meta") or not doc.get("episodes"):
        raise HTTPException(422, "不是分镜 IR：缺少 meta / episodes")
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
    return {"plan": plan, "packs": packs}


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
