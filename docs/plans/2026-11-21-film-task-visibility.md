# 出片片段生成的可见性、取消与观看 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让出片的每一段在生成期间看得见、停得下、出完看得到，并把任务铃铛点开的面板做成全局的个人任务队列：任何页面都能打开，「进行中 / 已结束」两个区，转换、出片片段、成片合成都在里面，每条定位到小说 › 章节 › 片段与镜号；片段卡写明「已等 m 分 s 秒 · 通常 x–y 分钟」；可以取消（厂商还没开始就真取消，已经在生成就「不等了」并提示可能仍扣费）；出完的片段卡上有明显的播放按钮，点开带声音与控制条的播放窗口；完成时发可点击的通知，点开直接播放。

**Architecture:**
- 后端在厂商接口上加两样东西：`typical_sec`（通常时长，只供显示）与 `cancel(task_id)`（只取消还在厂商那边排队的任务；先查状态，只有 `queued` 才发 DELETE，因为两家的 DELETE 对已结束的任务是「删除记录」）。
- 会话层（`render/session.py`）新增取消：还没提交的本地取消（`dequeued`）；已提交且厂商确认取消（`cancelled`）；取消不了就是「不等了」（`abandoned`）——段立刻放开，那一次尝试记为 `abandoned` 并带上提交时的计费快照，出片线程在后台继续盯；厂商后来出了结果就下载、按快照记费、标 `late`、**不自动采用**。不新增段状态，只新增两种尝试状态。
- 新接口 `GET /render/tasks` 返回本人的出片与合成任务（进行中的、一天内结束的、取消后才出结果的），带定位字段（小说、章节、版本、片段、镜号）、取消种类与可给普通用户看的失败原因；已等时长由服务端算，不带厂商与档位。转换任务仍走现有的 `GET /jobs`（补结束时间、失败原因、现在的名字与已删除标记），面板把两个来源合成一个队列。
- 前端：`film.ts` 放纯计算（等待文字、取消种类、播哪一次），`filmTasks.ts` 放任务列表的纯计算；片段卡加等待一行、取消入口、播放按钮；新组件 `ClipPlayer`（Radix Dialog + `<video controls>`）；`App.tsx` 与转换任务并行巡检出片任务，播报走 `notify.ts`（新增点击回调）与 sonner；点任务回到画布靠路由 state 里的 `focus`。
- 普通用户界面的新增文案一律不带厂商或模型名（有测试扫两份语言包与界面文字）。

**Tech Stack:** 后端 Python 3.12、FastAPI、脚本式测试（`.venv/bin/python tests/<目录>/test_x.py`，没有 pytest）；前端 React 19、TypeScript、Vite 8、react-router 8、Radix Dialog（`components/ui/dialog.tsx`）、sonner、lucide-react、happy-dom，测试是 `vite build --ssr` 构建后交给 node 跑的脚本，断言用文件内的 `must`（仓库**没有** vitest 和 testing-library）。

**Spec:** `docs/specs/2026-11-21-film-task-visibility-design.md`。下文用「§n」引用它的章节。

---

## 全局约束（每个 Task 都必须遵守）

- **只改本计划列出的文件**，不顺手重构。
- **不碰的文件与服务**：
  - 不读、不打印 `backend/.env`；
  - 不运行 `render/smoke.py`、`render/smoke_tts.py`、`assistant/smoke.py`，不调用付费服务或真实大模型；测试里的厂商一律用桩（`FakeVideo` 或假 HTTP 层），**不得发真实网络请求**；
  - 不启动、不停止前后端服务，不向 5173 / 8000 端口发请求；
  - 不读取、不打印任何 `session.json` 里的 `video_url`（带签名）；
  - 不动、不提交 `docs/specs/2026-10-27-commercialization-design-contract.md`（未跟踪文件，保持原样）。
- **提交规则**：
  - 只 `git add <具体文件>`，禁止 `git add -A`、`git commit -a`、`git add -N`、`git stash`；
  - 提交信息用中文、描述性写法，**不得带 `Co-Authored-By`、`Claude-Session` 等任何署名尾行**；
  - 不 push。
- **厂商名不进普通用户界面（硬性规则）**：本计划新增的界面文字、通知、任务列表字段都不出现 MiniMax、Seedance、ARK、方舟、海螺等厂商或模型名，也不出现 `provider` / `model` 的值。等待时长只说「通常 x–y 分钟」。不要为了「更清楚」加回去。
- **lint 基线**：`frontend/` 下 `npm run lint` 是 0 error、警告恰好 5 条（`VerificationPanel.tsx`、`CardPicker.tsx`、`timeline.ts`、`ParamsForm.tsx`、`App.tsx` 各一条），**不得增加**。
- **film.test 已知偶发卡死**：`tests/film.test.tsx` 在改动前就有小概率 CPU 自旋不退出（机器忙时更常见，实测基线 6 次里 2 次）。某条命令里它超过 2 分钟不结束就终止那个 node 进程，单独重跑判定：`cd frontend && npx vite build --ssr tests/film.test.tsx --outDir .ssrout --logLevel error && timeout 100 node .ssrout/film.test.js`。重跑通过即算通过；不要因此改测试或改设计。跑测试时不要同时跑别的重活。
- 代码块里的内容照抄即可，它们已在仓库的一份临时副本上（基于提交 `fe5ced6`）按 Task 顺序整套跑通（每个 Task 的失败与通过、最后的后端全套、`npm test`、`npm run lint`、`npm run build`、构建产物检查）。其后的两个提交 `040be6e`、`efaf854`（后台价格表）与本计划改的地方不重叠，已核对：把它们叠加到跑完的副本上能干净应用、类型检查通过。如果照抄后某一步的结果与本计划写的预期不符，先核对是否抄漏、锚点所在的文件是否在 `fe5ced6` 之后被别的提交改过，再报告，不要自行改设计。

## 本计划的写法（先读）

每个 Task 由若干步骤组成，步骤里只有下面六种指令，按出现顺序执行：

1. 「新建 + 路径」：后面紧跟的代码块是文件的完整内容，文件此前不存在。
2. 「在 + 路径 + 里找到」：后面第一个代码块是原文，它在该文件里**恰好出现一次**；接着「换成」后面的代码块是替换后的内容。原文块往往包含不变的上下文行，是为了定位，照样整块替换即可。
3. 「在 + 路径 + 末尾追加」：把后面的代码块接在文件末尾。
4. 「把 + 路径 + 整个换成」：后面的代码块是该文件的完整新内容，文件此前已存在，整个覆盖。
5. 「运行」：行内的命令在**仓库根目录**用 bash 执行；下一行的「预期」写明应当通过（退出码 0）还是失败（退出码非 0），以及输出里必须出现 / 不得出现的文字。「预期：失败」的步骤是 TDD 的红灯，失败才对。
6. 「提交」：后面的 bash 代码块原样执行；执行后 `git status --short` 里不应再有本 Task 的文件（那份未跟踪的商业化合约文档除外）。

路径都相对仓库根目录。后端命令用仓库自带的虚拟环境 `backend/.venv`（Python 3.12）。

## 先读这一节：仓库里与本任务有关的事实

- **出片的三层**：`backend/render/providers/`（厂商：`base.py` 是协议与公共函数，`fake.py` 是测试用假厂商，`minimax.py`、`seedance.py` 是真厂商）→ `backend/render/session.py`（会话：一个版本一份 `session.json`，所有读改写都在 `mutate(root)` 的锁里）→ `backend/render/runner.py`（出片线程：约 10 秒一轮，先查在跑的，再在并发上限内提交排队的）。`backend/server/app.py` 是接口。
- **段的状态**：`planned → queued → running → downloading → done / failed`，另有 `stale`（提示词改过）。`IN_FLIGHT = queued / running / downloading`。每段的 `attempts` 是历次尝试，`chosen` 是采用第几次。本计划**不新增段状态**，只给尝试新增 `cancelled`、`abandoned` 两种状态，给段新增 `ended_at` / `ended_as` 两个字段。
- **后端的用户可见文字必须登记**：`backend/server/messages.py` 里 `register(code, 中文)`，抛错用 `UserError.of(code, **params)`；改完跑 `python -m server.messages --write` 重新生成 `backend/server/messages_codes.json`；前端 `i18n/zh.ts`、`en.ts` 的 `srv` 节点要逐条对应（中文一字不差），`frontend/tests/srv-codes.test.ts` 会查。`backend/tests/server/test_i18n_scan.py` 扫描源码里未登记的中文，`app.py` 的新函数名要加进它的名单；纯内部日志在行尾加 `# i18n: internal`。
- **前端出片相关文件**：`src/useFilm.ts`（会话的读取、轮询与各种操作）、`src/film.ts`（纯计算，单测 `tests/film-lane.test.ts`）、`src/components/NodeCards.tsx`（节点图上的片段卡 / 自由节点卡）、`NodeGraph.tsx`（节点图）、`FilmPanel.tsx`（画布侧栏的「出片」页）、`TimelineCanvas.tsx`（画布本体，持有 `useFilm`）、`StoryboardView.tsx`（分镜页，挂画布）。集成测试 `tests/graph-view.test.tsx` 自带一个内存桩后端。
- **任务铃铛**：`src/App.tsx` 的 `watchJobs` 轮询 `/jobs`（转换任务），`announce` 发通知与 sonner 提示，`components/shell/ActivityPanel.tsx` 是右侧动态面板，`components/shell/AppShell.tsx` 的铃铛显示 `runningCount`。本计划在旁边并排加出片任务，不改转换任务那一套。
- **路由**：地址是唯一真相（`src/paths.ts`）。跨地址的一次性参数放路由 state（`NavState`：`vid`、`jobId`、`panel`…），`passState` 在 replace 时去掉一次性的键。`App.tsx` 的 `go()` 在目标等于当前地址时不导航并返回 `false`。
- **确认框**：`useConfirm()`（`components/common/ConfirmDialog.tsx`）返回 `[ask, confirmUi]`，`await ask({ title, body, action, danger })` 得到布尔值；测试里按钮是 `data-testid="confirm-ok"` / `confirm-cancel`。
- **前端测试的跑法**：单个文件 `cd frontend && npx vite build --ssr tests/<名>.test.tsx --outDir .ssrout --logLevel error && node .ssrout/<名>.test.js`；全部 `npm test`（`package.json` 里一长串 `&&`，新测试要接在末尾）。
- **后端测试的跑法**：`cd backend && .venv/bin/python tests/<目录>/test_<名>.py`，成功时最后一行是 `ALL PASS`。

## 文件总览

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/render/providers/base.py` | 改 | 协议加 `typical_sec`、`cancel`；公共函数 `typical_sec()`、`try_cancel()` |
| `backend/render/providers/fake.py` | 改 | 假厂商可配置取消成败 |
| `backend/render/providers/minimax.py`、`seedance.py` | 改 | 真厂商的取消（只取消排队中的）与通常时长 |
| `backend/server/messages.py`、`messages_codes.json` | 改 | 新增 6 条消息 |
| `backend/render/session.py` | 改 | 取消、「不等了」、迟到结果的落账、结束标记、预留计入 |
| `backend/render/free.py` | 改 | 自由节点的预留与删除保护 |
| `backend/render/runner.py` | 改 | 后台盯住「不等了」的尝试 |
| `backend/server/app.py` | 改 | 取消接口两个、任务列表接口一个 |
| `backend/tests/render/test_cancel.py`、`test_cancel_runner.py`、`backend/tests/server/test_film_tasks.py` | 新建 | 会话、出片线程、接口的测试 |
| `frontend/src/types.ts`、`api.ts`、`i18n/zh.ts`、`i18n/en.ts` | 改 | 类型、接口函数、文案 |
| `frontend/src/film.ts` | 改 | 等待文字、取消种类、播哪一次 |
| `frontend/src/filmTasks.ts` | 新建 | 任务列表的纯计算与「催一下」信号 |
| `frontend/src/components/ClipPlayer.tsx` | 新建 | 播放窗口 |
| `frontend/src/components/NodeCards.tsx`、`NodeGraph.tsx`、`FilmPanel.tsx`、`TimelineCanvas.tsx`、`StoryboardView.tsx` | 改 | 等待一行、取消、播放、聚焦请求 |
| `frontend/src/useFilm.ts`、`notify.ts`、`paths.ts` | 改 | 取消操作、可点击通知、路由 state |
| `frontend/src/components/shell/ActivityPanel.tsx`、`frontend/src/App.tsx` | 改 | 动态面板与应用接线 |
| `frontend/tests/film-tasks.test.tsx` | 新建 | 任务队列、通知、面板的测试 |

Task 1–9 做出片片段的可见性、取消与观看；Task 10–11 把任务面板扩成个人任务队列（合成任务、定位、面板里取消、已结束保留一天）；Task 12 是全量验收。Task 10、11 会改 Task 5、8、9 刚写的部分代码与测试，这是有意的（先把片段这条线跑通，再扩）。

---

### Task 1: 厂商接口加「通常时长」与「取消」（公共函数 + 假厂商）

**Files:**
- Modify: `backend/render/providers/base.py`
- Modify: `backend/render/providers/fake.py`
- Test: `backend/tests/render/test_providers.py`

- [ ] **Step 1: 写失败的测试**

在 `backend/tests/render/test_providers.py` 里找到：

```python
    print("脱敏：自重叠密钥线性查找 ✓")

    print("\nALL PASS")
```

换成：

```python
    print("脱敏：自重叠密钥线性查找 ✓")

    # 6. 通常时长：厂商给了用厂商的，没给用保守缺省；只是界面提示用的数字
    assert base.typical_sec(fake) == [60, 180]
    assert base.typical_sec(object()) == [60, 600]
    print("通常时长 ✓")

    # 7. 取消：厂商没有 cancel、cancel 抛异常都当「没取消成」，不往外抛，日志里没有密钥
    assert base.try_cancel(object(), "t") is False

    class Boom:
        _key = "k-secret"

        def cancel(self, task_id):
            raise RuntimeError("k-secret 炸了")

    with _LogGrab("render.providers.base") as g:
        assert base.try_cancel(Boom(), "t") is False
    assert g.lines and all("k-secret" not in x for x in g.lines), g.lines
    # 假厂商：缺省取消不了（任务照常跑）；cancel_ok 时确认取消，之后查询是「任务已取消」
    f2 = FakeVideo(polls_to_finish=3)
    tid = f2.submit(base.ClipRequest(prompt="p", model="fake-1", duration=4, resolution="720p"))
    assert base.try_cancel(f2, tid) is False and f2.poll(tid).status == "running"
    f2.cancel_ok = True
    assert base.try_cancel(f2, tid) is True
    st = f2.poll(tid)
    assert st.status == "failed" and st.error_msg["code"] == "film.provider.task_cancelled"
    assert f2.cancel_calls == [tid, tid]
    assert base.try_cancel(f2, "nope") is False
    print("取消 ✓")

    print("\nALL PASS")
```

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && .venv/bin/python tests/render/test_providers.py`
预期：失败，输出含 `AttributeError`

- [ ] **Step 3: 实现公共函数**

在 `backend/render/providers/base.py` 里找到：

```python
import math
import os
import re
```

换成：

```python
import logging
import math
import os
import re
```

在 `backend/render/providers/base.py` 里找到：

```python
from server.messages import UserError

REF_ROLES = ("character", "creature", "location", "prop", "first_frame", "style")
```

换成：

```python
from server.messages import UserError

log = logging.getLogger("render.providers.base")

REF_ROLES = ("character", "creature", "location", "prop", "first_frame", "style")
DEFAULT_TYPICAL_SEC = (60, 600)     # 厂商没给「通常时长」时的保守区间（秒）
```

在 `backend/render/providers/base.py` 里找到：

```python
    rate_note: dict     # 费率依据（消息对象 {code, params}）：如实写出处、是否经账单核对；出片确认框照抄
    console_name: str   # 厂商控制台名的代码，如 console.ark
```

换成：

```python
    rate_note: dict     # 费率依据（消息对象 {code, params}）：如实写出处、是否经账单核对；出片确认框照抄
    console_name: str   # 厂商控制台名的代码，如 console.ark
    typical_sec: tuple  # 一段通常要等多久（秒，下限与上限）：只给界面显示「通常 x–y 分钟」，不参与判定
```

在 `backend/render/providers/base.py` 里找到：

```python
    def download(self, st: TaskState, dest: Path) -> dict: ...   # {"video": Path, "last_frame": Path | None}
    def cost(self, st: TaskState, req: ClipRequest) -> float: ...
```

换成：

```python
    def download(self, st: TaskState, dest: Path) -> dict: ...   # {"video": Path, "last_frame": Path | None}
    def cost(self, st: TaskState, req: ClipRequest) -> float: ...
    def cancel(self, task_id: str) -> bool: ...                  # True = 厂商确认已取消且不计费；取消不了返回 False
```

在 `backend/render/providers/base.py` 末尾追加：

```python


def typical_sec(provider) -> list:
    """这家厂商一段通常要等多久（秒，[下限, 上限]）。厂商没给用 DEFAULT_TYPICAL_SEC。"""
    lo, hi = getattr(provider, "typical_sec", None) or DEFAULT_TYPICAL_SEC
    return [int(lo), int(hi)]


def try_cancel(provider, task_id: str) -> bool:
    """请厂商取消一个已提交的任务。True = 厂商确认已取消（不计费）；False = 没取消成（厂商没有取消接口、
    任务已在生成、查询或取消出错）：调用方按「不等了」处理，任务可能照常完成并计费。绝不往外抛。"""
    fn = getattr(provider, "cancel", None)
    if fn is None:
        return False
    try:
        return bool(fn(task_id))
    except Exception as e:
        log.warning("%s", scrub_secrets(f"取消任务出错：{type(e).__name__}", [getattr(provider, "_key", "")]))  # i18n: internal
        return False
```

- [ ] **Step 4: 假厂商支持取消**

在 `backend/render/providers/fake.py` 里找到：

```python
    console_name = "console.generic"
    rate_note = {"code": "rate.fake", "params": {}}

    def __init__(self, *, polls_to_finish: int = 1, fail_with: Optional[str] = None,
                 transient_submits: int = 0, max_refs: int = 3, frame_with_refs: bool = False,
                 native_audio: bool = True):
```

换成：

```python
    console_name = "console.generic"
    rate_note = {"code": "rate.fake", "params": {}}
    typical_sec = (60, 180)

    def __init__(self, *, polls_to_finish: int = 1, fail_with: Optional[str] = None,
                 transient_submits: int = 0, max_refs: int = 3, frame_with_refs: bool = False,
                 native_audio: bool = True, cancel_ok: bool = False):
```

在 `backend/render/providers/fake.py` 里找到：

```python
        self.submitted = []         # 依次提交的 ClipRequest
        self.tasks = {}
```

换成：

```python
        self.submitted = []         # 依次提交的 ClipRequest
        self.tasks = {}
        self.cancel_ok = cancel_ok  # True：取消一律成功（模拟任务还在厂商那边排队）；False：取消不了，任务照常跑
        self.cancel_calls = []      # 依次被要求取消的任务 id
```

在 `backend/render/providers/fake.py` 里找到：

```python
        if t is None:
            raise ProviderError.of("film.fake.no_task", id=task_id)
        t["polls"] += 1
```

换成：

```python
        if t is None:
            raise ProviderError.of("film.fake.no_task", id=task_id)
        if t.get("cancelled"):
            m = msg("film.provider.task_cancelled")
            return TaskState(task_id, "failed", error=m["message"], error_msg=compact(m))
        t["polls"] += 1
```

在 `backend/render/providers/fake.py` 里找到：

```python
    def cost(self, st, req):
        if st.status != "succeeded":
            return 0.0
        return round(st.usage.get("seconds", 0) * self._caps.cny_per_sec.get(req.resolution, 0.0), 2)
```

换成：

```python
    def cost(self, st, req):
        if st.status != "succeeded":
            return 0.0
        return round(st.usage.get("seconds", 0) * self._caps.cny_per_sec.get(req.resolution, 0.0), 2)

    def cancel(self, task_id):
        self.cancel_calls.append(task_id)
        t = self.tasks.get(task_id)
        if not self.cancel_ok or t is None:
            return False
        t["cancelled"] = True
        return True
```

- [ ] **Step 5: 运行，确认通过**

运行：`cd backend && .venv/bin/python tests/render/test_providers.py`
预期：通过，输出含 `取消 ✓`、`ALL PASS`

运行：`cd backend && .venv/bin/python tests/server/test_i18n_scan.py`
预期：通过

- [ ] **Step 6: 提交**

提交：

```bash
git add backend/render/providers/base.py backend/render/providers/fake.py backend/tests/render/test_providers.py
git commit -m "厂商接口加通常时长与取消：公共函数 typical_sec / try_cancel（取消出错不外抛、日志脱敏），假厂商可配置取消成败；补测试"
```
### Task 2: MiniMax 与 Seedance 的取消（只取消还在厂商那边排队的任务）

两家的取消接口同一个规矩（依据见 spec §3.1）：`DELETE` 对「排队中」是取消且不计费，对「运行中」报错，对「成功 / 失败」是**删除任务记录**（删了就再也查不到结果）。所以 `cancel` 必须先查状态，只有 `queued` 才发 `DELETE`。

**Files:**
- Modify: `backend/render/providers/minimax.py`
- Modify: `backend/render/providers/seedance.py`
- Test: `backend/tests/render/test_minimax.py`
- Test: `backend/tests/render/test_seedance.py`

- [ ] **Step 1: 写 MiniMax 的失败测试**

在 `backend/tests/render/test_minimax.py` 里找到：

```python
    print("10. 错误带代码 ✓")

    print("\nALL PASS")
```

换成：

```python
    print("10. 错误带代码 ✓")

    # 11. 取消：先查状态，只有排队中才发 DELETE；运行中、已结束都不发（对已结束的任务 DELETE 是删记录）
    calls = []

    def cancel_api(status, action="cancelled"):
        def handler(r):
            calls.append((r.method, r.url.path))
            if r.method == "GET":
                return httpx.Response(200, json={"task": {"status": status}})
            return httpx.Response(200, json={"task_id": "t1", "action": action, "status": action})
        return handler

    assert mmx(cancel_api("queued")).cancel("t1") is True
    assert calls == [("GET", "/v2/query/video_generation/t1"), ("DELETE", "/v2/video_generation/t1")], calls
    for status in ("running", "succeeded", "failed", "cancelled"):
        calls.clear()
        assert mmx(cancel_api(status)).cancel("t1") is False
        assert calls == [("GET", "/v2/query/video_generation/t1")], (status, calls)
    assert mmx(cancel_api("queued", "deleted")).cancel("t1") is False, "回的是删除而不是取消：不算取消成功"

    def cancel_refused(r):
        if r.method == "GET":
            return httpx.Response(200, json={"task": {"status": "queued"}})
        return httpx.Response(400, json={"base_resp": {"status_code": 2013, "status_msg": "task is running"}})

    must_raise(base.ProviderError, mmx(cancel_refused).cancel, "t1")
    assert base.try_cancel(mmx(cancel_refused), "t1") is False, "取消接口报错由 try_cancel 接住"
    assert MiniMax.typical_sec == (180, 420)
    print("11. 取消 ✓")

    print("\nALL PASS")
```

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && .venv/bin/python tests/render/test_minimax.py`
预期：失败，输出含 `AttributeError`

- [ ] **Step 3: 实现 MiniMax.cancel**

在 `backend/render/providers/minimax.py` 里找到：

```python
    console_name = "console.minimax"
    rate_note = {"code": "rate.minimax", "params": {}}
```

换成：

```python
    console_name = "console.minimax"
    rate_note = {"code": "rate.minimax", "params": {}}
    typical_sec = (180, 420)        # 2026-11-21 实测一段约 4–5 分钟，取保守区间 3–7 分钟
```

在 `backend/render/providers/minimax.py` 里找到：

```python
    def cost(self, st: TaskState, req: ClipRequest) -> float:
        if st.status != "succeeded":
            return 0.0                                  # 失败按不计费处理（官方未写明，待账单核对）
```

换成：

```python
    def cancel(self, task_id: str) -> bool:
        """只取消还在排队的任务。官方（DELETE /v2/video_generation/{task_id}，2026-11-21 核对）：排队中 → 取消且
        不扣费；运行中、已取消 → 报错；成功、失败 → 删除任务记录。所以先查状态，不是 queued 就不发 DELETE。"""
        j = self._call("GET", f"/v2/query/video_generation/{task_id}")
        t = j.get("task") if isinstance(j.get("task"), dict) else j
        if t.get("status") != "queued":
            return False
        r = self._call("DELETE", f"/v2/video_generation/{task_id}")
        return r.get("action") == "cancelled"

    def cost(self, st: TaskState, req: ClipRequest) -> float:
        if st.status != "succeeded":
            return 0.0                                  # 失败按不计费处理（官方未写明，待账单核对）
```

- [ ] **Step 4: 运行，确认通过**

运行：`cd backend && .venv/bin/python tests/render/test_minimax.py`
预期：通过，输出含 `11. 取消 ✓`、`ALL PASS`

- [ ] **Step 5: 写 Seedance 的失败测试**

在 `backend/tests/render/test_seedance.py` 里找到：

```python
    print("9b. 日志整体脱敏 ✓")

    print("\nALL PASS")
```

换成：

```python
    print("9b. 日志整体脱敏 ✓")

    # 10. 取消：先查状态，只有排队中才发 DELETE；方舟的 DELETE 回空对象，所以再查一次确认变成 cancelled
    calls = []

    def cancel_api(*statuses):
        left = list(statuses)

        def handler(r):
            calls.append((r.method, r.url.path))
            if r.method == "GET":
                return httpx.Response(200, json={"id": "cgt-1", "status": left.pop(0)})
            return httpx.Response(200, json={})
        return handler

    path = "/api/v3/contents/generations/tasks/cgt-1"
    assert ark(cancel_api("queued", "cancelled")).cancel("cgt-1") is True
    assert calls == [("GET", path), ("DELETE", path), ("GET", path)], calls
    for status in ("running", "succeeded", "failed", "expired", "cancelled"):
        calls.clear()
        assert ark(cancel_api(status)).cancel("cgt-1") is False
        assert calls == [("GET", path)], (status, calls)
    assert ark(cancel_api("queued", "running")).cancel("cgt-1") is False, "DELETE 之后没变成 cancelled：不算取消成功"

    def cancel_refused(r):
        if r.method == "GET":
            return httpx.Response(200, json={"id": "cgt-1", "status": "queued"})
        return httpx.Response(400, json={"error": {"code": "InvalidParameter", "message": "task is running"}})

    must_raise(base.ProviderError, ark(cancel_refused).cancel, "cgt-1")
    assert base.try_cancel(ark(cancel_refused), "cgt-1") is False, "取消接口报错由 try_cancel 接住"
    assert Seedance.typical_sec == (120, 480)
    print("10. 取消 ✓")

    print("\nALL PASS")
```

- [ ] **Step 6: 运行，确认失败**

运行：`cd backend && .venv/bin/python tests/render/test_seedance.py`
预期：失败，输出含 `AttributeError`

- [ ] **Step 7: 实现 Seedance.cancel**

在 `backend/render/providers/seedance.py` 里找到：

```python
    default_model = DEFAULT_MODEL
    rate_note = {"code": "rate.ark", "params": {}}
```

换成：

```python
    default_model = DEFAULT_MODEL
    rate_note = {"code": "rate.ark", "params": {}}
    typical_sec = (120, 480)        # 没有实测数据，先取保守区间 2–8 分钟；真跑后按实际校准
```

在 `backend/render/providers/seedance.py` 里找到：

```python
    def cost(self, st: TaskState, req: ClipRequest) -> float:
        if st.status != "succeeded":
            return 0.0                              # 方舟失败任务不计费
```

换成：

```python
    def cancel(self, task_id: str) -> bool:
        """只取消还在排队的任务。官方（DELETE /contents/generations/tasks/{id}，2026-11-21 核对）：queued → 取消排队、
        状态变 cancelled；running → 不支持；succeeded / failed / expired / cancelled → 删除任务记录。
        所以先查状态，不是 queued 就不发 DELETE；DELETE 回的是空对象，再查一次确认。"""
        url = f"/contents/generations/tasks/{task_id}"
        if self._call("GET", url, task_id=task_id).get("status") != "queued":
            return False
        self._call("DELETE", url, task_id=task_id)
        return self._call("GET", url, task_id=task_id).get("status") == "cancelled"

    def cost(self, st: TaskState, req: ClipRequest) -> float:
        if st.status != "succeeded":
            return 0.0                              # 方舟失败任务不计费
```

- [ ] **Step 8: 运行，确认通过**

运行：`cd backend && .venv/bin/python tests/render/test_seedance.py`
预期：通过，输出含 `10. 取消 ✓`、`ALL PASS`

运行：`cd backend && .venv/bin/python tests/server/test_i18n_scan.py`
预期：通过

- [ ] **Step 9: 提交**

提交：

```bash
git add backend/render/providers/minimax.py backend/render/providers/seedance.py backend/tests/render/test_minimax.py backend/tests/render/test_seedance.py
git commit -m "MiniMax 与 Seedance 支持取消还在厂商那边排队的任务：先查状态，只有 queued 才发 DELETE（对已结束的任务 DELETE 是删记录）；各给一个通常时长区间；补测试"
```
### Task 3: 会话层的取消、「不等了」与结束标记

这一步只动会话状态机（`session.py`、`free.py`）与消息登记，不调厂商、不动接口。新增的消息代码要同时进后端登记表、`messages_codes.json` 和前端两份语言包的 `srv` 节点（前端 `tests/srv-codes.test.ts` 逐条核对）。

**Files:**
- Modify: `backend/server/messages.py`
- Modify: `backend/server/messages_codes.json`（用命令重新生成）
- Modify: `frontend/src/i18n/zh.ts`
- Modify: `frontend/src/i18n/en.ts`
- Modify: `backend/render/session.py`
- Modify: `backend/render/free.py`
- Create: `backend/tests/render/test_cancel.py`

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/render/test_cancel.py`：

