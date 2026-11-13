"""出片：视频厂商统一接口。

主流程只用 caps / rewrite_prompt / submit / poll / download / cost。新增厂商 = 新文件 +
在 providers/__init__.py 注册一行。厂商的提示词语法（如 Seedance 的 @图片n）只在厂商模块里。
"""
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from server.messages import UserError

REF_ROLES = ("character", "creature", "location", "prop", "first_frame", "style")


class ProviderError(UserError, Exception):
    """厂商明确失败（审核、参数、密钥）：原因原样展示，不自动重试。"""


class TransientError(UserError, Exception):
    """断连、5xx、限流：调用方自动重试，不算新尝试。"""


class AmbiguousSubmit(UserError, Exception):
    """提交请求可能已被厂商受理（请求发出后断连、超时、5xx、2xx 却没拿到任务 id）：
    不能重试（重试可能再建一个付费任务），记失败并提示用户到厂商控制台核对。"""


@dataclass
class Caps:
    max_clip_sec: float
    min_clip_sec: float
    max_refs: int
    first_frame: bool               # 可指定首帧
    last_frame: bool                # 可指定结束帧
    returns_last_frame: bool        # 能返回成片尾帧，用于接力（拿不到时下一段不带首帧，链路自带兜底）
    native_audio: bool
    frame_with_refs: bool           # 首帧与参考图能否同用（方舟、MiniMax 都不能：两种模式互斥）
    resolutions: list
    cny_per_sec: dict               # 分辨率 → 元/秒，只用于预估
    short_side: dict = field(default_factory=dict)   # 分辨率 → 成片短边像素；空表时合成按 mix.SHORT_SIDE
    free_images: int = 0            # 每个任务免费的输入图片张数
    cny_per_image: float = 0.0      # 超出免费张数后每张的价格（元）


@dataclass
class RefImage:
    asset_id: str
    role: str                       # REF_ROLES 之一
    source: str                     # http(s) 地址或 data:image/...;base64,...


@dataclass
class ClipRequest:
    prompt: str                     # 已改写为该厂商语法
    model: str
    duration: float
    resolution: str
    aspect: str = "9:16"
    audio: bool = True
    refs: list = field(default_factory=list)   # list[RefImage]，已按 max_refs 裁剪
    first_frame: Optional[str] = None          # 首帧图，格式同 RefImage.source
    style_ref: Optional[str] = None            # 带上的风格图哈希（没带为 None）
    images: Optional[int] = None               # 只用于计费：提交时实际发出的图片张数（submit 不读）


@dataclass
class TaskState:
    task_id: str
    status: str                     # pending / running / succeeded / failed
    video_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    error: Optional[str] = None     # 中文兜底（含厂商原文）
    error_msg: Optional[dict] = None  # {code, params}：前端按代码渲染
    usage: dict = field(default_factory=dict)


class VideoProvider(Protocol):
    name: str
    default_model: str
    models: dict                    # 档位 id → {"label": ...}
    rate_note: dict     # 费率依据（消息对象 {code, params}）：如实写出处、是否经账单核对；出片确认框照抄
    console_name: str   # 厂商控制台名的代码，如 console.ark

    def caps(self, model: str) -> Caps: ...
    def rewrite_prompt(self, text: str) -> str: ...
    def submit(self, req: ClipRequest) -> str: ...
    def poll(self, task_id: str) -> TaskState: ...
    def download(self, st: TaskState, dest: Path) -> dict: ...   # {"video": Path, "last_frame": Path | None}
    def cost(self, st: TaskState, req: ClipRequest) -> float: ...


def scrub(text, secret: str = "", limit: Optional[int] = None) -> str:
    """服务端文字进报错前：抹掉密钥、Bearer 凭据与 x-api-key 头；limit 不为 None 时再截断。"""
    t = str(text)
    if secret:
        t = t.replace(secret, "***")
    t = re.sub(r"(?i)(bearer\s+)[^\s\"',;]+", r"\1***", t)
    t = re.sub(r"(?i)(x-api-key[\"']?\s*[:=]\s*[\"']?)[^\s\"',;}]+", r"\1***", t)
    return t if limit is None else t[:limit]


# 日志与错误记录里一律抹掉的环境变量值：厂商密钥、模型密钥（章后整理与转换，经 x-api-key 发出）、token 签名密钥
SECRET_ENVS = ("ARK_API_KEY", "MINIMAX_API_KEY", "VOLC_TTS_API_KEY", "VOLC_TTS_ACCESS_KEY",
               "ANTHROPIC_API_KEY", "STORYBOARD_SECRET")


def scrub_secrets(text, extra=()) -> str:
    """日志文字脱敏：抹掉 Bearer 凭据、环境里配置的各厂商密钥与调用方给的密钥（如厂商对象持有的）。
    非空密钥一律抹掉，没有最短长度。"""
    out = scrub(text)
    for k in [os.environ.get(n, "") for n in SECRET_ENVS] + list(extra):
        if isinstance(k, str) and k.strip():
            out = out.replace(k.strip(), "***")
    return out


def request_seconds(duration: float, caps: Caps) -> int:
    """发给厂商的整数秒：向上取整，夹在 [min_clip_sec, max_clip_sec]。"""
    return int(min(caps.max_clip_sec, max(caps.min_clip_sec, math.ceil(duration - 1e-6))))


def estimate_cny(duration: float, caps: Caps, resolution: str, images: int = 0) -> float:
    """预估金额：整数秒 × 单价，加超出免费张数的图片费。"""
    extra = max(0, int(images or 0) - caps.free_images) * caps.cny_per_image
    return round(request_seconds(duration, caps) * caps.cny_per_sec.get(resolution, 0.0) + extra, 2)


def last_frame_path(video: Path) -> Path:
    return video.with_name(video.stem + ".last.jpg")


def is_playable_mp4(path: Path) -> bool:
    """不依赖 ffmpeg 的最低校验：文件存在且是 MP4 容器（第 4–8 字节为 ftyp）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
    except OSError:
        return False
    return len(head) >= 8 and head[4:8] == b"ftyp"
