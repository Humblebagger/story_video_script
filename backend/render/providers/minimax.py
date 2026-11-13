"""MiniMax 海螺 H3：提示词改写（参考图N）、图片检查与规范化，以及提交、查询、下载（截尾帧）、计费。

接口与价格核对自 platform.minimax.cn 官方文档（2026-11-12）：
- POST /v2/video_generation → {"task_id"}；GET /v2/query/video_generation/{id} → {"task": {status,
  content.url（限时，过期重查）, usage.input_image_count, error}}；只能查 7 天内的任务。
- 图生（role=first_frame）与多模态参考（role=reference_image，≤ 9 张）互斥；不返回尾帧（下载后用 ffmpeg 截）。
- 计费：输出按秒；每个任务前 5 张输入图片免费，超出按张。失败任务按不计费处理（官方未写明，待账单核对）。
密钥 MINIMAX_API_KEY 写在 backend/.env，只放进请求头，不进日志与报错。
"""
import base64
import binascii
import itertools
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from pipeline.config import ROOT as BACKEND_ROOT
from pipeline.config import _load_dotenv
from render.providers.base import (AmbiguousSubmit, Caps, ClipRequest, ProviderError, TaskState,
                                   TransientError, last_frame_path, request_seconds)

BASE_URL = "https://api.minimax.cn"
# 2026-11 官方刊例价（元/秒，输出）；resolutions 的第一个为默认分辨率
MODELS = {
    "minimax-h3": {"id": "MiniMax-H3", "label": "MiniMax H3",
                   "cny_per_sec": {"768P": 0.50, "2K": 0.80}, "cny_per_image": 0.20},
    "minimax-h3-highspeed": {"id": "MiniMax-H3-Highspeed", "label": "MiniMax H3 Highspeed",
                             "cny_per_sec": {"768P": 0.40, "480P": 0.26}, "cny_per_image": 0.20},
    "minimax-h3-lite": {"id": "MiniMax-H3-Lite", "label": "MiniMax H3 Lite",
                        "cny_per_sec": {"768P": 0.26, "480P": 0.16}, "cny_per_image": 0.13},
}
DEFAULT_MODEL = "minimax-h3"
FREE_IMAGES = 5
SHORT_SIDE = {"480P": 480, "768P": 768, "2K": 1440}     # 2K 的实际像素待真跑核对（spec §5.1）
RATIOS = ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive")
TEXT_MAX = 300                                          # 拼进报错的服务端文字上限
PROMPT_MAX = 7000
IMAGE_MAX_BYTES = 30 * 1024 * 1024
BODY_MAX_BYTES = 60 * 1024 * 1024                       # 官方 64MB，留余量
SIDE_MIN, SIDE_MAX = 256, 5760
RATIO_MIN, RATIO_MAX = 0.4, 2.5
MIMES = ("image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif")
_EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/webp": ".webp",
        "image/heic": ".heic", "image/heif": ".heif"}
_STATUS = {"queued": "pending", "running": "running", "succeeded": "succeeded",
           "failed": "failed", "cancelled": "failed"}
_REF = re.compile(r"\{ref:([^{}]+)\}")
_DATA = re.compile(r"^data:([^;,]+);base64,(.*)$", re.S)
_CODE_IN_MSG = re.compile(r"\((\d{3,5})\)")
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_EXPIRED = (403, 404, 410)
_ALIAS = {"insufficient_balance_error": "1008", "authorized_error": "1004", "rate_limit_error": "1002"}
_HTTP_CODE = {402: "1008", 401: "1004", 422: "1026"}
MSG = {
    "1008": "MiniMax 账户余额不足（1008），充值后重新出这一段",
    "1004": "MiniMax 密钥无效（1004），检查 MINIMAX_API_KEY",
    "1026": "内容被 MiniMax 审核拦下（1026）：改写这一段的画面描述或换参考图后重试",
}
EXPIRED_MSG = "结果地址已过期且重新查询失败；任务只能在 7 天内查询"


