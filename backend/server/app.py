"""HTTP 服务：POST 小说文本 → 后台转换 → GET 取分镜 JSON。

启动：uvicorn server.app:app --host 0.0.0.0 --port 8000
转换耗时为分钟级（LLM 长输出），故采用异步任务模型：
  POST /convert          → {"job_id": ...}
  GET  /jobs/{job_id}    → {"status": queued|running|succeeded|completed_with_warnings|failed,
                            "result": 分镜JSON, "quality_report": 降级交付时的质量报告, "log": [...]}
  GET  /healthz          → 存活与配置探针
completed_with_warnings：软质量门（旁白密度/评审分）重试耗尽，产物结构合法、
逐字保真但质量未达阈值，已择优交付历次尝试中最优一版（请求置 strict=true 改为直接失败）。

任务表在内存中（进程重启即清空），但**完成的转换会落盘**到 runs/，经历史接口取用：
  GET    /history         → 历史记录摘要列表
  GET    /history/{id}    → 单条完整记录（含分镜 JSON）
  PUT    /history/{id}    → 保存人工编辑后的分镜
  DELETE /history/{id}    → 删除记录
  GET    /assets          → 按作品聚合的历史资产库（供新转换 seed_assets 沿用）
"""
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import __version__
from pipeline.config import load_settings
from pipeline.convert import ConversionError, ConvertParams, convert_text
from server import store

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
    # 沿用历史资产库（{"characters": [...], "locations": [...], ...}）：
    # 续写同一部小说的下一章时，角色/场景 ID 与描述保持一致，防跨章漂移
    seed_assets: Optional[dict] = None


def _run_job(job: dict, req: ConvertRequest) -> None:
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
    warnings: list = []
    try:
        job["result"] = convert_text(req.text, params, settings=settings,
                                     log=log, warnings_out=warnings,
                                     seed_assets=req.seed_assets)
        if warnings:
            job["quality_report"] = "\n\n".join(warnings)
            job["status"] = "completed_with_warnings"
        else:
            job["status"] = "succeeded"
        # 转换慢且花钱，产物必须落盘——内存任务表重启即清空
        try:
            store.save(job["id"], job["status"], params.__dict__,
                       job["result"], job["quality_report"])
            job["persisted"] = True
        except OSError as e:
            log(f"警告：历史记录落盘失败（产物仍可从本次响应取走）：{e!r}")
    except ConversionError as e:
        job["status"] = "failed"
        job["error"] = f"{e}\n{e.report}"
    except Exception as e:  # LLM/网络等运行期错误
        job["status"] = "failed"
        job["error"] = repr(e)


@app.post("/convert")
def submit(req: ConvertRequest):
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "status": "queued", "log": [], "result": None,
           "quality_report": None, "error": None, "persisted": False,
           "created_at": store.now_iso(),
           "work_title": req.work_title, "chapter": req.chapter,
           "chars": len(req.text)}
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_run_job, job, req)
    return {"job_id": job_id, "status_url": f"/jobs/{job_id}"}


@app.get("/jobs")
def list_jobs():
    """在跑/刚结束的任务摘要（不含分镜正文与日志）。

    转换是分钟级任务，前端关掉页面后转换仍在后台继续；靠这个接口重新接上，
    不必守着页面等。
    """
    with _lock:
        jobs = list(_jobs.values())
    return {"jobs": [{
        "id": j["id"], "status": j["status"], "created_at": j.get("created_at"),
        "work_title": j.get("work_title"), "chapter": j.get("chapter"),
        "chars": j.get("chars"), "log_lines": len(j["log"]),
        "last_log": j["log"][-1] if j["log"] else None,
    } for j in sorted(jobs, key=lambda x: x.get("created_at") or "", reverse=True)]}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "job 不存在（服务重启会清空任务表）")
    return job


@app.get("/history")
def history():
    """历史记录摘要（不含分镜正文，列表要轻）。"""
    return {"runs": store.list_runs()}


@app.get("/history/{run_id}")
def history_get(run_id: str):
    try:
        record = store.get(run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if record is None:
        raise HTTPException(404, "历史记录不存在")
    return record


@app.put("/history/{run_id}")
def history_update(run_id: str, result: dict = Body(..., embed=False)):
    """保存人工编辑后的分镜。

    只覆盖 result；创建时间与制作参数保持原样，另记 edited_at。
    """
    if not result.get("meta") or not result.get("episodes"):
        raise HTTPException(422, "不是分镜 IR：缺少 meta / episodes")
    try:
        record = store.update_result(run_id, result)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if record is None:
        raise HTTPException(404, "历史记录不存在")
    return {"id": run_id, "edited_at": record["edited_at"]}


@app.delete("/history/{run_id}")
def history_delete(run_id: str):
    try:
        ok = store.delete(run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "历史记录不存在")
    return {"deleted": run_id}


@app.get("/assets")
def assets():
    """按作品聚合的历史资产库，供新转换沿用（请求里回填 seed_assets）。"""
    return {"works": store.asset_library()}


@app.get("/healthz")
def healthz():
    s = load_settings()
    return {"status": "ok", "model": s.model,
            "api_key_configured": bool(s.api_key),
            "runs_dir": str(store.RUNS_DIR),
            "history_count": len(store.list_runs())}
