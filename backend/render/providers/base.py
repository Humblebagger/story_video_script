"""出片：视频厂商统一接口。

主流程只用 caps / rewrite_prompt / submit / poll / download / cost。新增厂商 = 新文件 +
在 providers/__init__.py 注册一行。厂商的提示词语法（如 Seedance 的 @图片n）只在厂商模块里。
"""
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

REF_ROLES = ("character", "creature", "location", "prop", "first_frame")


class ProviderError(Exception):
    """厂商明确失败（审核、参数、密钥）：原因原样展示，不自动重试。"""


class TransientError(Exception):
    """断连、5xx、限流：调用方自动重试，不算新尝试。"""


class AmbiguousSubmit(Exception):
    """提交请求可能已被厂商受理（请求发出后断连、超时、5xx、2xx 却没拿到任务 id）：
    不能重试（重试可能再建一个付费任务），记失败并提示用户到厂商控制台核对。"""


@dataclass
class Caps:
    max_clip_sec: float
    min_clip_sec: float
    max_refs: int
    first_frame: bool               # 可指定首帧
    last_frame: bool                # 可指定结束帧
    returns_last_frame: bool        # 能返回成片尾帧，用于接力
    native_audio: bool
    frame_with_refs: bool           # 首帧与参考图能否同用（方舟不能：两种模式互斥）
    resolutions: list
    cny_per_sec: dict               # 分辨率 → 元/秒，只用于预估


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


@dataclass
class TaskState:
    task_id: str
    status: str                     # pending / running / succeeded / failed
    video_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    error: Optional[str] = None     # 厂商原文
    usage: dict = field(default_factory=dict)


class VideoProvider(Protocol):
    name: str
    default_model: str
    models: dict                    # 档位 id → {"label": ...}

    def caps(self, model: str) -> Caps: ...
    def rewrite_prompt(self, text: str) -> str: ...
    def submit(self, req: ClipRequest) -> str: ...
    def poll(self, task_id: str) -> TaskState: ...
    def download(self, st: TaskState, dest: Path) -> dict: ...   # {"video": Path, "last_frame": Path | None}
    def cost(self, st: TaskState, req: ClipRequest) -> float: ...


def request_seconds(duration: float, caps: Caps) -> int:
    """发给厂商的整数秒：向上取整，夹在 [min_clip_sec, max_clip_sec]。"""
    return int(min(caps.max_clip_sec, max(caps.min_clip_sec, math.ceil(duration - 1e-6))))


def estimate_cny(duration: float, caps: Caps, resolution: str) -> float:
    return round(request_seconds(duration, caps) * caps.cny_per_sec.get(resolution, 0.0), 2)


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
