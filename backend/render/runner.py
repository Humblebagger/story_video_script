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
                 retries: int = 3, sleep=time.sleep, clock=time.monotonic,
                 poll_give_up_sec: float = 6 * 3600, download_give_up_sec: float = 20 * 3600):
        """request_builder(root, session, clip) → (ClipRequest, 实际首帧来源)；分镜改了抛 compose.Stale。"""
        self.request_builder = request_builder
        self.poll_sec = poll_sec
        self.max_parallel = max_parallel
        self.retries = retries
        self.sleep = sleep
        self.clock = clock
        self.poll_give_up_sec = poll_give_up_sec
        self.download_give_up_sec = download_give_up_sec
        self._first_fail: dict = {}
        self._roots: set = set()
        self._guard = threading.RLock()
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

    def _isolate(self, root, e: Exception) -> bool:
        """会话级错误：丢掉这个会话返回 True；其它错误打印后返回 False（继续下一个）。"""
        if isinstance(e, (sess.NotFound, sess.Corrupt)):
            print(f"[render] 跳过会话 {root}：{e}")
            self._forget(root)
            return True
        traceback.print_exc()
        return False

    def tick(self) -> None:
        roots = self.watching()
        for root in roots:
            try:
                s = sess.load(root)
                if s is None:
                    self._forget(root)
                    continue
                provider = get_video(s["provider"])
            except Exception as e:
                self._isolate(root, e)
                continue
            for c in s["clips"]:
                if c["state"] not in BUSY:
                    continue
                try:
                    if c["state"] == "running":
                        self._poll(root, provider, s, c)
                    else:
                        self._download(root, provider, s, c)
                except Exception as e:
                    if self._isolate(root, e):
                        break

        loaded = []
        for root in roots:
            try:
                s = sess.load(root)
            except Exception as e:
                self._isolate(root, e)
                continue
            if s is not None:
                loaded.append((root, s))
        busy = sum(1 for _, s in loaded for c in s["clips"] if c["state"] in BUSY)
        for root, s in loaded:
            try:
                provider = get_video(s["provider"])
            except Exception as e:
                self._isolate(root, e)
                continue
            for c in s["clips"]:
                if busy >= self.max_parallel:
                    break
                try:
                    if c["state"] != "queued" or sess.waiting_on_relay(s, c):
                        continue
                    if self._submit(root, provider, s, c):
                        busy += 1
                except Exception as e:
                    if self._isolate(root, e):
                        break

        for root in roots:
            self._settle(root)

    def _settle(self, root) -> None:
        """没有未完成的段就不再盯。读取与移除在锁内，与 watch 互斥，避免刚排队的段被漏掉。"""
        with self._guard:
            try:
                s = sess.load(root)
            except Exception:
                s = None
            if s is None or not any(c["state"] in sess.IN_FLIGHT for c in s["clips"]):
                self._roots.discard(Path(root))

    def _transient(self, kind, root, c, task_id, e, give_up) -> bool:
        """记下瞬时失败；超过期限返回 True（调用方应放弃）。"""
        key = (kind, str(root), c["id"], task_id)
        first = self._first_fail.setdefault(key, self.clock())
        if self.clock() - first >= give_up:
            self._first_fail.pop(key, None)
            return True
        sess.note_error(root, c["id"], f"厂商暂时不可达，正在重试：{e}")
        return False

    def _clear(self, kind, root, c, task_id) -> None:
        self._first_fail.pop((kind, str(root), c["id"], task_id), None)

    @staticmethod
    def _stub(s: dict, c: dict) -> base.ClipRequest:
        """计费用的最小请求：档位、分辨率、时长。"""
        return base.ClipRequest(prompt=c["prompt"], model=s["model"], duration=c["duration"],
                                resolution=s["resolution"])

    def _poll(self, root, provider, s, c) -> None:
        a = c["attempts"][-1]
        try:
            st = self._retry(lambda: provider.poll(a["task_id"]))
        except base.TransientError as e:
            if self._transient("poll", root, c, a["task_id"], e, self.poll_give_up_sec):
                st = base.TaskState(a["task_id"], "failed",
                                    error="多次查询都失败，已放弃；请到厂商控制台核对这个任务：" + str(e))
                sess.poll_update(root, c["id"], st, 0.0)
            return                                  # 下一轮再查
        except base.ProviderError as e:
            st = base.TaskState(a["task_id"], "failed", error=str(e))
        self._clear("poll", root, c, a["task_id"])
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
        except base.TransientError as e:
            if self._transient("download", root, c, a["task_id"], e, self.download_give_up_sec):
                sess.download_failed(root, c["id"], "下载一直失败，结果地址即将过期：" + str(e), cost)
            return                                  # 结果地址 24 小时有效，下一轮再下
        except base.ProviderError as e:
            self._clear("download", root, c, a["task_id"])
            sess.download_failed(root, c["id"], str(e), cost)
            return
        self._clear("download", root, c, a["task_id"])
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
        except Exception as e:
            sess.submit_failed(root, c["id"], f"提交异常：{type(e).__name__}: {e}")
            return False
        try:
            sess.submitted(root, c["id"], tid, used)
        except Exception:
            print(f"[render] 已提交但写回失败，任务 id {tid}（{root} {c['id']}），请到厂商控制台核对")
            raise
        return True
