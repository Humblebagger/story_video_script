"""火山方舟 Seedance：提示词语法（@图片n），以及提交、查询、下载、计费。

接口与价格核实于 2026-10-31 的官方文档：
- POST /contents/generations/tasks → {"id"}；GET /contents/generations/tasks/{id} → status、
  content.video_url / last_frame_url（24 小时有效）、usage.completion_tokens、error。
- 首帧模式（role=first_frame）与参考图模式（role=reference_image，2.0 最多 9 张）互斥。
- 计费按 completion_tokens × 单价；token ≈ 秒数 × 宽 × 高 × 24 / 1024；失败任务不计费。
密钥 ARK_API_KEY 写在 backend/.env，只放进请求头，不进日志与报错。
"""
import itertools
import logging
import os
import re
from pathlib import Path
from typing import Optional

import httpx

from pipeline.config import ROOT as BACKEND_ROOT
from pipeline.config import _load_dotenv
from render.providers.base import (AmbiguousSubmit, Caps, ClipRequest, ProviderError, TaskState,
                                   TransientError, estimate_cny, last_frame_path, request_seconds, scrub)
from server.messages import compact, msg, vendor

log = logging.getLogger("render.providers.seedance")

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


def _with_fallback(e: ProviderError, full: str) -> ProviderError:
    """中文兜底保持原样不截断（结构化的 vendor 参数仍限长）。"""
    e.args = (full,) + e.args[1:]
    return e


# 方舟错误码 → 我们的代码（官方错误码页 https://www.volcengine.com/docs/82379/1299023）。
# 匹配顺序：全名 → 「.PolicyViolation」后缀 → 族名（第一个「.」之前）→ Input*/Output* 前缀 +
# SensitiveContentDetected / RiskDetection 后缀。
# 限流族（RateLimitExceeded、ServerOverloaded、RequestBurstTooFast）不登记：落到可重试的瞬时分支。
_ARK_EXACT = {
    "OperationDenied.ServiceNotOpen": "film.ark.model_unavailable",
    "OperationDenied.ServiceOverdue": "film.ark.overdue",
    "OperationDenied.PermissionDenied": "film.ark.access_denied",
    "InvalidEndpoint.ClosedEndpoint": "film.ark.model_unavailable",
}
_ARK_FAMILY = {
    "AuthenticationError": "film.ark.auth", "InvalidSubscription": "film.ark.auth",
    "AccountOverdueError": "film.ark.overdue",
    "AccessDenied": "film.ark.access_denied", "InvalidAccountStatus": "film.ark.access_denied",
    "InvalidEndpointOrModel": "film.ark.model_unavailable", "ModelNotOpen": "film.ark.model_unavailable",
    "SetLimitExceeded": "film.ark.limit_paused",
    "QuotaExceeded": "film.ark.quota",                # 官方是 429：额度不足或排队已满，可重试
    "SensitiveContentDetected": "film.ark.input_moderated",
}
_ARK_HTTP = {401: "film.ark.auth", 403: "film.ark.access_denied"}
_ARK_TRANSIENT = {"film.ark.quota"}          # 映射后仍可重试的代码（不论 HTTP 状态）


def _ark_code(code) -> Optional[str]:
    if not isinstance(code, str) or not code:
        return None
    fam = code.split(".", 1)[0]
    out = fam.startswith("Output")
    if code in _ARK_EXACT:
        return _ARK_EXACT[code]
    if code.endswith(".PolicyViolation"):
        return "film.ark.output_copyright" if out else "film.ark.copyright"
    if fam in _ARK_FAMILY:
        return _ARK_FAMILY[fam]
    if fam.endswith(("SensitiveContentDetected", "RiskDetection")):
        if fam.startswith("Input"):
            return "film.ark.input_moderated"
        if out:
            return "film.ark.output_moderated"
    return None


def _err_body(r: httpx.Response) -> Optional[dict]:
    """响应体里的 error 对象。不是 JSON 为 None；是 JSON 但没有 error 对象为 {}。"""
    try:
        j = r.json()
    except ValueError:
        return None
    err = j.get("error") if isinstance(j, dict) else None
    return err if isinstance(err, dict) else {}


def _mapped(our: str, status, err: dict, key: str, *, request_id=None, task_id=None, model=None):
    """命中映射：原文脱敏进日志（带定位信息），返回带代码的异常；额度类可重试。"""
    parts = [str(x) for x in (err.get("code"), err.get("message")) if x]
    log.warning("方舟错误 HTTP %s request_id=%s task=%s model=%s：%s", status, request_id or "-",  # i18n: internal
                task_id or "-", model or "-", scrub(": ".join(parts), key))
    cls = TransientError if our in _ARK_TRANSIENT else ProviderError
    return cls.of(our)


def _reject(r: httpx.Response, key: str, *, model=None, task_id=None) -> ProviderError:
    """4xx：已知方舟错误码给友好文案（原文进日志）；其余把厂商原因脱敏（密钥、Bearer 凭据）后作原文参数。"""
    err = _err_body(r)
    our = _ark_code((err or {}).get("code"))
    if our is None and not (err and (err.get("code") or err.get("message"))):
        our = _ARK_HTTP.get(r.status_code)          # 没有任何错误信息时才按 HTTP 状态回落
    if our:
        return _mapped(our, r.status_code, err or {}, key, request_id=r.headers.get("X-Request-Id"),
                       task_id=task_id, model=model)
    if err is None:
        body = scrub(r.text, key)[:300]
        return _with_fallback(ProviderError.of("film.provider.http_rejected", status=r.status_code,
                                               detail=vendor(body)), f"HTTP {r.status_code}：{body}")
    parts = [x for x in (err.get("code"), err.get("message")) if x]
    zh = scrub("：".join(parts) or f"HTTP {r.status_code}", key)
    text = scrub(": ".join(parts) or f"HTTP {r.status_code}", key)
    return _with_fallback(ProviderError.of("film.provider.rejected", detail=vendor(text)), zh)