def rewrite_refs(text: str) -> str:
    """厂商无关占位符 {ref:ID} → 「参考图N」，按出现顺序编号（同一资产出现两次也各占一张图）。
    请求里 reference_image 按同一顺序排列，第 N 张图对应文字里的「参考图N」。"""
    n = itertools.count(1)
    return _REF.sub(lambda m: f"参考图{next(n)}", text)


def _tool(name: str) -> Optional[str]:
    return shutil.which(name)


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _scale() -> float:
    raw = os.environ.get("STORYBOARD_MINIMAX_PRICE_SCALE", "").strip()
    try:
        k = float(raw) if raw else 1.0
    except ValueError:
        return 1.0
    return k if k > 0 else 1.0


def _code(raw, msg) -> Optional[str]:
    """错误码统一成字符串数字：认 code / type 别名，或从说明里的「(1026)」取。"""
    c = None if raw in (None, "", 0, "0") else str(raw)
    c = _ALIAS.get(c, c)
    if (c is None or not c.isdigit()) and isinstance(msg, str):
        m = _CODE_IN_MSG.search(msg)
        if m:
            c = m.group(1)
    return c


def _error_of(j) -> tuple:
    """(错误码, 说明)：取顶层 error 或 base_resp（官方没给出完整结构，两种都兼容）；都没有为 (None, None)。"""
    if not isinstance(j, dict):
        return None, None
    code, msg = None, None
    err = j.get("error")
    if isinstance(err, dict):
        msg = err.get("message")
        code = _code(err.get("code") or err.get("type"), msg)
    br = j.get("base_resp")
    if isinstance(br, dict) and br.get("status_code") not in (None, 0, "0"):
        msg = msg or br.get("status_msg")
        code = code or _code(br.get("status_code"), msg)
    return code, msg


def scrub(text, secret: str = "") -> str:
    """服务端文字进报错前：抹掉密钥与 Bearer 凭据，并截到 TEXT_MAX 字。"""
    t = str(text)
    if secret:
        t = t.replace(secret, "***")
    t = re.sub(r"(?i)(bearer\s+)[^\s\"',;]+", r"\1***", t)
    return t[:TEXT_MAX]


def _reject(code, msg, status=None, body: str = "", secret: str = "") -> ProviderError:
    key = code if code in MSG else _HTTP_CODE.get(status)
    if key in MSG:
        return ProviderError(MSG[key])
    text = "：".join(str(x) for x in (code, msg) if x)
    return ProviderError(scrub(text, secret) if text else f"HTTP {status}：{scrub(body, secret)}")


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def _even_up(x: float) -> int:
    return int(math.ceil(x / 2)) * 2


def plan_normalize(w: int, h: int) -> Optional[tuple]:
    """宽高不合规时给出 (缩放宽, 缩放高, 补边后宽, 补边后高)；合规返回 None。纯函数。

    太小等比放大到短边 256，太大等比缩小到长边 5760；比例超界用灰边补到 0.4 或 2.5。不裁剪。"""
    if SIDE_MIN <= w <= SIDE_MAX and SIDE_MIN <= h <= SIDE_MAX and RATIO_MIN <= w / h <= RATIO_MAX:
        return None
    s = 1.0
    if min(w, h) < SIDE_MIN:
        s = SIDE_MIN / min(w, h)
    if max(w, h) * s > SIDE_MAX:
        s = SIDE_MAX / max(w, h)
    sw, sh = min(_even(w * s), SIDE_MAX), min(_even(h * s), SIDE_MAX)
    pw, ph = sw, sh
    if sw / sh > RATIO_MAX:
        ph = _even_up(sw / RATIO_MAX)
    elif sw / sh < RATIO_MIN:
        pw = _even_up(sh * RATIO_MIN)
    return sw, sh, max(pw, SIDE_MIN), max(ph, SIDE_MIN)


