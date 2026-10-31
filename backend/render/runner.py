"""出片后台线程：提交、轮询、下载。

主循环每 poll_sec 秒跑一次 tick()：先推进在跑的段（查询、下载），再在并发上限内提交排队的段。
厂商调用都在会话锁之外做，结果再用 session 的迁移函数写回。启动时 recover() 续上未完成的段：
已有任务 id 的接着查、接着下，不重复提交。
"""
import threading
import time
import traceback
from pathlib import Path

from render import compose, session as sess
from render.providers import base, get_video

BUSY = ("running", "downloading")


class Runner:
    def __init__(self, request_builder, *, poll_sec: float = 10.0, max_parallel: int = 2,
                 retries: int = 3, sleep=time.sleep):
        """request_builder(root, session, clip) → (ClipRequest, 实际首帧来源)；分镜改了抛 compose.Stale。"""
        self.request_builder = request_builder
        self.poll_sec = poll_sec
        self.max_parallel = max_parallel
        self.retries = retries
        self.sleep = sleep
        self._roots: set = set()
        self._guard = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    # ---------- 盯哪些会话 ----------

    def watch(self, root) -> None:
        with self._guard:
            self._roots.add(Path(root))

    def watching(self) -> list:
        with self._guard:
            return sorted(self._roots)

    def _forget(self, root) -> None:
        with self._guard:
            self._roots.discard(Path(root))

    def recover(self, data_dir) -> int:
        """扫描全部会话，续上还有在跑的段的会话。返回续上的会话数。"""
        n = 0
        for path in Path(data_dir).glob("users/*/novels/*/chapters/*/render/*/session.json"):
            if sess.recover(path.parent):
                self.watch(path.parent)
                n += 1
        return n

    # ---------- 线程 ----------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="render-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                traceback.print_exc()
            self._stop.wait(self.poll_sec)

    def _retry(self, fn):
        last = None
        for i in range(self.retries):
            try:
                return fn()
            except base.TransientError as e:
                last = e
                if i < self.retries - 1:
                    self.sleep(2 ** i)
        raise last

    # ---------- 一轮 ----------

    def tick(self) -> None:
        roots = self.watching()
        for root in roots:
            s = sess.load(root)
            if s is None:
                self._forget(root)
                continue
            provider = get_video(s["provider"])
            for c in s["clips"]:
                if c["state"] == "running":
                    self._poll(root, provider, s, c)
                elif c["state"] == "downloading":
                    self._download(root, provider, s, c)

        loaded = [(root, s) for root in roots if (s := sess.load(root)) is not None]
        busy = sum(1 for _, s in loaded for c in s["clips"] if c["state"] in BUSY)
        for root, s in loaded:
            provider = get_video(s["provider"])
            for c in s["clips"]:
                if busy >= self.max_parallel:
                    break
                if c["state"] != "queued" or sess.waiting_on_relay(s, c):
                    continue
                if self._submit(root, provider, s, c):
                    busy += 1

        for root in roots:
            s = sess.load(root)
            if s is None or not any(c["state"] in sess.IN_FLIGHT for c in s["clips"]):
                self._forget(root)

    @staticmethod
    def _stub(s: dict, c: dict) -> base.ClipRequest:
        """计费用的最小请求：档位、分辨率、时长。"""
        return base.ClipRequest(prompt=c["prompt"], model=s["model"], duration=c["duration"],
                                resolution=s["resolution"])

    def _poll(self, root, provider, s, c) -> None:
        a = c["attempts"][-1]
        try:
            st = self._retry(lambda: provider.poll(a["task_id"]))
        except base.TransientError:
            return                                  # 下一轮再查
        except base.ProviderError as e:
            st = base.TaskState(a["task_id"], "failed", error=str(e))
        cost = provider.cost(st, self._stub(s, c)) if st.status == "failed" else 0.0
        sess.poll_update(root, c["id"], st, cost)

    def _download(self, root, provider, s, c) -> None:
        a = c["attempts"][-1]
        st = base.TaskState(a["task_id"], "succeeded", video_url=a.get("video_url"),
                            last_frame_url=a.get("last_frame_url"), usage=a.get("usage") or {})
        dest = Path(root) / "clips" / f"{c['id']}.v{len(c['attempts'])}.mp4"
        cost = provider.cost(st, self._stub(s, c))
        try:
            files = self._retry(lambda: provider.download(st, dest))
        except base.TransientError:
            return                                  # 结果地址 24 小时有效，下一轮再下
        except base.ProviderError as e:
            sess.download_failed(root, c["id"], str(e), cost)
            return
        if not base.is_playable_mp4(files["video"]):
            sess.download_failed(root, c["id"], "下载到的文件不是可播放的视频", cost)
            return
        sess.downloaded(root, c["id"], files, cost)

    def _submit(self, root, provider, s, c) -> bool:
        snap = sess.begin_submit(root, c["id"])
        if snap is None:
            return False
        try:
            req, used = self.request_builder(root, s, snap)
        except compose.Stale:
            sess.submit_failed(root, c["id"], "分镜或关键帧已改动，没有提交；请确认后重新出这一段",
                               stale=True)
            return False
        except Exception as e:                     # 组装失败不能卡住整个队列
            sess.submit_failed(root, c["id"], f"组装请求失败：{e}")
            return False
        try:
            tid = self._retry(lambda: provider.submit(req))
        except base.TransientError as e:
            sess.submit_failed(root, c["id"], f"厂商暂时不可用（已重试 {self.retries} 次）：{e}")
            return False
        except base.ProviderError as e:
            sess.submit_failed(root, c["id"], str(e))
            return False
        sess.submitted(root, c["id"], tid, used)
        return True
