"""HTTP 服务：POST 小说文本 → 后台转换 → GET 取分镜 JSON。

启动：uvicorn server.app:app --host 0.0.0.0 --port 8000
转换耗时为分钟级（LLM 长输出），故采用异步任务模型：
  POST /convert          → {"job_id": ...}
  GET  /jobs/{job_id}    → {"status": queued|running|succeeded|failed, "result": 分镜JSON, "log": [...]}
  GET  /healthz          → 存活与配置探针
任务表在内存中，进程重启即清空（结果请在 succeeded 后及时取走）。
"""
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import __version__
from pipeline.config import load_settings
from pipeline.convert import ConversionError, ConvertParams, convert_text

app = FastAPI(title="小说 → 分镜 IR 转换服务", version=__version__)

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
    try:
        job["result"] = convert_text(req.text, params, log=log)
        job["status"] = "succeeded"
    except ConversionError as e:
        job["status"] = "failed"
        job["error"] = f"{e}\n{e.report}"
    except Exception as e:  # LLM/网络等运行期错误
        job["status"] = "failed"
        job["error"] = repr(e)


@app.post("/convert")
def submit(req: ConvertRequest):
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "status": "queued", "log": [], "result": None, "error": None}
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_run_job, job, req)
    return {"job_id": job_id, "status_url": f"/jobs/{job_id}"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "job 不存在（服务重启会清空任务表）")
    return job


@app.get("/healthz")
def healthz():
    s = load_settings()
    return {"status": "ok", "model": s.model,
            "api_key_configured": bool(s.api_key)}
