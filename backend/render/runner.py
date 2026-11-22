"""出片后台线程：提交、轮询、下载。

主循环每 poll_sec 秒跑一次 tick()：先推进在跑的段（查询、下载），再在并发上限内提交排队的段。
厂商调用都在会话锁之外做，结果再用 session 的迁移函数写回。启动时 recover() 续上未完成的段：
已有任务 id 的接着查、接着下，不重复提交。
"""
import logging
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

from safety.text import text_hash
from render import compose, session as sess
from render.providers import base, get_video
from server import error_refs
from server.messages import UserError, compact, msg, public_cause, with_ref


log = logging.getLogger("render.runner")


def _scrub_secrets(text: str, provider) -> str:
    """日志文字脱敏：抹掉 Bearer 凭据、厂商对象持有的密钥与环境里配置的厂商密钥。"""
    return base.scrub_secrets(text, [getattr(provider, "_key", "")])


BUSY = ("running", "downloading")
SESSIONS_GLOB = "users/*/novels/*/chapters/*/render/*/session.json"   # 数据目录下全部出片会话


class Runner:
    def __init__(self, request_builder, *, poll_sec: float = 10.0, max_parallel: int = 2,
                 retries: int = 3, sleep=time.sleep, clock=time.monotonic,
                 poll_give_up_sec: float = 6 * 3600, download_give_up_sec: float = 20 * 3600,
                 abandoned_give_up_sec: float = 3600, safety_check=None, safety_forget=None):
        """request_builder(root, session, item) → (ClipRequest, 实际首帧来源)；item 是剧本段或自由节点。
        分镜改了抛 compose.Stale；自由节点复查不过抛 compose.FreeInvalid。
        safety_check(root, session, item) → "pass" | "wait"；拦截或暂时无法检查时抛带代码的 UserError。
        它只能做毫秒级的查询（缓存、词表），要调模型的由它自己排到别的线程，这里下一轮再问。"""
        self.request_builder = request_builder
        self.safety_check = safety_check
        self.safety_forget = safety_forget   # (检查键) → None：段取消、重新排队或会话移除时作废它的等待登记
        self._checking: dict = {}        # 等内容检查结论的 (用户, 小说, 章节, 版本, 段) → 会话目录
        # 生命周期锁：段的「排队 / 取消迁移 + 作废检查登记」与出片线程的「检查回调 + 写回」互斥。
        # 锁顺序固定：_life_lock → _guard → 会话锁。异步模型分类不在锁内（回调只做毫秒级的查询与登记）。
        self._life_lock = threading.RLock()
        self.poll_sec = poll_sec
        self.max_parallel = max_parallel
        self.retries = retries
        self.sleep = sleep
        self.clock = clock
        self.poll_give_up_sec = poll_give_up_sec
        self.download_give_up_sec = download_give_up_sec
        self.abandoned_give_up_sec = abandoned_give_up_sec    # 用户不等了的那次：查询一直出错多久后放弃
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
        self._release_root(root)

    def _release_key(self, key) -> None:
        """这一段不再等检查结论：清掉标记，并让检查入口作废它的等待登记与未读结论（代次加一）。"""
        with self._life_lock:
            with self._guard:
                self._checking.pop(key, None)
            if self.safety_forget is not None:
                self.safety_forget(key)

    def _release_root(self, root) -> None:
        with self._guard:
            keys = [k for k, r in self._checking.items() if r == str(root)]
        for k in keys:
            self._release_key(k)

    def release_checks(self, owner: dict, item_ids=None) -> None:
        """作废这些段（缺省：该版本正标记等检查的段）上一代的检查登记。给了 ID 就一律作废，不看 _checking。"""
        prefix = self._check_key(owner, "")[:4]
        with self._life_lock:
            if item_ids is not None:
                keys = [prefix + (i,) for i in item_ids]
            else:
                with self._guard:
                    keys = [k for k in self._checking if k[:4] == prefix]
            for k in keys:
                self._release_key(k)

    def migrate(self, owner: dict, fn, ids):
        """接口侧的统一入口：在生命周期锁内做会话迁移 fn()（排队、取消），成功后作废实际迁移的段的检查登记。
        ids 是 ID 集合，或 fn 结果 → ID 集合的函数。fn 抛异常就不作废，原样上抛。"""
        with self._life_lock:
            result = fn()
            self.release_checks(owner, set(ids(result) if callable(ids) else ids))
            return result

    def recover(self, data_dir) -> int:
        """扫描全部会话，续上还有在跑的段的会话。返回续上的会话数。"""
        n = 0
        for path in Path(data_dir).glob(SESSIONS_GLOB):
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
            for c in sess.items(s):
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

        # 用户不等了的那些尝试：接着查到有结果为止（不占并发名额，不动所在段的状态）
        for root in roots:
            try:
                s = sess.load(root)
                pending = sess.abandoned(s) if s is not None else []
            except Exception as e:
                self._isolate(root, e)
                continue
            for h, a in pending:
                try:
                    self._track_abandoned(root, h, a)
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
        busy = sum(1 for _, s in loaded for c in sess.items(s) if c["state"] in BUSY)
        for root, s in loaded:
            try:
                provider = get_video(s["provider"])
            except Exception as e:
                self._isolate(root, e)
                continue
            for c in sess.items(s):
                if busy >= self.max_parallel:
                    break
                try:
                    if c["state"] != "queued" or sess.waiting_on_relay(s, c):
                        if self._checking and self._check_key(s.get("owner"), c["id"]) in self._checking:
                            self._release_key(self._check_key(s.get("owner"), c["id"]))   # 不再排队（取消等）
                        continue
                    ticket = self._safety(root, s, c)
                    if ticket is None:
                        continue
                    if self._submit(root, provider, s, c, ticket):
                        busy += 1
                except Exception as e:
                    if self._isolate(root, e):
                        break

        for root in roots:
            self._settle(root)

    @staticmethod
    def _check_key(owner: dict, item_id: str) -> tuple:
        o = owner or {}
        return (o.get("user_id"), o.get("nid"), o.get("cid"), o.get("vid"), item_id)

    def is_checking(self, owner: dict, item_id: str) -> bool:
        """这一段是不是正排着队等内容检查的结论（界面据此显示「内容检查中」）。"""
        with self._guard:
            return self._check_key(owner, item_id) in self._checking

    def _safety(self, root, s, c) -> bool:
        """提交前的内容检查，在 begin_submit 之前。等结论或已判失败返回 None；可以提交返回提交凭据：
        {"hash": 实际检查过的提示词 hash, "session": 支撑这次检查的会话快照, "proof": 回调给的附加凭据}。
        没配检查回调时凭据里 hash 为 None（不做比对）。"""
        if self.safety_check is None:
            return {"hash": None, "session": s, "proof": None}
        key = self._check_key(s.get("owner"), c["id"])
        with self._life_lock:
            # 锁内重读：本轮快照之后被取消或重新排队的，以当前状态为准（不对已取消的写失败）
            now = sess.load(root)
            cur = next((x for x in sess.items(now) if x["id"] == c["id"]), None) if now else None
            if cur is None or cur["state"] != "queued" or sess.waiting_on_relay(now, cur):
                return None
            try:
                verdict = self.safety_check(root, now, cur)
            except Exception as e:
                if isinstance(e, UserError):               # 拦截、暂时无法检查：不提交、不花钱
                    sess.submit_failed(root, c["id"], e)
                else:                                      # 检查自己出错同样不放行
                    log.warning("%s", _scrub_secrets(f'内容检查出错 root={root} clip={c["id"]} {type(e).__name__}: {e}', None))  # i18n: internal
                    sess.submit_failed(root, c["id"], msg("safety.unavailable"))
                self._release_key(key)
                return None
            with self._guard:
                if verdict == "wait":
                    self._checking[key] = str(root)
                else:
                    self._checking.pop(key, None)
        if verdict == "wait":
            return None
        proof = verdict[1] if isinstance(verdict, tuple) else None    # ("pass", 凭据) 或 "pass"
        # 凭据绑定锁内实际检查的那份快照（cur），不用 tick 开头读到的 c：A→B→A 时检查的是 B，提交 A 会被拒
        return {"hash": text_hash(cur.get("prompt") or ""), "session": now, "proof": proof}

    def _settle(self, root) -> None:
        """没有未完成的段就不再盯。读取与移除在锁内，与 watch 互斥，避免刚排队的段被漏掉。"""
        with self._guard:
            try:
                s = sess.load(root)
            except Exception:
                s = None
            if s is None or not sess.needs_runner(s):
                self._roots.discard(Path(root))
                drop = True
            else:
                drop = False
        if drop:
            self._release_root(root)

    def _transient(self, kind, root, c, task_id, e, give_up) -> bool:
        """记下瞬时失败；超过期限返回 True（调用方应放弃）。"""
        key = (kind, str(root), c["id"], task_id)
        first = self._first_fail.setdefault(key, self.clock())
        if self.clock() - first >= give_up:
            self._first_fail.pop(key, None)
            return True
        log.warning("%s", _scrub_secrets(f'暂时不可达 root={root} clip={c["id"]} task={task_id} {type(e).__name__}: {e}', None))  # i18n: internal
        sess.note_error(root, c["id"], msg("film.provider.retrying", cause=public_cause(e)), task_id)
        return False

    def _clear(self, kind, root, c, task_id) -> None:
        self._first_fail.pop((kind, str(root), c["id"], task_id), None)

    @staticmethod
    def _stub(s: dict, c: dict) -> base.ClipRequest:
        """计费用的最小请求：档位、分辨率、时长，以及提交时实际发出的图片张数（旧尝试没有记为 None）。"""
        last = (c.get("attempts") or [{}])[-1]
        return base.ClipRequest(prompt=c["prompt"], model=s["model"], duration=c["duration"],
                                resolution=s["resolution"], images=last.get("images"))

    def _poll(self, root, provider, s, c) -> None:
        a = c["attempts"][-1]
        try:
            st = self._retry(lambda: provider.poll(a["task_id"]))
        except (base.TransientError, base.ProviderError) as e:
            # 查询本身出错不等于任务失败：厂商那边可能还在跑、还在计费。只有厂商报的终态
            # （TaskState 里的 failed）才算结束；查询一直出错到期限才放弃，并标待核对
            if self._transient("poll", root, c, a["task_id"], e, self.poll_give_up_sec):
                log.warning("%s", _scrub_secrets(f'查询放弃 root={root} clip={c["id"]} task={a["task_id"]}', provider))  # i18n: internal
                log.warning("%s", _scrub_secrets(f'查询放弃原因 root={root} clip={c["id"]} {type(e).__name__}: {e}', provider))  # i18n: internal
                m = msg("film.poll.gave_up", cause=public_cause(e))
                st = base.TaskState(a["task_id"], "failed", error=m["message"], error_msg=compact(m))
                sess.poll_update(root, c["id"], st, 0.0, uncertain=True)
            return                                  # 下一轮再查
        self._clear("poll", root, c, a["task_id"])
        cost = provider.cost(st, self._stub(s, c)) if st.status == "failed" else 0.0
        sess.poll_update(root, c["id"], st, cost)

    def _download(self, root, provider, s, c) -> None:
        a = c["attempts"][-1]
        st = base.TaskState(a["task_id"], "succeeded", video_url=a.get("video_url"),
                            last_frame_url=a.get("last_frame_url"), usage=a.get("usage") or {})
        dest = sess.clip_dest(root, c["id"], a["task_id"])
        cost = provider.cost(st, self._stub(s, c))
        try:
            files = self._retry(lambda: provider.download(st, dest))
        except base.TransientError as e:
            if self._transient("download", root, c, a["task_id"], e, self.download_give_up_sec):
                log.warning("%s", _scrub_secrets(f'下载放弃 root={root} clip={c["id"]} {type(e).__name__}: {e}', provider))  # i18n: internal
                sess.download_failed(root, c["id"], msg("film.download.keeps_failing", cause=public_cause(e)), cost)
            return                                  # 结果地址限时有效，下一轮再下
        except base.ProviderError as e:
            self._clear("download", root, c, a["task_id"])
            sess.download_failed(root, c["id"], e, cost)
            return
        self._clear("download", root, c, a["task_id"])
        if not base.is_playable_mp4(files["video"]):
            sess.download_failed(root, c["id"], msg("film.download.not_playable"), cost)
            return
        sess.downloaded(root, c["id"], files, cost)

    def _lost(self, root, h, tid, key, known, provider=None) -> None:
        """用户不等了的那次一时查不到（或厂商实例建不起来）：计时，到期放弃。已确认过成功的按已知费用记。"""
        first = self._first_fail.setdefault(key, self.clock())
        if self.clock() - first >= self.abandoned_give_up_sec:
            self._first_fail.pop(key, None)
            log.warning("%s", _scrub_secrets(f'已取消的任务查询放弃 root={root} item={h["id"]} task={tid}', provider))  # i18n: internal
            sess.settle_abandoned(root, tid, "failed", cost=known or 0.0, error=msg("film.cancel.lost"))

    def _track_abandoned(self, root, h, a) -> None:
        """用户不等了的那次：查到厂商给出终态为止。成功 → 下载、记费、留作可采用的一次；失败或取消照实记。
        厂商、档位、分辨率、时长都用那次提交时记下的（billing），不看会话现在的设置。
        查到成功后结果与费用先记在那次尝试上；之后下载一直瞬时失败，同样到期限按已知费用结算为失败。"""
        b = a.get("billing") or {}
        tid = a["task_id"]
        key = ("abandoned", str(root), h["id"], tid)
        dl_key = ("abandoned-dl", str(root), h["id"], tid)
        known = a.get("known_cost_cny")
        try:
            provider = get_video(b.get("provider"))
        except (base.ProviderError, KeyError):
            self._lost(root, h, tid, key, known)
            return
        if known is None:
            try:
                st = self._retry(lambda: provider.poll(tid))
            except (base.TransientError, base.ProviderError):
                self._lost(root, h, tid, key, None, provider)
                return
            self._first_fail.pop(key, None)
            if st.status not in ("succeeded", "failed"):
                return                                  # 还在排队或生成：下一轮再查
            req = base.ClipRequest(prompt="", model=b.get("model"), duration=b.get("duration") or 0.0,
                                   resolution=b.get("resolution"), images=a.get("images"))
            cost = provider.cost(st, req)
            if st.status == "failed":
                gone = (st.error_msg or {}).get("code") == "film.provider.task_cancelled"
                err = ({"code": st.error_msg["code"], "params": st.error_msg.get("params") or {}, "message": st.error,
                        **({"ref": st.error_msg["ref"]} if st.error_msg.get("ref") else {})}
                       if st.error_msg else (st.error or msg("film.provider.failed")))
                sess.settle_abandoned(root, tid, "cancelled" if gone else "failed", cost=cost, error=err)
                return
            sess.record_abandoned_result(root, tid, st, cost)
        else:
            self._first_fail.pop(key, None)
            cost = known
            st = base.TaskState(tid, "succeeded", video_url=a.get("video_url"),
                                last_frame_url=a.get("last_frame_url"), usage=a.get("usage") or {})
        try:
            files = self._retry(lambda: provider.download(st, sess.clip_dest(root, h["id"], tid)))
        except base.TransientError as e:
            first = self._first_fail.setdefault(dl_key, self.clock())
            if self.clock() - first >= self.abandoned_give_up_sec:
                self._first_fail.pop(dl_key, None)
                log.warning("%s", _scrub_secrets(f'迟到结果下载放弃 root={root} task={tid} {type(e).__name__}: {e}', provider))  # i18n: internal
                sess.settle_abandoned(root, tid, "failed", cost=cost,
                                      error=msg("film.download.keeps_failing", cause=public_cause(e)))
            return                                  # 下一轮重下（已知成功，不再查询）
        except base.ProviderError as e:
            self._first_fail.pop(dl_key, None)
            sess.settle_abandoned(root, tid, "failed", cost=cost, error=e)
            return
        self._first_fail.pop(dl_key, None)
        if not base.is_playable_mp4(files["video"]):
            sess.settle_abandoned(root, tid, "failed", cost=cost, error=msg("film.download.not_playable"))
            return
        sess.settle_abandoned(root, tid, "succeeded", cost=cost, files=files)

    def _submit(self, root, provider, s, c, ticket: Optional[dict] = None) -> bool:
        # 提交凭据来自检查：提交时会话里的提示词必须就是检查过的那份，否则不提交，下一轮重新检查
        ticket = ticket or {"hash": None, "session": s, "proof": None}
        snap = sess.begin_submit(root, c["id"], ticket["hash"])
        if snap is None:
            return False
        if ticket["proof"] is not None:
            snap["safety_proof"] = ticket["proof"]       # 检查时的附加凭据（自由节点：资产 id → 名称），组装请求只用它
        s = ticket["session"]
        try:
            req, used = self.request_builder(root, s, snap)
        except compose.Stale:
            sess.submit_failed(root, c["id"], msg("film.submit.stale"), stale=True)
            return False
        except compose.FreeInvalid as e:          # 自由节点的参考图、尾帧或关键帧没了：不提交、不花钱
            sess.submit_failed(root, c["id"], e)
            return False
        except Exception as e:                     # 组装失败不能卡住整个队列
            log.warning("%s", _scrub_secrets(f'组装请求失败 root={root} clip={c["id"]} {type(e).__name__}: {e}', provider))  # i18n: internal
            sess.submit_failed(root, c["id"], msg("film.submit.build_failed", cause=public_cause(e)))
            return False
        try:
            tid = self._retry(lambda: provider.submit(req))
        except base.AmbiguousSubmit as e:          # 厂商可能已建了付费任务：不重试
            log.warning("%s", _scrub_secrets(f'提交结果不明 root={root} clip={c["id"]} {type(e).__name__}: {e}', provider))  # i18n: internal
            sess.submit_failed(root, c["id"], msg("film.submit.ambiguous", cause=public_cause(e)), uncertain=True)
            return False
        except base.TransientError as e:
            log.warning("%s", _scrub_secrets(f'提交不可用 root={root} clip={c["id"]} {type(e).__name__}: {e}', provider))  # i18n: internal
            sess.submit_failed(root, c["id"], msg("film.submit.unavailable", retries=self.retries, cause=public_cause(e)))
            return False
        except base.ProviderError as e:
            log.warning("%s", _scrub_secrets(f'段失败 root={root} clip={c["id"]} code={getattr(e, "code", None)}', provider))  # i18n: internal
            sess.submit_failed(root, c["id"], e)
            return False
        except Exception as e:
            err_ref = error_refs.record_exc(e, "film.submit.crashed", context=f'提交异常 root={root} clip={c["id"]}',  # i18n: internal
                                        user_id=error_refs.user_of_root(root), where=f'submit {root} {c["id"]}',
                                        secrets_extra=[getattr(provider, "_key", "")], logger=log)
            try:
                sess.submit_failed(root, c["id"], with_ref(msg("film.submit.crashed"), err_ref))
            except Exception as e2:
                # 状态写回也失败：段留在「提交中」，下一轮 begin_submit 会标待核对（不重复付费提交）。
                # 不让带厂商密钥的异常链（__context__ 是原提交异常）走到 _isolate 的 print_exc。
                if isinstance(e2, (sess.NotFound, sess.Corrupt)):
                    raise e2 from None                 # 会话级错误仍交给 _isolate 丢会话；断开链
                log.error("%s", error_refs.scrub_text(
                    f'提交失败状态写回失败 ref={err_ref} root={root} clip={c["id"]} {type(e2).__name__}: {e2}',  # i18n: internal
                    [getattr(provider, "_key", "")]))
            return False
        try:
            sess.submitted(root, c["id"], tid, used, style_ref=getattr(req, "style_ref", None),
                           images=len(req.refs) + (1 if req.first_frame else 0))
        except Exception:
            print(f"[render] 已提交但写回失败，任务 id {tid}（{root} {c['id']}），请到厂商控制台核对")
            raise
        return True
