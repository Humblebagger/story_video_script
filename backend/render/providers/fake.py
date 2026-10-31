"""假视频厂商：不联网、不花钱，按调用次数推进状态。测试与本地演示用。"""
import re
from typing import Optional

from render.providers.base import (Caps, ProviderError, TaskState, TransientError,
                                   last_frame_path, request_seconds)

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
FAKE_JPG = b"\xff\xd8\xff\xe0fake-last-frame"
_REF = re.compile(r"\{ref:([^{}]+)\}")


class FakeVideo:
    name = "fake"
    default_model = "fake-1"

    def __init__(self, *, polls_to_finish: int = 1, fail_with: Optional[str] = None,
                 transient_submits: int = 0, max_refs: int = 3, frame_with_refs: bool = False):
        self.models = {"fake-1": {"label": "假厂商"}}
        self._caps = Caps(max_clip_sec=10, min_clip_sec=2, max_refs=max_refs, first_frame=True,
                          last_frame=False, returns_last_frame=True, native_audio=True,
                          frame_with_refs=frame_with_refs, resolutions=["480p", "720p"],
                          cny_per_sec={"480p": 0.5, "720p": 1.0})
        self.polls_to_finish = polls_to_finish
        self.fail_with = fail_with
        self.transient_submits = transient_submits
        self.submitted = []         # 依次提交的 ClipRequest
        self.tasks = {}

    def caps(self, model):
        if model not in self.models:
            raise ProviderError(f"未知的档位：{model}")
        return self._caps

    def rewrite_prompt(self, text):
        return _REF.sub(lambda m: f"[参考{m.group(1)}]", text)

    def submit(self, req):
        if self.transient_submits > 0:
            self.transient_submits -= 1
            raise TransientError("假的限流")
        tid = f"fake-{len(self.submitted) + 1}"
        self.submitted.append(req)
        self.tasks[tid] = {"polls": 0, "req": req}
        return tid

    def poll(self, task_id):
        t = self.tasks.get(task_id)
        if t is None:
            raise ProviderError(f"任务不存在：{task_id}")
        t["polls"] += 1
        if t["polls"] < self.polls_to_finish:
            return TaskState(task_id, "running")
        if self.fail_with:
            return TaskState(task_id, "failed", error=self.fail_with)
        return TaskState(task_id, "succeeded", video_url=f"fake://{task_id}.mp4",
                         last_frame_url=f"fake://{task_id}.jpg",
                         usage={"seconds": request_seconds(t["req"].duration, self._caps)})

    def download(self, st, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(FAKE_MP4)
        last = None
        if st.last_frame_url:
            last = last_frame_path(dest)
            last.write_bytes(FAKE_JPG)
        return {"video": dest, "last_frame": last}

    def cost(self, st, req):
        if st.status != "succeeded":
            return 0.0
        return round(st.usage.get("seconds", 0) * self._caps.cny_per_sec.get(req.resolution, 0.0), 2)