```python
#!/usr/bin/env python3
"""出片取消（会话层）：还没提交的本地取消、提交中的不能取消、厂商确认取消、「不等了」（那次尝试留着、
计入预留、结果回来后记费且不自动采用）、状态变了要重试、结束标记、重启恢复、自由节点待结算时不能删。

全程临时目录 + 假厂商，不联网、不花钱。用法: python3 tests/render/test_cancel.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

os.environ["STORYBOARD_DATA_DIR"] = tempfile.mkdtemp()   # 数据目录用临时目录（必须在导入 server.*、render.* 之前）
# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"

from render import free, providers, session as sess  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from server.messages import msg  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}
FAKE = FakeVideo()
providers.register("fake", lambda: FAKE)


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def clip(root, cid):
    return next(c for c in sess.load(root)["clips"] if c["id"] == cid)


def request(root, snap):
    s = sess.load(root)
    return base.ClipRequest(prompt=snap["prompt"], model=s["model"], duration=snap["duration"],
                            resolution=s["resolution"])


def start(root, cid):
    """排队 → 提交 → 拿到任务 id（段进入 running）。返回 (任务 id, 请求)。"""
    sess.queue_run(root, [cid])
    snap = sess.begin_submit(root, cid)
    req = request(root, snap)
    tid = FAKE.submit(req)
    sess.submitted(root, cid, tid, None)
    return tid, req


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name) / "render" / "v"
    build = lambda **patch: sess.build(root, doc, owner=OWNER, patch=patch, keyframes={})  # noqa: E731
    s = build(budget_cny=100000)
    a, b, c3, d4 = [x["id"] for x in s["clips"][:4]]
    est = s["clips"][0]["estimate_cny"]

    # 1. 还没提交：本地取消，回到未出片，没有尝试记录、没花钱，记下「已取消」
    sess.queue_run(root, [a])
    assert sess.cancel_target(root, a) == (None, "fake")
    s = sess.cancel(root, a)
    c = clip(root, a)
    assert c["state"] == "planned" and c["attempts"] == [] and s["spent_cny"] == 0.0
    assert c["ended_as"] == "cancelled" and c["ended_at"]
    assert not sess.needs_runner(sess.load(root))
    print("1. 还没提交的本地取消 ✓")

    # 2. 正在提交（已追加「提交中」的尝试、还没拿到任务 id）：不能取消，稍后再试
    sess.queue_run(root, [a])
    snap = sess.begin_submit(root, a)
    e = must_raise(sess.Conflict, sess.cancel_target, root, a)
    assert e.code == "film.cancel.submitting"
    e = must_raise(sess.Conflict, sess.cancel, root, a)
    assert e.code == "film.cancel.submitting"
    req = request(root, snap)
    tid = FAKE.submit(req)
    sess.submitted(root, a, tid, None)
    assert sess.cancel_target(root, a) == (tid, "fake")
    print("2. 提交中不能取消 ✓")

    # 3. 状态在两步之间变了：任务 id 对不上就让用户再试一次，不改会话
    e = must_raise(sess.Conflict, sess.cancel, root, a, "other-task")
    assert e.code == "film.cancel.changed"
    e = must_raise(sess.Conflict, sess.cancel, root, a, None)
    assert e.code == "film.cancel.changed" and clip(root, a)["state"] == "running"
    print("3. 状态变了要重试 ✓")

    # 4. 厂商确认取消：那次尝试记「已取消」、不计费、不用再盯
    s = sess.cancel(root, a, tid, confirmed=True)
    c = clip(root, a)
    att = c["attempts"][-1]
    assert c["state"] == "planned" and c["ended_as"] == "cancelled" and c["error"] is None
    assert att["state"] == "cancelled" and att["cost_cny"] == 0.0 and att["cancelled_at"]
    assert att["error_msg"]["code"] == "film.provider.task_cancelled"
    assert sess.abandoned(s) == [] and not sess.needs_runner(s) and s["spent_cny"] == 0.0
    print("4. 厂商确认取消 ✓")

    # 5. 不等了：这一段立即放开；那次尝试留着（记下提交时的厂商、档位、分辨率、时长、预估），
    #    计入预留与上限，出片线程还要盯；不算「在跑」，所以可以改设置、可以重出
    tid, req = start(root, b)
    s = sess.cancel(root, b, tid)
    c = clip(root, b)
    att = c["attempts"][-1]
    assert c["state"] == "planned" and c["ended_as"] == "cancelled"
    assert att["state"] == "abandoned" and att["task_id"] == tid
    assert att["billing"] == {"provider": "fake", "model": "fake-1", "resolution": "720p",
                              "duration": c["duration"], "estimate_cny": c["estimate_cny"]}
    assert [(h["id"], x["task_id"]) for h, x in sess.abandoned(s)] == [(b, tid)]
    assert sess.needs_runner(s) and not sess.any_in_flight(s)
    assert sess.abandoned_cny(s) == c["estimate_cny"] and sess.view(s)["reserved_cny"] == c["estimate_cny"]
    assert sess.recover(root) is True, "重启后还有待结算的尝试：要接着盯"
    tight = build(budget_cny=round(c["estimate_cny"] * 1.5, 2))       # 不在跑：可以改设置
    assert clip(root, b)["attempts"][-1]["state"] == "abandoned"
    e = must_raise(sess.BudgetExceeded, sess.queue_run, root, [b])
    assert e.code == "film.budget.exceeded", "待结算的那次按预估占着上限"
    build(budget_cny=100000, resolution="480p")
    assert clip(root, b)["attempts"][-1]["billing"]["resolution"] == "720p", "记费按提交时的设置，不跟着后来的设置变"
    build(resolution="720p")
    assert tight["budget_cny"] > 0
    print("5. 不等了 ✓")

    # 6. 厂商后来还是生成完了：下载、记费、标 late，留作可采用的一次；不自动采用，段的状态不动
    st = FAKE.poll(tid)
    files = FAKE.download(st, sess.clip_dest(root, b, tid))
    cost = FAKE.cost(st, req)
    sess.settle_abandoned(root, tid, "succeeded", cost=cost, files=files)
    s = sess.load(root)
    c = clip(root, b)
    att = c["attempts"][-1]
    assert att["state"] == "succeeded" and att["late"] is True and att["cost_cny"] == cost > 0
    assert (root / att["file"]).exists() and att["settled_at"]
    assert c["state"] == "planned" and c["chosen"] is None, "不自动采用"
    assert s["spent_cny"] == cost and sess.abandoned(s) == [] and not sess.needs_runner(s)
    assert sess.view(s)["reserved_cny"] == 0
    s = sess.set_chosen(root, b, len(c["attempts"]) - 1)
    assert clip(root, b)["state"] == "done", "仍可采用"
    print("6. 结果回来：记费、可采用、不自动采用 ✓")

    # 7. 已有采用的段重出时不等了：回到原来的 done，采用不变；厂商后来报失败 / 取消 → 照实记，不计费
    tid2, _ = start(root, b)
    sess.cancel(root, b, tid2)
    c = clip(root, b)
    assert c["state"] == "done" and c["chosen"] == 0 and c["attempts"][-1]["state"] == "abandoned"
    spent = sess.load(root)["spent_cny"]
    sess.settle_abandoned(root, tid2, "failed", error=msg("film.provider.generation_failed"))
    att = clip(root, b)["attempts"][-1]
    assert att["state"] == "failed" and att["error_msg"]["code"] == "film.provider.generation_failed"
    assert sess.load(root)["spent_cny"] == spent and clip(root, b)["state"] == "done"
    tid3, _ = start(root, b)
    sess.cancel(root, b, tid3)
    sess.settle_abandoned(root, tid3, "cancelled", error=msg("film.provider.task_cancelled"))
    assert clip(root, b)["attempts"][-1]["state"] == "cancelled"
    sess.settle_abandoned(root, "no-such-task", "failed", error="x")      # 找不到就什么都不做
    print("7. 有采用的段、厂商后来失败或取消 ✓")

    # 8. 已经在取回、已经结束、不存在：不能取消
    tid4, req4 = start(root, c3)
    sess.poll_update(root, c3, FAKE.poll(tid4))
    assert clip(root, c3)["state"] == "downloading"
    assert must_raise(sess.Conflict, sess.cancel_target, root, c3).code == "film.cancel.finished"
    st4 = FAKE.poll(tid4)
    sess.downloaded(root, c3, FAKE.download(st4, sess.clip_dest(root, c3, tid4)), FAKE.cost(st4, req4))
    assert clip(root, c3)["ended_as"] == "done" and clip(root, c3)["ended_at"]
    assert must_raise(sess.Conflict, sess.cancel_target, root, c3).code == "film.cancel.not_running"
    assert must_raise(sess.Conflict, sess.cancel_target, root, d4).code == "film.cancel.not_running"
    must_raise(sess.NotFound, sess.cancel_target, root, "E99-C99")
    print("8. 不能取消的情况 ✓")

    # 9. 结束标记：失败也记（任务列表「最近结束」用）
    tid5, _ = start(root, d4)
    sess.poll_update(root, d4, base.TaskState(tid5, "failed", error="审核未通过"))
    assert clip(root, d4)["ended_as"] == "failed" and clip(root, d4)["ended_at"]
    print("9. 结束标记 ✓")

    # 10. 视图带通常时长（只是数字，不带厂商名）
    assert sess.view(sess.load(root))["options"]["typical_sec"] == [60, 180]
    print("10. 通常时长进视图 ✓")

    # 11. 自由节点：有一次待结算的尝试时不能删（删了那笔费用就没处记）
    with sess.mutate(root) as s:
        s["free"] = [{"id": "F01", "target": None, "target_shots": None, "target_lost": False, "prompt": "雨夜",
                      "refs": [], "first_frame": None, "duration": 4.0, "estimate_cny": 4.0, "state": "planned",
                      "error": None, "error_msg": None, "uncertain": False, "chosen": None,
                      "created_at": "2026-11-21T00:00:00+00:00",
                      "attempts": [{"task_id": "fake-x", "state": "abandoned", "cost_cny": 0.0, "file": None,
                                    "last_frame": None, "error": None, "error_msg": None,
                                    "at": "2026-11-21T00:00:00+00:00", "fingerprint": None, "first_frame_used": None,
                                    "billing": {"provider": "fake", "model": "fake-1", "resolution": "720p",
                                                "duration": 4.0, "estimate_cny": 4.0}}]}]
        s["free_seq"] = 1
    assert must_raise(sess.Conflict, free.delete, root, "F01").code == "film.free.pending_delete"
    sess.settle_abandoned(root, "fake-x", "failed", error=msg("film.cancel.lost"))
    s = free.delete(root, "F01")
    assert s["free"] == []
    assert est > 0
    print("11. 自由节点待结算时不能删 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && .venv/bin/python tests/render/test_cancel.py`
预期：失败，输出含 `AttributeError`

- [ ] **Step 3: 登记消息代码**

在 `backend/server/messages.py` 里找到：

```python
register("film.choose.not_success", "只能采用成功的那几次")
```

换成：

```python
register("film.choose.not_success", "只能采用成功的那几次")
register("film.cancel.submitting", "正在提交，几秒后再取消")
register("film.cancel.finished", "这一段已经生成完成，正在取回，不用取消了")
register("film.cancel.not_running", "这一段不在排队或生成中")
register("film.cancel.changed", "状态刚刚变了，请再试一次")
register("film.cancel.lost", "已取消的这一次一直查不到结果，无法确认是否计费")
```

在 `backend/server/messages.py` 里找到：

```python
register("film.free.busy_delete", "这个节点正在生成，等它结束再删")
```

换成：

```python
register("film.free.busy_delete", "这个节点正在生成，等它结束再删")
register("film.free.pending_delete", "这个节点有一次已取消的生成还没有结果，等它结束再删")
```

运行：`cd backend && .venv/bin/python -m server.messages --write`
预期：通过，输出含 `wrote`

- [ ] **Step 4: 前端两份语言包补上这几条（中文必须与后端一字不差）**

在 `frontend/src/i18n/zh.ts` 里找到：

```ts
      choose: {
        busy: '这一段正在生成，等它结束再换',
        not_success: '只能采用成功的那几次',
      },
```

换成：

```ts
      choose: {
        busy: '这一段正在生成，等它结束再换',
        not_success: '只能采用成功的那几次',
      },
      cancel: {
        submitting: '正在提交，几秒后再取消',
        finished: '这一段已经生成完成，正在取回，不用取消了',
        not_running: '这一段不在排队或生成中',
        changed: '状态刚刚变了，请再试一次',
        lost: '已取消的这一次一直查不到结果，无法确认是否计费',
      },
```

在 `frontend/src/i18n/zh.ts` 里找到：

```ts
        busy_delete: '这个节点正在生成，等它结束再删',
```

换成：

```ts
        busy_delete: '这个节点正在生成，等它结束再删',
        pending_delete: '这个节点有一次已取消的生成还没有结果，等它结束再删',
```

在 `frontend/src/i18n/en.ts` 里找到：

```ts
      choose: {
        busy: 'This clip is generating; wait for it to finish before switching',
        not_success: 'Only successful attempts can be adopted',
      },
```

换成：

```ts
      choose: {
        busy: 'This clip is generating; wait for it to finish before switching',
        not_success: 'Only successful attempts can be adopted',
      },
      cancel: {
        submitting: 'Still submitting; try cancelling again in a few seconds',
        finished: 'This clip has finished generating and is being fetched; nothing to cancel',
        not_running: 'This clip is not queued or generating',
        changed: 'The status just changed; please try again',
        lost: 'No result could be found for this cancelled attempt, so it is unclear whether it was billed',
      },
```

在 `frontend/src/i18n/en.ts` 里找到：

```ts
        busy_delete: 'This node is generating; wait for it to finish before deleting',
```

换成：

```ts
        busy_delete: 'This node is generating; wait for it to finish before deleting',
        pending_delete: 'This node has a cancelled generation with no result yet; wait for it to finish before deleting',
```

运行：`cd frontend && npx vite build --ssr tests/srv-codes.test.ts --outDir .ssrout --logLevel error && node .ssrout/srv-codes.test.js`
预期：通过，输出含 `ALL PASS`

- [ ] **Step 5: 会话层——常量与小工具**

在 `backend/render/session.py` 里找到：

```python
IN_FLIGHT = ("queued", "running", "downloading")
```

换成：

```python
IN_FLIGHT = ("queued", "running", "downloading")
ABANDONED = "abandoned"     # 尝试的状态：用户不等了，厂商那边可能还在跑；出片线程在后台盯到它有结果
```

在 `backend/render/session.py` 里找到：

```python
def _provider(name: str):
    try:
        return get_video(name)
```

换成：

```python
def _ended(c: dict, how: str) -> None:
    """记下这一条刚结束（done / failed / cancelled）：任务列表的「最近结束」按它显示。"""
    c["ended_at"], c["ended_as"] = _now(), how


def _rest_state(c: dict) -> str:
    """不在跑时该回到的状态：有采用的按指纹判 done / stale（自由节点没有过期），没有采用就是未出片。"""
    if c.get("chosen") is None:
        return "planned"
    if is_free(c["id"]):
        return "done"
    return "done" if c["attempts"][c["chosen"]].get("fingerprint") == c.get("fingerprint") else "stale"


def abandoned(s: dict) -> list:
    """[(所在的段 / 自由节点 / orphaned 记录, 尝试)]：用户不等了、还没有结果的尝试。"""
    holders = items(s) + list(s.get("orphaned") or [])
    return [(h, a) for h in holders for a in h.get("attempts") or []
            if a.get("state") == ABANDONED and a.get("task_id")]


def abandoned_cny(s: dict) -> float:
    """这些尝试厂商可能照常完成并计费：按提交时的预估预留，算进上限。"""
    return round(sum(float((a.get("billing") or {}).get("estimate_cny") or 0.0) for _, a in abandoned(s)), 2)


def needs_runner(s: dict) -> bool:
    """出片线程还要不要盯这个会话：有在跑的，或有不等了但还没结果的。"""
    return any_in_flight(s) or bool(abandoned(s))


def _provider(name: str):
    try:
        return get_video(name)
```

- [ ] **Step 6: 会话层——预留、通常时长、结束标记**

在 `backend/render/session.py` 里找到：

```python
    out["reserved_cny"] = round(sum(c["estimate_cny"] for c in items(s)
                                    if c["state"] in IN_FLIGHT), 2)
```

换成：

```python
    out["reserved_cny"] = round(sum(c["estimate_cny"] for c in items(s)
                                    if c["state"] in IN_FLIGHT) + abandoned_cny(s), 2)
```

在 `backend/render/session.py` 里找到：

```python
                      "rate_note": provider.rate_note,
                      "default_note": _default_note(s)}
```

换成：

```python
                      "rate_note": provider.rate_note,
                      "typical_sec": base.typical_sec(provider),
                      "default_note": _default_note(s)}
```

在 `backend/render/session.py` 里找到：

```python
        reserved = sum(c["estimate_cny"] for c in items(s) if c["state"] in IN_FLIGHT)
        if s["spent_cny"] + reserved + total > s["budget_cny"] + 1e-9:
            raise BudgetExceeded.of("film.budget.exceeded", budget=f"{s['budget_cny']:g}",
                                    spent=money(s["spent_cny"]), reserved=money(reserved), total=money(total))
        for c in targets:
```

换成：

```python
        reserved = sum(c["estimate_cny"] for c in items(s) if c["state"] in IN_FLIGHT) + abandoned_cny(s)
        if s["spent_cny"] + reserved + total > s["budget_cny"] + 1e-9:
            raise BudgetExceeded.of("film.budget.exceeded", budget=f"{s['budget_cny']:g}",
                                    spent=money(s["spent_cny"]), reserved=money(reserved), total=money(total))
        for c in targets:
```

在 `backend/render/session.py` 里找到：

```python
            set_error(last, msg("film.submit.interrupted"))
            last["state"] = "failed"
            c["state"], c["uncertain"] = "failed", True
            copy_error(c, last)
            return None
        running = sum(x["estimate_cny"] for x in items(s) if x["state"] in ("running", "downloading"))
        if s["spent_cny"] + running + c["estimate_cny"] > s["budget_cny"] + 1e-9:
            c["state"] = "failed"
            set_error(c, msg("film.submit.over_budget"))
            return None
```

换成：

```python
            set_error(last, msg("film.submit.interrupted"))
            last["state"] = "failed"
            c["state"], c["uncertain"] = "failed", True
            copy_error(c, last)
            _ended(c, "failed")
            return None
        running = sum(x["estimate_cny"] for x in items(s) if x["state"] in ("running", "downloading"))
        if s["spent_cny"] + running + abandoned_cny(s) + c["estimate_cny"] > s["budget_cny"] + 1e-9:
            c["state"] = "failed"
            set_error(c, msg("film.submit.over_budget"))
            _ended(c, "failed")
            return None
```

在 `backend/render/session.py` 里找到：

```python
            c["state"] = "failed"
            if uncertain:
                c["uncertain"] = True
        set_error(c, error)
```

换成：

```python
            c["state"] = "failed"
            if uncertain:
                c["uncertain"] = True
        set_error(c, error)
        _ended(c, "failed")
```

在 `backend/render/session.py` 里找到：

```python
            s["spent_cny"] = round(s["spent_cny"] + cost, 2)
            c["state"] = "failed"
            copy_error(c, a)
            if uncertain:
                c["uncertain"] = True
```

换成：

```python
            s["spent_cny"] = round(s["spent_cny"] + cost, 2)
            c["state"] = "failed"
            copy_error(c, a)
            _ended(c, "failed")
            if uncertain:
                c["uncertain"] = True
```

在 `backend/render/session.py` 里找到：

```python
        else:
            c["state"] = "done" if a["fingerprint"] == c["fingerprint"] else "stale"
        set_error(c, None)


def download_failed(root, clip_id: str, error, cost: float) -> None:
    """已经生成、但下载或校验失败：生成费用照记。"""
    with mutate(root) as s:
        c = _item(s, clip_id)
        c["attempts"][-1].update(state="failed", cost_cny=cost)
        set_error(c["attempts"][-1], error)
        s["spent_cny"] = round(s["spent_cny"] + cost, 2)
        c["state"] = "failed"
        set_error(c, error)
```

换成：

```python
        else:
            c["state"] = "done" if a["fingerprint"] == c["fingerprint"] else "stale"
        set_error(c, None)
        _ended(c, "done")


def download_failed(root, clip_id: str, error, cost: float) -> None:
    """已经生成、但下载或校验失败：生成费用照记。"""
    with mutate(root) as s:
        c = _item(s, clip_id)
        c["attempts"][-1].update(state="failed", cost_cny=cost)
        set_error(c["attempts"][-1], error)
        s["spent_cny"] = round(s["spent_cny"] + cost, 2)
        c["state"] = "failed"
        set_error(c, error)
        _ended(c, "failed")


def settle_abandoned(root, task_id: str, state: str, *, cost: float = 0.0, files: Optional[dict] = None,
                     error=None) -> None:
    """用户不等了的那次有了结果。state：succeeded（文件已下好）/ failed / cancelled。费用照记进 spent_cny。
    成功的标 late、留作可采用的一次，不自动采用，也不动所在段的状态；挂靠的自由节点照常复制进目标段。"""
    with mutate(root) as s:
        for h, a in abandoned(s):
            if a["task_id"] != task_id:
                continue
            a.update(state=state, cost_cny=cost, settled_at=_now())
            if state == "succeeded":
                a.update(file=_rel(root, files["video"]), last_frame=_rel(root, files.get("last_frame")), late=True)
                set_error(a, None)
                if is_free(h["id"]) and h.get("target"):
                    _deliver(s, h, a)
            else:
                set_error(a, error)
            s["spent_cny"] = round(s["spent_cny"] + cost, 2)
            return
```

在 `backend/render/session.py` 里找到：

```python
                a["state"] = "failed"
                set_error(a, msg("film.submit.interrupted"))
                c["state"], c["uncertain"] = "failed", True
                copy_error(c, a)
                changed = True
        changed = _fail_interrupted_compose(s) or changed
        if changed:
            _save(root, s)
        return any_in_flight(s)
```

换成：

```python
                a["state"] = "failed"
                set_error(a, msg("film.submit.interrupted"))
                c["state"], c["uncertain"] = "failed", True
                copy_error(c, a)
                _ended(c, "failed")
                changed = True
        changed = _fail_interrupted_compose(s) or changed
        if changed:
            _save(root, s)
        return needs_runner(s)
```

- [ ] **Step 7: 会话层——取消**

在 `backend/render/session.py` 里找到：

```python
# ---------- 出片线程侧迁移 ----------
```

换成：

```python
def _cancel_check(c: dict) -> Optional[str]:
    """能不能取消：还没提交返回 None（纯本地取消，不花钱）；已提交返回任务 id；其余抛 Conflict。"""
    last = c["attempts"][-1] if c["attempts"] else None
    if c["state"] == "queued":
        if last and last["state"] == "submitting":
            raise Conflict.of("film.cancel.submitting")     # 请求正在路上，拿不到任务 id：几秒后再试
        return None
    if c["state"] == "running" and last and last.get("task_id"):
        return last["task_id"]
    if c["state"] == "downloading":
        raise Conflict.of("film.cancel.finished")
    raise Conflict.of("film.cancel.not_running")


def cancel_target(root, item_id: str) -> tuple:
    """取消前看一眼（不改会话）：(任务 id 或 None, 厂商名)。调用方拿任务 id 在锁外请厂商取消，再调 cancel。"""
    with _lock(root):
        s = _read_existing(root)
        if s is None:
            raise NotFound.of("film.session.none")
        return _cancel_check(_item(s, item_id)), s["provider"]


def cancel(root, item_id: str, task_id: Optional[str] = None, confirmed: bool = False) -> dict:
    """取消一段或一个自由节点，立即放开它（回到未出片 / 原来采用的那次）。
    task_id 是 cancel_target 看到的那个：对不上说明两步之间状态变了，抛 Conflict 让用户再试。
    - 还没提交（task_id=None）：什么都没发出去，不留尝试。
    - 已提交、厂商确认取消（confirmed=True）：那次尝试记 cancelled，不计费。
    - 已提交、没取消成：那次尝试记 abandoned，连同提交时的厂商、档位、分辨率、时长与预估（之后改设置也按它记费）；
      出片线程接着盯，结果回来由 settle_abandoned 落账。"""
    with mutate(root) as s:
        c = _item(s, item_id)
        if _cancel_check(c) != task_id:
            raise Conflict.of("film.cancel.changed")
        if task_id is not None:
            a = c["attempts"][-1]
            a["cancelled_at"] = _now()
            if confirmed:
                a["state"] = "cancelled"
                set_error(a, msg("film.provider.task_cancelled"))
            else:
                a["state"] = ABANDONED
                a["billing"] = {"provider": s["provider"], "model": s["model"], "resolution": s["resolution"],
                                "duration": c["duration"], "estimate_cny": c["estimate_cny"]}
        c["state"] = _rest_state(c)
        set_error(c, None)
        _ended(c, "cancelled")
        return s


# ---------- 出片线程侧迁移 ----------
```

- [ ] **Step 8: 自由节点——预留与删除保护**

在 `backend/render/free.py` 里找到：

```python
        if n["state"] in sess.IN_FLIGHT:
            raise sess.Conflict.of("film.free.busy_delete")
```

换成：

```python
        if n["state"] in sess.IN_FLIGHT:
            raise sess.Conflict.of("film.free.busy_delete")
        if any(a.get("state") == sess.ABANDONED for a in n["attempts"]):
            raise sess.Conflict.of("film.free.pending_delete")      # 那次可能还会计费：删了节点就没处记
```

在 `backend/render/free.py` 里找到：

```python
        reserved = sum(c["estimate_cny"] for c in sess.items(s) if c["state"] in sess.IN_FLIGHT)
```

换成：

```python
        reserved = sum(c["estimate_cny"] for c in sess.items(s) if c["state"] in sess.IN_FLIGHT) + sess.abandoned_cny(s)
```

- [ ] **Step 9: 运行，确认通过**

运行：`cd backend && .venv/bin/python tests/render/test_cancel.py`
预期：通过，输出含 `11. 自由节点待结算时不能删 ✓`、`ALL PASS`

运行：`cd backend && for t in tests/render/test_session.py tests/render/test_free.py tests/render/test_runner.py tests/render/test_free_runner.py tests/server/test_render.py tests/server/test_render_free.py tests/server/test_messages.py tests/server/test_i18n_scan.py; do .venv/bin/python $t > /dev/null 2>&1 || echo "FAILED $t"; done; echo finished`
预期：通过，输出含 `finished`，不含 `FAILED`

- [ ] **Step 10: 提交**

提交：

```bash
git add backend/server/messages.py backend/server/messages_codes.json frontend/src/i18n/zh.ts frontend/src/i18n/en.ts backend/render/session.py backend/render/free.py backend/tests/render/test_cancel.py
git commit -m "出片会话支持取消：还没提交的本地取消；已提交的按厂商是否确认记「已取消」或「不等了」（那次尝试留着、按提交时的设置记费、计入预留与上限、结果回来不自动采用）；段与自由节点记结束时间与结局；视图带通常时长；自由节点有待结算的尝试时不能删；登记取消相关消息并补中英文案"
```
### Task 4: 出片线程在后台盯住「不等了」的尝试

**Files:**
- Modify: `backend/render/runner.py`
- Create: `backend/tests/render/test_cancel_runner.py`

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/render/test_cancel_runner.py`：

```python
#!/usr/bin/env python3
"""出片线程与「不等了」：厂商后来完成 → 下载、记费、不自动采用；与重出并行；厂商后来失败 / 取消；
查询一直失败到期限放弃；下载失败照记生成费；改了设置仍按提交时的设置记费；重启后接着盯。

全程临时目录 + 假厂商，不联网、不花钱。用法: python3 tests/render/test_cancel_runner.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_DATA_DIR"] = tempfile.mkdtemp()   # 错误记录写临时目录（在导入 render/server 之前）
# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None

from render import compose, providers, session as sess  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from render.runner import Runner  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}


def clip(root, cid):
    return next(c for c in sess.load(root)["clips"] if c["id"] == cid)


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    fake = FakeVideo(polls_to_finish=3)
    providers.register("fake", lambda: fake)
    tmp = tempfile.TemporaryDirectory()
    data = Path(tmp.name)
    root = data / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    build = lambda **patch: sess.build(root, doc, owner=OWNER, patch=patch, keyframes={})  # noqa: E731
    s = build(budget_cny=100000)
    ids = [c["id"] for c in s["clips"] if c["id"].endswith("-C01")] + [c["id"] for c in s["clips"]]
    ids = list(dict.fromkeys(ids))                   # 各集第一段在前：它们不等接力

    def builder(r, sess_now, c):
        return compose.request_for(doc, sess_now, c, keyframes={}, relay_frame=sess.relay_frame(r, sess_now, c),
                                   caps=fake.caps(sess_now["model"]), rewrite=fake.rewrite_prompt, style=None)

    now = [0.0]
    runner = Runner(builder, sleep=lambda _s: None, clock=lambda: now[0], abandoned_give_up_sec=100)

    def drain(limit=50):
        for _ in range(limit):
            if not runner.watching():
                return
            runner.tick()
        raise AssertionError("没跑完")

    def abandon(cid):
        """排队 → 出片线程提交 → 用户不等了。返回任务 id。"""
        sess.queue_run(root, [cid])
        runner.watch(root)
        runner.tick()
        assert clip(root, cid)["state"] == "running"
        tid, _ = sess.cancel_target(root, cid)
        sess.cancel(root, cid, tid)
        runner.watch(root)
        return tid

    # 1. 不等了之后厂商照常完成：接着查、下载、记费；段不动、不自动采用；之后不再盯这个会话
    a = ids[0]
    tid = abandon(a)
    runner.tick()
    runner.tick()
    assert clip(root, a)["attempts"][-1]["state"] == "abandoned" and runner.watching() == [root], "厂商还在跑：接着盯"
    runner.tick()
    c = clip(root, a)
    att = c["attempts"][-1]
    assert att["state"] == "succeeded" and att["late"] is True and (root / att["file"]).exists()
    assert att["cost_cny"] > 0 and sess.load(root)["spent_cny"] == att["cost_cny"]
    assert c["state"] == "planned" and c["chosen"] is None
    assert runner.watching() == []
    cost = att["cost_cny"]
    print("1. 厂商照常完成：记费、不自动采用 ✓")

    # 2. 不等了之后马上重出：两次并行推进，旧的那次落账为 late，新的那次正常采用
    tid = abandon(a)
    sess.queue_run(root, [a])
    runner.watch(root)
    drain()
    c = clip(root, a)
    states = [(x["state"], bool(x.get("late"))) for x in c["attempts"]]
    assert states == [("succeeded", True), ("succeeded", True), ("succeeded", False)], states
    assert c["state"] == "done" and c["chosen"] == 2
    assert sess.load(root)["spent_cny"] == round(cost * 3, 2)
    print("2. 与重出并行 ✓")

    # 3. 厂商后来报失败：照实记，不计费
    b = ids[1]
    spent = sess.load(root)["spent_cny"]
    tid = abandon(b)
    fake.fail_with = "OutputVideoSensitiveContentDetected: 审核未通过"
    drain()
    fake.fail_with = None
    att = clip(root, b)["attempts"][-1]
    assert att["state"] == "failed" and att["error"] == "OutputVideoSensitiveContentDetected: 审核未通过"
    assert sess.load(root)["spent_cny"] == spent and clip(root, b)["state"] == "planned"
    print("3. 厂商后来失败 ✓")

    # 4. 厂商那边后来变成已取消：记「已取消」
    tid = abandon(b)
    fake.tasks[tid]["cancelled"] = True
    drain()
    att = clip(root, b)["attempts"][-1]
    assert att["state"] == "cancelled" and att["error_msg"]["code"] == "film.provider.task_cancelled"
    print("4. 厂商后来取消 ✓")

    # 5. 查询一直失败：到期限放弃，记失败并说明无法确认是否计费；不再盯
    tid = abandon(b)
    real_poll = fake.poll

    def down(_tid):
        raise base.TransientError.of("film.fake.throttled")

    fake.poll = down
    runner.tick()
    assert clip(root, b)["attempts"][-1]["state"] == "abandoned" and clip(root, b)["error"] is None, "不往段上写重试提示"
    now[0] += 101
    runner.tick()
    fake.poll = real_poll
    att = clip(root, b)["attempts"][-1]
    assert att["state"] == "failed" and att["error_msg"]["code"] == "film.cancel.lost"
    assert runner.watching() == []
    print("5. 查询一直失败 → 放弃 ✓")

    # 6. 生成成功但下载被拒：生成费照记，那次记失败
    spent = sess.load(root)["spent_cny"]
    tid = abandon(b)
    real_download = fake.download

    def refuse(_st, _dest):
        raise base.ProviderError.of("film.provider.download_failed", status=404)

    fake.download = refuse
    drain()
    fake.download = real_download
    att = clip(root, b)["attempts"][-1]
    assert att["state"] == "failed" and att["error_msg"]["code"] == "film.provider.download_failed"
    assert att["cost_cny"] > 0 and sess.load(root)["spent_cny"] == round(spent + att["cost_cny"], 2)
    print("6. 下载失败照记生成费 ✓")

    # 7. 不等了之后改了分辨率：仍按提交时的分辨率记费
    spent = sess.load(root)["spent_cny"]
    tid = abandon(b)
    build(resolution="480p")
    drain()
    att = clip(root, b)["attempts"][-1]
    assert att["state"] == "succeeded" and att["billing"]["resolution"] == "720p"
    secs = base.request_seconds(att["billing"]["duration"], fake.caps("fake-1"))
    assert att["cost_cny"] == round(secs * 1.0, 2), "720p 是 1 元/秒，480p 是 0.5 元/秒"
    assert sess.load(root)["spent_cny"] == round(spent + att["cost_cny"], 2)
    build(resolution="720p")
    print("7. 按提交时的设置记费 ✓")

    # 8. 进程重启：只有待结算尝试的会话也要续上
    tid = abandon(b)
    fresh = Runner(builder, sleep=lambda _s: None)
    assert fresh.recover(data) == 1 and fresh.watching() == [root]
    for _ in range(10):
        if not fresh.watching():
            break
        fresh.tick()
    assert fresh.watching() == [] and clip(root, b)["attempts"][-1]["state"] == "succeeded"
    assert tid
    print("8. 重启后接着盯 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && .venv/bin/python tests/render/test_cancel_runner.py`
预期：失败，输出含 `abandoned_give_up_sec`

- [ ] **Step 3: 实现**

在 `backend/render/runner.py` 里找到：

```python
                 retries: int = 3, sleep=time.sleep, clock=time.monotonic,
                 poll_give_up_sec: float = 6 * 3600, download_give_up_sec: float = 20 * 3600):
```

换成：

```python
                 retries: int = 3, sleep=time.sleep, clock=time.monotonic,
                 poll_give_up_sec: float = 6 * 3600, download_give_up_sec: float = 20 * 3600,
                 abandoned_give_up_sec: float = 3600):
```

在 `backend/render/runner.py` 里找到：

```python
        self.poll_give_up_sec = poll_give_up_sec
        self.download_give_up_sec = download_give_up_sec
```

换成：

```python
        self.poll_give_up_sec = poll_give_up_sec
        self.download_give_up_sec = download_give_up_sec
        self.abandoned_give_up_sec = abandoned_give_up_sec    # 用户不等了的那次：查询一直出错多久后放弃
```

在 `backend/render/runner.py` 里找到：

```python
                except Exception as e:
                    if self._isolate(root, e):
                        break

        loaded = []
```

换成：

```python
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
```

在 `backend/render/runner.py` 里找到：

```python
            if s is None or not sess.any_in_flight(s):
                self._roots.discard(Path(root))
```

换成：

```python
            if s is None or not sess.needs_runner(s):
                self._roots.discard(Path(root))
```

在 `backend/render/runner.py` 里找到：

```python
    def _submit(self, root, provider, s, c) -> bool:
        snap = sess.begin_submit(root, c["id"])
```

换成：

```python
    def _track_abandoned(self, root, h, a) -> None:
        """用户不等了的那次：查到厂商给出终态为止。成功 → 下载、记费、留作可采用的一次；失败或取消照实记。
        厂商、档位、分辨率、时长都用那次提交时记下的（billing），不看会话现在的设置。"""
        b = a.get("billing") or {}
        provider = get_video(b.get("provider"))
        tid = a["task_id"]
        key = ("abandoned", str(root), h["id"], tid)
        try:
            st = self._retry(lambda: provider.poll(tid))
        except (base.TransientError, base.ProviderError):
            first = self._first_fail.setdefault(key, self.clock())
            if self.clock() - first >= self.abandoned_give_up_sec:
                self._first_fail.pop(key, None)
                log.warning("%s", _scrub_secrets(f'已取消的任务查询放弃 root={root} item={h["id"]} task={tid}', provider))  # i18n: internal
                sess.settle_abandoned(root, tid, "failed", error=msg("film.cancel.lost"))
            return
        self._first_fail.pop(key, None)
        if st.status not in ("succeeded", "failed"):
            return                                  # 还在排队或生成：下一轮再查
        req = base.ClipRequest(prompt="", model=b.get("model"), duration=b.get("duration") or 0.0,
                               resolution=b.get("resolution"), images=a.get("images"))
        cost = provider.cost(st, req)
        if st.status == "failed":
            gone = (st.error_msg or {}).get("code") == "film.provider.task_cancelled"
            err = ({"code": st.error_msg["code"], "params": st.error_msg.get("params") or {}, "message": st.error}
                   if st.error_msg else (st.error or msg("film.provider.failed")))
            sess.settle_abandoned(root, tid, "cancelled" if gone else "failed", cost=cost, error=err)
            return
        try:
            files = self._retry(lambda: provider.download(st, sess.clip_dest(root, h["id"], tid)))
        except base.TransientError:
            return                                  # 下一轮重查、重下
        except base.ProviderError as e:
            sess.settle_abandoned(root, tid, "failed", cost=cost, error=e)
            return
        if not base.is_playable_mp4(files["video"]):
            sess.settle_abandoned(root, tid, "failed", cost=cost, error=msg("film.download.not_playable"))
            return
        sess.settle_abandoned(root, tid, "succeeded", cost=cost, files=files)

    def _submit(self, root, provider, s, c) -> bool:
        snap = sess.begin_submit(root, c["id"])
```

- [ ] **Step 4: 运行，确认通过**

运行：`cd backend && .venv/bin/python tests/render/test_cancel_runner.py`
预期：通过，输出含 `8. 重启后接着盯 ✓`、`ALL PASS`

运行：`cd backend && for t in tests/render/test_runner.py tests/render/test_free_runner.py tests/render/test_cancel.py tests/server/test_render.py tests/server/test_i18n_scan.py; do .venv/bin/python $t > /dev/null 2>&1 || echo "FAILED $t"; done; echo finished`
预期：通过，输出含 `finished`，不含 `FAILED`

- [ ] **Step 5: 提交**

提交：

```bash
git add backend/render/runner.py backend/tests/render/test_cancel_runner.py
git commit -m "出片线程盯住用户不等了的尝试：接着查到厂商给出终态，成功就下载记费并留作可采用的一次，失败或取消照实记；按提交时的设置记费；查询一直失败到期限放弃；只剩这类尝试的会话重启后也续上；补测试"
```
### Task 5: 接口——取消与本人的出片任务列表

**Files:**
- Modify: `backend/server/app.py`
- Modify: `backend/tests/server/test_i18n_scan.py`（把新函数加进扫描名单）
- Create: `backend/tests/server/test_film_tasks.py`

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/server/test_film_tasks.py`：

```python
#!/usr/bin/env python3
"""出片的取消接口与任务列表接口：只看得到本人的；排队中 / 生成中 / 最近结束 / 取消后才出结果；
不带厂商与档位；还没提交的本地取消、厂商确认取消、不等了；不能取消的情况；自由节点。

