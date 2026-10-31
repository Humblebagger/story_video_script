"""火山方舟 Seedance：提示词语法（@图片n），以及提交、查询、下载、计费。

接口与价格核实于 2026-10-31 的官方文档：
- POST /contents/generations/tasks → {"id"}；GET /contents/generations/tasks/{id} → status、
  content.video_url / last_frame_url（24 小时有效）、usage.completion_tokens、error。
- 首帧模式（role=first_frame）与参考图模式（role=reference_image，2.0 最多 9 张）互斥。
- 计费按 completion_tokens × 单价；token ≈ 秒数 × 宽 × 高 × 24 / 1024；失败任务不计费。
密钥 ARK_API_KEY 写在 backend/.env，只放进请求头，不进日志与报错。
"""
import itertools
import os
import re
from pathlib import Path

import httpx

from pipeline.config import ROOT as BACKEND_ROOT
from pipeline.config import _load_dotenv
from render.providers.base import (AmbiguousSubmit, Caps, ClipRequest, ProviderError, TaskState,
                                   TransientError, estimate_cny, last_frame_path, request_seconds)

BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
# 2026-10 刊例价（元/百万 token，输入不含视频）；资源包与折扣不建模。
# 用真实账单校准后可用 STORYBOARD_SEEDANCE_CNY_PER_M 覆盖（对所有档位生效）。
MODELS = {
    "seedance-2.0": {"id": "doubao-seedance-2-0-260128", "label": "Seedance 2.0",
                     "cny_per_m": 46.0, "resolutions": ["480p", "720p", "1080p"]},
    "seedance-2.0-fast": {"id": "doubao-seedance-2-0-fast-260128", "label": "Seedance 2.0 fast",
                          "cny_per_m": 37.0, "resolutions": ["480p", "720p"]},
    "seedance-2.0-mini": {"id": "doubao-seedance-2-0-mini-260615", "label": "Seedance 2.0 mini",
                          "cny_per_m": 23.0, "resolutions": ["480p", "720p"]},
}
DEFAULT_MODEL = "seedance-2.0-fast"
FPS = 24
PIXELS = {"480p": 480 * 864, "720p": 720 * 1280, "1080p": 1080 * 1920}
_STATUS = {"queued": "pending", "running": "running", "succeeded": "succeeded",
           "failed": "failed", "expired": "failed", "cancelled": "failed"}
_REF = re.compile(r"\{ref:([^{}]+)\}")
# 这几种错误发生时请求还没发出去，提交可以放心重试；其它传输错误下方舟可能已建了任务
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def rewrite_refs(text: str) -> str:
    """厂商无关占位符 {ref:ID} → Seedance 的 @图片n，按出现顺序编号。

    同一资产出现两次也各占一张图（同一场景的两个机位是两张图），所以按次序而不是按 ID
    编号；请求里的参考图按同一顺序排列。
    """
    n = itertools.count(1)
    return _REF.sub(lambda m: f"@图片{next(n)}", text)


def _error_text(r: httpx.Response) -> str:
    try:
        err = (r.json() or {}).get("error") or {}
    except ValueError:
        return f"HTTP {r.status_code}：{r.text[:300]}"
    text = "：".join(x for x in (err.get("code"), err.get("message")) if x)
    return text or f"HTTP {r.status_code}"