class Seedance:
    name = "seedance"
    console_name = "console.ark"
    default_model = DEFAULT_MODEL
    rate_note = {"code": "rate.ark", "params": {}}

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
            raise ProviderError.of("film.ark.no_key")
        return cls(key)

    def _model(self, model: str) -> dict:
        m = MODELS.get(model)
        if m is None:
            raise ProviderError.of("film.ark.unknown_model", model=model)
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

    def _call(self, method: str, url: str, *, submit: bool = False, model=None, task_id=None, meta=None, **kw) -> dict:
        """submit=True（提交任务）时，请求可能已被受理的情况抛 AmbiguousSubmit 而不是瞬时错误：
        只有请求没发出去（连不上、连接超时、连接池超时）或 429 才允许重试。"""
        try:
            r = self._http.request(method, url, headers={"Authorization": f"Bearer {self._key}"}, **kw)
        except _NOT_SENT as e:
            raise TransientError.of("film.ark.connect_failed", kind=type(e).__name__)
        except httpx.TransportError as e:
            if submit:
                raise AmbiguousSubmit.of("film.provider.submit_cut", kind=type(e).__name__)
            raise TransientError.of("film.ark.connect_failed", kind=type(e).__name__)
        if r.status_code == 429:
            err = _err_body(r)
            our = _ark_code((err or {}).get("code"))
            # 429 里只有 SetLimitExceeded 不重试、QuotaExceeded 用自己的代码；其余（含鉴权、审核等
            # 不该出现在 429 的码）一律当限流重试
            if our in ("film.ark.limit_paused", "film.ark.quota"):
                raise _mapped(our, 429, err, self._key, request_id=r.headers.get("X-Request-Id"),
                              task_id=task_id, model=model)
            raise TransientError.of("film.ark.throttled")
        if r.status_code >= 500:
            if submit:
                raise AmbiguousSubmit.of("film.ark.http_ambiguous", status=r.status_code)
            raise TransientError.of("film.ark.unavailable", status=r.status_code)
        if meta is not None:
            meta["request_id"] = r.headers.get("X-Request-Id")
        if r.status_code >= 400:
            raise _reject(r, self._key, model=model, task_id=task_id)
        try:
            return r.json()
        except ValueError:
            if submit:
                raise AmbiguousSubmit.of("film.ark.not_json")
            raise TransientError.of("film.ark.not_json")

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
        j = self._call("POST", "/contents/generations/tasks", submit=True,
                       model=m["id"], json=body)
        tid = j.get("id") if isinstance(j, dict) else None
        if not tid:
            raise AmbiguousSubmit.of("film.ark.no_task_id")
        return tid

    def poll(self, task_id: str) -> TaskState:
        meta = {}
        j = self._call("GET", f"/contents/generations/tasks/{task_id}", task_id=task_id, meta=meta)
        raw = j.get("status")
        status = _STATUS.get(raw, "running")
        content = j.get("content") or {}
        error, error_msg = None, None
        if status == "failed":
            err = j.get("error") or {}
            our = _ark_code(err.get("code"))
            if our:
                _mapped(our, "task", err, self._key, request_id=meta.get("request_id"), task_id=task_id)
            parts = [x for x in (err.get("code"), err.get("message")) if x]
            text = scrub(": ".join(parts), self._key)
            zh = scrub("：".join(parts), self._key)              # 中文兜底保持原样
            m = (msg(our) if our
                 else msg("film.provider.rejected", detail=vendor(text)) if text
                 else msg("film.ark.task_expired") if raw == "expired"
                 else msg("film.provider.task_cancelled") if raw == "cancelled"
                 else msg("film.provider.generation_failed"))
            error, error_msg = (zh if zh and not our else m["message"]), compact(m)
        return TaskState(task_id, status, video_url=content.get("video_url"),
                         last_frame_url=content.get("last_frame_url"), error=error, error_msg=error_msg,
                         usage={"completion_tokens": (j.get("usage") or {}).get("completion_tokens")}
                         if status == "succeeded" else {})

    def _fetch(self, url: str, dest: Path) -> None:
        """结果地址是对象存储的签名直链：不带方舟密钥，24 小时有效。"""
        if not url:
            raise ProviderError.of("film.ark.no_result_url")
        dest.parent.mkdir(exist_ok=True)              # 不建上级目录：版本删了不能被下载重新建出来
        part = dest.with_name(dest.name + ".part")
        try:
            with self._http.stream("GET", url) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransientError.of("film.provider.download_retry", status=r.status_code)
                if r.status_code >= 400:
                    raise ProviderError.of("film.ark.download_failed", status=r.status_code)
                with open(part, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
        except httpx.TransportError as e:
            raise TransientError.of("film.provider.download_connect", kind=type(e).__name__)
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