全程临时数据目录 + 假厂商，不联网、不花钱。用法: python3 tests/server/test_film_tasks.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前

# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"     # 不起后台线程，测试里手动 tick

from fastapi.testclient import TestClient  # noqa: E402
from server.messages import msg  # noqa: E402
from render import providers, session as render_session  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402

FAKE = FakeVideo(polls_to_finish=2)
providers.register("fake", lambda: FAKE)
DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))


def drain(limit=200):
    runner = app_mod._render_runner
    for _ in range(limit):
        if not runner.watching():
            return
        runner.tick()
    raise AssertionError("出片线程没跑完")


def pick(s, iid):
    return next(x for x in s["clips"] + s["free"] if x["id"] == iid)


def main() -> int:
    runner = app_mod._render_runner
    runner.sleep = lambda _s: None
    c = TestClient(app_mod.app)
    alice = auth.register("alice", "secret1")["id"]
    bob = auth.register("bob", "secret2")["id"]
    H = {"Authorization": f"Bearer {auth.issue_token(alice)}"}
    HB = {"Authorization": f"Bearer {auth.issue_token(bob)}"}
    nid = novels.create_novel(alice, "药")["id"]
    cid = novels.create_chapter(alice, nid, "第一章", text="原文")["id"]
    novels.create_version(alice, nid, cid, "v1", {}, "原文")
    novels.update_version_state(alice, nid, cid, "v1", "succeeded", result=copy.deepcopy(DOC))
    R = f"/novels/{nid}/chapters/{cid}/versions/v1/render"
    root = novels.render_dir(alice, nid, cid, "v1")
    tasks = lambda h=H: c.get("/render/tasks", headers=h).json()["tasks"]  # noqa: E731

    # 1. 要登录；没有出片会话时是空的；视图带通常时长
    assert c.get("/render/tasks").status_code == 401
    assert tasks() == []
    s = c.post(R + "/session", headers=H, json={"budget_cny": 100000}).json()
    assert s["options"]["typical_sec"] == [60, 180]
    x = s["clips"][0]["id"]
    assert tasks() == [], "只是建了会话：没有任务"
    print("1. 登录与空列表 ✓")

    # 2. 排队中：本人看得到（章节、片段、已等、通常时长），别人看不到；不带厂商与档位
    r = c.post(R + f"/clips/{x}/run", headers=H, json={})
    assert r.status_code == 200, r.text
    (t,) = tasks()
    assert t["id"] == f"v1:{x}" and t["item_id"] == x and t["kind"] == "clip" and t["state"] == "queued"
    assert (t["novel_id"], t["chapter_id"], t["version_id"]) == (nid, cid, "v1")
    assert (t["work_title"], t["chapter"]) == ("药", "第一章")
    assert t["typical_sec"] == [60, 180] and isinstance(t["elapsed_sec"], int) and t["elapsed_sec"] >= 0
    assert t["ended_at"] is None and t["cost_cny"] is None
    assert tasks(HB) == [], "别人的任务看不到"
    raw = c.get("/render/tasks", headers=H).text
    assert "fake" not in raw and "provider" not in raw and "model" not in raw, raw
    print("2. 排队中、只对本人可见、不带厂商 ✓")

    # 3. 还没提交就取消：不找厂商、不花钱，回到未出片；任务列表里记「已取消」
    assert c.post(R + f"/clips/{x}/cancel", headers=HB).status_code == 404, "别人不能取消"
    r = c.post(R + f"/clips/{x}/cancel", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["cancel_outcome"] == "dequeued" and pick(r.json(), x)["state"] == "planned"
    assert FAKE.cancel_calls == [] and FAKE.submitted == [] and r.json()["spent_cny"] == 0
    (t,) = tasks()
    assert t["state"] == "cancelled" and t["ended_at"] and t["id"] == f"v1:{x}"
    print("3. 还没提交的取消 ✓")

    # 4. 已提交、厂商取消不了：不等了。这一段立即放开；那次按预估占着预留；结果回来后列表里多一条「取消后才出结果」
    c.post(R + f"/clips/{x}/run", headers=H, json={})
    runner.tick()
    assert tasks()[0]["state"] == "running"
    r = c.post(R + f"/clips/{x}/cancel", headers=H)
    assert r.status_code == 200, r.text
    s = r.json()
    tid = pick(s, x)["attempts"][-1]["task_id"]
    assert s["cancel_outcome"] == "abandoned" and FAKE.cancel_calls == [tid]
    assert pick(s, x)["state"] == "planned" and pick(s, x)["attempts"][-1]["state"] == "abandoned"
    assert s["reserved_cny"] == pick(s, x)["estimate_cny"] and runner.watching() == [root]
    assert [t["state"] for t in tasks()] == ["cancelled"]
    drain()
    s = c.get(R + "/session", headers=H).json()
    att = pick(s, x)["attempts"][-1]
    assert att["state"] == "succeeded" and att["late"] is True and s["spent_cny"] == att["cost_cny"] > 0
    assert pick(s, x)["chosen"] is None and pick(s, x)["state"] == "planned" and s["reserved_cny"] == 0
    late = [t for t in tasks() if t["state"] == "late"]
    assert len(late) == 1 and late[0]["id"] == f"v1:{x}:{tid}" and late[0]["cost_cny"] == att["cost_cny"]
    assert late[0]["item_id"] == x
    print("4. 不等了 → 后来出了结果 ✓")

    # 5. 已提交、厂商确认取消：那次记「已取消」，不计费，不用再盯
    FAKE.cancel_ok = True
    c.post(R + f"/clips/{x}/run", headers=H, json={})
    runner.tick()
    spent = s["spent_cny"]
    r = c.post(R + f"/clips/{x}/cancel", headers=H)
    assert r.status_code == 200 and r.json()["cancel_outcome"] == "cancelled", r.text
    assert pick(r.json(), x)["attempts"][-1]["state"] == "cancelled" and r.json()["spent_cny"] == spent
    runner.tick()
    assert runner.watching() == []
    FAKE.cancel_ok = False
    print("5. 厂商确认取消 ✓")

    # 6. 不能取消的情况：不在跑 409、没有这一段 404、正在提交 409、已经在取回 409
    r = c.post(R + f"/clips/{x}/cancel", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "film.cancel.not_running", r.text
    assert c.post(R + "/clips/E99-C99/cancel", headers=H).status_code == 404
    c.post(R + f"/clips/{x}/run", headers=H, json={})
    render_session.begin_submit(root, x)
    r = c.post(R + f"/clips/{x}/cancel", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "film.cancel.submitting", r.text
    render_session.submit_failed(root, x, msg("film.provider.failed"))
    c.post(R + f"/clips/{x}/run", headers=H, json={})
    runner.tick()
    runner.tick()
    runner.tick()
    assert pick(c.get(R + "/session", headers=H).json(), x)["state"] == "downloading"
    r = c.post(R + f"/clips/{x}/cancel", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "film.cancel.finished", r.text
    drain()
    done = [t for t in tasks() if t["id"] == f"v1:{x}"]
    assert len(done) == 1 and done[0]["state"] == "done" and done[0]["elapsed_sec"] >= 0
    print("6. 不能取消的情况 ✓")

    # 7. 自由节点同一套
    c.post(R + "/free", headers=H, json={})
    c.patch(R + "/free/F01", headers=H, json={"prompt": "空镜：河面"})
    r = c.post(R + "/free/F01/run", headers=H, json={})
    assert r.status_code == 200, r.text
    live = [t for t in tasks() if t["ended_at"] is None]
    assert [(t["item_id"], t["kind"], t["state"]) for t in live] == [("F01", "free", "queued")]
    assert tasks()[0]["item_id"] == "F01", "在跑的排在最近结束的前面"
    r = c.post(R + "/free/F01/cancel", headers=H)
    assert r.status_code == 200 and r.json()["cancel_outcome"] == "dequeued", r.text
    assert pick(r.json(), "F01")["state"] == "planned"
    print("7. 自由节点 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && .venv/bin/python tests/server/test_film_tasks.py`
预期：失败，输出含 `AssertionError`

- [ ] **Step 3: 实现取消接口**

在 `backend/server/app.py` 里找到：

```python
import uuid
from concurrent.futures import ThreadPoolExecutor
```

换成：

```python
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
```

在 `backend/server/app.py` 里找到：

```python
@app.post(_R + "/clips/{clip_id}/run")
def render_clip_run(nid: str, cid: str, vid: str, clip_id: str,
```

换成：

```python
def _film_cancel(user: dict, nid: str, cid: str, vid: str, item_id: str) -> dict:
    """取消排队或生成中的一段 / 一个自由节点。还没提交：本地取消，不花钱。已提交：先请厂商取消（只有还在厂商
    那边排队的才取消得了）；取消不了就是「不等了」——这一条立即放开，那次尝试留给出片线程在后台盯到有结果。
    厂商调用在会话锁之外；两步之间状态变了由 session.cancel 抛 409。"""
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid)
    task_id, provider_name = _render_call(render_session.cancel_target, root, item_id)
    confirmed = False
    if task_id is not None:
        try:
            provider = render_providers.get_video(provider_name)
        except (KeyError, render_video_base.ProviderError):
            provider = None                     # 厂商建不起来（如密钥被撤）：按取消不了处理
        confirmed = provider is not None and render_video_base.try_cancel(provider, task_id)
    s = _render_call(render_session.cancel, root, item_id, task_id, confirmed)
    _render_runner.watch(root)                  # 不等了的那次还要盯；没有要盯的，下一轮自己放下
    out = _render_call(render_session.view, s)
    out["cancel_outcome"] = "dequeued" if task_id is None else "cancelled" if confirmed else "abandoned"
    return out


@app.post(_R + "/clips/{clip_id}/cancel")
def render_clip_cancel(nid: str, cid: str, vid: str, clip_id: str, user: dict = Depends(novel_user)):
    """取消这一段。响应是会话视图加 cancel_outcome：dequeued（还没提交）/ cancelled（厂商确认，不计费）/
    abandoned（不等了，厂商可能照常完成并计费）。不在跑、正在提交、已在取回 → 409。"""
    return _film_cancel(user, nid, cid, vid, clip_id)


@app.post(_R + "/clips/{clip_id}/run")
def render_clip_run(nid: str, cid: str, vid: str, clip_id: str,
```

在 `backend/server/app.py` 里找到：

```python
@app.put(_R + "/free/{fid}/chosen")
def render_free_chosen(nid: str, cid: str, vid: str, fid: str, body: RenderChosenBody,
```

换成：

```python
@app.post(_R + "/free/{fid}/cancel")
def render_free_cancel(nid: str, cid: str, vid: str, fid: str, user: dict = Depends(novel_user)):
    """取消这个自由节点的生成（与取消一段同一套）。"""
    return _film_cancel(user, nid, cid, vid, fid)


@app.put(_R + "/free/{fid}/chosen")
def render_free_chosen(nid: str, cid: str, vid: str, fid: str, body: RenderChosenBody,
```

- [ ] **Step 4: 实现任务列表接口**

在 `backend/server/app.py` 里找到：

```python
# ---------- 配音与合成：音色存在 session.json 的 voices，成片在 final/ ----------
```

换成：

```python
FILM_RECENT_SEC = 600       # 任务列表里「最近结束」保留多久（秒）


def _iso_ts(value) -> Optional[float]:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


def _film_tasks(uid: str) -> list:
    """本人的出片任务：在排队 / 生成 / 取回的段与自由节点，最近 FILM_RECENT_SEC 秒内结束的，以及取消后才出结果的。
    只读两类会话：出片线程正盯着的，和文件最近改过的；不必每次读遍所有章节。给普通用户看：不带厂商与档位。
    已等时长由服务端算（不让浏览器拿自己的时钟去减）。在跑的在前，结束的按结束时间倒序。"""
    now = time.time()
    since = now - FILM_RECENT_SEC
    home = novels.novels_dir(uid)
    roots = {p for p in _render_runner.watching() if home in p.parents}
    for f in home.glob("*/chapters/*/render/*/session.json"):
        try:
            if f.stat().st_mtime >= since:
                roots.add(f.parent)
        except OSError:
            continue
    out = []
    for root in sorted(roots):
        s = render_session.load(root)
        o = (s or {}).get("owner") or {}
        if s is None or o.get("user_id") != uid:
            continue
        try:
            typical = render_video_base.typical_sec(render_providers.get_video(s["provider"]))
        except (KeyError, render_video_base.ProviderError):
            typical = list(render_video_base.DEFAULT_TYPICAL_SEC)
        title, chapter = novels.titles(uid, o.get("nid"), o.get("cid"))
        for c in render_session.items(s):
            row = {"id": f'{o.get("vid")}:{c["id"]}', "item_id": c["id"],
                   "kind": "free" if render_session.is_free(c["id"]) else "clip",
                   "novel_id": o.get("nid"), "chapter_id": o.get("cid"), "version_id": o.get("vid"),
                   "work_title": title, "chapter": chapter, "typical_sec": typical,
                   "ended_at": None, "elapsed_sec": None, "cost_cny": None}
            queued, ended = _iso_ts(c.get("queued_at")), _iso_ts(c.get("ended_at"))
            if c["state"] in render_session.IN_FLIGHT:
                out.append({**row, "state": c["state"],
                            "elapsed_sec": max(0, round(now - queued)) if queued else None})
            elif ended is not None and ended >= since and c.get("ended_as"):
                out.append({**row, "state": c["ended_as"], "ended_at": c["ended_at"],
                            "elapsed_sec": max(0, round(ended - queued)) if queued else None})
            for a in c.get("attempts") or []:
                settled = _iso_ts(a.get("settled_at"))
                if (a.get("late") and not a.get("free_id") and a.get("state") == "succeeded"
                        and settled is not None and settled >= since):
                    out.append({**row, "id": f'{row["id"]}:{a["task_id"]}', "state": "late",
                                "ended_at": a["settled_at"], "cost_cny": a.get("cost_cny")})
    live = [t for t in out if t["ended_at"] is None]
    past = sorted((t for t in out if t["ended_at"] is not None), key=lambda t: t["ended_at"], reverse=True)
    return live + past


@app.get("/render/tasks")
def render_tasks(user: dict = Depends(novel_user)):
    """本人的出片任务（任务铃铛与动态面板用）。每项：id、item_id、kind（clip / free）、novel_id、chapter_id、
    version_id、work_title、chapter、state（queued / running / downloading / done / failed / cancelled / late）、
    elapsed_sec、typical_sec、ended_at、cost_cny（只有 late 有）。"""
    return {"tasks": _film_tasks(user["id"])}


# ---------- 配音与合成：音色存在 session.json 的 voices，成片在 final/ ----------
```

- [ ] **Step 5: 新函数进文案扫描名单**

在 `backend/tests/server/test_i18n_scan.py` 里找到：

```python
                      "render_free_patch", "render_free_delete", "render_free_run", "render_free_chosen",
```

换成：

```python
                      "render_free_patch", "render_free_delete", "render_free_run", "render_free_chosen",
                      "_film_cancel", "render_clip_cancel", "render_free_cancel", "_film_tasks", "render_tasks",
```

- [ ] **Step 6: 运行，确认通过**

运行：`cd backend && .venv/bin/python tests/server/test_film_tasks.py`
预期：通过，输出含 `7. 自由节点 ✓`、`ALL PASS`

运行：`cd backend && for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t > /dev/null 2>&1 || echo "FAILED $t"; done; echo finished`
预期：通过，输出含 `finished`，不含 `FAILED`

- [ ] **Step 7: 提交**

提交：

```bash
git add backend/server/app.py backend/tests/server/test_i18n_scan.py backend/tests/server/test_film_tasks.py
git commit -m "出片加取消接口与本人任务列表接口：POST …/clips/{id}/cancel、…/free/{id}/cancel（响应带取消结局）；GET /render/tasks 列出本人排队中、生成中、最近结束与取消后才出结果的片段，带服务端算的已等时长与通常时长，不带厂商与档位；补接口测试"
```
### Task 6: 前端基础——类型、接口函数、文案、等待与取消的纯计算

界面要用到的中英文案在这一步一次加齐，后面的任务只引用、不再改语言包。所有新文案里只说「服务商」，不出现任何厂商或模型的名字（测试里有一条专门扫）。

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/i18n/zh.ts`
- Modify: `frontend/src/i18n/en.ts`
- Modify: `frontend/src/film.ts`
- Test: `frontend/tests/film-lane.test.ts`

- [ ] **Step 1: 写失败的测试**

在 `frontend/tests/film-lane.test.ts` 里找到：

```ts
import {
  anyInFlight, batchSummary, chosenAttempt, clipOffset, clipSpans, copyIndex, firstFrameText, laneKind, laneText,
  laneTitle, mainAction, needsConfirm, pollDelay, POLL_FAST_MS, POLL_SLOW_MS, precheck, slotsNeeded, spanAt,
  tailSources,
} from '../src/film'
```

换成：

```ts
import {
  anyInFlight, batchSummary, cancelKind, chosenAttempt, clipOffset, clipSpans, copyIndex, firstFrameText, fmtWait,
  laneKind, laneText, laneTitle, mainAction, needsConfirm, playableAttempt, pollDelay, POLL_FAST_MS, POLL_SLOW_MS,
  precheck, slotsNeeded, spanAt, tailSources, waitedSec, waitLine,
} from '../src/film'
import { setCurrentLocale } from '../src/i18n/core'
import { en } from '../src/i18n/en'
import { zh } from '../src/i18n/zh'
```

在 `frontend/tests/film-lane.test.ts` 里找到：

```ts
  console.log('6. 自由节点 ✓')
}
```

换成：

```ts
  console.log('6. 自由节点 ✓')
}

// 7. 等待与取消：已等时长、通常区间（分钟：下限向下、上限向上取整）、超过上限换说法；能不能取消；播哪一次
{
  must(fmtWait(245.9) === '4 分 05 秒' && fmtWait(0) === '0 分 00 秒' && fmtWait(-3) === '0 分 00 秒', '已等时长')
  must(waitLine(245, [180, 420]) === '已等 4 分 05 秒 · 通常 3–7 分钟', `等待一行：${waitLine(245, [180, 420])}`)
  must(waitLine(30, [100, 130]) === '已等 0 分 30 秒 · 通常 1–3 分钟', '下限向下、上限向上取整到分钟')
  must(waitLine(421, [180, 420]) === '已等 7 分 01 秒 · 比通常久，仍在处理', '超过上限换说法')
  must(waitLine(10, null) === '已等 0 分 10 秒' && waitLine(10) === '已等 0 分 10 秒', '没有通常区间只说已等')
  must(waitedSec({ queued_at: new Date(1000).toISOString() }, 6000) === 5 && waitedSec({}, 6000) === 0, '从排队那一刻算')
  setCurrentLocale('en')
  must(waitLine(245, [180, 420]) === 'Waited 4m 05s · usually 3–7 min', `英文等待一行：${waitLine(245, [180, 420])}`)
  must(waitLine(421, [180, 420]) === 'Waited 7m 01s · longer than usual, still working', '英文超过上限')
  setCurrentLocale('zh')

  const sub = { ...ok, state: 'submitting' as const, task_id: null, file: null }
  const run = { ...ok, state: 'running' as const, file: null }
  must(cancelKind(clip('C1', [], { state: 'queued' })) === 'free', '还没提交：取消不花钱')
  must(cancelKind(clip('C1', [], { state: 'queued', attempts: [sub] })) === null, '正在提交：先不给取消')
  must(cancelKind(clip('C1', [], { state: 'running', attempts: [run] })) === 'paid', '已提交：可能仍扣费')
  must(cancelKind(clip('C1', [], { state: 'downloading', attempts: [run] })) === null
       && cancelKind(clip('C1', [], { state: 'done', attempts: [ok], chosen: 0 })) === null
       && cancelKind(clip('C1', [])) === null, '在取回、已结束、没出过：不能取消')

  const late = { ...ok, task_id: 't2', file: 'clips/x.t2.mp4', late: true }
  const bad = { ...ok, task_id: 't3', state: 'failed' as const, file: null }
  must(playableAttempt(clip('C1', [], { attempts: [ok, late], chosen: 0 }))?.index === 0, '默认播采用的那次')
  must(playableAttempt(clip('C1', [], { attempts: [ok, late], chosen: 0 }), 1)?.index === 1, '点名播哪次就播哪次')
  must(playableAttempt(clip('C1', [], { attempts: [bad, late], chosen: null }))?.index === 1, '没有采用：播最近成功的一次')
  must(playableAttempt(clip('C1', [], { attempts: [bad] })) === null
       && playableAttempt(clip('C1', [], { attempts: [ok], chosen: 0 }), 5) === null, '没有可播的')

  // 等待、取消、播放、任务列表、通知的文案：两种语言都不出现厂商或模型的名字
  const vendor = /minimax|seedance|hailuo|ark\b|方舟|海螺|豆包|火山/i
  const flat = (node: unknown): string[] =>
    (typeof node === 'string' ? [node] : Object.values(node as Record<string, unknown>).flatMap(flat))
  for (const pack of [zh, en]) {
    const texts = [pack.film.wait, pack.film.waitOver, pack.film.waitOnly, pack.film.waitMin, pack.film.lateTag,
                   pack.film.lateHint,
                   ...flat(pack.film.cancel), ...flat(pack.film.play), ...flat(pack.activity), ...flat(pack.app.notify),
                   ...flat(pack.enums.attemptState)]
    must(texts.length > 30 && texts.every((x) => !vendor.test(x)), `文案里不出现厂商名：${texts.find((x) => vendor.test(x))}`)
  }
  console.log('7. 等待、取消与播放 ✓')
}
```

- [ ] **Step 2: 运行，确认失败**

运行：`cd frontend && npx vite build --ssr tests/film-lane.test.ts --outDir .ssrout --logLevel error && node .ssrout/film-lane.test.js`
预期：失败

- [ ] **Step 3: 类型**

在 `frontend/src/types.ts` 里找到：

```ts
  state: 'submitting' | 'running' | 'succeeded' | 'failed'
  cost_cny: number
```

换成：

```ts
  /** cancelled：服务商确认已取消（不计费）；abandoned：用户不等了，服务商那边可能还在跑，后台盯到有结果 */
  state: 'submitting' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'abandoned'
  cost_cny: number
```

在 `frontend/src/types.ts` 里找到：

```ts
  /** 自由节点生成后复制进剧本段的那次：来自哪个节点（花费记在节点上，这里为 0） */
  free_id?: string
}
```

换成：

```ts
  /** 自由节点生成后复制进剧本段的那次：来自哪个节点（花费记在节点上，这里为 0） */
  free_id?: string
  /** 用户不等了之后才出结果的那次：已计费、可采用，不会自动采用 */
  late?: boolean
  cancelled_at?: string
}
```

在 `frontend/src/types.ts` 里找到：

```ts
  state: FilmClipState
  queued_at?: string
  /** 风格图：used 已带上 / full 参考位已满 / first_frame 本段用首帧 / null 没有风格图 */
```

换成：

```ts
  state: FilmClipState
  queued_at?: string
  /** 最近一次结束的时间与结局（任务列表用） */
  ended_at?: string
  ended_as?: 'done' | 'failed' | 'cancelled'
  /** 风格图：used 已带上 / full 参考位已满 / first_frame 本段用首帧 / null 没有风格图 */
```

在 `frontend/src/types.ts` 里找到：

```ts
  created_at: string
  queued_at?: string
  /** 参考位超出当前厂商上限：删减之前不能生成 */
```

换成：

```ts
  created_at: string
  queued_at?: string
  ended_at?: string
  ended_as?: 'done' | 'failed' | 'cancelled'
  /** 参考位超出当前厂商上限：删减之前不能生成 */
```

在 `frontend/src/types.ts` 里找到：

```ts
    /** 费率说明：消息对象（按界面语言渲染）；旧数据是字符串 */
    rate_note: MsgLike
```

换成：

```ts
    /** 费率说明：消息对象（按界面语言渲染）；旧数据是字符串 */
    rate_note: MsgLike
    /** 一段通常要等多久（秒，[下限, 上限]）：只用于显示「通常 x–y 分钟」 */
    typical_sec?: [number, number]
```

在 `frontend/src/types.ts` 里找到：

```ts
export interface FilmSettings {
  provider?: string
```

换成：

```ts
/** 取消接口的结局：dequeued 还没提交 / cancelled 服务商确认取消 / abandoned 不等了（可能仍扣费） */
export type CancelOutcome = 'dequeued' | 'cancelled' | 'abandoned'

/** 本人的一条出片任务（GET /render/tasks）：在跑的，或最近结束的。不带厂商与档位 */
export interface FilmTask {
  /** <版本>:<段或节点 id>；late 的再加 :<任务 id> */
  id: string
  item_id: string
  kind: 'clip' | 'free'
  novel_id: string
  chapter_id: string
  version_id: string
  work_title: string | null
  chapter: string | null
  /** late：取消后服务商仍生成完成（已计费，可采用） */
  state: 'queued' | 'running' | 'downloading' | 'done' | 'failed' | 'cancelled' | 'late'
  /** 服务端算的已等秒数（结束的为总共等了多久）；late 没有 */
  elapsed_sec: number | null
  typical_sec: [number, number]
  /** 在跑的为 null */
  ended_at: string | null
  /** 只有 late 有 */
  cost_cny: number | null
}

export interface FilmSettings {
  provider?: string
```

在 `frontend/src/types.ts` 里找到：

```ts
  /** 可按新风格图重出的段数 */
  style_outdated_count?: number
```

换成：

```ts
  /** 可按新风格图重出的段数 */
  style_outdated_count?: number
  /** 只有取消接口的响应带 */
  cancel_outcome?: CancelOutcome
```

- [ ] **Step 4: 接口函数**

在 `frontend/src/api.ts` 里找到：

```ts
/** 取会话目录下的文件（片段视频、尾帧）。<video>/<image> 带不了 token，转成 blob URL（用完要 revoke） */
```

换成：

```ts
/** 取消排队或生成中的一段 / 一个自由节点；响应带 cancel_outcome。不在跑、正在提交、已在取回 → 409 */
export function cancelFilmItem(nid: string, cid: string, vid: string, itemId: string,
                               free: boolean): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/${free ? 'free' : 'clips'}/${enc(itemId)}/cancel`, { method: 'POST' })
}

/** 本人的出片任务：在跑的与最近结束的（任务铃铛与动态面板用） */
export function listFilmTasks(): Promise<{ tasks: FilmTask[] }> {
  return req<{ tasks: FilmTask[] }>('/render/tasks')
}

/** 取会话目录下的文件（片段视频、尾帧）。<video>/<image> 带不了 token，转成 blob URL（用完要 revoke） */
```

在 `frontend/src/api.ts` 里找到：

```ts
  FilmSession, FilmSettings, FreePatch, StyleImageMeta, ComposePreview, VoicesInfo,
```

换成：

```ts
  FilmSession, FilmSettings, FilmTask, FreePatch, StyleImageMeta, ComposePreview, VoicesInfo,
```

- [ ] **Step 5: 中文文案**

在 `frontend/src/i18n/zh.ts` 里找到：

```ts
  activity: {
    tab: '任务', close: '关闭', running: '在跑', done: '最近完成', view: '查看',
    empty: '没有在跑的任务', emptyHint: '开始转换或出片后，进度会出现在这里',
  },
```

换成：

```ts
  activity: {
    tab: '任务', close: '关闭', running: '在跑', done: '最近完成', view: '查看',
    empty: '没有在跑的任务', emptyHint: '开始转换或出片后，进度会出现在这里',
    film: {
      play: '播放',
      late: '服务商已计费 {cost}，可在片段里采用',
      state: {
        queued: '排队中', running: '生成中', downloading: '取回中', done: '已生成', failed: '生成失败',
        cancelled: '已取消', late: '取消后仍生成完成',
      },
    },
  },
```

在 `frontend/src/i18n/zh.ts` 里找到：

```ts
      doneBody: '{who} 已生成，点开即可审阅',
```

换成：

```ts
      doneBody: '{who} 已生成，点开即可审阅',
      filmDone: '片段已生成',
      filmDoneBody: '{who} 已生成，点开播放',
      filmFailed: '片段生成失败',
      filmFailedBody: '{who}——点开查看原因',
      filmLate: '已取消的片段仍生成完成',
      filmLateBody: '{who}：服务商已计费 {cost}，结果可以采用',
```

在 `frontend/src/i18n/zh.ts` 里找到：

```ts
    attemptState: { submitting: '提交中', running: '生成中', succeeded: '成功', failed: '失败' },
```

换成：

```ts
    attemptState: {
      submitting: '提交中', running: '生成中', succeeded: '成功', failed: '失败',
      cancelled: '已取消', abandoned: '已取消 · 等服务商结束',
    },
```

在 `frontend/src/i18n/zh.ts` 里找到：

```ts
    readClipFailed: '读取片段文件失败：{error}',
```

换成：

```ts
    readClipFailed: '读取片段文件失败：{error}',
    wait: '已等 {wait} · 通常 {lo}–{hi} 分钟',
    waitOver: '已等 {wait} · 比通常久，仍在处理',
    waitOnly: '已等 {wait}',
    waitMin: '{m} 分 {s} 秒',
    lateTag: '取消后才出的结果',
    lateHint: '有取消后才出的结果，可以切换采用',
    cancel: {
      free: '取消',
      paid: '不等了',
      freeTitle: '取消 {id}？',
      freeBody: '还没有提交给生成服务，现在取消不花钱。',
      freeAction: '取消生成',
      paidTitle: '不等 {id} 了？',
      paidBody: '这一段已经提交给生成服务。我们会先尝试取消；取消不了的话，服务商可能仍会生成并扣费——结果会留在这一段的尝试记录里，之后还可以采用。',
      paidAction: '不等了',
      dequeued: '已取消，没有花钱',
      cancelled: '已取消，服务商没有扣费',
      abandoned: '已停止等待。服务商如果仍然生成完成会照常扣费，结果会留在尝试记录里',
    },
    play: {
      open: '播放',
      aria: '播放 {id}',
      title: '{id} · 第 {n} 次',
      loading: '读取视频…',
      none: '这一段还没有可播放的结果',
      desc: '带声音与进度条的播放窗口',
    },
```

- [ ] **Step 6: 英文文案**

在 `frontend/src/i18n/en.ts` 里找到：

```ts
  activity: {
    tab: 'Jobs', close: 'Close', running: 'Running', done: 'Recently finished', view: 'View',
    empty: 'No running jobs', emptyHint: 'Progress shows up here once a conversion or render starts',
  },
```

换成：

```ts
  activity: {
    tab: 'Jobs', close: 'Close', running: 'Running', done: 'Recently finished', view: 'View',
    empty: 'No running jobs', emptyHint: 'Progress shows up here once a conversion or render starts',
    film: {
      play: 'Play',
      late: 'The provider charged {cost}; you can adopt it on the clip',
      state: {
        queued: 'Queued', running: 'Generating', downloading: 'Fetching', done: 'Generated', failed: 'Failed',
        cancelled: 'Cancelled', late: 'Finished after cancelling',
      },
    },
  },
```

在 `frontend/src/i18n/en.ts` 里找到：

```ts
      doneBody: '{who} is ready. Open it to review.',
```

换成：

```ts
      doneBody: '{who} is ready. Open it to review.',
      filmDone: 'Clip generated',
      filmDoneBody: '{who} is ready. Open it to play.',
      filmFailed: 'Clip generation failed',
      filmFailedBody: '{who} — open it to see why',
      filmLate: 'A cancelled clip finished anyway',
      filmLateBody: '{who}: the provider charged {cost}; the result can be adopted',
```

在 `frontend/src/i18n/en.ts` 里找到：

```ts
    attemptState: { submitting: 'Submitting', running: 'Generating', succeeded: 'Succeeded', failed: 'Failed' },
```

换成：

```ts
    attemptState: {
      submitting: 'Submitting', running: 'Generating', succeeded: 'Succeeded', failed: 'Failed',
      cancelled: 'Cancelled', abandoned: 'Cancelled · waiting for the provider',
    },
```

在 `frontend/src/i18n/en.ts` 里找到：

```ts
    readClipFailed: 'Could not read the clip file: {error}',
```

换成：

```ts
    readClipFailed: 'Could not read the clip file: {error}',
    wait: 'Waited {wait} · usually {lo}–{hi} min',
    waitOver: 'Waited {wait} · longer than usual, still working',
    waitOnly: 'Waited {wait}',
    waitMin: '{m}m {s}s',
    lateTag: 'Finished after cancelling',
    lateHint: 'A result arrived after cancelling; switch takes to adopt it',
    cancel: {
      free: 'Cancel',
      paid: 'Stop waiting',
      freeTitle: 'Cancel {id}?',
      freeBody: 'It has not been sent to the generation service yet, so cancelling now costs nothing.',
      freeAction: 'Cancel generation',
      paidTitle: 'Stop waiting for {id}?',
      paidBody: 'This clip has already been sent to the generation service. We will try to cancel it first; if that is not possible, the provider may still generate it and charge for it — the result will stay in this clip\'s attempts and can be adopted later.',
      paidAction: 'Stop waiting',
      dequeued: 'Cancelled; nothing was spent',
      cancelled: 'Cancelled; the provider did not charge',
      abandoned: 'Stopped waiting. If the provider still finishes it you will be charged as usual, and the result will stay in the attempts',
    },
    play: {
      open: 'Play',
      aria: 'Play {id}',
      title: '{id} · take {n}',
      loading: 'Loading video…',
      none: 'This clip has no playable result yet',
      desc: 'Player with sound and a progress bar',
    },
```

- [ ] **Step 7: 纯计算**

在 `frontend/src/film.ts` 里找到：

```ts
export type LaneKind = 'planned' | 'busy' | 'done' | 'failed' | 'stale'
```

换成：

```ts
/** 要播的那一次：点名第几次就播它；否则播采用的那次；没有采用就播最近成功的一次。没有可播的为 null */
export function playableAttempt(c: { chosen: number | null; attempts: FilmAttempt[] },
                                index?: number): { attempt: FilmAttempt; index: number } | null {
  const playable = (i: number | null | undefined) => {
    const a = i == null ? undefined : c.attempts[i]
    return a && a.state === 'succeeded' && a.file ? { attempt: a, index: i as number } : null
  }
  if (index !== undefined) return playable(index)
  const picked = playable(c.chosen)
  if (picked) return picked
  for (let i = c.attempts.length - 1; i >= 0; i--) {
    const hit = playable(i)
    if (hit) return hit
  }
  return null
}

/** 已等时长：「4 分 05 秒」 */
export function fmtWait(sec: number): string {
  const n = Math.max(0, Math.floor(sec))
  return tr('film.waitMin', { m: Math.floor(n / 60), s: String(n % 60).padStart(2, '0') })
}

/** 生成中那一行：已等多久 + 通常要多久（分钟：下限向下、上限向上取整）；超过上限换说法。只有时间，不带厂商或模型名 */
export function waitLine(sec: number, typical?: number[] | null): string {
  const wait = fmtWait(sec)
  if (!typical || typical.length < 2) return tr('film.waitOnly', { wait })
  const [lo, hi] = typical
  if (sec > hi) return tr('film.waitOver', { wait })
  return tr('film.wait', { wait, lo: Math.max(1, Math.floor(lo / 60)), hi: Math.max(1, Math.ceil(hi / 60)) })
}

/** 已等秒数：从排队那一刻算；now 为毫秒时间戳 */
export const waitedSec = (c: { queued_at?: string }, now: number) =>
  (c.queued_at ? Math.max(0, (now - Date.parse(c.queued_at)) / 1000) : 0)

/** 能不能取消：free 还没提交（不花钱）；paid 已提交（服务商可能仍扣费）；null 不能（不在跑、正在提交、已在取回） */
export function cancelKind(c: { state: FilmClipState; attempts: FilmAttempt[] }): 'free' | 'paid' | null {
  const last = c.attempts[c.attempts.length - 1]
  if (c.state === 'queued') return last?.state === 'submitting' ? null : 'free'
  if (c.state === 'running') return last?.task_id ? 'paid' : null
  return null
}

export type LaneKind = 'planned' | 'busy' | 'done' | 'failed' | 'stale'
```

- [ ] **Step 8: 运行，确认通过**

运行：`cd frontend && npx vite build --ssr tests/film-lane.test.ts --outDir .ssrout --logLevel error && node .ssrout/film-lane.test.js`
预期：通过，输出含 `7. 等待、取消与播放 ✓`、`ALL PASS`

运行：`cd frontend && npm run typecheck`
预期：通过

- [ ] **Step 9: 提交**

提交：

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/src/film.ts frontend/tests/film-lane.test.ts
git commit -m "出片前端基础：尝试加已取消与不等了两种状态、任务列表与取消结局的类型；取消与任务列表的接口函数；等待、取消、播放、任务列表、通知的中英文案（只说服务商，不带厂商名）；已等时长、通常区间、能否取消、播哪一次的纯计算；补测试"
```
### Task 7: 画布——生成中的等待与取消、出完后的播放

节点图的片段卡与自由节点卡：在跑时显示「已等 m 分 s 秒 · 通常 x–y 分钟」和取消入口；出完后封面上有明显的「播放」按钮，点开是带声音与控制条的播放窗口。侧栏「出片」页的选中段详情同样有等待一行、取消与「播放」。取消一律先过确认框（`useConfirm`），已提交的那种在确认框里写明服务商可能仍会扣费。

**Files:**
- Modify: `frontend/src/useFilm.ts`
- Create: `frontend/src/components/ClipPlayer.tsx`
- Modify: `frontend/src/components/NodeCards.tsx`
- Modify: `frontend/src/components/NodeGraph.tsx`
- Modify: `frontend/src/components/FilmPanel.tsx`
- Modify: `frontend/src/components/TimelineCanvas.tsx`
- Modify: `frontend/src/styles/nodegraph.css`
- Modify: `frontend/src/styles/film.css`
- Test: `frontend/tests/graph-view.test.tsx`

- [ ] **Step 1: 写失败的测试**

先给桩后端加取消接口、给会话加通常时长，再追加用例。

在 `frontend/tests/graph-view.test.tsx` 里找到：

```ts
                 'localStorage', 'sessionStorage', 'PointerEvent', 'MouseEvent', 'matchMedia', 'ResizeObserver', 'DOMRect',
                 'MutationObserver']) {
```

换成（播放窗口是 Radix 的 Dialog，聚焦时要用到 `NodeFilter`）：

```ts
                 'localStorage', 'sessionStorage', 'PointerEvent', 'MouseEvent', 'matchMedia', 'ResizeObserver', 'DOMRect',
                 'MutationObserver', 'NodeFilter']) {
```

在 `frontend/tests/graph-view.test.tsx` 里找到：

```ts
    Object.assign(n, { state: 'queued', queued_at: new Date().toISOString() })
    film = recount(film!)
    return ok(film)
  }
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}
```

换成：

```ts
    Object.assign(n, { state: 'queued', queued_at: new Date().toISOString() })
    film = recount(film!)
    return ok(film)
  }
  m = sub.match(/^\/(clips|free)\/([^/]+)\/cancel$/)
  if (m && method === 'POST') {
    const it = m[1] === 'free' ? freeOf(m[2]) : clipOf(decodeURIComponent(m[2]))
    const outcome = it.state === 'queued' ? 'dequeued' : 'abandoned'
    if (outcome === 'abandoned') it.attempts[it.attempts.length - 1].state = 'abandoned'
    it.state = it.chosen === null ? 'planned' : 'done'
    film = recount(film!)
    return ok({ ...film, cancel_outcome: outcome })
  }
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}
```

在 `frontend/tests/graph-view.test.tsx` 里找到：

```ts
               frame_with_refs: false, audio_modes: ['tts_all', 'dialogue_native', 'all_native', 'silent'],
               rate_note: '假厂商：不联网、不花钱' },