def _normalize(raw: bytes, mime: str) -> tuple:
    """在临时目录里用 ffprobe 读宽高、必要时用 ffmpeg 规范化成 JPEG；返回 (字节, MIME)。
    没装 ffmpeg / 读不出宽高 / 转换失败：原样返回，由厂商判定。临时目录随即删除，不落盘缓存。"""
    ffprobe, ffmpeg = _tool("ffprobe"), _tool("ffmpeg")
    if not ffprobe or not ffmpeg:
        return raw, mime
    with tempfile.TemporaryDirectory(prefix="mm-norm-") as d:
        src = Path(d) / ("in" + _EXT.get(mime, ".img"))
        src.write_bytes(raw)
        try:
            out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                  "stream=width,height", "-of", "csv=p=0", str(src)],
                                 capture_output=True, text=True, timeout=30)
            w, h = (int(x) for x in out.stdout.strip().split(",")[:2])
        except (OSError, subprocess.SubprocessError, ValueError):
            return raw, mime
        plan = plan_normalize(w, h)
        if plan is None:
            return raw, mime
        sw, sh, pw, ph = plan
        dst = Path(d) / "out.jpg"
        try:
            r = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(src), "-vf",
                                f"scale={sw}:{sh},pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:color=gray",
                                "-frames:v", "1", "-q:v", "2", str(dst)], capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return raw, mime
        if r.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
            return raw, mime
        return dst.read_bytes(), "image/jpeg"


def _check_image(uri: str, label: str) -> tuple:
    """返回 (要发出的地址, 计入请求体的字节数)。http(s)、mm_file:// 原样透传；data URI 校验格式与体积并规范化。"""
    if not isinstance(uri, str):
        raise ProviderError(f"{label} 不是可用的图片地址")
    if uri.startswith(("http://", "https://", "mm_file://")):
        return uri, len(uri)
    m = _DATA.match(uri)
    if not m:
        raise ProviderError(f"{label} 不是可用的图片地址")
    mime = m.group(1).strip().lower()
    if mime not in MIMES:
        raise ProviderError(f"{label} 的格式 {mime} MiniMax 不支持（只收 JPG、PNG、WEBP、HEIC、HEIF）")
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise ProviderError(f"{label} 的图片数据损坏")
    if len(raw) > IMAGE_MAX_BYTES:
        raise ProviderError(f"{label} 有 {len(raw) / 1048576:.1f}MB，超过 MiniMax 单张 30MB 上限")
    raw, mime = _normalize(raw, mime)
    out = f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
    return out, len(out)


