"""假视频厂商：不联网、不花钱，按调用次数推进状态。测试与本地演示用。"""
import logging
import re
from pathlib import Path
from typing import Optional

from render.providers.base import (Caps, ProviderError, TaskState, TransientError,
                                   last_frame_path, request_seconds)
from server.messages import compact, msg, vendor
from render.providers.tts_base import BilledError, TtsCaps, TtsResult, Voice, tts_cost, write_wav

log = logging.getLogger("render.providers.fake")

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
FAKE_JPG = b"\xff\xd8\xff\xe0fake-last-frame"
_REF = re.compile(r"\{ref:([^{}]+)\}")


class FakeVideo:
    name = "fake"
    default_model = "fake-1"
    console_name = "console.generic"
    rate_note = {"code": "rate.fake", "params": {}}

    def __init__(self, *, polls_to_finish: int = 1, fail_with: Optional[str] = None,
                 transient_submits: int = 0, max_refs: int = 3, frame_with_refs: bool = False,
                 native_audio: bool = True):
        self.models = {"fake-1": {"label": "假厂商"}}
        self._caps = Caps(max_clip_sec=10, min_clip_sec=2, max_refs=max_refs, first_frame=True,
                          last_frame=False, returns_last_frame=True, native_audio=native_audio,
                          frame_with_refs=frame_with_refs, resolutions=["480p", "720p"],
                          cny_per_sec={"480p": 0.5, "720p": 1.0})
        self.polls_to_finish = polls_to_finish
        self.fail_with = fail_with
        self.transient_submits = transient_submits
        self.submitted = []         # 依次提交的 ClipRequest
        self.tasks = {}

    def caps(self, model):
        if model not in self.models:
            log.warning("未知的假厂商档位：%s", model)  # i18n: internal
            raise ProviderError.of("film.fake.unknown_model")
        return self._caps

    def rewrite_prompt(self, text):
        return _REF.sub(lambda m: f"[参考{m.group(1)}]", text)

    def submit(self, req):
        if self.transient_submits > 0:
            self.transient_submits -= 1
            raise TransientError.of("film.fake.throttled")
        tid = f"fake-{len(self.submitted) + 1}"
        self.submitted.append(req)
        self.tasks[tid] = {"polls": 0, "req": req}
        return tid

    def poll(self, task_id):
        t = self.tasks.get(task_id)
        if t is None:
            raise ProviderError.of("film.fake.no_task", id=task_id)
        t["polls"] += 1
        if t["polls"] < self.polls_to_finish:
            return TaskState(task_id, "running")
        if self.fail_with:
            return TaskState(task_id, "failed", error=self.fail_with,
                             error_msg=compact(msg("film.provider.rejected", detail=vendor(self.fail_with))))
        return TaskState(task_id, "succeeded", video_url=f"fake://{task_id}.mp4",
                         last_frame_url=f"fake://{task_id}.jpg",
                         usage={"seconds": request_seconds(t["req"].duration, self._caps)})

    def download(self, st, dest):
        dest.parent.mkdir(exist_ok=True)
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


class FakeTts:
    """假 TTS：不联网、不花钱，按字数出静音 WAV（每字 1/4.5 秒）；可指定前几次限流、一律失败或收下后失败（已计费）。"""
    name = "fake"
    rate_note = {"code": "rate.fake_tts", "params": {}}
    RATE = 24000

    def __init__(self, *, fail_times: int = 0, fail_with: Optional[str] = None,
                 fail_billed: Optional[str] = None, max_chars: int = 300):
        self.caps = TtsCaps(voices=[Voice("fake-male", "假男声", "male"), Voice("fake-female", "假女声", "female")],
                            emotions=False, max_chars=max_chars, cny_per_k_chars=0.3)
        self.fail_times = fail_times
        self.fail_with = fail_with
        self.fail_billed = fail_billed      # 模拟收下请求后才失败（按已计费记账）
        self.calls = []         # 依次合成的 (文字, 音色)

    def synthesize(self, text, voice, emotion, speed, dest):
        self.calls.append((text, voice))
        if self.fail_with:
            raise ProviderError.of("tts.fake.failed", detail=vendor(self.fail_with))
        if self.fail_billed:
            raise BilledError(self.fail_billed, tts_cost(len(text), self.caps))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise TransientError.of("tts.fake.throttled")
        if voice not in {v.id for v in self.caps.voices}:
            raise ProviderError.of("tts.unknown_voice", voice=voice)
        frames = int(round(len(text) / 4.5 / speed * self.RATE))
        duration = write_wav(Path(dest), b"\x00\x00" * frames, self.RATE)
        return TtsResult(Path(dest), duration, tts_cost(len(text), self.caps), len(text))