```

换成：

```ts
               frame_with_refs: false, audio_modes: ['tts_all', 'dialogue_native', 'all_native', 'silent'],
               rate_note: '假厂商：不联网、不花钱', typical_sec: [180, 420] },
```

在 `frontend/tests/graph-view.test.tsx` 里找到：

```ts
// 7. 切回时间轴：节点图收起
```

换成：

```ts
// 6d. 在跑的卡片：已等多久 · 通常多久，不带厂商名；还没提交的取消先确认、不花钱
{
  const third = film!.clips[2].id
  const waitText = () => card(third).querySelector('[data-testid="ngv-wait"]')?.textContent ?? ''
  const dialogText = () => win.document.body.querySelector('[data-testid="confirm-dialog"]')?.textContent ?? ''
  const answer = (ok: boolean) =>
    click(win.document.body.querySelector(`[data-testid="${ok ? 'confirm-ok' : 'confirm-cancel'}"]`)!)
  const cancelCalls = () => calls.filter((c) => c === `POST /clips/${third}/cancel`).length
  Object.assign(clipOf(third), { state: 'queued', queued_at: new Date(Date.now() - 65000).toISOString() })
  film = recount(film!)
  await refresh()
  must(/已等 1 分 0\d 秒 · 通常 3–7 分钟/.test(waitText()), `等待一行：${waitText()}`)
  must(!/minimax|seedance|fake|假厂商/i.test(card(third).textContent ?? ''), '卡片上不出现厂商名')
  await click(inCard(third, '取消'))
  must(dialogText().includes(`取消 ${third}？`) && dialogText().includes('现在取消不花钱') && cancelCalls() === 0,
       `还没提交：先确认，说明不花钱：${dialogText()}`)
  await answer(true)
  must(cancelCalls() === 1 && clipOf(third).state === 'planned', '确认后取消')
  must(!card(third).querySelector('[data-testid="ngv-wait"]'), '取消后不再显示等待')

  // 已提交、等得比通常久：换说法；「不等了」的确认框写明可能仍扣费；点「取消」不发请求，确认才发
  Object.assign(clipOf(third), { state: 'running', queued_at: new Date(Date.now() - 500000).toISOString(),
    attempts: [{ ...attempt(third, 1, 0), state: 'running', file: null, last_frame: null }] })
  film = recount(film!)
  await refresh()
  must(waitText().includes('比通常久，仍在处理'), `超过通常上限：${waitText()}`)
  await click(inCard(third, '不等了'))
  must(dialogText().includes('服务商可能仍会生成并扣费'), `已提交：确认框写明可能仍扣费：${dialogText()}`)
  await answer(false)
  must(cancelCalls() === 1 && clipOf(third).state === 'running', '确认框里点取消：不发请求')
  await click(inCard(third, '不等了'))
  await answer(true)
  must(cancelCalls() === 2 && clipOf(third).attempts[0].state === 'abandoned', '确认后不等了')
  const { notice } = await import('../src/lib/notice')
  must(notice.log.some((x) => x.msg.includes('已取消，没有花钱'))
       && notice.log.some((x) => x.msg.includes('已停止等待')), '两种结局各有提示')
  console.log('6d. 等待与取消 ✓')
}

// 6e. 出完的卡片有明显的播放按钮：点开是带控制条、不静音的播放窗口；侧栏选中段也能点开
{
  const player = () => win.document.body.querySelector('[data-testid="clip-player"]')
  const closePlayer = async () => {
    await click(win.document.body.querySelector('[data-testid="clip-player"] [data-slot="dialog-close"]')!)
    await settle(300)
  }
  const playBtn = card(first).querySelector('[data-testid="ngv-play"]')
  must(!!playBtn && (playBtn.textContent ?? '').includes('播放'), '出完的卡片有播放按钮')
  must(!card(film!.clips[2].id).querySelector('[data-testid="ngv-play"]'), '没有结果的卡片没有播放按钮')
  await click(playBtn!)
  const video = player()?.querySelector('video')
  must(!!video && video.hasAttribute('controls') && !video.hasAttribute('muted') && !video.hasAttribute('loop'),
       '播放窗口：有控制条、不静音、不循环')
  must((player()?.textContent ?? '').includes(`${first} · 第 ${clipOf(first).chosen! + 1} 次`), '标题写明哪一段第几次')
  await closePlayer()
  must(!player(), '关掉播放窗口')
  await click(card(first))
  const side = container.querySelector('[data-testid="clip-play"]')
  must(!!side, '侧栏选中段有播放按钮')
  await click(side!)
  must(!!player()?.querySelector('video[controls]'), '侧栏也能点开播放窗口')
  await closePlayer()
  console.log('6e. 播放 ✓')
}