def _grab_last_frame(video: Path) -> Optional[Path]:
    """从成片末尾截一帧作尾帧（接力用）；截不到返回 None，不让本段失败。"""
    ffmpeg = _tool("ffmpeg")
    if not ffmpeg:
        return None
    out = last_frame_path(video)
    try:
        r = subprocess.run([ffmpeg, "-y", "-v", "error", "-sseof", "-0.1", "-i", str(video),
                            "-frames:v", "1", "-q:v", "2", str(out)], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        r = None
    if r is None or r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        return None
    return out


class _Expired(Exception):
    """下载地址过期（403/404/410）：download 内部用来触发一次重查。"""


class MiniMax:
    name = "minimax"
    default_model = DEFAULT_MODEL
    console_name = "MiniMax 开放平台"
    rate_note = ("2026-11 MiniMax 官方刊例价（H3 768P 0.50、2K 0.80 元/秒，Highspeed、Lite 见档位；"
                 "每段前 5 张参考图免费，超出另计），未经账单核对")

    def __init__(self, api_key: str, *, client=None, base_url: str = BASE_URL, timeout: float = 60.0):
        self._key = api_key
        self._http = client or httpx.Client(base_url=base_url, timeout=timeout)
        self.models = {k: {"label": v["label"]} for k, v in MODELS.items()}

    @classmethod
    def from_env(cls) -> "MiniMax":
        _load_dotenv(BACKEND_ROOT / ".env")
        _load_dotenv(BACKEND_ROOT.parent / ".env")
        key = os.environ.get("MINIMAX_API_KEY", "").strip()
        if not key:
            raise ProviderError("没有配置 MiniMax 密钥：在 backend/.env 写 MINIMAX_API_KEY=…")
        base_url = os.environ.get("STORYBOARD_MINIMAX_BASE_URL", "").strip() or BASE_URL
        return cls(key, base_url=base_url)

    def _model(self, model: str) -> dict:
        m = MODELS.get(model)
        if m is None:
            raise ProviderError(f"未知的 MiniMax 档位：{model}")
        return m

    def caps(self, model: str) -> Caps:
        m = self._model(model)
        k = _scale()
        res = list(m["cny_per_sec"])
        return Caps(max_clip_sec=15, min_clip_sec=4, max_refs=9, first_frame=True, last_frame=False,
                    returns_last_frame=True, native_audio=_flag("STORYBOARD_MINIMAX_NATIVE_AUDIO"),
                    frame_with_refs=False, resolutions=res,
                    cny_per_sec={r: round(p * k, 4) for r, p in m["cny_per_sec"].items()},
                    short_side={r: SHORT_SIDE[r] for r in res},
                    free_images=FREE_IMAGES, cny_per_image=round(m["cny_per_image"] * k, 4))

    def rewrite_prompt(self, text: str) -> str:
        return rewrite_refs(text)

    def _call(self, method: str, url: str, *, submit: bool = False, **kw) -> dict:
        """按 spec §8.1 的判定顺序归类：submit=True 时可能已受理的情况抛 AmbiguousSubmit（不重试）。"""
        try:
            r = self._http.request(method, url, headers={"Authorization": f"Bearer {self._key}"}, **kw)
        except _NOT_SENT as e:
            raise TransientError(f"连接 MiniMax 失败：{type(e).__name__}")
        except httpx.TransportError as e:
            if submit:
                raise AmbiguousSubmit(f"提交时连接中断：{type(e).__name__}")
            raise TransientError(f"连接 MiniMax 失败：{type(e).__name__}")
        try:
            j = r.json()
        except ValueError:
            j = None
        code, msg = _error_of(j)
        if r.status_code in (429, 529) or code == "1002":
            raise TransientError(f"MiniMax 限流或过载（HTTP {r.status_code}）")
        if r.status_code >= 500:
            if submit:
                raise AmbiguousSubmit(f"MiniMax 返回 HTTP {r.status_code}")
            raise TransientError(f"MiniMax 暂时不可用（HTTP {r.status_code}）")
        if r.status_code >= 400:
            raise _reject(code, msg, r.status_code, r.text, self._key)
        if code:                                      # 2xx 但厂商明确报了错：没建任务
            raise _reject(code, msg, secret=self._key)
        if not isinstance(j, dict):
            if submit:
                raise AmbiguousSubmit("MiniMax 返回的不是 JSON")
            raise TransientError("MiniMax 返回的不是 JSON")
        return j

    def submit(self, req: ClipRequest) -> str:
        m = self._model(req.model)
        caps = self.caps(req.model)
        if req.resolution not in caps.resolutions:
            raise ProviderError(f"{m['label']} 不支持 {req.resolution}，可选：{'、'.join(caps.resolutions)}")
        if len(req.prompt) > PROMPT_MAX:
            raise ProviderError(f"提示词超出 MiniMax 上限 {PROMPT_MAX} 字（当前 {len(req.prompt)} 字）")
        content = [{"type": "text", "text": req.prompt}]
        size = len(req.prompt.encode("utf-8"))
        body = {"model": m["id"], "content": content, "resolution": req.resolution,
                "duration": request_seconds(req.duration, caps), "aigc_watermark": False}
        if req.refs:
            for ref in req.refs:
                label = "首帧" if ref.role == "first_frame" else f"参考图 {ref.asset_id}"
                url, n = _check_image(ref.source, label)
                content.append({"type": "image_url", "image_url": {"url": url}, "role": "reference_image"})
                size += n
        elif req.first_frame:
            url, n = _check_image(req.first_frame, "首帧")
            content.append({"type": "image_url", "image_url": {"url": url}, "role": "first_frame"})
            size += n
        if req.refs or not req.first_frame:           # 参考生与文生显式给比例；图生由图决定
            if req.aspect == "adaptive" and req.refs and req.model == "minimax-h3-lite":
                raise ProviderError("MiniMax H3 Lite 的参考生视频必须明确画幅，不支持 adaptive")
            if req.aspect not in RATIOS:
                raise ProviderError(f"MiniMax 不支持画幅 {req.aspect}，可选：{'、'.join(RATIOS)}")
            body["ratio"] = req.aspect
        if size > BODY_MAX_BYTES:
            raise ProviderError(f"请求体约 {size / 1048576:.1f}MB，超过 MiniMax 上限：减少参考图或换小一些的图")
        j = self._call("POST", "/v2/video_generation", submit=True, json=body)
        tid = j.get("task_id")
        if not tid:
            raise AmbiguousSubmit("MiniMax 受理了请求却没有返回任务 id")
        return str(tid)

    def poll(self, task_id: str) -> TaskState:
        j = self._call("GET", f"/v2/query/video_generation/{task_id}")
        t = j.get("task") if isinstance(j.get("task"), dict) else j
        raw = t.get("status")
        status = _STATUS.get(raw, "running")
        content = t.get("content") if isinstance(t.get("content"), dict) else {}
        error = None
        if status == "failed":
            if raw == "cancelled":
                error = "任务已取消"
            else:
                err = t.get("error") if isinstance(t.get("error"), dict) else {}
                code = _code(err.get("code") or err.get("type"), err.get("message"))
                error = (MSG.get(code) or scrub("：".join(str(x) for x in (code, err.get("message")) if x), self._key)
                         or "生成失败")
        usage = t.get("usage") if status == "succeeded" and isinstance(t.get("usage"), dict) else {}
        return TaskState(task_id, status, video_url=content.get("url"), last_frame_url=None,
                         error=error, usage=dict(usage))

    def _fetch(self, url: Optional[str], dest: Path) -> None:
        """结果地址是限时签名直链：不带密钥。先写 .part 再改名；不建上级目录（版本删了不能被下载重建）。"""
        if not url:
            raise ProviderError("MiniMax 没有返回结果地址")
        dest.parent.mkdir(exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        try:
            with self._http.stream("GET", url) as r:
                if r.status_code in _EXPIRED:
                    raise _Expired()
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransientError(f"下载暂时失败（HTTP {r.status_code}）")
                if r.status_code >= 400:
                    raise ProviderError(f"下载失败（HTTP {r.status_code}）")
                with open(part, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
        except httpx.TransportError as e:
            raise TransientError(f"下载连接失败：{type(e).__name__}")
        part.replace(dest)

    def download(self, st: TaskState, dest: Path) -> dict:
        try:
            self._fetch(st.video_url, dest)
        except _Expired:
            # 地址过期：用任务 id 重查一次拿新地址（新地址不写回尝试，下次过期再重查）
            try:
                fresh = self.poll(st.task_id)
            except ProviderError:
                raise ProviderError(EXPIRED_MSG)
            if fresh.status != "succeeded" or not fresh.video_url:
                raise ProviderError(EXPIRED_MSG)
            try:
                self._fetch(fresh.video_url, dest)
            except _Expired:
                raise ProviderError(EXPIRED_MSG)
        return {"video": dest, "last_frame": _grab_last_frame(dest)}

    def cost(self, st: TaskState, req: ClipRequest) -> float:
        if st.status != "succeeded":
            return 0.0                                  # 失败按不计费处理（官方未写明，待账单核对）
        caps = self.caps(req.model)
        used = (st.usage or {}).get("input_image_count")
        images = used if isinstance(used, int) and not isinstance(used, bool) else (req.images or 0)
        sec = request_seconds(req.duration, caps)
        extra = max(0, images - caps.free_images) * caps.cny_per_image
        return round(sec * caps.cny_per_sec.get(req.resolution, 0.0) + extra, 2)