class Seedance:
    name = "seedance"
    default_model = DEFAULT_MODEL
    rate_note = ("2026-10 方舟官方刊例价（2.0 为 46、fast 为 37、mini 为 23 元/百万 token，"
                 "token ≈ 秒 × 宽 × 高 × 24 / 1024），未经账单核对")

    def __init__(self, api_key: str, *, client=None, base_url: str = BASE_URL, timeout: float = 60.0):
        self._key = api_key
        self._http = client or httpx.Client(base_url=base_url, timeout=timeout)
        self.models = {k: {"label": v["label"]} for k, v in MODELS.items()}

    @classmethod
    def from_env(cls) -> "Seedance":
        _load_dotenv(BACKEND_ROOT / ".env")
        _load_dotenv(BACKEND_ROOT.parent / ".env")
        key = os.environ.get("ARK_API_KEY", "").strip()
        if not key:
            raise ProviderError("没有配置方舟密钥：在 backend/.env 写 ARK_API_KEY=…")
        return cls(key)

    def _model(self, model: str) -> dict:
        m = MODELS.get(model)
        if m is None:
            raise ProviderError(f"未知的 Seedance 档位：{model}")
        return m

    def _per_m(self, model: str) -> float:
        raw = os.environ.get("STORYBOARD_SEEDANCE_CNY_PER_M", "").strip()
        try:
            return float(raw) if raw else self._model(model)["cny_per_m"]
        except ValueError:
            return self._model(model)["cny_per_m"]

    def caps(self, model: str) -> Caps:
        m = self._model(model)
        per_m = self._per_m(model)
        return Caps(max_clip_sec=15, min_clip_sec=4, max_refs=9, first_frame=True,
                    last_frame=True, returns_last_frame=True, native_audio=True,
                    frame_with_refs=False, resolutions=list(m["resolutions"]),
                    cny_per_sec={r: round(PIXELS[r] * FPS / 1024 * per_m / 1e6, 4)
                                 for r in m["resolutions"]})

    def rewrite_prompt(self, text: str) -> str:
        return rewrite_refs(text)

    def _call(self, method: str, url: str, *, submit: bool = False, **kw) -> dict:
        """submit=True（提交任务）时，请求可能已被受理的情况抛 AmbiguousSubmit 而不是瞬时错误：
        只有请求没发出去（连不上、连接超时、连接池超时）或 429 才允许重试。"""
        try:
            r = self._http.request(method, url, headers={"Authorization": f"Bearer {self._key}"}, **kw)
        except _NOT_SENT as e:
            raise TransientError(f"连接方舟失败：{type(e).__name__}")
        except httpx.TransportError as e:
            if submit:
                raise AmbiguousSubmit(f"提交时连接中断：{type(e).__name__}")
            raise TransientError(f"连接方舟失败：{type(e).__name__}")
        if r.status_code == 429:
            raise TransientError("方舟限流（HTTP 429）")
        if r.status_code >= 500:
            if submit:
                raise AmbiguousSubmit(f"方舟返回 HTTP {r.status_code}")
            raise TransientError(f"方舟暂时不可用（HTTP {r.status_code}）")
        if r.status_code >= 400:
            raise ProviderError(_error_text(r))
        try:
            return r.json()
        except ValueError:
            if submit:
                raise AmbiguousSubmit("方舟返回的不是 JSON")
            raise TransientError("方舟返回的不是 JSON")

    def submit(self, req: ClipRequest) -> str:
        m = self._model(req.model)
        content = [{"type": "text", "text": req.prompt}]
        if req.first_frame and not req.refs:
            content.append({"type": "image_url", "image_url": {"url": req.first_frame},
                            "role": "first_frame"})
        for ref in req.refs:
            content.append({"type": "image_url", "image_url": {"url": ref.source},
                            "role": "reference_image"})
        body = {"model": m["id"], "content": content, "resolution": req.resolution,
                "ratio": req.aspect, "duration": request_seconds(req.duration, self.caps(req.model)),
                "generate_audio": req.audio, "watermark": False, "return_last_frame": True}
        j = self._call("POST", "/contents/generations/tasks", submit=True, json=body)
        tid = j.get("id") if isinstance(j, dict) else None
        if not tid:
            raise AmbiguousSubmit("方舟受理了请求却没有返回任务 id")
        return tid

    def poll(self, task_id: str) -> TaskState:
        j = self._call("GET", f"/contents/generations/tasks/{task_id}")
        raw = j.get("status")
        status = _STATUS.get(raw, "running")
        content = j.get("content") or {}
        error = None
        if status == "failed":
            err = j.get("error") or {}
            error = ("：".join(x for x in (err.get("code"), err.get("message")) if x)
                     or {"expired": "任务超时", "cancelled": "任务已取消"}.get(raw, "生成失败"))
        return TaskState(task_id, status, video_url=content.get("video_url"),
                         last_frame_url=content.get("last_frame_url"), error=error,
                         usage={"completion_tokens": (j.get("usage") or {}).get("completion_tokens")}
                         if status == "succeeded" else {})

    def _fetch(self, url: str, dest: Path) -> None:
        """结果地址是对象存储的签名直链：不带方舟密钥，24 小时有效。"""
        if not url:
            raise ProviderError("方舟没有返回结果地址")
        dest.parent.mkdir(exist_ok=True)              # 不建上级目录：版本删了不能被下载重新建出来
        part = dest.with_name(dest.name + ".part")
        try:
            with self._http.stream("GET", url) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransientError(f"下载暂时失败（HTTP {r.status_code}）")
                if r.status_code >= 400:
                    raise ProviderError(f"下载失败（HTTP {r.status_code}）：结果地址 24 小时内有效")
                with open(part, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
        except httpx.TransportError as e:
            raise TransientError(f"下载连接失败：{type(e).__name__}")
        part.replace(dest)

    def download(self, st: TaskState, dest: Path) -> dict:
        self._fetch(st.video_url, dest)
        last = None
        if st.last_frame_url:
            last = last_frame_path(dest)
            try:
                self._fetch(st.last_frame_url, last)
            except ProviderError:
                last = None                         # 尾帧只用于接力，拿不到不影响这一段
        return {"video": dest, "last_frame": last}

    def cost(self, st: TaskState, req: ClipRequest) -> float:
        if st.status != "succeeded":
            return 0.0                              # 方舟失败任务不计费
        tokens = (st.usage or {}).get("completion_tokens")
        if tokens:
            return round(tokens * self._per_m(req.model) / 1e6, 2)
        return estimate_cny(req.duration, self.caps(req.model), req.resolution)