// 7. 切回时间轴：节点图收起
```

- [ ] **Step 2: 运行，确认失败**

运行：`cd frontend && npx vite build --ssr tests/graph-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/graph-view.test.js`
预期：失败，输出含 `等待一行`

- [ ] **Step 3: useFilm 加取消；花钱的操作顺手申请通知权限**

在 `frontend/src/useFilm.ts` 里找到：

```ts
import {
  ApiError, chooseFilmAttempt, chooseFreeAttempt, conflictCny, createFilm, createFreeNode, deleteFreeNode,
  filmFileUrl, getFilm, muteFilmClip, patchFilm, patchFreeNode, runFilmClip, runFilmRest, runFreeNode,
} from './api'
```

换成：

```ts
import {
  ApiError, cancelFilmItem, chooseFilmAttempt, chooseFreeAttempt, conflictCny, createFilm, createFreeNode,
  deleteFreeNode, filmFileUrl, getFilm, muteFilmClip, patchFilm, patchFreeNode, runFilmClip, runFilmRest, runFreeNode,
} from './api'
import { primeNotifications } from './notify'
```

在 `frontend/src/useFilm.ts` 里找到：

```ts
import type { FilmClip, FilmSession, FilmSettings, FreePatch, VersionRef } from './types'
```

换成：

```ts
import type { CancelOutcome, FilmClip, FilmSession, FilmSettings, FreePatch, VersionRef } from './types'
```

在 `frontend/src/useFilm.ts` 里找到：

```ts
    const mine = gen.current
    setBusy(true)
    setError(null)
    try {
      const got = await fn()
      if (gen.current !== mine) return { kind: 'stale' }
```

换成：

```ts
    const mine = gen.current
    primeNotifications()     // 出片要等几分钟：趁这次点击申请通知权限，出完好提醒
    setBusy(true)
    setError(null)
    try {
      const got = await fn()
      if (gen.current !== mine) return { kind: 'stale' }
```

在 `frontend/src/useFilm.ts` 里找到：

```ts
  /** 花钱的操作（确认框）：409 带了重算金额就放回确认框，等用户再确认 */
```

换成：

```ts
  /** 取消排队或生成中的一段 / 一个自由节点：成功返回结局（调用方据此提示）；被拒（409 等）记到 error 并重读会话 */
  const cancelItem = useCallback(async (itemId: string, free: boolean): Promise<CancelOutcome | null> => {
    const mine = gen.current
    setBusy(true)
    setError(null)
    try {
      const got = await cancelFilmItem(nid!, cid!, vid!, itemId, free)
      if (gen.current !== mine) return null
      accept(got)
      return got.cancel_outcome ?? null
    } catch (e) {
      if (gen.current !== mine) return null
      fail(e)
      void load()
      return null
    } finally {
      if (gen.current === mine) setBusy(false)
    }
  }, [nid, cid, vid, accept, fail, load])

  /** 花钱的操作（确认框）：409 带了重算金额就放回确认框，等用户再确认 */
```

在 `frontend/src/useFilm.ts` 里找到：

```ts
    mute: (clipId: string, mute: boolean) => apply(() => muteFilmClip(nid!, cid!, vid!, clipId, mute)),
```

换成：

```ts
    mute: (clipId: string, mute: boolean) => apply(() => muteFilmClip(nid!, cid!, vid!, clipId, mute)),
    cancelItem,
```

- [ ] **Step 4: 播放窗口**

新建 `frontend/src/components/ClipPlayer.tsx`：

```tsx
/** 片段播放窗口：带声音与控制条（节点图卡片、出片页的选中段、完成通知都从这里播）。
 *  文件走 useFilm 的同一套 blob 缓存（ensure / files），和卡片封面、侧栏里的小播放器取的是同一份。
 *  target 为 null 时关着；attempt 不给就播采用的那次，没有采用播最近成功的一次。 */
import { useEffect } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useI18n } from '@/i18n/core'
import { freeNodes, playableAttempt } from '../film'
import type { Film } from '../useFilm'

export interface PlayTarget { id: string; attempt?: number }

export function ClipPlayer({ film, target, onClose }: {
  film: Film; target: PlayTarget | null; onClose: () => void
}) {
  const { t } = useI18n()
  const s = film.session
  const item = target && s ? [...s.clips, ...freeNodes(s)].find((x) => x.id === target.id) : undefined
  const hit = item ? playableAttempt(item, target?.attempt) : null
  const file = hit?.attempt.file ?? null
  const { ensure } = film
  useEffect(() => { ensure(file) }, [file, ensure])
  const url = file ? film.files[file] : undefined
  return (
    <Dialog open={!!target} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-3xl" data-testid="clip-player">
        <DialogHeader>
          <DialogTitle>
            {target && hit ? t('film.play.title', { id: target.id, n: hit.index + 1 }) : target?.id ?? ''}
            {hit?.attempt.late && <span className="ml-2 text-xs font-normal text-muted-foreground">{t('film.lateTag')}</span>}
          </DialogTitle>
          <DialogDescription className="sr-only">{t('film.play.desc')}</DialogDescription>
        </DialogHeader>
        {url
          ? <video className="film__video film__video--big" src={url} controls autoPlay playsInline />
          : <p className="tlc__kfnote">{t(!s || !item || file ? 'film.play.loading' : 'film.play.none')}</p>}
      </DialogContent>
    </Dialog>
  )
}
```

在 `frontend/src/styles/film.css` 里找到：

```css
.film__video { width: 100%; max-height: 40vh; background: #000; border-radius: 12px; }
```

换成：

```css
.film__video { width: 100%; max-height: 40vh; background: #000; border-radius: 12px; }
.film__video--big { max-height: 70vh; }
.film__play { align-self: flex-start; }
```

- [ ] **Step 5: 卡片——等待一行、取消入口、播放按钮**

在 `frontend/src/components/NodeCards.tsx` 里找到：

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
```

换成：

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
```

在 `frontend/src/components/NodeCards.tsx` 里找到：

```tsx
import { chosenAttempt, copyIndex, inFlight, laneText, needsConfirm, slotsNeeded, tailSources } from '../film'
```

换成：

```tsx
import {
  cancelKind, chosenAttempt, copyIndex, inFlight, needsConfirm, slotsNeeded, tailSources, waitedSec, waitLine,
} from '../film'
```

在 `frontend/src/components/NodeCards.tsx` 里找到：

```tsx
/** 结果区：悬停或选中时播采用的那次（静音循环），平时显示它的尾帧；没有结果时显示首帧来源图 */
function Preview({ film, attempt, fallback, hot }: {
  film: Film; attempt: FilmAttempt | null; fallback: string | null; hot: boolean
}) {
  const { t } = useI18n()
  const { ensure, files } = film
  const poster = attempt?.last_frame ?? null
  const file = attempt?.file ?? null
  useEffect(() => { ensure(poster) }, [poster, ensure])
  useEffect(() => { if (hot) ensure(file) }, [hot, file, ensure])
  const video = hot && file ? files[file] : undefined
  const still = (poster && files[poster]) || fallback
  if (video) return <video className="ngv__media" src={video} autoPlay muted loop playsInline />
  if (still) return <img className="ngv__media" src={still} alt="" />
  return <div className="ngv__media ngv__media--empty">{t('graph.noResult')}</div>
}
```

换成：

```tsx
/** 结果区：悬停或选中时播采用的那次（静音循环），平时显示它的尾帧；没有结果时显示首帧来源图。
 *  有结果且给了 onPlay 时，封面正中是「播放」按钮：点开带声音与控制条的播放窗口 */
function Preview({ film, attempt, fallback, hot, id, onPlay }: {
  film: Film; attempt: FilmAttempt | null; fallback: string | null; hot: boolean
  id: string; onPlay?: () => void
}) {
  const { t } = useI18n()
  const { ensure, files } = film
  const poster = attempt?.last_frame ?? null
  const file = attempt?.file ?? null
  useEffect(() => { ensure(poster) }, [poster, ensure])
  useEffect(() => { if (hot) ensure(file) }, [hot, file, ensure])
  const video = hot && file ? files[file] : undefined
  const still = (poster && files[poster]) || fallback
  const media = video ? <video className="ngv__media" src={video} autoPlay muted loop playsInline />
    : still ? <img className="ngv__media" src={still} alt="" />
    : <div className="ngv__media ngv__media--empty">{t('graph.noResult')}</div>
  if (!file || !onPlay) return media
  return (
    <div className="ngv__stage">
      {media}
      <button type="button" className="ngv__play" data-testid="ngv-play" aria-label={t('film.play.aria', { id })}
              onClick={(e) => { e.stopPropagation(); onPlay() }}>
        <Play aria-hidden />{t('film.play.open')}
      </button>
    </div>
  )
}

/** 在跑的那一行：已等多久 · 通常多久（每秒走一次），右边是取消入口（还没提交写「取消」，已提交写「不等了」）。
 *  只有时间，不带厂商或模型名。确认框由上层弹（onCancel） */
export function WaitRow({ item, typical, disabled, onCancel }: {
  item: { state: FilmClipState; attempts: FilmAttempt[]; queued_at?: string }
  typical?: number[] | null
  disabled: boolean
  onCancel?: () => void
}) {
  const { t } = useI18n()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])
  const kind = cancelKind(item)
  return (
    <p className="ngv__wait" data-testid="ngv-wait" onClick={(e) => e.stopPropagation()}>
      <span>{waitLine(waitedSec(item, now), typical)}</span>
      {kind && onCancel && (
        <button type="button" className="tlc__linkbtn" disabled={disabled} onClick={onCancel}>
          {t(kind === 'free' ? 'film.cancel.free' : 'film.cancel.paid')}
        </button>
      )}
    </p>
  )
}
```

在 `frontend/src/components/NodeCards.tsx` 里找到：

```tsx
export function ClipCard({ clip: c, s, film, blocked, hot, fallback, tags, onDerive }: {
  clip: FilmClip; s: FilmSession; film: Film; blocked: string | null; hot: boolean
  /** 这一段每个镜头的小标签（「SH003 特写·推」），由 NodeGraph 按分镜算好 */
  tags: string[]
  /** 没有结果时显示的首帧来源图（关键帧或上一段尾帧） */
  fallback: string | null
  onDerive: () => void
}) {
```

换成：

```tsx
export function ClipCard({ clip: c, s, film, blocked, hot, fallback, tags, onDerive, onPlay, onCancel }: {
  clip: FilmClip; s: FilmSession; film: Film; blocked: string | null; hot: boolean
  /** 这一段每个镜头的小标签（「SH003 特写·推」），由 NodeGraph 按分镜算好 */
  tags: string[]
  /** 没有结果时显示的首帧来源图（关键帧或上一段尾帧） */
  fallback: string | null
  onDerive: () => void
  /** 点封面上的「播放」；点等待一行里的取消（都由画布接：播放窗口、确认框） */
  onPlay?: () => void
  onCancel?: () => void
}) {
```

在 `frontend/src/components/NodeCards.tsx` 里找到：

```tsx
        <StatusPill tone={TONE[c.state]}>{inFlight(c) ? laneText(c, Date.now()) : label(FILM_STATE, c.state)}</StatusPill>
        {c.uncertain && <StatusPill tone="warn">{t('graph.uncertainTag')}</StatusPill>}
```

换成：

```tsx
        <StatusPill tone={TONE[c.state]}>{label(FILM_STATE, c.state)}</StatusPill>
        {c.uncertain && <StatusPill tone="warn">{t('graph.uncertainTag')}</StatusPill>}
```

在 `frontend/src/components/NodeCards.tsx` 里找到：

```tsx
      <Preview film={film} attempt={chosen} fallback={fallback} hot={hot} />
      {chosen?.free_id && <p className="ngv__dim">{t('graph.fromFree', { id: chosen.free_id })}</p>}
      <p className="ngv__prompt" title={c.prompt}>{c.prompt}</p>
```

换成：

```tsx
      <Preview film={film} attempt={chosen} fallback={fallback} hot={hot} id={c.id} onPlay={onPlay} />
      {inFlight(c) && (
        <WaitRow item={c} typical={s.options.typical_sec} disabled={film.busy} onCancel={onCancel} />
      )}
      {chosen?.free_id && <p className="ngv__dim">{t('graph.fromFree', { id: chosen.free_id })}</p>}
      {c.attempts.some((a, i) => a.late && a.state === 'succeeded' && i !== c.chosen) && (
        <p className="ngv__dim" data-testid="ngv-late">{t('film.lateHint')}</p>
      )}
      <p className="ngv__prompt" title={c.prompt}>{c.prompt}</p>
```

在 `frontend/src/components/NodeCards.tsx` 里找到：

```tsx
        {ok.length > 1 && (
          <AttemptNav at={at} total={ok.length} disabled={lock} onPick={(k) => void film.choose(c.id, ok[k].i)} />
        )}
```

换成：

```tsx
        {(ok.length > 1 || (ok.length === 1 && at < 0)) && (
          <AttemptNav at={at} total={ok.length} disabled={lock} onPick={(k) => void film.choose(c.id, ok[k].i)} />
        )}
```

在 `frontend/src/components/NodeCards.tsx` 里找到：

```tsx
export function FreeCard({ node: n, s, film, blocked, hot, fallback, kfShots, assetOptions }: {
  node: FilmFreeNode; s: FilmSession; film: Film; blocked: string | null; hot: boolean
  fallback: string | null
```

换成：

```tsx
export function FreeCard({ node: n, s, film, blocked, hot, fallback, kfShots, assetOptions, onPlay, onCancel }: {
  node: FilmFreeNode; s: FilmSession; film: Film; blocked: string | null; hot: boolean
  fallback: string | null
  onPlay?: () => void
  onCancel?: () => void
```

在 `frontend/src/components/NodeCards.tsx` 里找到：

```tsx
      <Preview film={film} attempt={chosen} fallback={fallback} hot={hot} />
      <div className="ngv__form" onClick={(e) => e.stopPropagation()}>
```

换成：

```tsx
      <Preview film={film} attempt={chosen} fallback={fallback} hot={hot} id={n.id} onPlay={onPlay} />
      {inFlight(n) && (
        <WaitRow item={n} typical={s.options.typical_sec} disabled={film.busy} onCancel={onCancel} />
      )}
      <div className="ngv__form" onClick={(e) => e.stopPropagation()}>
```

在 `frontend/src/components/NodeCards.tsx` 里找到：

```tsx
        {ok.length > 1 && (
          <AttemptNav at={at} total={ok.length} disabled={lock} onPick={(k) => void film.chooseFree(n.id, ok[k].i)} />
        )}
```

换成：

```tsx
        {(ok.length > 1 || (ok.length === 1 && at < 0)) && (
          <AttemptNav at={at} total={ok.length} disabled={lock} onPick={(k) => void film.chooseFree(n.id, ok[k].i)} />
        )}
```

在 `frontend/src/styles/nodegraph.css` 里找到：

```css
.ngv__media--empty, .ngv__thumb--empty { display: grid; place-items: center; color: var(--ui-muted-foreground); }
```

换成：

```css
.ngv__media--empty, .ngv__thumb--empty { display: grid; place-items: center; color: var(--ui-muted-foreground); }
/* 有结果的封面：正中一个「播放」按钮（点开带声音与控制条的播放窗口） */
.ngv__stage { position: relative; flex: none; }
.ngv__stage .ngv__media { display: block; }
.ngv__play {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 12px; border: 0; border-radius: 999px; background: rgb(0 0 0 / .62); color: #fff; font-size: 12px; font-weight: 600;
  cursor: pointer; transition: background-color .15s ease-out;
}
.ngv__play:hover, .ngv__play:focus-visible { background: rgb(0 0 0 / .82); }
.ngv__play svg { width: 14px; height: 14px; }
/* 在跑的那一行：已等多久 · 通常多久 + 取消 */
.ngv__wait { display: flex; flex: none; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 2px 8px; margin: 0; font-variant-numeric: tabular-nums; }
```

- [ ] **Step 6: 节点图把两个回调传给卡片**

在 `frontend/src/components/NodeGraph.tsx` 里找到：

```tsx
export function NodeGraph({ film, doc, styleUrl, kfUrls, selected, blocked, onSelect, onOpenAssets, onOpenFilm }: {
```

换成：

```tsx
export function NodeGraph({ film, doc, styleUrl, kfUrls, selected, blocked, onSelect, onOpenAssets, onOpenFilm, onPlay, onCancel }: {
```

在 `frontend/src/components/NodeGraph.tsx` 里找到：

```tsx
  onOpenAssets: () => void
  onOpenFilm: () => void
}) {
```

换成：

```tsx
  onOpenAssets: () => void
  onOpenFilm: () => void
  /** 播放某一段 / 自由节点采用的那次；取消它的生成（画布弹播放窗口与确认框） */
  onPlay?: (id: string) => void
  onCancel?: (id: string) => void
}) {
```

在 `frontend/src/components/NodeGraph.tsx` 里找到：

```tsx
                          fallback={frameOf(n.clip.first_frame)} onDerive={() => void film.createFree(n.clip.id)} />
```

换成：

```tsx
                          fallback={frameOf(n.clip.first_frame)} onDerive={() => void film.createFree(n.clip.id)}
                          onPlay={onPlay && (() => onPlay(n.id))} onCancel={onCancel && (() => onCancel(n.id))} />
```

在 `frontend/src/components/NodeGraph.tsx` 里找到：

```tsx
                          fallback={frameOf(n.node.first_frame)} kfShots={kfShots} assetOptions={assetOptions} />
```

换成：

```tsx
                          fallback={frameOf(n.node.first_frame)} kfShots={kfShots} assetOptions={assetOptions}
                          onPlay={onPlay && (() => onPlay(n.id))} onCancel={onCancel && (() => onCancel(n.id))} />
```

- [ ] **Step 7: 侧栏「出片」页的选中段：播放、等待、取消**

在 `frontend/src/components/FilmPanel.tsx` 里找到：

```tsx
import { useEffect, useRef, useState } from 'react'
import { ATTEMPT_STATE, AUDIO_MODE, FILM_STATE, label } from '../labels'
```

换成：

```tsx
import { useEffect, useRef, useState } from 'react'
import { Play } from 'lucide-react'
import { ATTEMPT_STATE, AUDIO_MODE, FILM_STATE, label } from '../labels'
```

在 `frontend/src/components/FilmPanel.tsx` 里找到：

```tsx
import { anyInFlight, batchSummary, firstFrameText, inFlight, mainAction, precheck } from '../film'
import type { Film } from '../useFilm'
import { ComposePanel } from './ComposePanel'
```

换成：

```tsx
import { anyInFlight, batchSummary, firstFrameText, inFlight, mainAction, playableAttempt, precheck } from '../film'
import type { Film } from '../useFilm'
import { ComposePanel } from './ComposePanel'
import { WaitRow } from './NodeCards'
```

在 `frontend/src/components/FilmPanel.tsx` 里找到：

```tsx
  /** 有未保存的改动：出片只认已保存的版本 */
  dirty: boolean
}

export function FilmPanel({ film, selected, onPickShot, dirty }: Props) {
```

换成：

```tsx
  /** 有未保存的改动：出片只认已保存的版本 */
  dirty: boolean
  /** 点「播放」（画布弹播放窗口）；点取消（画布弹确认框） */
  onPlay?: (id: string) => void
  onCancel?: (id: string) => void
}

export function FilmPanel({ film, selected, onPickShot, dirty, onPlay, onCancel }: Props) {
```

在 `frontend/src/components/FilmPanel.tsx` 里找到：

```tsx
            ? <ClipDetail key={clip.id} c={clip} film={film} blocked={blocked} onPickShot={onPickShot} />
```

换成：

```tsx
            ? <ClipDetail key={clip.id} c={clip} s={s} film={film} blocked={blocked} onPickShot={onPickShot}
                          onPlay={onPlay} onCancel={onCancel} />
```

在 `frontend/src/components/FilmPanel.tsx` 里找到：

```tsx
function ClipDetail({ c, film, blocked, onPickShot }: {
  c: FilmClip; film: Film; blocked: string | null; onPickShot: (shotId: string) => void
}) {
```

换成：

```tsx
function ClipDetail({ c, s, film, blocked, onPickShot, onPlay, onCancel }: {
  c: FilmClip; s: FilmSession; film: Film; blocked: string | null; onPickShot: (shotId: string) => void
  onPlay?: (id: string) => void
  onCancel?: (id: string) => void
}) {
```

在 `frontend/src/components/FilmPanel.tsx` 里找到：

```tsx
        <span>{t('film.panel.clipMeta', { state: label(FILM_STATE, c.state), dur: c.duration, cost: yuan(c.estimate_cny) })}{c.truncated ? t('film.panel.clipCut') : ''}</span>
      </header>
```

换成：

```tsx
        <span>{t('film.panel.clipMeta', { state: label(FILM_STATE, c.state), dur: c.duration, cost: yuan(c.estimate_cny) })}{c.truncated ? t('film.panel.clipCut') : ''}</span>
      </header>
      {flying && (
        <WaitRow item={c} typical={s.options.typical_sec} disabled={film.busy}
                 onCancel={onCancel && (() => onCancel(c.id))} />
      )}
      {onPlay && playableAttempt(c) && (
        <Button size="sm" variant="secondary" className="film__play" data-testid="clip-play" onClick={() => onPlay(c.id)}>
          <Play aria-hidden />{t('film.play.open')}
        </Button>
      )}
```

在 `frontend/src/components/FilmPanel.tsx` 里找到：

```tsx
                <td>{when(a.at)}</td>
                <td>{label(ATTEMPT_STATE, a.state)}</td>
                <td>{yuan(a.cost_cny)}</td>
                <td>
                  {a.state === 'succeeded' && a.file && (
                    <button className="tlc__linkbtn" onClick={() => setWatch(i)}>{t('film.panel.play')}</button>
                  )}
                </td>
                <td>
                  {i === c.chosen ? <span title={t('film.panel.chosenTip')}>★</span> : a.state === 'succeeded' && (
```

换成：

```tsx
                <td>{when(a.at)}</td>
                <td>{label(ATTEMPT_STATE, a.state)}{a.late ? ` · ${t('film.lateTag')}` : ''}</td>
                <td>{yuan(a.cost_cny)}</td>
                <td>
                  {a.state === 'succeeded' && a.file && (
                    <button className="tlc__linkbtn" onClick={() => setWatch(i)}>{t('film.panel.play')}</button>
                  )}
                </td>
                <td>
                  {i === c.chosen ? <span title={t('film.panel.chosenTip')}>★</span> : a.state === 'succeeded' && (
```

- [ ] **Step 8: 画布接上播放窗口与取消确认**

在 `frontend/src/components/TimelineCanvas.tsx` 里找到：

```tsx
import { chosenAttempt, clipOffset, clipSpans, laneKind, laneText, laneTitle, spanAt } from '../film'
import { useFilm } from '../useFilm'
import { onTask } from '@/lib/assistantBridge'
import { FilmPanel } from './FilmPanel'
```

换成：

```tsx
import {
  cancelKind, chosenAttempt, clipOffset, clipSpans, freeNodes, laneKind, laneText, laneTitle, spanAt,
} from '../film'
import { useFilm } from '../useFilm'
import { onTask } from '@/lib/assistantBridge'
import { notice } from '@/lib/notice'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { ClipPlayer } from './ClipPlayer'
import type { PlayTarget } from './ClipPlayer'
import { FilmPanel } from './FilmPanel'
```

在 `frontend/src/components/TimelineCanvas.tsx` 里找到：

```tsx
  /** 「成片」泳道上选中的段 */
  const [clipSel, setClipSel] = useState<string | null>(null)
```

换成：

```tsx
  /** 「成片」泳道上选中的段 */
  const [clipSel, setClipSel] = useState<string | null>(null)
  /** 播放窗口正在播的那一段 / 自由节点（null 为关着） */
  const [player, setPlayer] = useState<PlayTarget | null>(null)
  const [ask, confirmUi] = useConfirm()
  /** 取消排队或生成中的一条：先过确认框。已提交的那种要说明服务商可能仍会扣费 */
  const cancelItem = async (id: string) => {
    const s = film.session
    const free = !!s && freeNodes(s).some((n) => n.id === id)
    const item = s ? [...s.clips, ...freeNodes(s)].find((x) => x.id === id) : undefined
    const kind = item ? cancelKind(item) : null
    if (!kind) return
    const paid = kind === 'paid'
    const sure = await ask({
      title: tt(paid ? 'film.cancel.paidTitle' : 'film.cancel.freeTitle', { id }),
      body: tt(paid ? 'film.cancel.paidBody' : 'film.cancel.freeBody'),
      action: tt(paid ? 'film.cancel.paidAction' : 'film.cancel.freeAction'),
      danger: paid,
    })
    if (!sure) return
    const outcome = await film.cancelItem(id, free)
    if (outcome) notice.ok(tt(`film.cancel.${outcome}`))
  }
```

在 `frontend/src/components/TimelineCanvas.tsx` 里找到：

```tsx
                   onSelect={(id) => { setClipSel(id); setPanel('film') }}
                   onOpenAssets={() => setPanel('assets')} onOpenFilm={() => setPanel('film')} />
      )}
```

换成：

```tsx
                   onSelect={(id) => { setClipSel(id); setPanel('film') }}
                   onOpenAssets={() => setPanel('assets')} onOpenFilm={() => setPanel('film')}
                   onPlay={(id) => setPlayer({ id })} onCancel={(id) => void cancelItem(id)} />
      )}
      {confirmUi}
      {film.enabled && <ClipPlayer film={film} target={player} onClose={() => setPlayer(null)} />}
```

在 `frontend/src/components/TimelineCanvas.tsx` 里找到：

```tsx
          <FilmPanel film={film} selected={clipSel} onPickShot={selectShot} dirty={dirty} />
```

换成：

```tsx
          <FilmPanel film={film} selected={clipSel} onPickShot={selectShot} dirty={dirty}
                     onPlay={(id) => setPlayer({ id })} onCancel={(id) => void cancelItem(id)} />
```

- [ ] **Step 9: 运行，确认通过**

运行：`cd frontend && npx vite build --ssr tests/graph-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/graph-view.test.js`
预期：通过，输出含 `6d. 等待与取消 ✓`、`6e. 播放 ✓`、`ALL PASS`

运行：`cd frontend && npm run typecheck && for t in film canvas compose; do npx vite build --ssr tests/$t.test.tsx --outDir .ssrout --logLevel error && { timeout 100 node .ssrout/$t.test.js > /dev/null 2>&1 || timeout 100 node .ssrout/$t.test.js > /dev/null 2>&1; } || echo "FAILED $t"; done; test "$(npm run lint 2>&1 | grep -c ': warning ')" = 5 && echo lint-ok`
预期：通过，输出含 `lint-ok`，不含 `FAILED`

（每个测试限时 100 秒、失败重跑一次：`film.test` 有既有的偶发卡死，见全局约束。）

- [ ] **Step 10: 提交**

提交：

```bash
git add frontend/src/useFilm.ts frontend/src/components/ClipPlayer.tsx frontend/src/components/NodeCards.tsx frontend/src/components/NodeGraph.tsx frontend/src/components/FilmPanel.tsx frontend/src/components/TimelineCanvas.tsx frontend/src/styles/nodegraph.css frontend/src/styles/film.css frontend/tests/graph-view.test.tsx
git commit -m "出片画布：在跑的片段卡显示已等时长与通常时长并可取消（先过确认框，已提交的写明服务商可能仍会扣费）；出完的封面上加播放按钮，点开带声音与控制条的播放窗口；侧栏选中段同样有等待、取消与播放；取消后才出的结果在卡片上有提示并可切换采用；补界面测试"
```
### Task 8: 任务列表——纯计算、动态面板里的出片任务、可点击的通知

**Files:**
- Create: `frontend/src/filmTasks.ts`
- Modify: `frontend/src/notify.ts`
- Modify: `frontend/src/components/shell/ActivityPanel.tsx`
- Create: `frontend/tests/film-tasks.test.tsx`
- Modify: `frontend/package.json`（把新测试接到 `test` 串的末尾）

- [ ] **Step 1: 写失败的测试**

新建 `frontend/tests/film-tasks.test.tsx`：

```tsx
/** 出片任务列表：纯计算（哪些在跑、哪些要播报、名字、等待文字）、可点击的桌面通知、动态面板里的出片任务。
 *  应用里的轮询、铃铛计数与跳转由 routing.test.tsx 覆盖。跑法：npm test */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'MouseEvent', 'matchMedia', 'ResizeObserver', 'DOMRect',
                 'MutationObserver', 'NodeFilter']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame = (cb: (t: number) => void) =>
  setTimeout(() => cb(performance.now()), 16) as unknown as number
g.cancelAnimationFrame = (id: number) => clearTimeout(id)

import type { FilmTask } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const task = (over: Partial<FilmTask> = {}): FilmTask => ({
  id: 'v1:E01-C01', item_id: 'E01-C01', kind: 'clip', novel_id: 'n1', chapter_id: 'c1', version_id: 'v1',
  work_title: '药', chapter: '第一章', state: 'running', elapsed_sec: 245, typical_sec: [180, 420],
  ended_at: null, cost_cny: null, ...over,
})

const { diffFilmTasks, isLiveTask, lateTaskId, onFilmPoke, pokeFilmTasks, taskName, taskWait } = await import('../src/filmTasks')

// 1. 名字与等待文字：服务端给的已等秒数加上取回之后过去的时间
{
  must(taskName(task()) === '药 · 第一章 · E01-C01', `名字：${taskName(task())}`)
  must(taskName(task({ work_title: null, chapter: null })) === 'E01-C01', '标题缺失时只写片段')
  must(taskWait(task(), 1000, 1000) === '已等 4 分 05 秒 · 通常 3–7 分钟', `等待：${taskWait(task(), 1000, 1000)}`)
  must(taskWait(task(), 1000, 6000) === '已等 4 分 10 秒 · 通常 3–7 分钟', '取回之后接着走')
  must(taskWait(task({ elapsed_sec: null }), 1000, 3000) === '已等 0 分 02 秒 · 通常 3–7 分钟', '没有已等秒数从 0 算')
  must(isLiveTask(task({ state: 'queued' })) && isLiveTask(task({ state: 'downloading' }))
       && !isLiveTask(task({ state: 'done' })) && !isLiveTask(task({ state: 'late' })), '在跑的三种状态')
  must(lateTaskId(task({ id: 'v1:E01-C01:t9', state: 'late' })) === 't9' && lateTaskId(task()) === undefined,
       '取消后才出结果的那条带着厂商任务号，其它没有')
  let poked = 0
  const off = onFilmPoke(() => { poked += 1 })
  pokeFilmTasks()
  off()
  pokeFilmTasks()
  must(poked === 1, '出片操作之后催一次任务列表；退订后不再收到')
  console.log('1. 名字与等待文字 ✓')
}

// 2. 播报：登录后的第一轮只记账；之后新结束的各播一次；取消的不播；同一段再出一次、再结束照常播
{
  const seen = new Set<string>()
  const done = task({ state: 'done', ended_at: '2026-11-21T03:00:00+00:00', elapsed_sec: 280 })
  const first = diffFilmTasks([task({ id: 'v1:E01-C02', item_id: 'E01-C02' }), done], seen, true)
  must(first.live.length === 1 && first.ended.length === 1 && first.announce.length === 0, '第一轮不播报')
  must(diffFilmTasks([done], seen, false).announce.length === 0, '第一轮见过的之后也不播')
  const next = task({ id: 'v1:E01-C02', item_id: 'E01-C02', state: 'failed', ended_at: '2026-11-21T03:05:00+00:00' })
  const second = diffFilmTasks([done, next], seen, false)
  must(second.announce.length === 1 && second.announce[0].id === 'v1:E01-C02', '新结束的播一次')
  must(diffFilmTasks([done, next], seen, false).announce.length === 0, '不重复播')
  const cancelled = task({ id: 'v1:E01-C03', state: 'cancelled', ended_at: '2026-11-21T03:06:00+00:00' })
  must(diffFilmTasks([cancelled], seen, false).announce.length === 0, '自己取消的不播')
  const late = task({ id: 'v1:E01-C03:t9', state: 'late', ended_at: '2026-11-21T03:09:00+00:00', cost_cny: 7.5 })
  must(diffFilmTasks([cancelled, late], seen, false).announce[0]?.state === 'late', '取消后才出结果的要播')
  const again = { ...done, ended_at: '2026-11-21T03:20:00+00:00' }
  must(diffFilmTasks([again], seen, false).announce.length === 1, '同一段再出一次、再结束：照常播')
  console.log('2. 播报 ✓')
}

// 3. 桌面通知：带标签；给了点击回调时，点通知先把窗口拉到前面再执行
{
  const made: { title: string; opts: { body: string; tag: string }; onclick: (() => void) | null; closed: boolean }[] = []
  class FakeNotification {
    static permission = 'granted'
    static requestPermission = async () => 'granted'
    onclick: (() => void) | null = null
    closed = false
    title: string
    opts: { body: string; tag: string }
    constructor(title: string, opts: { body: string; tag: string }) {
      this.title = title
      this.opts = opts
      made.push(this)
    }
    close() { this.closed = true }
  }
  g.Notification = FakeNotification
  ;(win as unknown as Record<string, unknown>).Notification = FakeNotification
  let focused = 0
  ;(win as unknown as { focus: () => void }).focus = () => { focused += 1 }
  const { notify } = await import('../src/notify')
  notify('转换完成', '药 第一章')
  must(made[0].opts.tag === 'storyboard-job' && made[0].onclick === null, '不给回调：老样子')
  let clicked = 0
  notify('片段已生成', '药 · 第一章 · E01-C01', { tag: 'film-v1:E01-C01', onClick: () => { clicked += 1 } })
  must(made[1].opts.tag === 'film-v1:E01-C01' && made[1].opts.body === '药 · 第一章 · E01-C01', '标签与正文')
  made[1].onclick!()
  must(clicked === 1 && focused === 1 && made[1].closed, '点通知：拉到前面、关掉通知、执行回调')
  console.log('3. 可点击的通知 ✓')
}

// 4. 动态面板：在跑的出片任务（章节、片段、状态、已等与通常时长）、最近结束的；点击带着是否播放回调
{
  const { act } = await import('react')
  const { createRoot } = await import('react-dom/client')
  const { ActivityPanel } = await import('../src/components/shell/ActivityPanel')
  const { I18nProvider } = await import('../src/i18n')
  const container = win.document.createElement('div')
  win.document.body.appendChild(container)
  const root = createRoot(container as unknown as HTMLElement)
  const opened: [string, boolean][] = []
  const live = [task(), task({ id: 'v1:F01', item_id: 'F01', kind: 'free', state: 'queued', elapsed_sec: 5 })]
  const ended = [
    task({ id: 'v1:E01-C02', item_id: 'E01-C02', state: 'done', ended_at: '2026-11-21T03:00:00+00:00' }),
    task({ id: 'v1:E01-C03', item_id: 'E01-C03', state: 'failed', ended_at: '2026-11-21T02:59:00+00:00' }),
    task({ id: 'v1:E01-C04:t9', item_id: 'E01-C04', state: 'late', ended_at: '2026-11-21T02:58:00+00:00', cost_cny: 7.5 }),
    task({ id: 'v1:E01-C05', item_id: 'E01-C05', state: 'cancelled', ended_at: '2026-11-21T02:57:00+00:00' }),
  ]
  const panel = (film?: { live: FilmTask[]; ended: FilmTask[]; at: number }) => (
    <I18nProvider initial="zh">
      <ActivityPanel running={[]} done={[]} onOpen={() => {}} onClose={() => {}} film={film}
                     onOpenFilm={(tk, play) => opened.push([tk.id, play])} />
    </I18nProvider>
  )
  await act(async () => { root.render(panel()) })
  must((container.textContent ?? '').includes('没有在跑的任务'), '没有任何任务时是空状态')
  await act(async () => { root.render(panel({ live, ended, at: Date.now() })) })
  const text = container.textContent ?? ''
  must(!text.includes('没有在跑的任务'), '有出片任务就不是空状态')
  const running = [...container.querySelectorAll('[data-testid="activity-film-running"]')]
  must(running.length === 2, `在跑两条：${running.length}`)
  must((running[0].textContent ?? '').includes('药 · 第一章 · E01-C01') && (running[0].textContent ?? '').includes('生成中')
       && /已等 4 分 0\d 秒 · 通常 3–7 分钟/.test(running[0].textContent ?? ''), `在跑的一条：${running[0].textContent}`)
  must((running[1].textContent ?? '').includes('排队中'), '排队中的一条')
  must(!/minimax|seedance|fake|假厂商/i.test(text), '面板里不出现厂商名')
  const done = [...container.querySelectorAll('[data-testid="activity-film-done"]')]
  must(done.length === 4, `最近结束四条：${done.length}`)
  must((done[0].textContent ?? '').includes('已生成') && (done[1].textContent ?? '').includes('生成失败')
       && (done[2].textContent ?? '').includes('取消后仍生成完成') && (done[2].textContent ?? '').includes('¥7.50')
       && (done[3].textContent ?? '').includes('已取消'), '各种结局的标签')
  const press = async (el: Element) => {
    await act(async () => { el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
  }
  await press(running[0].querySelector('button')!)
  for (const li of done) await press(li.querySelector('button')!)
  must(JSON.stringify(opened) === JSON.stringify([
    ['v1:E01-C01', false], ['v1:E01-C02', true], ['v1:E01-C03', false], ['v1:E01-C04:t9', true], ['v1:E01-C05', false],
  ]), `点击回调：${JSON.stringify(opened)}`)
  await act(async () => { root.unmount() })
  console.log('4. 动态面板里的出片任务 ✓')
}

console.log('\nALL PASS')
```

- [ ] **Step 2: 接进 npm test，运行确认失败**

在 `frontend/package.json` 里找到：

```json
 && vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js",
```

换成：

```json
 && vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js && vite build --ssr tests/film-tasks.test.tsx --outDir .ssrout --logLevel error && node .ssrout/film-tasks.test.js",
```

运行：`cd frontend && npx vite build --ssr tests/film-tasks.test.tsx --outDir .ssrout --logLevel error && node .ssrout/film-tasks.test.js`
预期：失败

- [ ] **Step 3: 纯计算**

新建 `frontend/src/filmTasks.ts`：

```ts
/** 出片任务列表（GET /render/tasks）：哪些在跑、哪些要播报、显示用的名字与等待文字（都是纯计算），
 *  外加一个「催一下」的小信号（画布 → 应用）。App 轮询、动态面板只吃这里的结果；单测见 tests/film-tasks.test.tsx。 */
import { waitLine } from './film'
import type { FilmTask } from './types'

const LIVE: FilmTask['state'][] = ['queued', 'running', 'downloading']

export const isLiveTask = (t: FilmTask) => LIVE.includes(t.state)

/** 「药 · 第一章 · E01-C01」：小说、章节、片段；标题缺失的略过 */
export const taskName = (t: FilmTask) => [t.work_title, t.chapter, t.item_id].filter(Boolean).join(' · ')

/** 在跑的一条的等待文字：服务端算的已等秒数，加上取回（fetchedAt）之后过去的时间；now、fetchedAt 为毫秒时间戳 */
export const taskWait = (t: FilmTask, fetchedAt: number, now: number) =>
  waitLine((t.elapsed_sec ?? 0) + Math.max(0, (now - fetchedAt) / 1000), t.typical_sec)

/** 取消后才出结果的那条（state 为 late）对应的任务号：id 是 <版本>:<段>:<任务号>。其它状态没有 */
export const lateTaskId = (t: FilmTask) =>
  (t.state === 'late' ? t.id.slice(`${t.version_id}:${t.item_id}:`.length) || undefined : undefined)

const pokeSubs = new Set<() => void>()

/** 画布上刚发起或取消了出片：让应用马上重取任务列表，不必等下一轮巡检 */
export function pokeFilmTasks(): void {
  pokeSubs.forEach((f) => f())
}

export function onFilmPoke(cb: () => void): () => void {
  pokeSubs.add(cb)
  return () => { pokeSubs.delete(cb) }
}

/** 把一轮取回的任务分成在跑的、已结束的，并挑出要播报的。
 *  seen 记见过的结束（id + 结束时间）：每条只播一次；同一段再出一次、再结束，结束时间不同，照常播。
 *  first（登录后的第一轮）只记账不播报：刷新页面不该把十分钟内的结果再弹一遍。自己取消的不播。 */
export function diffFilmTasks(tasks: FilmTask[], seen: Set<string>, first: boolean) {
  const live = tasks.filter(isLiveTask)
  const ended = tasks.filter((t) => !isLiveTask(t))
  const announce: FilmTask[] = []
  for (const t of ended) {
    const key = `${t.id}@${t.ended_at ?? ''}`
    if (seen.has(key)) continue
    seen.add(key)
    if (!first && t.state !== 'cancelled') announce.push(t)
  }
  return { live, ended, announce }
}
```

- [ ] **Step 4: 通知可以点**

在 `frontend/src/notify.ts` 里找到：

```ts
export function notify(title: string, body: string): void {
  if (!('Notification' in window) || Notification.permission !== 'granted') return
  try {
    new Notification(title, { body, tag: 'storyboard-job' })
  } catch {
```

换成：

```ts
/** tag 相同的通知互相顶替（出片按片段给，各段的通知不互相盖掉）；给了 onClick，点通知先把窗口拉到前面再执行 */
export function notify(title: string, body: string, opts: { tag?: string; onClick?: () => void } = {}): void {
  if (!('Notification' in window) || Notification.permission !== 'granted') return
  try {
    const n = new Notification(title, { body, tag: opts.tag ?? 'storyboard-job' })
    const { onClick } = opts
    if (onClick) n.onclick = () => { window.focus(); n.close(); onClick() }
  } catch {
```

- [ ] **Step 5: 动态面板显示出片任务**

在 `frontend/src/components/shell/ActivityPanel.tsx` 里找到：

```tsx
import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
```

换成：

```tsx
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
```

在 `frontend/src/components/shell/ActivityPanel.tsx` 里找到：

```tsx
import { fmtEta, JOB_STATUS, label } from '@/labels'
import type { JobStatus, JobSummary } from '@/types'
```

换成：

```tsx
import { fmtEta, JOB_STATUS, label } from '@/labels'
import { taskName, taskWait } from '@/filmTasks'
import { cny } from '@/lib/fmt'
import type { MsgKey } from '@/i18n/core'
import type { FilmTask, JobStatus, JobSummary } from '@/types'
```

在 `frontend/src/components/shell/ActivityPanel.tsx` 里找到：

```tsx
const TONE: Partial<Record<JobStatus, Tone>> = {
  succeeded: 'ok', completed_with_warnings: 'warn', failed: 'err', draft_invalid: 'warn',
}

export function ActivityPanel({ running, done, onOpen, onOpenDone, onClose, tab = 'activity', onTab, assistant }: {
  running: JobSummary[]
  done: DoneJob[]
```

换成：

```tsx
const TONE: Partial<Record<JobStatus, Tone>> = {
  succeeded: 'ok', completed_with_warnings: 'warn', failed: 'err', draft_invalid: 'warn',
}
const FILM_TONE: Record<FilmTask['state'], Tone> = {
  queued: 'live', running: 'live', downloading: 'live', done: 'ok', failed: 'err', cancelled: 'idle', late: 'warn',
}

/** 本人的出片任务：在跑的、最近结束的，以及这份列表是什么时候取回的（毫秒时间戳，等待时长从它接着走） */
export interface FilmActivity { live: FilmTask[]; ended: FilmTask[]; at: number }

export function ActivityPanel({ running, done, onOpen, onOpenDone, onClose, tab = 'activity', onTab, assistant, film, onOpenFilm }: {
  running: JobSummary[]
  done: DoneJob[]
  /** 出片任务（没有就不显示）；点一条回到画布上的那一段，play 为 true 时顺便打开播放 */
  film?: FilmActivity
  onOpenFilm?: (t: FilmTask, play: boolean) => void
```

在 `frontend/src/components/shell/ActivityPanel.tsx` 里找到：

```tsx
  const showAssistant = tab === 'assistant' && !!assistant
  return (
```

换成：

```tsx
  const showAssistant = tab === 'assistant' && !!assistant
  const filmLive = film?.live ?? []
  const filmEnded = film?.ended ?? []
  /** 有出片任务在跑时每秒走一次，等待时长跟着动 */
  const [now, setNow] = useState(() => Date.now())
  const ticking = filmLive.length > 0
  useEffect(() => {
    if (!ticking) return
    setNow(Date.now())
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [ticking])
  const filmState = (tk: FilmTask) => t(`activity.film.state.${tk.state}` as MsgKey)
  return (
```

在 `frontend/src/components/shell/ActivityPanel.tsx` 里找到：

```tsx
        {!running.length && !done.length && (
          <EmptyState icon={<BellRing className="size-5" />} title={t('activity.empty')} hint={t('activity.emptyHint')} />
        )}
        {!!running.length && (
```

换成：

```tsx
        {!running.length && !done.length && !filmLive.length && !filmEnded.length && (
          <EmptyState icon={<BellRing className="size-5" />} title={t('activity.empty')} hint={t('activity.emptyHint')} />
        )}
        {!!filmLive.length && (
          <section>
            {!running.length && <h3 className="activity__title">{t('activity.running')}</h3>}
            <ul className="space-y-2">
              {filmLive.map((tk) => (
                <li key={tk.id} data-testid="activity-film-running" className="activity__item">
                  <p className="truncate text-sm font-medium">{taskName(tk)}</p>
                  <div className="flex items-center justify-between gap-2">
                    <StatusPill tone={FILM_TONE[tk.state]}>{filmState(tk)}</StatusPill>
                    <Button variant="outline" size="sm" onClick={() => onOpenFilm?.(tk, false)}>{t('activity.view')}</Button>
                  </div>
                  <p className="text-xs tabular-nums text-muted-foreground">{taskWait(tk, film?.at ?? now, now)}</p>
                </li>
              ))}
            </ul>
          </section>
        )}
        {!!running.length && (
```

在 `frontend/src/components/shell/ActivityPanel.tsx` 里找到：

```tsx
        {!!done.length && (
          <section>
            <h3 className="activity__title">{t('activity.done')}</h3>
```

换成：

```tsx
        {!!filmEnded.length && (
          <section>
            {!done.length && <h3 className="activity__title">{t('activity.done')}</h3>}
            <ul className="space-y-2">
              {filmEnded.map((tk) => (
                <li key={tk.id} data-testid="activity-film-done" className="activity__item activity__item--click">
                  <button type="button" className="block w-full text-left"
                          onClick={() => onOpenFilm?.(tk, tk.state === 'done' || tk.state === 'late')}>
                    <p className="truncate text-sm">{taskName(tk)}</p>
                    <div><StatusPill tone={FILM_TONE[tk.state]}>{filmState(tk)}</StatusPill></div>
                    {tk.state === 'late' && tk.cost_cny != null && (
                      <p className="text-xs text-muted-foreground">{t('activity.film.late', { cost: cny(tk.cost_cny) })}</p>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
        {!!done.length && (
          <section>
            <h3 className="activity__title">{t('activity.done')}</h3>
```

- [ ] **Step 6: 运行，确认通过**

运行：`cd frontend && npx vite build --ssr tests/film-tasks.test.tsx --outDir .ssrout --logLevel error && node .ssrout/film-tasks.test.js`
预期：通过，输出含 `4. 动态面板里的出片任务 ✓`、`ALL PASS`

运行：`cd frontend && npm run typecheck && test "$(npm run lint 2>&1 | grep -c ': warning ')" = 5 && echo lint-ok`
预期：通过，输出含 `lint-ok`

- [ ] **Step 7: 提交**

提交：

```bash
git add frontend/src/filmTasks.ts frontend/src/notify.ts frontend/src/components/shell/ActivityPanel.tsx frontend/tests/film-tasks.test.tsx frontend/package.json
git commit -m "动态面板显示出片任务：在跑的写明小说、章节、片段、状态、已等与通常时长，最近结束的带结局（已生成、失败、已取消、取消后仍生成完成并注明已计费）；任务播报的纯计算（第一轮只记账、每条只播一次、自己取消的不播）；桌面通知可带标签与点击回调；补测试并接进 npm test"
```
### Task 9: 应用接线——铃铛与动态面板里的出片任务、完成播报、点回画布上的片段并播放

应用和转换任务并行巡检 `GET /render/tasks`：在跑的计入铃铛数字并列在动态面板；结束的播报一次（桌面通知 + 页内提示，都能点）。点任务、提示或通知：打开那一版的画布（节点图、出片页）并选中那一段，完成的顺便打开播放窗口。要聚焦的片段放在路由 state 的 `focus` 里（和 `panel` 一样跟着这条历史记录走），画布用完后由应用清掉。

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/paths.ts`
- Modify: `frontend/src/useFilm.ts`
- Modify: `frontend/src/components/TimelineCanvas.tsx`
- Modify: `frontend/src/components/StoryboardView.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/tests/graph-view.test.tsx`
- Test: `frontend/tests/routing.test.tsx`

- [ ] **Step 1: 写失败的测试（画布收到聚焦请求）**

在 `frontend/tests/graph-view.test.tsx` 里找到：

```tsx
function Host() {
  const [dirty, set] = useState(false)
  return <StoryboardView doc={doc} canSave dirty={dirty} saving={false}
                         version={{ nid: 'n1', cid: 'c1', vid: 'v1' }}
                         onChange={() => set(true)} onSave={() => set(false)} />
}
```

换成：

```tsx
/** 测试用：给画布一个聚焦请求（从任务列表、提示、通知点过来）；focusDone 记画布回报了几次「用完了」 */
let giveFocus: (f: FilmFocus | undefined) => void = () => {}
let focusDone = 0
function Host() {
  const [dirty, set] = useState(false)
  const [focus, setFocus] = useState<FilmFocus | undefined>(undefined)
  giveFocus = setFocus
  return <StoryboardView doc={doc} canSave dirty={dirty} saving={false}
                         version={{ nid: 'n1', cid: 'c1', vid: 'v1' }}
                         onChange={() => set(true)} onSave={() => set(false)}
                         canvasFocus={focus} onCanvasFocusDone={() => { focusDone += 1; setFocus(undefined) }} />
}
```

在 `frontend/tests/graph-view.test.tsx` 里找到：

```ts
import type { FilmAttempt, FilmClip, FilmFreeNode, FilmSession, Storyboard } from '../src/types'
```

换成：

```ts
import type { FilmAttempt, FilmClip, FilmFocus, FilmFreeNode, FilmSession, Storyboard } from '../src/types'
```

在 `frontend/tests/graph-view.test.tsx` 里找到：

```ts
// 7. 切回时间轴：节点图收起
```

换成：

```ts
// 6f. 聚焦请求：只认本版本的；选中那一段、停在出片页，要播放就打开播放窗口；点名任务号就播那一次；每个请求只执行一次
{
  const player = () => win.document.body.querySelector('[data-testid="clip-player"]')
  const closePlayer = async () => {
    await click(win.document.body.querySelector('[data-testid="clip-player"] [data-slot="dialog-close"]')!)
    await settle(300)
  }
  const give = async (f: FilmFocus) => { await act(async () => { giveFocus(f) }); await settle() }
  const second = film!.clips[1].id
  await click(card(second))
  await give({ vid: 'other', id: first, play: true })
  must(!player() && focusDone === 0, '别的版本的请求：不动，留着等那一版')
  await act(async () => { giveFocus(undefined) })
  await give({ vid: 'v1', id: first, play: false })
  must(!player() && focusDone === 1, '不要播放：只选中')
  must(tab('出片')?.getAttribute('aria-pressed') === 'true'
       && !!container.querySelector('[data-testid="clip-play"]'), '停在出片页，选中的是有结果的那一段')
  const late = { ...attempt(first, 9, 7.5), task_id: 't-late', late: true }
  clipOf(first).attempts.push(late)
  film = recount(film!)
  await refresh()
  must(!!card(first).querySelector('[data-testid="ngv-late"]'), '卡片上提示有取消后才出的结果')
  await give({ vid: 'v1', id: first, play: true, taskId: 't-late' })
  must((player()?.textContent ?? '').includes(`${first} · 第 ${clipOf(first).attempts.length} 次`)
       && (player()?.textContent ?? '').includes('取消后才出的结果') && focusDone === 2,
       `点名任务号：播的是那一次：${player()?.textContent}`)
  await closePlayer()
  await give({ vid: 'v1', id: 'E99-C99', play: true })
  must(!player() && focusDone === 3, '找不到的片段：不打开播放窗口，请求照样用掉')
  clipOf(first).attempts.pop()
  film = recount(film!)
  await refresh()
  console.log('6f. 聚焦请求 ✓')
}

// 7. 切回时间轴：节点图收起
```

- [ ] **Step 2: 写失败的测试（应用里的铃铛、面板、跳转与通知）**

在 `frontend/tests/routing.test.tsx` 里找到：

```ts
const jobsById: Record<string, unknown> = {}
let jobsList: unknown[] = []
```

换成：

```ts
const jobsById: Record<string, unknown> = {}
let jobsList: unknown[] = []
/** 本人的出片任务（GET /render/tasks 原样返回） */
let filmTasks: unknown[] = []
```

在 `frontend/tests/routing.test.tsx` 里找到：

```ts
  if (path === '/jobs') return json({ jobs: jobsList })
```

换成：

```ts
  if (path === '/jobs') return json({ jobs: jobsList })
  if (path === '/render/tasks') return json({ tasks: filmTasks })
```

在 `frontend/tests/routing.test.tsx` 里找到：

```ts
  jobsList = []
  for (const k of Object.keys(jobsById)) delete jobsById[k]
```

换成：

```ts
  jobsList = []
  filmTasks = []
  for (const k of Object.keys(jobsById)) delete jobsById[k]
```

在 `frontend/tests/routing.test.tsx` 里找到：

```ts
console.log('T9e. 当前会话的 401 经请求层清令牌并提示过期 ✓')
```

换成：

```ts
console.log('T9e. 当前会话的 401 经请求层清令牌并提示过期 ✓')

// 出片任务：在跑的计入铃铛并列在动态面板；点「查看」到那一版的画布（节点图）并带上要选中的片段；
// 结束时发一条能点的桌面通知，点它带着「播放」回到那一段
{
  const { pokeFilmTasks } = await import('../src/filmTasks')
  const made: { title: string; body: string; tag: string; onclick: (() => void) | null }[] = []
  class Granted {
    static permission = 'granted'
    static requestPermission = async () => 'granted'
    onclick: (() => void) | null = null
    title: string
    body: string
    tag: string
    constructor(title: string, o: { body: string; tag: string }) {
      this.title = title; this.body = o.body; this.tag = o.tag
      made.push(this)
    }
    close() {}
  }
  const wn = win as unknown as Record<string, unknown>
  const before = [g.Notification, wn.Notification, wn.focus]
  g.Notification = Granted; wn.Notification = Granted; wn.focus = () => {}
  const task = (over: Record<string, unknown> = {}) => ({
    id: 'v1:E01-C01', item_id: 'E01-C01', kind: 'clip', novel_id: 'n1', chapter_id: 'c1', version_id: 'v1',
    work_title: '药', chapter: '第一章', state: 'running', elapsed_sec: 245, typical_sec: [180, 420],
    ended_at: null, cost_cny: null, ...over })
  const poke = async () => { await act(async () => { pokeFilmTasks() }); await settle(150) }
  const focusOf = (r: Router) => (r.state.location.state as { focus?: unknown; panel?: string } | null)

  const a = await boot('/novels/n1/overview', 'alice')
  must(!a.q('[data-testid="activity-count"]'), '没有任务：铃铛上没有数字')
  filmTasks = [task()]
  await poke()
  must(a.q('[data-testid="activity-count"]')?.textContent === '1', '在跑的出片任务计入铃铛')
  await click(a.q('[data-testid="activity-bell"]')!)
  const row = doc.body.querySelector('[data-testid="activity-film-running"]') as unknown as HTMLElement | null
  must(!!row && (row.textContent ?? '').includes('药 · 第一章 · E01-C01') && /已等 4 分 \d\d 秒 · 通常 3–7 分钟/.test(row.textContent ?? ''),
       `动态面板里有这条：${row?.textContent}`)
  must(made.length === 0, '在跑的不发通知')
  await click(button(row!, '查看')!)
  await settle(300)
  must(a.here() === '/novels/n1/chapters/c1/render/canvas?view=graph', `点查看到画布的节点图，实际 ${a.here()}`)
  must(JSON.stringify(focusOf(a.router)?.focus) === JSON.stringify({ vid: 'v1', id: 'E01-C01', play: false })
       && focusOf(a.router)?.panel === 'film', `带上要选中的片段：${JSON.stringify(a.router.state.location.state)}`)

  filmTasks = [task({ state: 'done', ended_at: '2026-11-21T03:00:00+00:00', elapsed_sec: 280 })]
  await poke()
  must(!a.q('[data-testid="activity-count"]'), '结束后铃铛数字消失')
  must(made.length === 1 && made[0].title === '片段已生成' && made[0].body.includes('药 · 第一章 · E01-C01')
       && made[0].tag === 'film-v1:E01-C01', `结束发一条通知：${JSON.stringify(made)}`)
  must(!/minimax|seedance|fake/i.test(made[0].title + made[0].body), '通知里不出现厂商名')
  await poke()
  must(made.length === 1, '同一条不重复通知')
  await act(async () => { made[0].onclick!() })
  await settle(300)
  must(a.here() === '/novels/n1/chapters/c1/render/canvas?view=graph', '点通知：还在这一章的画布')
  must(JSON.stringify(focusOf(a.router)?.focus) === JSON.stringify({ vid: 'v1', id: 'E01-C01', play: true }),
       `点通知带着播放：${JSON.stringify(a.router.state.location.state)}`)
  await a.done()

  // 登录后第一轮看到的已结束任务不播报（刷新页面不重弹）；取消后才出结果的要播报，带任务号
  filmTasks = []
  const b = await boot('/novels/n1/overview', 'alice')
  must(made.length === 1, '第一轮不播报')
  filmTasks = [task({ id: 'v1:E01-C02:t9', item_id: 'E01-C02', state: 'late', elapsed_sec: null,
                      ended_at: '2026-11-21T03:09:00+00:00', cost_cny: 7.5 })]
  await poke()
  must(made.length === 2 && made[1].title === '已取消的片段仍生成完成' && made[1].body.includes('¥7.50'),
       `取消后才出结果：${JSON.stringify(made[1])}`)
  await act(async () => { made[1].onclick!() })
  await settle(300)
  must(JSON.stringify(focusOf(b.router)?.focus) === JSON.stringify({ vid: 'v1', id: 'E01-C02', play: true, taskId: 't9' }),
       `点通知带着任务号：${JSON.stringify(b.router.state.location.state)}`)
  await b.done()
  ;[g.Notification, wn.Notification, wn.focus] = before
}
console.log('出片任务：铃铛、面板、跳转与通知 ✓')
```

- [ ] **Step 3: 运行，确认失败**

两条命令都用 grep 把第一条断言失败（`Error: ✗ …` 那一行）捞出来：捞得到、且是下面写的那一条，才是对的红灯。

运行：`cd frontend && npx vite build --ssr tests/graph-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/graph-view.test.js 2>&1 | grep -m1 'Error: ✗'`
预期：通过，输出含 `不要播放：只选中`

运行：`cd frontend && npx vite build --ssr tests/routing.test.tsx --outDir .ssrout --logLevel error && node .ssrout/routing.test.js 2>&1 | grep -m1 'Error: ✗'`
预期：通过，输出含 `在跑的出片任务计入铃铛`

- [ ] **Step 4: 类型与路由 state**

在 `frontend/src/types.ts` 里找到：

```ts
export interface FilmSettings {
```

换成：

```ts
/** 让画布选中某一段 / 自由节点的请求（从任务列表、提示、通知点过来；放在路由 state 里）。
 *  vid：属于哪一版（画布只认自己这一版的）；play：顺便打开播放窗口；taskId：点名播哪个任务出的那一次 */
export interface FilmFocus {
  vid: string
  id: string
  play: boolean
  taskId?: string
}

export interface FilmSettings {
```

在 `frontend/src/paths.ts` 里找到：

```ts
import type { Tab } from './components/StoryboardView'
```

换成：

```ts
import type { Tab } from './components/StoryboardView'
import type { FilmFocus } from './types'
```

在 `frontend/src/paths.ts` 里找到：

```ts
  /** 打开画布时停在哪个侧栏页（只有「出片」） */
  panel?: 'film'
}
```

换成：

```ts
  /** 打开画布时停在哪个侧栏页（只有「出片」） */
  panel?: 'film'
  /** 打开画布后选中哪一段（并可顺便播放）：画布用完由应用清掉，刷新、后退不会再来一次 */
  focus?: FilmFocus
}
```

- [ ] **Step 5: 画布上发起或取消出片后，催一次任务列表**

在 `frontend/src/useFilm.ts` 里找到：

```ts
import { primeNotifications } from './notify'
```

换成：

```ts
import { pokeFilmTasks } from './filmTasks'
import { primeNotifications } from './notify'
```

在 `frontend/src/useFilm.ts` 里找到：

```ts
      if (gen.current !== mine) return { kind: 'stale' }
      accept(got, true)
      return { kind: 'ok' }
```

换成：

```ts
      if (gen.current !== mine) return { kind: 'stale' }
      accept(got, true)
      pokeFilmTasks()
      return { kind: 'ok' }
```

在 `frontend/src/useFilm.ts` 里找到：

```ts
      if (gen.current !== mine) return null
      accept(got)
      return got.cancel_outcome ?? null
```

换成：

```ts
      if (gen.current !== mine) return null
      accept(got)
      pokeFilmTasks()
      return got.cancel_outcome ?? null
```

- [ ] **Step 6: 画布认聚焦请求**

在 `frontend/src/components/TimelineCanvas.tsx` 里找到：

```tsx
import type { Storyboard, VersionRef } from '../types'
```

换成：

```tsx
import type { FilmFocus, Storyboard, VersionRef } from '../types'
```

在 `frontend/src/components/TimelineCanvas.tsx` 里找到：

```tsx
  view?: 'timeline' | 'graph'
  onView?: (v: 'timeline' | 'graph') => void
}

/** 连续打字时把一串改动并成一步撤销 */
```

换成：

```tsx
  view?: 'timeline' | 'graph'
  onView?: (v: 'timeline' | 'graph') => void
  /** 聚焦请求（从任务列表、提示、通知点过来）：选中这一段、停在「出片」页，要播放就打开播放窗口。
   *  只认本版本的；会话读到后执行一次，然后回报 onFocusDone（上层清掉请求） */
  focus?: FilmFocus
  onFocusDone?: () => void
}

/** 连续打字时把一串改动并成一步撤销 */
```

在 `frontend/src/components/TimelineCanvas.tsx` 里找到：

```tsx
  styleUrl = null, styleMime, view: viewProp, onView,
}: Props) {
```

换成：

```tsx
  styleUrl = null, styleMime, view: viewProp, onView, focus, onFocusDone,
}: Props) {
```

在 `frontend/src/components/TimelineCanvas.tsx` 里找到：

```tsx
    const outcome = await film.cancelItem(id, free)
    if (outcome) notice.ok(tt(`film.cancel.${outcome}`))
  }
```

换成：

```tsx
    const outcome = await film.cancelItem(id, free)
    if (outcome) notice.ok(tt(`film.cancel.${outcome}`))
  }
  /** 聚焦请求：同一个请求只执行一次（按对象认，上层清掉之前可能再渲染几次） */
  const focusSeen = useRef<FilmFocus | null>(null)
  const filmSession = film.session
  const focusReady = !!focus && focus.vid === version?.vid && !!filmSession
  useEffect(() => {
    if (!focus || !focusReady || !filmSession || focusSeen.current === focus) return
    focusSeen.current = focus
    const item = [...filmSession.clips, ...freeNodes(filmSession)].find((x) => x.id === focus.id)
    if (item) {
      setClipSel(focus.id)
      setPanel('film')
      if (focus.play) {
        const at = focus.taskId ? item.attempts.findIndex((a) => a.task_id === focus.taskId) : -1
        setPlayer({ id: focus.id, ...(at >= 0 ? { attempt: at } : {}) })
      }
    }
    onFocusDone?.()
  }, [focus, focusReady, filmSession, onFocusDone])
```

在 `frontend/src/components/StoryboardView.tsx` 里找到：

```tsx
import type { FilmSession, Shot, Storyboard, VerificationReport, VersionRef } from '../types'
```

换成：

```tsx
import type { FilmFocus, FilmSession, Shot, Storyboard, VerificationReport, VersionRef } from '../types'
```

在 `frontend/src/components/StoryboardView.tsx` 里找到：

```tsx
  canvasView?: 'timeline' | 'graph'
  onCanvasView?: (v: 'timeline' | 'graph') => void
  /** 从画布跳回某个镜头
```

换成：

```tsx
  canvasView?: 'timeline' | 'graph'
  onCanvasView?: (v: 'timeline' | 'graph') => void
  /** 画布的聚焦请求与「用完了」的回报（原样交给画布） */
  canvasFocus?: FilmFocus
  onCanvasFocusDone?: () => void
  /** 从画布跳回某个镜头
```

在 `frontend/src/components/StoryboardView.tsx` 里找到：

```tsx
  tab: tabProp, onTab, canvasOpen, onCanvas, canvasPanel: canvasPanelProp, canvasView, onCanvasView, onJumpShot,
}: Props) {
```

换成：

```tsx
  tab: tabProp, onTab, canvasOpen, onCanvas, canvasPanel: canvasPanelProp, canvasView, onCanvasView, onJumpShot,
  canvasFocus, onCanvasFocusDone,
}: Props) {
```

在 `frontend/src/components/StoryboardView.tsx` 里找到：

```tsx
                        view={onCanvasView ? canvasView : undefined} onView={onCanvasView}
                        styleUrl={styleUrl} styleMime={styleMime} />
```

换成：

```tsx
                        view={onCanvasView ? canvasView : undefined} onView={onCanvasView}
                        focus={canvasFocus} onFocusDone={onCanvasFocusDone}
                        styleUrl={styleUrl} styleMime={styleMime} />
```

运行：`cd frontend && npx vite build --ssr tests/graph-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/graph-view.test.js`
预期：通过，输出含 `6f. 聚焦请求 ✓`、`ALL PASS`

- [ ] **Step 7: 应用巡检出片任务并播报**

在 `frontend/src/App.tsx` 里找到：

```tsx
  getChapter, getJobPartial, getNovel, getVersion, health, listJobs, listNovels, me,
```

换成：

```tsx
  getChapter, getJobPartial, getNovel, getVersion, health, listFilmTasks, listJobs, listNovels, me,
```

在 `frontend/src/App.tsx` 里找到：

```tsx
import type { DoneJob } from './components/shell/ActivityPanel'
```

换成：

```tsx
import type { DoneJob, FilmActivity } from './components/shell/ActivityPanel'
import { diffFilmTasks, lateTaskId, onFilmPoke, taskName } from './filmTasks'
import { cny } from './lib/fmt'
```

在 `frontend/src/App.tsx` 里找到：

```tsx
import type {
  AdminService, Chapter, Health, Job, JobSummary, NarrationMode, Novel, NovelSummary, Storyboard,
  VerificationReport,
} from './types'
```

换成：

```tsx
import type {
  AdminService, Chapter, FilmFocus, FilmTask, Health, Job, JobSummary, NarrationMode, Novel, NovelSummary, Storyboard,
  VerificationReport,
} from './types'
```

在 `frontend/src/App.tsx` 里找到：

```tsx
  const [recentDone, setRecentDone] = useState<DoneJob[]>([])
  const [activityDot, setActivityDot] = useState(false)
```

换成：

```tsx
  const [recentDone, setRecentDone] = useState<DoneJob[]>([])
  /** 本人的出片任务（在跑的、最近结束的）与取回时刻：铃铛数字与动态面板用 */
  const [filmAct, setFilmAct] = useState<FilmActivity>({ live: [], ended: [], at: 0 })
  const [activityDot, setActivityDot] = useState(false)
```

在 `frontend/src/App.tsx` 里找到：

```tsx
    } catch {
      /* 巡检失败静默重试，不打扰用户 */
    }
  }, [announce, refreshNovels, reloadOpen, bumpSummary])
```

换成：

```tsx
    } catch {
      /* 巡检失败静默重试，不打扰用户 */
    }
  }, [announce, refreshNovels, reloadOpen, bumpSummary])

  /** 出片任务巡检：和转换任务并行。结束的各播报一次（桌面通知 + 页内提示，都能点回那一段）；
   *  登录后的第一轮只记账。提示里只有小说、章节、片段，不带厂商或模型名 */
  const filmSeen = useRef<Set<string>>(new Set())
  const filmFirst = useRef(true)
  const openFilmRef = useRef<(tk: FilmTask, play: boolean) => void>(() => {})
  const watchFilm = useCallback(async () => {
    const ep = epoch.current
    try {
      const { tasks } = await listFilmTasks()
      if (epoch.current !== ep) return
      const { live, ended, announce: fresh } = diffFilmTasks(tasks, filmSeen.current, filmFirst.current)
      filmFirst.current = false
      setFilmAct({ live, ended, at: Date.now() })
      for (const tk of fresh) {
        const who = taskName(tk)
        const play = tk.state !== 'failed'
        const open = () => openFilmRef.current(tk, play)
        const action = { label: t(play ? 'activity.film.play' : 'flow.view'), onClick: open }
        const tag = `film-${tk.id}`
        if (tk.state === 'failed') {
          notify(t('app.notify.filmFailed'), t('app.notify.filmFailedBody', { who }), { tag, onClick: open })
          toast.error(t('app.notify.filmFailed'), { description: who, action })
        } else if (tk.state === 'late') {
          const body = t('app.notify.filmLateBody', { who, cost: cny(tk.cost_cny ?? 0) })
          notify(t('app.notify.filmLate'), body, { tag, onClick: open })
          toast.warning(t('app.notify.filmLate'), { description: body, action })
        } else {
          notify(t('app.notify.filmDone'), t('app.notify.filmDoneBody', { who }), { tag, onClick: open })
          toast.success(t('app.notify.filmDone'), { description: who, action })
        }
      }
      if (fresh.length) {
        if (!activityOpenRef.current) setActivityDot(true)
        bumpSummary()     // 出片花了钱：费用表重算
      }
    } catch {
      /* 巡检失败静默重试，不打扰用户 */
    }
  }, [t, bumpSummary])
```

在 `frontend/src/App.tsx` 里找到：

```tsx
  // 章后整理在后台跑（一次小调用）：跑着时盯一下，完了刷新小说页的待确认提议
```

换成：

```tsx
  // 出片任务：登录后立刻取一轮；画布上发起或取消后马上再取；有在跑的 5 秒一轮，闲时 15 秒
  const signedIn = !!user
  useEffect(() => {
    if (!signedIn) return
    void watchFilm()
    return onFilmPoke(() => void watchFilm())
  }, [signedIn, watchFilm])
  const filmLiveCount = filmAct.live.length
  useEffect(() => {
    if (!signedIn) return
    const id = window.setInterval(() => void watchFilm(), filmLiveCount ? 5000 : 15000)
    return () => clearInterval(id)
  }, [signedIn, filmLiveCount, watchFilm])

  // 章后整理在后台跑（一次小调用）：跑着时盯一下，完了刷新小说页的待确认提议
```

在 `frontend/src/App.tsx` 里找到：

```tsx
    if (task.kind === 'job') void watchJobs()
    if (task.kind === 'edit' && novel) {
```

换成：

```tsx
    if (task.kind === 'job') void watchJobs()
    if (task.kind === 'film') void watchFilm()
    if (task.kind === 'edit' && novel) {
```

在 `frontend/src/App.tsx` 里找到：

```tsx
  }), [watchJobs, bumpSummary, novel, chapter?.id, docVid, dirty, reloadOpen, openVersion, t])
```

换成：

```tsx
  }), [watchJobs, watchFilm, bumpSummary, novel, chapter?.id, docVid, dirty, reloadOpen, openVersion, t])
```

在 `frontend/src/App.tsx` 里找到：

```tsx
    setRecentDone([]); setActivityDot(false); setActivityOpen(false); setActivityTab('activity')
    prevRunning.current = new Set()
```

换成：

```tsx
    setRecentDone([]); setActivityDot(false); setActivityOpen(false); setActivityTab('activity')
    prevRunning.current = new Set()
    setFilmAct({ live: [], ended: [], at: 0 }); filmSeen.current = new Set(); filmFirst.current = true
```

- [ ] **Step 8: 点任务回到画布上的那一段**

在 `frontend/src/App.tsx` 里找到：

```tsx
  const openJob = (j: JobSummary) => {
```

换成：

```tsx
  /** 从任务列表、提示或通知回到出片任务所在的片段：打开那一版的画布（节点图、出片页）并选中它，play 时顺便播放。
   *  要选中谁放在路由 state 的 focus 里；跨章节时版本号作一次性 state，章节加载时打开那一版（§5.4） */
  const openFilmTask = async (tk: FilmTask, play: boolean) => {
    const taskId = lateTaskId(tk)
    const focus: FilmFocus = { vid: tk.version_id, id: tk.item_id, play, ...(taskId ? { taskId } : {}) }
    if (tk.novel_id === nid && tk.chapter_id === cid) {
      if (docVid !== tk.version_id) {
        if (!(await confirmLeave())) return
        void openVersion(tk.novel_id, tk.chapter_id, tk.version_id)
      }
      const to = chapterPath(tk.novel_id, tk.chapter_id, { step: boardStep(), tab: urlTab, canvas: true, view: 'graph' })
      // 已经在这个地址：不导航，只把请求写进当前这条历史记录
      if (!go(to, { state: { fromChapter: true, panel: 'film', focus } })) {
        navigate(to, { replace: true, state: { ...passState(navStateRef.current), panel: 'film', focus } })
      }
      return
    }
    go(chapterPath(tk.novel_id, tk.chapter_id, { step: 'render', canvas: true, view: 'graph' }),
       { state: { vid: tk.version_id, panel: 'film', focus } })
  }
  openFilmRef.current = (tk, play) => void openFilmTask(tk, play)
  /** 画布用完了聚焦请求：从当前这条历史记录里清掉 */
  const clearFilmFocus = useCallback(() => {
    const rest = passState(navStateRef.current)
    delete rest.focus
    navigate(hereRef.current, { replace: true, state: rest })
  }, [navigate])

  const openJob = (j: JobSummary) => {
```

在 `frontend/src/App.tsx` 里找到：

```tsx
            canvasPanel: navState?.panel,
```

换成：

```tsx
            canvasPanel: navState?.panel,
            canvasFocus: navState?.focus,
            onCanvasFocusDone: clearFilmFocus,
```

在 `frontend/src/App.tsx` 里找到：

```tsx
        runningCount={running.length}
```

换成：

```tsx
        runningCount={running.length + filmAct.live.length}
```

在 `frontend/src/App.tsx` 里找到：

```tsx
          <ActivityPanel running={running} done={recentDone} onOpen={openJob}
```

换成：

```tsx
          <ActivityPanel running={running} done={recentDone} onOpen={openJob}
                         film={filmAct} onOpenFilm={(tk, play) => void openFilmTask(tk, play)}
```

- [ ] **Step 9: 运行，确认通过**

运行：`cd frontend && npx vite build --ssr tests/routing.test.tsx --outDir .ssrout --logLevel error && node .ssrout/routing.test.js 2>&1 | tail -4`
预期：通过，输出含 `出片任务：铃铛、面板、跳转与通知 ✓`、`ALL PASS`

运行：`cd frontend && npx vite build --ssr tests/graph-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/graph-view.test.js | tail -2 && npm run typecheck && test "$(npm run lint 2>&1 | grep -c ': warning ')" = 5 && echo lint-ok`
预期：通过，输出含 `ALL PASS`、`lint-ok`

- [ ] **Step 10: 提交**

提交：

```bash
git add frontend/src/types.ts frontend/src/paths.ts frontend/src/useFilm.ts frontend/src/components/TimelineCanvas.tsx frontend/src/components/StoryboardView.tsx frontend/src/App.tsx frontend/tests/graph-view.test.tsx frontend/tests/routing.test.tsx
git commit -m "出片任务接进应用：和转换任务并行巡检，在跑的计入铃铛并列在动态面板，结束时发可点击的桌面通知与页内提示（第一轮只记账、不带厂商名）；点任务、提示或通知回到那一版画布的节点图并选中那一段，完成的顺便打开播放（取消后才出的结果播它自己那一次）；聚焦请求走路由 state，画布用完即清；补画布与路由测试"
```
### Task 10: 个人任务队列的后端——合成任务、取消种类、失败原因、已结束保留一天

把任务列表从「出片片段」扩成本人的任务队列（§8.5）：`GET /render/tasks` 加上成片合成；每条带取消种类（面板里好给取消入口）、所含镜头与可以给普通用户看的失败原因；名字取现在的；已结束的保留一天、最多 30 条。转换任务仍走 `GET /jobs`，补上结束时间、失败原因、现在的名字与「已删除」标记。

**Files:**
- Modify: `backend/server/app.py`
- Test: `backend/tests/server/test_film_tasks.py`
- Modify: `backend/tests/server/test_i18n_scan.py`（新函数进扫描名单）

- [ ] **Step 1: 写失败的测试**

在 `backend/tests/server/test_film_tasks.py` 里找到：

```python
    print("7. 自由节点 ✓")

    print("\nALL PASS")
```

换成：

```python
    print("7. 自由节点 ✓")

    # 8. 取消种类：还没提交是 free，已提交是 paid；结束的没有
    z = c.get(R + "/session", headers=H).json()["clips"][2]["id"]
    row = lambda iid: next(t for t in tasks() if t["id"] == f"v1:{iid}")  # noqa: E731
    c.post(R + f"/clips/{z}/run", headers=H, json={})
    assert row(z)["cancel"] == "free" and row(z)["error"] is None and row(z)["step"] is None
    sess_z = pick(c.get(R + "/session", headers=H).json(), z)
    assert row(z)["shot_ids"] == sess_z["shots"] and len(sess_z["shots"]) >= 1, "带上这一段含哪些镜头"
    runner.tick()
    assert row(z)["state"] == "running" and row(z)["cancel"] == "paid"
    FAKE.cancel_ok = True
    assert c.post(R + f"/clips/{z}/cancel", headers=H).json()["cancel_outcome"] == "cancelled"
    FAKE.cancel_ok = False
    assert row(z)["state"] == "cancelled" and row(z)["cancel"] is None
    print("8. 取消种类 ✓")

    # 9. 失败原因：能给普通用户看的才给；带厂商原话或厂商名的不给（列表里只写失败）
    def fail_with(err):
        with render_session.mutate(root) as ss:
            cz = next(k for k in ss["clips"] if k["id"] == z)
            cz["state"] = "failed"
            render_session.set_error(cz, err)
            render_session._ended(cz, "failed")
        return row(z)

    t = fail_with(msg("film.download.not_playable"))
    assert t["state"] == "failed" and t["error"]["code"] == "film.download.not_playable" and t["error"]["message"]
    assert fail_with("视频服务（MiniMax）超时")["error"] is None
    assert fail_with("fake-1 不可用")["error"] is None, "会话的模型名也算"
    with render_session.mutate(root) as ss:
        cz = next(k for k in ss["clips"] if k["id"] == z)
        cz["error_msg"] = {"code": "film.download.not_playable", "params": {"detail": {"t": "vendor", "text": "x"}}}
        cz["error"] = "下载的文件不能播放"
    assert row(z)["error"] is None, "带厂商原话的不给"
    print("9. 失败原因 ✓")

    # 10. 成片合成也在队列里：合成中带步骤、不能取消、没有通常时长；结束后带结局与失败原因；一个版本只有一条
    render_session.begin_compose(root, fingerprint="fp", tts_cny=0.0, draft=True)
    t = row("compose")
    assert (t["kind"], t["item_id"], t["state"]) == ("compose", "compose", "running")
    assert t["step"]["code"] == "compose.step.start" and t["cancel"] is None and t["typical_sec"] is None
    assert isinstance(t["elapsed_sec"], int) and t["ended_at"] is None and tasks()[0]["id"] == "v1:compose"
    assert t["shot_ids"] == [] and (t["work_title"], t["chapter"]) == ("药", "第一章")
    assert tasks(HB) == []
    render_session.compose_failed(root, msg("compose.interrupted"))
    t = row("compose")
    assert t["state"] == "failed" and t["ended_at"] and t["error"]["code"] == "compose.interrupted" and t["step"] is None
    render_session.begin_compose(root, fingerprint="fp", tts_cny=0.0, draft=True)
    render_session.compose_done(root, ["final/a.mp4"], "ok")
    assert [(t["state"], t["error"]) for t in tasks() if t["kind"] == "compose"] == [("done", None)]
    print("10. 成片合成 ✓")

    # 11. 已结束的最多返回这么多条，最新的在前
    ended = [t for t in tasks() if t["ended_at"]]
    assert len(ended) >= 3 and [t["ended_at"] for t in ended] == sorted((t["ended_at"] for t in ended), reverse=True)
    app_mod.FILM_RECENT_MAX = 2
    assert [t["id"] for t in tasks() if t["ended_at"]] == [t["id"] for t in ended[:2]]
    app_mod.FILM_RECENT_MAX = 30
    print("11. 已结束的条数上限 ✓")

    # 12. 转换任务（/jobs）带结束时间与失败原因；同样不带厂商名
    job = {"id": "jb1", "user_id": alice, "status": "queued", "log": [], "progress": {}, "created_at": "2026-11-21T00:00:00+00:00"}

    def boom(*_a, **_k):
        job["status"] = "failed"
        render_session.set_error(job, msg("compose.interrupted"))
        raise RuntimeError("x")

    saved = app_mod._execute
    app_mod._execute = boom
    try:
        app_mod._run_version_job(job, alice, nid, cid, "原文", type("P", (), {"work_title": "药"})(), False)
    except RuntimeError:
        pass
    finally:
        app_mod._execute = saved
    assert job.get("finished_at"), "转换结束（哪怕抛异常）都记结束时间"
    app_mod._jobs["jb1"] = job
    (j,) = [x for x in c.get("/jobs", headers=H).json()["jobs"] if x["id"] == "jb1"]
    assert j["finished_at"] == job["finished_at"] and j["error_msg"]["code"] == "compose.interrupted"
    render_session.set_error(job, "大模型（MiniMax）超时")
    (j,) = [x for x in c.get("/jobs", headers=H).json()["jobs"] if x["id"] == "jb1"]
    assert j["error_msg"] is None
    print("12. 转换任务的结束时间与失败原因 ✓")

    # 13. 名字取现在的：小说、章节改名后队列跟着变；章节删掉后转换任务留原名并标已删除，出片任务随会话一起消失
    job.update(novel_id=nid, chapter_id=cid, work_title="旧书名", chapter="旧章名")
    novels.update_novel(alice, nid, title="药（修订）")
    novels.update_chapter(alice, nid, cid, title="第一章 华老栓")
    (j,) = [x for x in c.get("/jobs", headers=H).json()["jobs"] if x["id"] == "jb1"]
    assert (j["work_title"], j["chapter"], j["deleted"]) == ("药（修订）", "第一章 华老栓", False)
    assert {(t["work_title"], t["chapter"]) for t in tasks()} == {("药（修订）", "第一章 华老栓")}
    novels.delete_chapter(alice, nid, cid)
    (j,) = [x for x in c.get("/jobs", headers=H).json()["jobs"] if x["id"] == "jb1"]
    assert (j["work_title"], j["chapter"], j["deleted"]) == ("药（修订）", "旧章名", True)
    assert tasks() == [], "章节删了，它的出片任务不再出现（不报错）"
    del app_mod._jobs["jb1"]
    print("13. 现在的名字与已删除 ✓")

    print("\nALL PASS")
```

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && .venv/bin/python tests/server/test_film_tasks.py`
预期：失败，输出含 `KeyError`

- [ ] **Step 3: 转换任务记结束时间，/jobs 带上它与失败原因**

在 `backend/server/app.py` 里找到：

```python
    _execute(job, text, params, strict, seed,
             lambda status, **f: novels.update_version_state(
                 user_id, nid, cid, job["id"], status, **f),
             after_success, numbering, context)
```

换成：

```python
    try:
        _execute(job, text, params, strict, seed,
                 lambda status, **f: novels.update_version_state(
                     user_id, nid, cid, job["id"], status, **f),
                 after_success, numbering, context)
    finally:
        job["finished_at"] = store.now_iso()     # 任务队列的「已结束」按它排序、显示
```

在 `backend/server/app.py` 里找到：

```python
@app.get("/jobs")
def list_jobs(user: dict = Depends(current_user)):
```

换成：

```python
def _job_where(uid: str, j: dict) -> dict:
    """任务队列里这条转换任务属于哪本小说、哪一章：名字取现在的（改名后跟着变）；小说或章节已删除时
    留提交时的名字并标 deleted。旧接口提交的任务（没有小说）原样。"""
    nid, cid = j.get("novel_id"), j.get("chapter_id")
    if not nid:
        return {"deleted": False}
    title, chapter = novels.titles(uid, nid, cid)
    return {"work_title": title or j.get("work_title"), "chapter": chapter or j.get("chapter"),
            "deleted": title is None or (bool(cid) and chapter is None)}


@app.get("/jobs")
def list_jobs(user: dict = Depends(current_user)):
```

在 `backend/server/app.py` 里找到：

```python
        "progress": _progress_view(j),
    } for j in sorted(jobs, key=lambda x: x.get("created_at") or "", reverse=True)]}
```

换成：

```python
        "progress": _progress_view(j),
        "finished_at": j.get("finished_at"),
        "error_msg": _public_error(j) if j["status"] == "failed" else None,
        **_job_where(user["id"], j),
    } for j in sorted(jobs, key=lambda x: x.get("created_at") or "", reverse=True)]}
```

- [ ] **Step 4: 任务列表——保留一天、失败原因、取消种类、成片合成**

在 `backend/server/app.py` 里找到：

```python
FILM_RECENT_SEC = 600       # 任务列表里「最近结束」保留多久（秒）
```

换成：

```python
FILM_RECENT_SEC = 86400     # 任务列表里「已结束」保留多久（秒）：一天
FILM_RECENT_MAX = 30        # 已结束的最多返回多少条（最新的在前）
_VENDOR_WORDS = re.compile(r"minimax|seedance|hailuo|doubao|volc|\bark\b|方舟|海螺|豆包|火山", re.I)  # i18n: internal


def _has_vendor_text(v) -> bool:
    """消息参数里有没有厂商原话（vendor(...) 包过的值）。"""
    if isinstance(v, dict):
        return v.get("t") == "vendor" or any(_has_vendor_text(x) for x in v.values())
    if isinstance(v, list):
        return any(_has_vendor_text(x) for x in v)
    return False


def _public_error(obj: dict, *names) -> Optional[dict]:
    """任务队列里给普通用户看的失败原因或步骤（消息对象，前端按语言渲染）。obj 带 error / error_msg。
    带厂商原话、或文字里出现厂商名、模型名（names：这个会话的厂商与模型）的不给：队列里只写结局，
    原因到任务所在的页面看。"""
    m, text = obj.get("error_msg"), obj.get("error") or ""
    if not m and not text:
        return None
    if _has_vendor_text((m or {}).get("params") or {}) or _VENDOR_WORDS.search(text):
        return None
    if any(n and str(n).lower() in text.lower() for n in names):
        return None
    return {"code": m["code"], "params": m.get("params") or {}, "message": text} if m else {"message": text}


def _cancel_kind(c: dict) -> Optional[str]:
    """在跑的一条现在能怎么取消：free = 还没提交，取消不花钱；paid = 已提交，取消不了就是不等了；None = 现在不能取消。
    与 render_session._cancel_check 同一判断，只是不抛异常。"""
    last = c["attempts"][-1] if c.get("attempts") else None
    if c["state"] == "queued":
        return None if last and last.get("state") == "submitting" else "free"
    if c["state"] == "running" and last and last.get("task_id"):
        return "paid"
    return None
```

在 `backend/server/app.py` 里找到：

```python
                   "work_title": title, "chapter": chapter, "typical_sec": typical,
                   "ended_at": None, "elapsed_sec": None, "cost_cny": None}
```

换成：

```python
                   "work_title": title, "chapter": chapter, "typical_sec": typical,
                   "ended_at": None, "elapsed_sec": None, "cost_cny": None,
                   "cancel": None, "error": None, "step": None,
                   "shot_ids": list(c.get("shots") or c.get("target_shots") or [])}
```

在 `backend/server/app.py` 里找到：

```python
                out.append({**row, "state": c["state"],
                            "elapsed_sec": max(0, round(now - queued)) if queued else None})
            elif ended is not None and ended >= since and c.get("ended_as"):
                out.append({**row, "state": c["ended_as"], "ended_at": c["ended_at"],
                            "elapsed_sec": max(0, round(ended - queued)) if queued else None})
```

换成：

```python
                out.append({**row, "state": c["state"], "cancel": _cancel_kind(c),
                            "elapsed_sec": max(0, round(now - queued)) if queued else None})
            elif ended is not None and ended >= since and c.get("ended_as"):
                out.append({**row, "state": c["ended_as"], "ended_at": c["ended_at"],
                            "elapsed_sec": max(0, round(ended - queued)) if queued else None,
                            "error": (_public_error(c, s.get("provider"), s.get("model"))
                                      if c["ended_as"] == "failed" else None)})
```

在 `backend/server/app.py` 里找到：

```python
    live = [t for t in out if t["ended_at"] is None]
    past = sorted((t for t in out if t["ended_at"] is not None), key=lambda t: t["ended_at"], reverse=True)
    return live + past
```

换成：

```python
        # 成片合成：一个版本一条。合成中带当前步骤；没有进度百分比、没有通常时长，也不能取消
        f = s.get("final") or {}
        row = {"id": f'{o.get("vid")}:compose', "item_id": "compose", "kind": "compose",
               "novel_id": o.get("nid"), "chapter_id": o.get("cid"), "version_id": o.get("vid"),
               "work_title": title, "chapter": chapter, "typical_sec": None,
               "ended_at": None, "elapsed_sec": None, "cost_cny": None,
               "cancel": None, "error": None, "step": None, "shot_ids": []}
        started, finished = _iso_ts(f.get("started_at")), _iso_ts(f.get("finished_at"))
        names = (s.get("provider"), s.get("model"))
        if f.get("state") in render_session.COMPOSE_BUSY:
            out.append({**row, "state": f["state"],
                        "step": _public_error({"error_msg": f.get("step_msg"), "error": f.get("step")}, *names),
                        "elapsed_sec": max(0, round(now - started)) if started else None})
        elif f.get("state") in ("done", "failed") and finished is not None and finished >= since:
            out.append({**row, "state": f["state"], "ended_at": f["finished_at"],
                        "elapsed_sec": max(0, round(finished - started)) if started else None,
                        "error": _public_error(f, *names) if f["state"] == "failed" else None})
    live = [t for t in out if t["ended_at"] is None]
    past = sorted((t for t in out if t["ended_at"] is not None), key=lambda t: t["ended_at"], reverse=True)
    return live + past[:FILM_RECENT_MAX]
```

在 `backend/server/app.py` 里找到：

```python
    """本人的出片任务（任务铃铛与动态面板用）。每项：id、item_id、kind（clip / free）、novel_id、chapter_id、
    version_id、work_title、chapter、state（queued / running / downloading / done / failed / cancelled / late）、
    elapsed_sec、typical_sec、ended_at、cost_cny（只有 late 有）。"""
```

换成：

```python
    """本人的出片与合成任务（任务铃铛与任务面板用；转换任务在 /jobs）。在跑的在前，已结束的保留一天、最多
    FILM_RECENT_MAX 条。每项：id、item_id、kind（clip / free / compose）、novel_id、chapter_id、version_id、
    work_title、chapter、state（queued / running / downloading / done / failed / cancelled / late）、elapsed_sec、
    typical_sec（合成没有）、ended_at、cost_cny（只有 late 有）、cancel（free / paid / null）、
    error（失败原因，消息对象，不能给普通用户看的为 null）、step（合成的当前步骤）、shot_ids（这一段含哪些镜头；
    自由节点为它挂靠的那一段的镜头，合成为空）。work_title、chapter 是现在的名字（改名后跟着变），读不到为 null。
    不带厂商与档位。"""
```

在 `backend/tests/server/test_i18n_scan.py` 里找到：

```python
                      "_film_cancel", "render_clip_cancel", "render_free_cancel", "_film_tasks", "render_tasks",
```

换成：

```python
                      "_film_cancel", "render_clip_cancel", "render_free_cancel", "_film_tasks", "render_tasks",
                      "_has_vendor_text", "_public_error", "_cancel_kind", "_job_where",
```

- [ ] **Step 5: 运行，确认通过**

运行：`cd backend && .venv/bin/python tests/server/test_film_tasks.py`
预期：通过，输出含 `13. 现在的名字与已删除 ✓`、`ALL PASS`

运行：`cd backend && for t in tests/server/test_i18n_scan.py tests/server/test_jobs.py tests/server/test_novels.py tests/server/test_render.py tests/server/test_compose.py tests/server/test_assistant_ops.py; do .venv/bin/python $t > /dev/null 2>&1 || echo "FAILED $t"; done; echo checked`
预期：通过，输出含 `checked`，不含 `FAILED`

- [ ] **Step 6: 提交**

提交：

```bash
git add backend/server/app.py backend/tests/server/test_film_tasks.py backend/tests/server/test_i18n_scan.py
git commit -m "任务列表扩成个人任务队列的后端：/render/tasks 加成片合成（合成中带步骤），每条带取消种类与可以给普通用户看的失败原因（带厂商原话或厂商名的不给），已结束的保留一天、最多 30 条；每条带所含镜头，名字取现在的；转换任务记结束时间，/jobs 带结束时间、失败原因、现在的名字与已删除标记；补测试"
```
### Task 11: 个人任务队列的前端——一个面板两个区，定位到小说 › 章节 › 片段，面板里可取消

任务面板（铃铛点开的那个，任何页面都能开）改成本人的任务队列（§8.5）：「进行中」与「已结束」两个区，转换、出片片段、成片合成都在里面。每条第一行是定位（小说 › 章节 › 片段 · 镜号范围；转换与合成到章为止；名字读不到写「已删除」），窄了截断、悬停看全称。进行中的出片任务可以直接在面板里取消（确认框与画布上同一套）。已结束的带结束时间与失败原因，转换任务的已结束列表改为同时从 `/jobs` 取（刷新页面后还在）。

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`
- Modify: `frontend/src/filmTasks.ts`
- Modify: `frontend/src/components/shell/ActivityPanel.tsx`（整个换掉）
- Modify: `frontend/src/App.tsx`
- Test: `frontend/tests/film-tasks.test.tsx`（整个换掉）
- Test: `frontend/tests/workspace.test.tsx`、`frontend/tests/routing.test.tsx`

- [ ] **Step 1: 换掉任务队列的测试**

把 `frontend/tests/film-tasks.test.tsx` 整个换成：

```tsx
/** 个人任务队列：纯计算（哪些在跑、哪些要播报、名字与定位、等待文字、已结束的合并与排序）、可点击的桌面通知、
 *  任务面板里的进行中与已结束（转换、出片片段、成片合成）。
 *  应用里的轮询、铃铛计数与跳转由 routing.test.tsx 覆盖。跑法：npm test */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'MouseEvent', 'matchMedia', 'ResizeObserver', 'DOMRect',
                 'MutationObserver', 'NodeFilter']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame = (cb: (t: number) => void) =>
  setTimeout(() => cb(performance.now()), 16) as unknown as number
g.cancelAnimationFrame = (id: number) => clearTimeout(id)

import type { FilmTask } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const task = (over: Partial<FilmTask> = {}): FilmTask => ({
  id: 'v1:E01-C01', item_id: 'E01-C01', kind: 'clip', novel_id: 'n1', chapter_id: 'c1', version_id: 'v1',
  work_title: '药', chapter: '第一章', state: 'running', elapsed_sec: 245, typical_sec: [180, 420],
  ended_at: null, cost_cny: null, cancel: null, error: null, step: null,
  shot_ids: ['E01-SH001', 'E01-SH002', 'E01-SH003'], ...over,
})

const {
  clockText, diffFilmTasks, endedItems, isLiveTask, jobWhere, lateTaskId, mergeDoneJobs, onFilmPoke, pokeFilmTasks,
  shotRange, taskName, taskWait, taskWhere,
} = await import('../src/filmTasks')

// 1. 名字与等待文字：服务端给的已等秒数加上取回之后过去的时间
{
  must(taskName(task()) === '药 · 第一章 · E01-C01', `名字：${taskName(task())}`)
  must(taskName(task({ work_title: null, chapter: null })) === 'E01-C01', '标题缺失时只写片段')
  must(taskWait(task(), 1000, 1000) === '已等 4 分 05 秒 · 通常 3–7 分钟', `等待：${taskWait(task(), 1000, 1000)}`)
  must(taskWait(task(), 1000, 6000) === '已等 4 分 10 秒 · 通常 3–7 分钟', '取回之后接着走')
  must(taskWait(task({ elapsed_sec: null }), 1000, 3000) === '已等 0 分 02 秒 · 通常 3–7 分钟', '没有已等秒数从 0 算')
  must(isLiveTask(task({ state: 'queued' })) && isLiveTask(task({ state: 'downloading' }))
       && !isLiveTask(task({ state: 'done' })) && !isLiveTask(task({ state: 'late' })), '在跑的三种状态')
  must(lateTaskId(task({ id: 'v1:E01-C01:t9', state: 'late' })) === 't9' && lateTaskId(task()) === undefined,
       '取消后才出结果的那条带着厂商任务号，其它没有')
  let poked = 0
  const off = onFilmPoke(() => { poked += 1 })
  pokeFilmTasks()
  off()
  pokeFilmTasks()
  must(poked === 1, '出片操作之后催一次任务列表；退订后不再收到')
  console.log('1. 名字与等待文字 ✓')
}

// 1b. 定位：小说 › 章节 › 片段 · 镜号范围；名字读不到写「已删除」；合成与转换到章为止
{
  must(taskWhere(task()) === '药 › 第一章 › E01-C01 · SH001–SH003', `片段：${taskWhere(task())}`)
  must(shotRange(['E01-SH004']) === 'SH004' && shotRange([]) === '', '一个镜头不写范围，没有镜头不写')
  must(taskWhere(task({ item_id: 'F01', kind: 'free', shot_ids: [] })) === '药 › 第一章 › F01', '没有镜头的只写编号')
  must(taskWhere(task({ work_title: null, chapter: null })) === '已删除 › 已删除 › E01-C01 · SH001–SH003', '名字读不到：占位')
  const compose = task({ id: 'v1:compose', item_id: 'compose', kind: 'compose', shot_ids: [], typical_sec: null })
  must(taskWhere(compose) === '药 › 第一章 › 成片合成' && taskName(compose) === '药 · 第一章 · 成片合成', '合成到章为止')
  must(taskWait({ ...compose, elapsed_sec: 65 }, 0, 0) === '已等 1 分 05 秒', '合成没有通常时长')
  must(jobWhere({ work_title: '药', chapter: '第一章' }) === '药 › 第一章', '转换到章为止')
  must(jobWhere({ work_title: '药', chapter: '第一章', deleted: true }) === '药 › 第一章（已删除）', '已删除的转换任务留名并标出')
  must(jobWhere({ work_title: null, chapter: null }) === '转换中', '旧任务没有名字')
  console.log('1b. 定位 ✓')
}

// 1c. 已结束的：转换与出片合在一起按结束时间倒序；没有时间的（刚结束、应用自己记下的）排最前；最多 20 条
{
  const dj = (id: string, finished_at?: string) => ({ id, status: 'succeeded' as const, work_title: '药', chapter: id, finished_at })
  const tk = (id: string, ended_at: string) => task({ id, state: 'done', ended_at })
  const got = endedItems([dj('a', '2026-11-21T03:00:00+00:00'), dj('b'), dj('c', '2026-11-21T01:00:00+00:00')],
                         [tk('x', '2026-11-21T04:00:00+00:00'), tk('y', '2026-11-21T02:00:00+00:00')])
  must(got.map((it) => it.job?.id ?? it.task?.id).join() === 'b,x,a,y,c', `顺序：${got.map((it) => it.job?.id ?? it.task?.id)}`)
  const many = Array.from({ length: 30 }, (_, i) => tk(`t${i}`, `2026-11-21T03:${String(i).padStart(2, '0')}:00+00:00`))
  must(endedItems([], many).length === 20 && endedItems([], many)[0].task?.id === 't29', '最多 20 条，留最新的')

  // 转换任务：/jobs 里已结束、带结束时间的并进来（刷新页面后还在）；应用记下的那条补上结束时间与失败原因；在跑的不算
  const sj = (id: string, status: string, o: object = {}) => ({ id, status, created_at: null, work_title: '药', chapter: id,
    chars: 1, log_lines: 0, last_log: null, ...o }) as unknown as import('../src/types').JobSummary
  const merged = mergeDoneJobs([dj('a')], [
    sj('a', 'failed', { finished_at: '2026-11-21T03:00:00+00:00', error_msg: { code: 'x', message: '原因' }, deleted: true }),
    sj('b', 'succeeded', { finished_at: '2026-11-21T05:00:00+00:00' }), sj('c', 'running'), sj('d', 'succeeded')])
  must(merged.map((d) => d.id).join() === 'b,a', `合并：${merged.map((d) => d.id)}`)
  must(merged[1].status === 'failed' && merged[1].finished_at === '2026-11-21T03:00:00+00:00' && merged[1].deleted === true
       && (merged[1].error_msg as { message: string }).message === '原因', '应用记下的那条补全')
  const noon = new Date(2026, 10, 21, 12, 0)
  must(clockText(new Date(2026, 10, 21, 9, 5).toISOString(), noon) === '09:05'
       && clockText(new Date(2026, 10, 20, 23, 40).toISOString(), noon) === '11-20 23:40'
       && clockText(null) === '' && clockText('乱写') === '', '结束时间：当天只写时分，隔天带日期')
  console.log('1c. 已结束的合并与排序 ✓')
}

// 2. 播报：登录后的第一轮只记账；之后新结束的各播一次；取消的不播；同一段再出一次、再结束照常播
{
  const seen = new Set<string>()
  const done = task({ state: 'done', ended_at: '2026-11-21T03:00:00+00:00', elapsed_sec: 280 })
  const first = diffFilmTasks([task({ id: 'v1:E01-C02', item_id: 'E01-C02' }), done], seen, true)
  must(first.live.length === 1 && first.ended.length === 1 && first.announce.length === 0, '第一轮不播报')
  must(diffFilmTasks([done], seen, false).announce.length === 0, '第一轮见过的之后也不播')
  const next = task({ id: 'v1:E01-C02', item_id: 'E01-C02', state: 'failed', ended_at: '2026-11-21T03:05:00+00:00' })
  const second = diffFilmTasks([done, next], seen, false)
  must(second.announce.length === 1 && second.announce[0].id === 'v1:E01-C02', '新结束的播一次')
  must(diffFilmTasks([done, next], seen, false).announce.length === 0, '不重复播')
  const cancelled = task({ id: 'v1:E01-C03', state: 'cancelled', ended_at: '2026-11-21T03:06:00+00:00' })
  must(diffFilmTasks([cancelled], seen, false).announce.length === 0, '自己取消的不播')
  const late = task({ id: 'v1:E01-C03:t9', state: 'late', ended_at: '2026-11-21T03:09:00+00:00', cost_cny: 7.5 })
  must(diffFilmTasks([cancelled, late], seen, false).announce[0]?.state === 'late', '取消后才出结果的要播')
  const again = { ...done, ended_at: '2026-11-21T03:20:00+00:00' }
  must(diffFilmTasks([again], seen, false).announce.length === 1, '同一段再出一次、再结束：照常播')
  console.log('2. 播报 ✓')
}

// 3. 桌面通知：带标签；给了点击回调时，点通知先把窗口拉到前面再执行
{
  const made: { title: string; opts: { body: string; tag: string }; onclick: (() => void) | null; closed: boolean }[] = []
  class FakeNotification {
    static permission = 'granted'
    static requestPermission = async () => 'granted'
    onclick: (() => void) | null = null
    closed = false
    title: string
    opts: { body: string; tag: string }
    constructor(title: string, opts: { body: string; tag: string }) {
      this.title = title
      this.opts = opts
      made.push(this)
    }
    close() { this.closed = true }
  }
  g.Notification = FakeNotification
  ;(win as unknown as Record<string, unknown>).Notification = FakeNotification
  let focused = 0
  ;(win as unknown as { focus: () => void }).focus = () => { focused += 1 }
  const { notify } = await import('../src/notify')
  notify('转换完成', '药 第一章')
  must(made[0].opts.tag === 'storyboard-job' && made[0].onclick === null, '不给回调：老样子')
  let clicked = 0
  notify('片段已生成', '药 · 第一章 · E01-C01', { tag: 'film-v1:E01-C01', onClick: () => { clicked += 1 } })
  must(made[1].opts.tag === 'film-v1:E01-C01' && made[1].opts.body === '药 · 第一章 · E01-C01', '标签与正文')
  made[1].onclick!()
  must(clicked === 1 && focused === 1 && made[1].closed, '点通知：拉到前面、关掉通知、执行回调')
  console.log('3. 可点击的通知 ✓')
}

// 4. 任务面板：进行中（转换、出片、合成）与已结束两区；定位行悬停有全称；可取消的有取消入口；失败带原因；点击带着是否播放回调
{
  const { act } = await import('react')
  const { createRoot } = await import('react-dom/client')
  const { ActivityPanel } = await import('../src/components/shell/ActivityPanel')
  const { I18nProvider } = await import('../src/i18n')
  const container = win.document.createElement('div')
  win.document.body.appendChild(container)
  const root = createRoot(container as unknown as HTMLElement)
  const opened: [string, boolean][] = []
  const cancelled: string[] = []
  const live = [
    task({ cancel: 'paid' }),
    task({ id: 'v1:F01', item_id: 'F01', kind: 'free', state: 'queued', elapsed_sec: 5, cancel: 'free', shot_ids: [] }),
    task({ id: 'v1:compose', item_id: 'compose', kind: 'compose', elapsed_sec: 65, typical_sec: null, shot_ids: [],
           step: { code: 'compose.step.start', params: {}, message: '准备合成' } }),
  ]
  const ended = [
    task({ id: 'v1:E01-C02', item_id: 'E01-C02', state: 'done', ended_at: '2026-11-21T03:00:00+00:00' }),
    task({ id: 'v1:E01-C03', item_id: 'E01-C03', state: 'failed', ended_at: '2026-11-21T02:59:00+00:00',
           error: { message: '下载的文件不能播放' } }),
    task({ id: 'v1:E01-C04:t9', item_id: 'E01-C04', state: 'late', ended_at: '2026-11-21T02:58:00+00:00', cost_cny: 7.5 }),
    task({ id: 'v1:E01-C05', item_id: 'E01-C05', state: 'cancelled', ended_at: '2026-11-21T02:57:00+00:00' }),
    task({ id: 'v1:E01-C06', item_id: 'E01-C06', state: 'failed', ended_at: '2026-11-21T02:56:00+00:00' }),
    task({ id: 'v2:compose', item_id: 'compose', kind: 'compose', state: 'done', typical_sec: null, shot_ids: [],
           ended_at: '2026-11-21T02:55:00+00:00' }),
  ]
  const job = { id: 'j1', status: 'running', created_at: null, work_title: '雾港', chapter: '第二章', chars: 100, log_lines: 1,
    last_log: null, novel_id: 'n2', chapter_id: 'c2',
    progress: { batches: 4, batch: 2, total_chars: 100, done_chars: 40, attempt: 1, max_attempts: 3, phase: 'checking',
                elapsed_sec: 30, eta_sec: 150 } } as unknown as import('../src/types').JobSummary
  const doneJob = { id: 'j0', status: 'failed' as const, work_title: '雾港', chapter: '第一章', deleted: true,
    finished_at: '2026-11-21T02:58:30+00:00', error_msg: { message: '本章还没有原文' } }
  const panel = (film?: { live: FilmTask[]; ended: FilmTask[]; at: number }, withJobs = false) => (
    <I18nProvider initial="zh">
      <ActivityPanel running={withJobs ? [job] : []} done={withJobs ? [doneJob] : []} onOpen={() => {}} onClose={() => {}} film={film}
                     onOpenFilm={(tk, play) => opened.push([tk.id, play])} onCancelFilm={(tk) => cancelled.push(tk.id)} />
    </I18nProvider>
  )
  await act(async () => { root.render(panel()) })
  must((container.textContent ?? '').includes('没有在跑的任务'), '没有任何任务时是空状态')
  await act(async () => { root.render(panel({ live, ended, at: Date.now() }, true)) })
  const text = container.textContent ?? ''
  must(!text.includes('没有在跑的任务'), '有任务就不是空状态')
  const zone = (id: string) => container.querySelector(`[data-testid="${id}"]`)!
  must((zone('queue-running').querySelector('h3')?.textContent ?? '') === '进行中'
       && (zone('queue-ended').querySelector('h3')?.textContent ?? '') === '已结束', '两个区')
  must(zone('queue-running').querySelectorAll('li').length === 4 && zone('queue-ended').querySelectorAll('li').length === 7,
       '进行中 4 条（1 转换 + 3 出片与合成），已结束 7 条（1 转换 + 6 出片与合成）')
  must(!!zone('queue-running').querySelector('[data-testid="activity-running"] [role="progressbar"]'), '转换任务带进度条')
  const running = [...container.querySelectorAll('[data-testid="activity-film-running"]')]
  const whereOf = (el: Element) => el.querySelector('[data-testid="activity-where"]')!
  must(whereOf(running[0]).textContent === '药 › 第一章 › E01-C01 · SH001–SH003'
       && whereOf(running[0]).getAttribute('title') === '药 › 第一章 › E01-C01 · SH001–SH003'
       && (whereOf(running[0]).getAttribute('class') ?? '').includes('truncate'), `定位行：可截断，悬停有全称：${whereOf(running[0]).textContent}`)
  must((running[0].textContent ?? '').includes('生成中')
       && /已等 4 分 0\d 秒 · 通常 3–7 分钟/.test(running[0].textContent ?? ''), `在跑的一条：${running[0].textContent}`)
  must((running[1].textContent ?? '').includes('排队中') && whereOf(running[1]).textContent === '药 › 第一章 › F01', '排队中的自由节点')
  must(whereOf(running[2]).textContent === '药 › 第一章 › 成片合成' && (running[2].textContent ?? '').includes('合成中')
       && /已等 1 分 0\d 秒/.test(running[2].textContent ?? '') && !(running[2].textContent ?? '').includes('通常'),
       `合成：步骤与已等，没有通常时长：${running[2].textContent}`)
  const cancelBtns = running.map((li) => li.querySelector('[data-testid="activity-film-cancel"]'))
  must(cancelBtns[0]?.textContent === '不等了' && cancelBtns[1]?.textContent === '取消' && !cancelBtns[2], '可取消的才有取消入口；合成没有')
  must(!/minimax|seedance|fake|假厂商/i.test(text), '面板里不出现厂商名')
  const endedLis = [...zone('queue-ended').querySelectorAll('li')]
  must(endedLis.map((li) => li.getAttribute('data-testid') === 'activity-done' ? 'job' : 'task').join()
       === 'task,task,job,task,task,task,task', '转换与出片按结束时间混排')
  const done = [...container.querySelectorAll('[data-testid="activity-film-done"]')]
  must((done[0].textContent ?? '').includes('已生成') && (done[1].textContent ?? '').includes('生成失败')
       && (done[2].textContent ?? '').includes('取消后仍生成完成') && (done[2].textContent ?? '').includes('¥7.50')
       && (done[3].textContent ?? '').includes('已取消') && (done[5].textContent ?? '').includes('已合成'), '各种结局的标签')
  must(/\d\d:\d\d/.test(done[0].textContent ?? ''), '已结束的带结束时间')
  must(done[1].querySelector('[data-testid="activity-reason"]')?.textContent === '下载的文件不能播放'
       && done[4].querySelector('[data-testid="activity-reason"]')?.textContent === '点开查看原因'
       && !done[0].querySelector('[data-testid="activity-reason"]'), '失败的带原因；原因不能给的写「点开查看原因」')
  const jobLi = container.querySelector('[data-testid="activity-done"]')!
  must(whereOf(jobLi).textContent === '雾港 › 第一章（已删除）'
       && jobLi.querySelector('[data-testid="activity-reason"]')?.textContent === '本章还没有原文', `已结束的转换任务：${jobLi.textContent}`)
  const press = async (el: Element) => {
    await act(async () => { el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
  }
  await press(cancelBtns[0]!)
  await press(cancelBtns[1]!)
  must(cancelled.join() === 'v1:E01-C01,v1:F01' && opened.length === 0, '点取消：交给上层，不触发查看')
  await press([...running[0].querySelectorAll('button')].find((b) => b.textContent === '查看')!)
  for (const li of done) await press(li.querySelector('button')!)
  must(JSON.stringify(opened) === JSON.stringify([
    ['v1:E01-C01', false], ['v1:E01-C02', true], ['v1:E01-C03', false], ['v1:E01-C04:t9', true], ['v1:E01-C05', false],
    ['v1:E01-C06', false], ['v2:compose', false],
  ]), `点击回调：${JSON.stringify(opened)}`)
  await act(async () => { root.unmount() })
  console.log('4. 任务面板 ✓')
}

console.log('\nALL PASS')
```

在 `frontend/tests/workspace.test.tsx` 里找到：

```ts
  must(r0.includes('雾港 · 第1章') && r0.includes('第 2 批校验中') && r0.includes('3 分'), '在跑项内容：' + r0)
```

换成：

```ts
  must(r0.includes('雾港 › 第1章') && r0.includes('第 2 批校验中') && r0.includes('3 分'), '在跑项内容：' + r0)
```

- [ ] **Step 2: 应用层的测试——面板里取消、合成任务的通知与跳转**

在 `frontend/tests/routing.test.tsx` 里找到：

```ts
  if (path === '/render/tasks') return json({ tasks: filmTasks })
```

换成：

```ts
  if (path === '/render/tasks') return json({ tasks: filmTasks })
  if (method === 'POST' && /\/render\/(clips|free)\/[^/]+\/cancel$/.test(path)) {
    cancelCalls.push(path)
    return json({ cancel_outcome: 'abandoned', clips: [], free: [] })
  }
```

在 `frontend/tests/routing.test.tsx` 里找到：

```ts
/** 本人的出片任务（GET /render/tasks 原样返回） */
let filmTasks: unknown[] = []
```

换成：

```ts
/** 本人的出片任务（GET /render/tasks 原样返回） */
let filmTasks: unknown[] = []
/** 收到的取消请求（路径） */
const cancelCalls: string[] = []
```

在 `frontend/tests/routing.test.tsx` 里找到：

```ts
  filmTasks = [task()]
  await poke()
  must(a.q('[data-testid="activity-count"]')?.textContent === '1', '在跑的出片任务计入铃铛')
```

换成：

```ts
  filmTasks = [task({ cancel: 'paid', shot_ids: ['E01-SH001', 'E01-SH002'] })]
  await poke()
  must(a.q('[data-testid="activity-count"]')?.textContent === '1', '在跑的出片任务计入铃铛')
```

在 `frontend/tests/routing.test.tsx` 里找到：

```ts
  must(!!row && (row.textContent ?? '').includes('药 · 第一章 · E01-C01') && /已等 4 分 \d\d 秒 · 通常 3–7 分钟/.test(row.textContent ?? ''),
       `动态面板里有这条：${row?.textContent}`)
  must(made.length === 0, '在跑的不发通知')
```

换成：

```ts
  must(!!row && (row.textContent ?? '').includes('药 › 第一章 › E01-C01 · SH001–SH002') && /已等 4 分 \d\d 秒 · 通常 3–7 分钟/.test(row.textContent ?? ''),
       `任务面板里有这条，定位到小说、章节、片段与镜号：${row?.textContent}`)
  must(made.length === 0, '在跑的不发通知')
  // 面板里直接取消：先过确认框（写明可能仍扣费），确认才发请求，然后按结局提示
  const confirmBtn = (ok: boolean) => doc.body.querySelector(`[data-testid="${ok ? 'confirm-ok' : 'confirm-cancel'}"]`) as unknown as HTMLElement
  await click(row!.querySelector('[data-testid="activity-film-cancel"]') as unknown as HTMLElement)
  must((doc.body.querySelector('[data-testid="confirm-dialog"]')?.textContent ?? '').includes('服务商可能仍会生成并扣费')
       && cancelCalls.length === 0, '面板里取消：先确认')
  await click(confirmBtn(false))
  must(cancelCalls.length === 0, '确认框里点取消：不发请求')
  await click(row!.querySelector('[data-testid="activity-film-cancel"]') as unknown as HTMLElement)
  await click(confirmBtn(true))
  must(cancelCalls.join() === '/novels/n1/chapters/c1/versions/v1/render/clips/E01-C01/cancel', `确认后发取消请求：${cancelCalls}`)
```

在 `frontend/tests/routing.test.tsx` 里找到：

```ts
  await b.done()
  ;[g.Notification, wn.Notification, wn.focus] = before
```

换成：

```ts
  // 成片合成也播报；点开到这一章的画布（出片页），不带要选中的片段
  filmTasks = [task({ id: 'v1:compose', item_id: 'compose', kind: 'compose', state: 'done', typical_sec: null,
                      elapsed_sec: 40, ended_at: '2026-11-21T03:12:00+00:00' })]
  await poke()
  must(made.length === 3 && made[2].title === '成片已合成' && made[2].body.includes('药 · 第一章 · 成片合成'),
       `合成完成的通知：${JSON.stringify(made[2])}`)
  await act(async () => { made[2].onclick!() })
  await settle(300)
  must(b.here() === '/novels/n1/chapters/c1/render/canvas' && !focusOf(b.router)?.focus && focusOf(b.router)?.panel === 'film',
       `点合成的通知：到画布的出片页，实际 ${b.here()} ${JSON.stringify(b.router.state.location.state)}`)
  await b.done()
  ;[g.Notification, wn.Notification, wn.focus] = before
```

- [ ] **Step 3: 运行，确认失败**

运行：`cd frontend && npx vite build --ssr tests/film-tasks.test.tsx --outDir .ssrout --logLevel error && node .ssrout/film-tasks.test.js 2>&1 | grep -m1 'Error: ✗\|TypeError'`
预期：通过，输出含 `taskWhere`

- [ ] **Step 4: 类型**

在 `frontend/src/types.ts` 里找到：

```ts
/** 本人的一条出片任务（GET /render/tasks）：在跑的，或最近结束的。不带厂商与档位 */
export interface FilmTask {
  /** <版本>:<段或节点 id>；late 的再加 :<任务 id> */
  id: string
  item_id: string
  kind: 'clip' | 'free'
```

换成：

```ts
/** 本人任务队列里的一条出片或合成任务（GET /render/tasks）：进行中的，或一天内结束的。不带厂商与档位 */
export interface FilmTask {
  /** <版本>:<段或节点 id>；late 的再加 :<任务 id>；合成是 <版本>:compose */
  id: string
  item_id: string
  kind: 'clip' | 'free' | 'compose'
```

在 `frontend/src/types.ts` 里找到：

```ts
  typical_sec: [number, number]
  /** 在跑的为 null */
  ended_at: string | null
  /** 只有 late 有 */
  cost_cny: number | null
}
```

换成：

```ts
  /** 合成没有通常时长 */
  typical_sec: [number, number] | null
  /** 在跑的为 null */
  ended_at: string | null
  /** 只有 late 有 */
  cost_cny: number | null
  /** 现在能怎么取消：free 还没提交（不花钱）、paid 已提交（可能已计费）、null 不能取消 */
  cancel?: 'free' | 'paid' | null
  /** 失败原因（消息对象）；不能给普通用户看的为 null，界面写「点开查看原因」 */
  error?: ServerMsg | { message: string } | null
  /** 合成的当前步骤 */
  step?: ServerMsg | { message: string } | null
  /** 这一段含哪些镜头（自由节点为它挂靠的那一段的；合成为空） */
  shot_ids?: string[]
}
```

在 `frontend/src/types.ts` 里找到：

```ts
  progress?: JobProgress | null
  novel_id?: string | null
  chapter_id?: string | null
}
```

换成：

```ts
  progress?: JobProgress | null
  novel_id?: string | null
  chapter_id?: string | null
  /** 结束时间（在跑的没有） */
  finished_at?: string | null
  /** 失败原因；不能给普通用户看的为 null */
  error_msg?: ServerMsg | { message: string } | null
  /** 所属的小说或章节已删除（名字是提交时的） */
  deleted?: boolean
}
```

- [ ] **Step 5: 文案**

在 `frontend/src/i18n/zh.ts` 里找到：

```ts
    tab: '任务', close: '关闭', running: '在跑', done: '最近完成', view: '查看',
    empty: '没有在跑的任务', emptyHint: '开始转换或出片后，进度会出现在这里',
    film: {
```

换成：

```ts
    tab: '任务', close: '关闭', running: '进行中', done: '已结束', view: '查看',
    empty: '没有在跑的任务', emptyHint: '开始转换或出片后，进度会出现在这里',
    deleted: '已删除', deletedTag: '（已删除）', failedHint: '点开查看原因',
    kind: { compose: '成片合成' },
    compose: { running: '合成中', done: '已合成', failed: '合成失败' },
    film: {
```

在 `frontend/src/i18n/zh.ts` 里找到：

```ts
      filmLateBody: '{who}：服务商已计费 {cost}，结果可以采用',
```

换成：

```ts
      filmLateBody: '{who}：服务商已计费 {cost}，结果可以采用',
      composeDone: '成片已合成',
      composeDoneBody: '{who} 已合成，点开查看',
      composeFailed: '成片合成失败',
      composeFailedBody: '{who}——点开查看原因',
```

在 `frontend/src/i18n/en.ts` 里找到：

```ts
    tab: 'Jobs', close: 'Close', running: 'Running', done: 'Recently finished', view: 'View',
    empty: 'No running jobs', emptyHint: 'Progress shows up here once a conversion or render starts',
    film: {
```

换成：

```ts
    tab: 'Jobs', close: 'Close', running: 'In progress', done: 'Finished', view: 'View',
    empty: 'No running jobs', emptyHint: 'Progress shows up here once a conversion or render starts',
    deleted: 'Deleted', deletedTag: ' (deleted)', failedHint: 'Open it to see why',
    kind: { compose: 'Final cut' },
    compose: { running: 'Composing', done: 'Composed', failed: 'Compose failed' },
    film: {
```

在 `frontend/src/i18n/en.ts` 里找到：

```ts
      filmLateBody: '{who}: the provider charged {cost}; the result can be adopted',
```

换成：

```ts
      filmLateBody: '{who}: the provider charged {cost}; the result can be adopted',
      composeDone: 'Final cut composed',
      composeDoneBody: '{who} is composed. Open it to view.',
      composeFailed: 'Composing the final cut failed',
      composeFailedBody: '{who} — open it to see why',
```

- [ ] **Step 6: 纯计算——定位、已结束的合并与排序、结束时间**

在 `frontend/src/filmTasks.ts` 里找到：

```ts
import { waitLine } from './film'
import type { FilmTask } from './types'
```

换成：

```ts
import type { DoneJob } from './components/shell/ActivityPanel'
import { waitLine } from './film'
import { tr } from './i18n/core'
import { shortShotId } from './shotSheet'
import type { FilmTask, JobSummary } from './types'
```

在 `frontend/src/filmTasks.ts` 里找到：

```ts
export const taskName = (t: FilmTask) => [t.work_title, t.chapter, t.item_id].filter(Boolean).join(' · ')
```

换成：

```ts
export const taskName = (t: FilmTask) =>
  [t.work_title, t.chapter, t.kind === 'compose' ? tr('activity.kind.compose') : t.item_id].filter(Boolean).join(' · ')

/** 「SH001–SH003」：一段所含镜头的短镜号范围；只有一个镜头不写范围，没有镜头为空 */
export const shotRange = (ids: string[]) =>
  (ids.length === 0 ? '' : ids.length === 1 ? shortShotId(ids[0])
    : `${shortShotId(ids[0])}–${shortShotId(ids[ids.length - 1])}`)

/** 任务队列里的定位行：小说 › 章节 › 片段 · 镜号范围（合成到章为止）。名字是服务端给的现在的名字，读不到写「已删除」 */
export function taskWhere(t: FilmTask): string {
  const last = t.kind === 'compose' ? tr('activity.kind.compose')
    : [t.item_id, shotRange(t.shot_ids ?? [])].filter(Boolean).join(' · ')
  return [t.work_title ?? tr('activity.deleted'), t.chapter ?? tr('activity.deleted'), last].join(' › ')
}

/** 转换任务的定位行：小说 › 章节；所属的小说或章节已删除时留名并标出 */
export function jobWhere(j: { work_title: string | null; chapter: string | null; deleted?: boolean }): string {
  const text = [j.work_title || tr('shell.shelf.converting'), j.chapter].filter(Boolean).join(' › ')
  return j.deleted ? text + tr('activity.deletedTag') : text
}

/** 结束时间：当天只写时分，隔天带月日（本地时间）；没有或解析不了为空 */
export function clockText(iso: string | null | undefined, now: Date = new Date()): string {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  return d.toDateString() === now.toDateString() ? hm : `${p(d.getMonth() + 1)}-${p(d.getDate())} ${hm}`
}

/** 任务面板「已结束」最多显示多少条 */
export const ENDED_MAX = 20
const RUNNING_JOB = ['queued', 'running']
const endTime = (iso: string | null | undefined) => {
  const v = iso ? Date.parse(iso) : NaN
  return Number.isNaN(v) ? Infinity : v      // 没有时间的是应用刚记下的：排最前
}
/** 按结束时间倒序（稳定：时间相同或都没有时保持原来的先后） */
function newestFirst<T>(list: T[], at: (x: T) => number): T[] {
  return list.map((x, i) => ({ x, i, at: at(x) }))
    .sort((a, b) => (a.at === b.at ? a.i - b.i : b.at - a.at)).map((e) => e.x)
}

/** 已结束的转换任务：应用记下的（prev）与 /jobs 里已结束、带结束时间的合在一起——刷新页面后列表还在。
 *  prev 里的条目用 /jobs 的最新信息补全（结束时间、失败原因、现在的名字、是否已删除） */
export function mergeDoneJobs(prev: DoneJob[], jobs: JobSummary[]): DoneJob[] {
  const ended = jobs.filter((j) => !RUNNING_JOB.includes(j.status))
  const fresh = (j: JobSummary): DoneJob => ({
    id: j.id, status: j.status, work_title: j.work_title, chapter: j.chapter, novel_id: j.novel_id, chapter_id: j.chapter_id,
    finished_at: j.finished_at ?? null, error_msg: j.error_msg ?? null, deleted: !!j.deleted,
  })
  const byId = new Map(ended.map((j) => [j.id, j]))
  const kept = prev.map((d) => {
    const j = byId.get(d.id)
    return j ? { ...d, ...fresh(j), finished_at: j.finished_at ?? d.finished_at ?? null } : d
  })
  const have = new Set(prev.map((d) => d.id))
  const added = ended.filter((j) => !have.has(j.id) && !!j.finished_at).map(fresh)
  return newestFirst([...kept, ...added], (d) => endTime(d.finished_at)).slice(0, ENDED_MAX)
}

export type EndedItem = { job: DoneJob; task?: undefined } | { task: FilmTask; job?: undefined }

/** 任务面板的「已结束」：转换任务与出片、合成任务合在一起，按结束时间倒序，最多 ENDED_MAX 条 */
export function endedItems(done: DoneJob[], tasks: FilmTask[]): EndedItem[] {
  const all: EndedItem[] = [...done.map((job) => ({ job })), ...tasks.map((task) => ({ task }))]
  return newestFirst(all, (it) => endTime(it.job ? it.job.finished_at : it.task.ended_at)).slice(0, ENDED_MAX)
}
```

- [ ] **Step 7: 任务面板**

把 `frontend/src/components/shell/ActivityPanel.tsx` 整个换成：

```tsx
/** 右侧面板：两个页签：任务、助手。任务页是本人的任务队列（任意小说）：进行中的与已结束的，
 *  转换、出片片段、成片合成都在这里；助手页签只在进了小说后出现。
 *  宽屏时挤压主区，窄屏（< 1100px）盖在主区上方（样式见 workspace.css）。Esc 或「关闭」收起。 */
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { motion } from 'motion/react'
import { BellRing, X } from 'lucide-react'
import { EmptyState } from '@/components/common/EmptyState'
import { StatusPill } from '@/components/common/StatusPill'
import type { Tone } from '@/components/common/StatusPill'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { useI18n } from '@/i18n/core'
import { formatMsg } from '@/i18n/serverMsg'
import { DUR, EASE_OUT } from '@/motion'
import { useReducedMotion } from 'motion/react'
import { fmtEta, JOB_STATUS, label } from '@/labels'
import { clockText, endedItems, jobWhere, taskWait, taskWhere } from '@/filmTasks'
import { cny } from '@/lib/fmt'
import type { MsgKey } from '@/i18n/core'
import type { FilmTask, JobStatus, JobSummary } from '@/types'

/** 已结束的一条转换任务：刚结束的由应用记下，其余来自 /jobs（带结束时间与失败原因） */
export interface DoneJob {
  id: string
  status: JobStatus
  work_title: string | null
  chapter: string | null
  novel_id?: string | null
  chapter_id?: string | null
  finished_at?: string | null
  /** 失败原因（消息对象或文字）；不能给普通用户看的为 null */
  error_msg?: unknown
  /** 所属的小说或章节已删除 */
  deleted?: boolean
}

const TONE: Partial<Record<JobStatus, Tone>> = {
  succeeded: 'ok', completed_with_warnings: 'warn', failed: 'err', draft_invalid: 'warn',
}
const FILM_TONE: Record<FilmTask['state'], Tone> = {
  queued: 'live', running: 'live', downloading: 'live', done: 'ok', failed: 'err', cancelled: 'idle', late: 'warn',
}

/** 本人的出片与合成任务：进行中的、已结束的，以及这份列表是什么时候取回的（毫秒时间戳，等待时长从它接着走） */
export interface FilmActivity { live: FilmTask[]; ended: FilmTask[]; at: number }

export function ActivityPanel({
  running, done, onOpen, onOpenDone, onClose, tab = 'activity', onTab, assistant, film, onOpenFilm, onCancelFilm,
}: {
  running: JobSummary[]
  done: DoneJob[]
  /** 出片与合成任务（没有就不显示）；点一条回到它所在的位置，play 为 true 时顺便打开播放 */
  film?: FilmActivity
  onOpenFilm?: (t: FilmTask, play: boolean) => void
  /** 取消一条进行中的出片任务（确认框由上层弹）；不给就没有取消入口 */
  onCancelFilm?: (t: FilmTask) => void
  onOpen: (j: JobSummary) => void
  onOpenDone?: (j: DoneJob) => void
  onClose: () => void
  /** 当前页签；没有 assistant 时只显示「任务」 */
  tab?: 'activity' | 'assistant'
  onTab?: (t: 'activity' | 'assistant') => void
  /** 助手页签的内容（进了小说才有） */
  assistant?: ReactNode
}) {
  const { t, locale } = useI18n()
  const reduced = !!useReducedMotion()
  const ref = useRef<HTMLElement>(null)
  useEffect(() => { ref.current?.focus({ preventScroll: true }) }, [])
  const showAssistant = tab === 'assistant' && !!assistant
  const filmLive = film?.live ?? []
  const ended = endedItems(done, film?.ended ?? [])
  /** 有出片任务在跑时每秒走一次，等待时长跟着动 */
  const [now, setNow] = useState(() => Date.now())
  const ticking = filmLive.length > 0
  useEffect(() => {
    if (!ticking) return
    setNow(Date.now())
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [ticking])
  /** 状态药丸上的字：合成有自己的说法，其余按出片的状态 */
  const filmState = (tk: FilmTask) => (tk.kind === 'compose' && tk.state !== 'queued'
    ? t(`activity.compose.${tk.state === 'done' ? 'done' : tk.state === 'failed' ? 'failed' : 'running'}`)
    : t(`activity.film.state.${tk.state}` as MsgKey))
  /** 定位行：小说 › 章节 › 片段与镜号。窄了截断，悬停看全称 */
  const where = (text: string, strong = false) => (
    <p className={`truncate text-sm${strong ? ' font-medium' : ''}`} title={text} data-testid="activity-where">{text}</p>
  )
  const endedAt = (iso: string | null | undefined) => {
    const text = clockText(iso)
    return text ? <span className="text-xs tabular-nums text-muted-foreground">{text}</span> : null
  }
  const reason = (failed: boolean, err: unknown) =>
    (failed ? <p className="activity__log" data-testid="activity-reason">{err ? formatMsg(err, locale) : t('activity.failedHint')}</p> : null)
  const jobBody = (j: DoneJob) => (
    <>
      {where(jobWhere(j))}
      <div className="flex items-center justify-between gap-2">
        <StatusPill tone={TONE[j.status] ?? 'idle'}>{label(JOB_STATUS, j.status)}</StatusPill>
        {endedAt(j.finished_at)}
      </div>
      {reason(j.status === 'failed', j.error_msg)}
    </>
  )
  return (
    <motion.aside ref={ref} tabIndex={-1} data-testid="activity-panel" className={`activity${showAssistant ? ' activity--wide' : ''}`}
                  aria-label={t('shell.activity')}
                  initial={reduced ? { opacity: 0 } : { opacity: 0, x: 48 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={reduced ? { opacity: 0 } : { opacity: 0, x: 48 }}
                  transition={{ duration: DUR.base, ease: EASE_OUT }}
                  onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}>
      <div className="activity__head">
        <div role="tablist" className="activity__tabs">
          <button role="tab" aria-selected={!showAssistant} data-testid="activity-tab-activity"
                  className={`activity__tab${showAssistant ? ' activity__tab--off' : ''}`}
                  onClick={() => onTab?.('activity')}>{t('activity.tab')}</button>
          {assistant && (
            <button role="tab" aria-selected={showAssistant} data-testid="activity-tab-assistant"
                    className={`activity__tab${showAssistant ? '' : ' activity__tab--off'}`}
                    onClick={() => onTab?.('assistant')}>{t('assistant.tab')}</button>
          )}
        </div>
        <Button variant="ghost" size="icon" aria-label={t('activity.close')} onClick={onClose}>
          <X className="size-4" />
        </Button>
      </div>
      <div className="activity__body">
        {showAssistant ? assistant : (<>
        {!running.length && !filmLive.length && !ended.length && (
          <EmptyState icon={<BellRing className="size-5" />} title={t('activity.empty')} hint={t('activity.emptyHint')} />
        )}
        {(!!running.length || !!filmLive.length) && (
          <section data-testid="queue-running">
            <h3 className="activity__title">{t('activity.running')}</h3>
            <ul className="space-y-2">
              {running.map((j) => {
                const p = j.progress
                const pct = p ? Math.min(100, Math.round((p.done_chars / (p.total_chars || 1)) * 100)) : 0
                return (
                  <li key={j.id} data-testid="activity-running" className="activity__item">
                    {where(jobWhere(j), true)}
                    <Progress value={pct} className="h-1" />
                    <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span className="font-mono tabular-nums">
                        {p?.eta_sec != null ? t('job.etaShort', { t: fmtEta(p.eta_sec) }) : t('shell.shelf.queued')}
                      </span>
                      <Button variant="outline" size="sm" onClick={() => onOpen(j)}>{t('activity.view')}</Button>
                    </div>
                    {j.last_log && <p className="activity__log">{formatMsg(j.last_log, locale)}</p>}
                  </li>
                )
              })}
              {filmLive.map((tk) => (
                <li key={tk.id} data-testid="activity-film-running" className="activity__item">
                  {where(taskWhere(tk), true)}
                  <div className="flex items-center justify-between gap-2">
                    <StatusPill tone={FILM_TONE[tk.state]}>{filmState(tk)}</StatusPill>
                    <span className="flex items-center gap-1">
                      {tk.cancel && onCancelFilm && (
                        <Button variant="ghost" size="sm" data-testid="activity-film-cancel" onClick={() => onCancelFilm(tk)}>
                          {t(tk.cancel === 'free' ? 'film.cancel.free' : 'film.cancel.paid')}
                        </Button>
                      )}
                      <Button variant="outline" size="sm" onClick={() => onOpenFilm?.(tk, false)}>{t('activity.view')}</Button>
                    </span>
                  </div>
                  <p className="text-xs tabular-nums text-muted-foreground">{taskWait(tk, film?.at ?? now, now)}</p>
                  {!!tk.step && <p className="activity__log">{formatMsg(tk.step, locale)}</p>}
                </li>
              ))}
            </ul>
          </section>
        )}
        {!!ended.length && (
          <section data-testid="queue-ended">
            <h3 className="activity__title">{t('activity.done')}</h3>
            <ul className="space-y-2">
              {ended.map((it) => {
                if (it.job) {
                  const j = it.job
                  return (
                    <li key={`job-${j.id}`} data-testid="activity-done"
                        className={`activity__item${onOpenDone ? ' activity__item--click' : ''}`}>
                      {onOpenDone
                        ? <button type="button" className="block w-full text-left" onClick={() => onOpenDone(j)}>{jobBody(j)}</button>
                        : jobBody(j)}
                    </li>
                  )
                }
                const tk = it.task
                const play = tk.kind !== 'compose' && (tk.state === 'done' || tk.state === 'late')
                return (
                  <li key={`task-${tk.id}`} data-testid="activity-film-done" className="activity__item activity__item--click">
                    <button type="button" className="block w-full text-left" onClick={() => onOpenFilm?.(tk, play)}>
                      {where(taskWhere(tk))}
                      <div className="flex items-center justify-between gap-2">
                        <StatusPill tone={FILM_TONE[tk.state]}>{filmState(tk)}</StatusPill>
                        {endedAt(tk.ended_at)}
                      </div>
                      {tk.state === 'late' && tk.cost_cny != null && (
                        <p className="text-xs text-muted-foreground">{t('activity.film.late', { cost: cny(tk.cost_cny) })}</p>
                      )}
                      {reason(tk.state === 'failed', tk.error)}
                    </button>
                  </li>
                )
              })}
            </ul>
          </section>
        )}
        </>)}
      </div>
    </motion.aside>
  )
}
```

运行：`cd frontend && npx vite build --ssr tests/film-tasks.test.tsx --outDir .ssrout --logLevel error && node .ssrout/film-tasks.test.js`
预期：通过，输出含 `1b. 定位 ✓`、`1c. 已结束的合并与排序 ✓`、`4. 任务面板 ✓`、`ALL PASS`

- [ ] **Step 8: 应用接线——已结束的转换任务从 /jobs 补、合成的播报与跳转、面板里取消**

在 `frontend/src/App.tsx` 里找到：

```tsx
import { diffFilmTasks, lateTaskId, onFilmPoke, taskName } from './filmTasks'
```

换成：

```tsx
import { diffFilmTasks, lateTaskId, mergeDoneJobs, onFilmPoke, taskName } from './filmTasks'
```

在 `frontend/src/App.tsx` 里找到：

```tsx
import { onTask } from './lib/assistantBridge'
```

换成：

```tsx
import { notifyTask, onTask } from './lib/assistantBridge'
```

在 `frontend/src/App.tsx` 里找到：

```tsx
import {
  adminService, adoptVersion, convertChapter, createChapter, createNovel, deleteChapter, deleteVersion,
```

换成：

```tsx
import {
  adminService, adoptVersion, cancelFilmItem, convertChapter, createChapter, createNovel, deleteChapter, deleteVersion,
```

在 `frontend/src/App.tsx` 里找到：

```tsx
      prevRunning.current = liveIds
      if (finished) {
```

换成：

```tsx
      // 已结束的：/jobs 里带结束时间的并进来（刷新页面后还在），已有的补上结束时间与失败原因
      setRecentDone((r) => mergeDoneJobs(r, jobs))
      prevRunning.current = liveIds
      if (finished) {
```

在 `frontend/src/App.tsx` 里找到：

```tsx
      for (const tk of fresh) {
        const who = taskName(tk)
        const play = tk.state !== 'failed'
        const open = () => openFilmRef.current(tk, play)
        const action = { label: t(play ? 'activity.film.play' : 'flow.view'), onClick: open }
        const tag = `film-${tk.id}`
        if (tk.state === 'failed') {
          notify(t('app.notify.filmFailed'), t('app.notify.filmFailedBody', { who }), { tag, onClick: open })
          toast.error(t('app.notify.filmFailed'), { description: who, action })
        } else if (tk.state === 'late') {
          const body = t('app.notify.filmLateBody', { who, cost: cny(tk.cost_cny ?? 0) })
          notify(t('app.notify.filmLate'), body, { tag, onClick: open })
          toast.warning(t('app.notify.filmLate'), { description: body, action })
        } else {
          notify(t('app.notify.filmDone'), t('app.notify.filmDoneBody', { who }), { tag, onClick: open })
          toast.success(t('app.notify.filmDone'), { description: who, action })
        }
      }
```

换成：

```tsx
      for (const tk of fresh) {
        const who = taskName(tk)
        const kind = tk.kind === 'compose' ? 'compose' : 'film'
        const play = kind === 'film' && tk.state !== 'failed'
        const open = () => openFilmRef.current(tk, play)
        const action = { label: t(play ? 'activity.film.play' : 'flow.view'), onClick: open }
        const tag = `film-${tk.id}`
        if (tk.state === 'failed') {
          notify(t(`app.notify.${kind}Failed`), t(`app.notify.${kind}FailedBody`, { who }), { tag, onClick: open })
          toast.error(t(`app.notify.${kind}Failed`), { description: who, action })
        } else if (tk.state === 'late') {
          const body = t('app.notify.filmLateBody', { who, cost: cny(tk.cost_cny ?? 0) })
          notify(t('app.notify.filmLate'), body, { tag, onClick: open })
          toast.warning(t('app.notify.filmLate'), { description: body, action })
        } else {
          notify(t(`app.notify.${kind}Done`), t(`app.notify.${kind}DoneBody`, { who }), { tag, onClick: open })
          toast.success(t(`app.notify.${kind}Done`), { description: who, action })
        }
      }
```

在 `frontend/src/App.tsx` 里找到：

```tsx
  const openFilmTask = async (tk: FilmTask, play: boolean) => {
    const taskId = lateTaskId(tk)
    const focus: FilmFocus = { vid: tk.version_id, id: tk.item_id, play, ...(taskId ? { taskId } : {}) }
    if (tk.novel_id === nid && tk.chapter_id === cid) {
      if (docVid !== tk.version_id) {
        if (!(await confirmLeave())) return
        void openVersion(tk.novel_id, tk.chapter_id, tk.version_id)
      }
      const to = chapterPath(tk.novel_id, tk.chapter_id, { step: boardStep(), tab: urlTab, canvas: true, view: 'graph' })
      // 已经在这个地址：不导航，只把请求写进当前这条历史记录
      if (!go(to, { state: { fromChapter: true, panel: 'film', focus } })) {
        navigate(to, { replace: true, state: { ...passState(navStateRef.current), panel: 'film', focus } })
      }
      return
    }
    go(chapterPath(tk.novel_id, tk.chapter_id, { step: 'render', canvas: true, view: 'graph' }),
       { state: { vid: tk.version_id, panel: 'film', focus } })
  }
```

换成：

```tsx
  const openFilmTask = async (tk: FilmTask, play: boolean) => {
    // 合成任务：到这一章画布的出片页（时间轴），没有要选中的片段
    const compose = tk.kind === 'compose'
    const taskId = lateTaskId(tk)
    const focus: FilmFocus | undefined = compose ? undefined
      : { vid: tk.version_id, id: tk.item_id, play, ...(taskId ? { taskId } : {}) }
    const st: NavState = { panel: 'film', ...(focus ? { focus } : {}) }
    const view = compose ? null : 'graph'
    if (tk.novel_id === nid && tk.chapter_id === cid) {
      if (docVid !== tk.version_id) {
        if (!(await confirmLeave())) return
        void openVersion(tk.novel_id, tk.chapter_id, tk.version_id)
      }
      const to = chapterPath(tk.novel_id, tk.chapter_id, { step: boardStep(), tab: urlTab, canvas: true, view })
      // 已经在这个地址：不导航，只把请求写进当前这条历史记录
      if (!go(to, { state: { fromChapter: true, ...st } })) {
        navigate(to, { replace: true, state: { ...passState(navStateRef.current), ...st } })
      }
      return
    }
    go(chapterPath(tk.novel_id, tk.chapter_id, { step: 'render', canvas: true, view }),
       { state: { vid: tk.version_id, ...st } })
  }
  /** 在任务面板里取消一条进行中的出片任务：确认框与画布上同一套；取消后让任务列表和开着的画布都重读 */
  const cancelFilmTask = async (tk: FilmTask) => {
    if (!tk.cancel || tk.kind === 'compose') return
    const paid = tk.cancel === 'paid'
    const sure = await ask({
      title: t(paid ? 'film.cancel.paidTitle' : 'film.cancel.freeTitle', { id: tk.item_id }),
      body: t(paid ? 'film.cancel.paidBody' : 'film.cancel.freeBody'),
      action: t(paid ? 'film.cancel.paidAction' : 'film.cancel.freeAction'),
      danger: paid,
    })
    if (!sure) return
    try {
      const got = await cancelFilmItem(tk.novel_id, tk.chapter_id, tk.version_id, tk.item_id, tk.kind === 'free')
      if (got.cancel_outcome) notice.ok(t(`film.cancel.${got.cancel_outcome}`))
      notifyTask({ kind: 'film', chapter_id: tk.chapter_id, version_id: tk.version_id })
    } catch (e) {
      notice.err(msg(e))
      void watchFilm()
    }
  }
```

在 `frontend/src/App.tsx` 里找到：

```tsx
                         film={filmAct} onOpenFilm={(tk, play) => void openFilmTask(tk, play)}
```

换成：

```tsx
                         film={filmAct} onOpenFilm={(tk, play) => void openFilmTask(tk, play)}
                         onCancelFilm={(tk) => void cancelFilmTask(tk)}
```

- [ ] **Step 9: 运行，确认通过**

运行：`cd frontend && npx vite build --ssr tests/routing.test.tsx --outDir .ssrout --logLevel error && node .ssrout/routing.test.js 2>&1 | tail -4`
预期：通过，输出含 `出片任务：铃铛、面板、跳转与通知 ✓`、`ALL PASS`

运行：`cd frontend && for t in workspace flow assistant; do npx vite build --ssr tests/$t.test.tsx --outDir .ssrout --logLevel error && { timeout 200 node .ssrout/$t.test.js > /dev/null 2>&1 || timeout 200 node .ssrout/$t.test.js > /dev/null 2>&1; } || echo "FAILED $t"; done; npx vite build --ssr tests/film-lane.test.ts --outDir .ssrout --logLevel error && node .ssrout/film-lane.test.js > /dev/null || echo "FAILED film-lane"; npm run typecheck && test "$(npm run lint 2>&1 | grep -c ': warning ')" = 5 && echo lint-ok`
预期：通过，输出含 `lint-ok`，不含 `FAILED`

- [ ] **Step 10: 提交**

提交：

```bash
git add frontend/src/types.ts frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/src/filmTasks.ts frontend/src/components/shell/ActivityPanel.tsx frontend/src/App.tsx frontend/tests/film-tasks.test.tsx frontend/tests/workspace.test.tsx frontend/tests/routing.test.tsx
git commit -m "任务面板改成个人任务队列：进行中与已结束两个区，转换、出片片段、成片合成都在里面；每条定位到小说、章节、片段与镜号范围（窄了截断、悬停看全称，名字读不到写已删除）；进行中的出片任务可在面板里取消（确认框同画布）；已结束的带结束时间与失败原因，转换任务的已结束列表同时从 /jobs 取，刷新后还在；合成完成与失败也播报，点开到画布出片页；补测试"
```
### Task 12: 全量验收

不改代码，只把全部检查跑一遍。任何一条不符都先按「全局约束」里的办法核对（`film.test` 的偶发卡死按那里写的单独重跑），再报告；不要为了过检查改测试或改设计。

**Files:** 无（只运行命令）

- [ ] **Step 1: 后端全套**

运行：`cd backend && for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t > /dev/null 2>&1 || echo "FAILED $t"; done; echo backend-done`
预期：通过，输出含 `backend-done`，不含 `FAILED`

- [ ] **Step 2: 前端全套测试**

运行：`cd frontend && set -o pipefail && npm test 2>&1 | tail -3`
预期：通过，输出含 `ALL PASS`

- [ ] **Step 3: lint 仍是基线的 5 条警告**

运行：`cd frontend && npm run lint > /dev/null 2>&1; test "$(npm run lint 2>&1 | grep -c ': warning ')" = 5 && echo lint-ok`
预期：通过，输出含 `lint-ok`

- [ ] **Step 4: 构建与构建产物检查**

运行：`cd frontend && npm run build > /dev/null 2>&1 && node tests/admin-bundle.check.mjs && echo bundle-ok`
预期：通过，输出含 `bundle-ok`

- [ ] **Step 5: 确认没有留下未提交的改动**

运行：`git status --short | grep -v 'commercialization-design-contract' | grep -v '^??' ; echo status-done`
预期：通过，输出含 `status-done`，不含 ` M `
