# 出片后端（A1）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有后端里加上「出片」：分镜 → 按厂商能力切段 → 厂商无关提示词 → 出片会话（试段、确认金额后批量、重做、采用）→ 后台线程提交/轮询/下载；首家厂商 Seedance（火山方舟），全程可用假厂商测试。

**Architecture:** 新增 `backend/render/` 下的厂商统一接口（`providers/`）、切段与提示词（`compose.py`）、会话状态（`session.py`，读写 `session.json`）、后台线程（`runner.py`）；`server/app.py` 加 `/render` 接口。状态存文件，不引数据库与队列。生产包（`plan.py`、`adapters/seedance.py`）改为调用 `compose.py` 的同一套提示词组装，输出逐字不变（用快照测试锁住）。

**Tech Stack:** Python 3.12（`backend/.venv`），FastAPI，httpx（已装，0.28），脚本式测试（`.venv/bin/python tests/.../test_*.py`，结尾打印 `ALL PASS`）。

**Spec:** `docs/specs/2026-10-28-video-generation-design.md`。本计划覆盖其第 1 节与第 5 节第 1–5 步；画布交互（第 2 节）另出 A2 计划，配音与合成（第 3 节）另出 A3 计划。

---

## 全局约束

- 提交只 `git add` 具体文件，不用 `git add -A` / `git commit -a`；提交信息用中文、风格同 `git log --oneline -5`，**不带任何 Claude 署名**（无 `Co-Authored-By`、无 `Claude-Session`）。
- 不读、不打印 `backend/.env`；密钥不进日志、报错、`session.json`。
- 测试不联网、不花钱：一律用假厂商或 `httpx.MockTransport`。真实厂商只在 Task 8 的手动冒烟里用，花费上限 5 元，由用户执行。
- 所有命令在 `backend/` 下执行：`cd backend`。

## 核实结果（设计文档第 5 节第 1 步，2026-10-31 查官方文档）

- 接口：`POST https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks` → `{"id": "cgt-…"}`；`GET …/tasks/{id}` → `status`（`queued`/`running`/`succeeded`/`failed`/`expired`/`cancelled`）、`content.video_url`、`content.last_frame_url`（需 `return_last_frame: true`）、`usage.completion_tokens`、`error.{code,message}`。鉴权 `Authorization: Bearer $ARK_API_KEY`。结果地址 24 小时有效。
- 请求体：`model`、`content[]`（`{"type":"text"}`、`{"type":"image_url","image_url":{"url":…},"role":…}`），顶层 `resolution`、`ratio`、`duration`（整数，2.0 系列 4–15）、`generate_audio`、`watermark`、`return_last_frame`。图片 `url` 可以是公网地址或 `data:image/<fmt>;base64,…`。
- **首帧模式（`role: first_frame`）与参考图模式（`role: reference_image`，2.0 最多 9 张）互斥，不能同用。** 这与设计文档 1.3 第 5 条「首帧 + 参考图」冲突，裁定见下。
- 模型 ID：2.0 `doubao-seedance-2-0-260128`，2.0 fast `doubao-seedance-2-0-fast-260128`，2.0 mini `doubao-seedance-2-0-mini-260615`。分辨率：2.0 为 480p/720p/1080p（另有 4k），fast 与 mini 为 480p/720p。
- 价格（刊例价，元/百万 token，输入不含视频）：2.0 为 46，fast 为 37，mini 为 23。token ≈ 输出秒数 × 宽 × 高 × 24 / 1024（720p 约 21600 token/秒，即 fast 约 0.80 元/秒、mini 约 0.50 元/秒）。失败任务不计费。
- Seedance 2.5（4–30 秒、最多 30 张参考图）已上线，首版不接；以后在档位表加一行即可。

## 实施裁定（与设计文档的差异，Task 8 写回设计文档）

1. **首帧与参考图互斥**：`Caps` 增加 `frame_with_refs`。方舟为 `False`：本段有参考图时，关键帧作为第一个参考位（提示词写「【首帧】@图片1 本段开场画面」），占一个参考名额；尾帧接力只在本段没有参考图时使用（首帧模式）。
2. **参考图来源是字符串**：`RefImage.source` 为 http(s) 地址或 `data:image/…` URI，取自资产卡 `reference_images[].uri`（场景取 `angles[].uri`）。其他形式的 uri 视为没有图，只用文字描述。目前没有资产图上传入口，要出带参考图的片需先把 uri 回填进资产卡（A2/B 再做上传）。关键帧与接力尾帧是本地文件，提交时转成 data URI。
3. **能力按档位**：`VideoProvider.caps(model)` 是方法（不同档位分辨率、单价不同），另有 `rewrite_prompt(text)` 负责改写占位符。
4. **会话目录**：`chapters/<cid>/render/<vid>/`（与关键帧 `chapters/<cid>/keyframes/<vid>/` 同层），删版本时一并删除。
5. **计费**：成功按 `usage.completion_tokens × 单价`；没有 usage 按秒数估；厂商失败记 0；下载失败（已生成）照记生成费用。
6. **提交中断**：重启时发现「提交中」且没有任务 id 的尝试，标失败并提示到控制台核对，不重复提交（宁可让人看一眼，也不重复扣钱）。
7. **出片费用暂不进管理后台流水账**（管理后台设计「不做」一栏已写明，出片稳定后作为新用途接入）。

## 文件结构

| 文件 | 职责 |
|---|---|
| `render/providers/__init__.py` | 厂商注册表：`register`、`get_video`、`default_video_name`、`names` |
| `render/providers/base.py` | `Caps`、`RefImage`、`ClipRequest`、`TaskState`、`VideoProvider`、两类错误、整数秒与预估、MP4 校验 |
| `render/providers/fake.py` | 假视频厂商（测试与本地演示） |
| `render/providers/seedance.py` | 占位符改写 `rewrite_refs`；`Seedance` 厂商：提交、查询、下载、计费 |
| `render/compose.py` | 可播时长、切段、参考位与优先级裁剪、四种声音模式的提示词、首帧来源、指纹、组装厂商请求 |
| `render/session.py` | `session.json` 读写与全部状态迁移（接口与出片线程共用） |
| `render/runner.py` | 后台线程：提交、轮询、下载、重启恢复 |
| `render/smoke.py` | 真实厂商手动冒烟（花钱，上限 5 元） |
| `render/plan.py` | 修改：`clip_prompt` 改为调用 `compose`，输出不变 |
| `render/keyframes.py` | 修改：导出资产文字描述函数给 `compose` 用 |
| `server/novels.py` | 修改：`render_dir`，删版本时删会话目录 |
| `server/app.py` | 修改：验证门抽成 `_render_gate`；`/render` 接口；出片线程随服务启动 |
| `tests/render/test_providers.py`、`test_compose.py`、`test_session.py`、`test_runner.py`、`test_seedance.py` | 新增 |
| `tests/render/golden_plan_yao.json` | 新增：改造前生产包输出的快照 |
| `tests/server/test_render.py` | 新增：接口端到端（假厂商） |

---

### Task 1: 厂商统一接口、假厂商、注册表

**Files:**
- Create: `backend/render/providers/__init__.py`
- Create: `backend/render/providers/base.py`
- Create: `backend/render/providers/fake.py`
- Test: `backend/tests/render/test_providers.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/render/test_providers.py`:

```python
#!/usr/bin/env python3
"""出片：厂商统一接口的公共函数、假厂商、注册表。用法: python3 tests/render/test_providers.py"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import providers  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FAKE_MP4, FakeVideo  # noqa: E402


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def main() -> int:
    fake = FakeVideo()
    caps = fake.caps("fake-1")

    # 1. 整数秒：向上取整，夹在上下限之间；预估 = 秒数 × 单价
    assert base.request_seconds(4.2, caps) == 5
    assert base.request_seconds(1.0, caps) == 2 and base.request_seconds(30, caps) == 10
    assert base.request_seconds(6.0, caps) == 6, "整数不多算一秒"
    assert base.estimate_cny(4.2, caps, "720p") == 5.0
    assert base.estimate_cny(4.2, caps, "480p") == 2.5
    print("1. 整数秒与预估 ✓")

    # 2. 可播放校验：MP4 容器头，不依赖 ffmpeg
    with tempfile.TemporaryDirectory() as d:
        good, bad = Path(d) / "a.mp4", Path(d) / "b.mp4"
        good.write_bytes(FAKE_MP4)
        bad.write_bytes(b"<html>expired</html>")
        assert base.is_playable_mp4(good) and not base.is_playable_mp4(bad)
        assert not base.is_playable_mp4(Path(d) / "missing.mp4")
    print("2. 可播放校验 ✓")

    # 3. 假厂商：提交 → 轮询 → 成功 → 下载 → 计费；失败、瞬时错误
    slow = FakeVideo(polls_to_finish=2)
    req = base.ClipRequest(prompt="p", model="fake-1", duration=4.2, resolution="720p")
    tid = slow.submit(req)
    assert slow.poll(tid).status == "running"
    st = slow.poll(tid)
    assert st.status == "succeeded" and st.usage == {"seconds": 5}
    with tempfile.TemporaryDirectory() as d:
        files = slow.download(st, Path(d) / "clips" / "E01-C01.v1.mp4")
        assert base.is_playable_mp4(files["video"])
        assert files["last_frame"].name == "E01-C01.v1.last.jpg" and files["last_frame"].exists()
    assert slow.cost(st, req) == 5.0
    assert slow.cost(base.TaskState("x", "failed"), req) == 0.0, "失败不计费"
    must_raise(base.ProviderError, slow.poll, "nope")
    bad = FakeVideo(fail_with="审核未通过")
    st = bad.poll(bad.submit(req))
    assert st.status == "failed" and st.error == "审核未通过"
    flaky = FakeVideo(transient_submits=1)
    must_raise(base.TransientError, flaky.submit, req)
    assert flaky.submit(req) == "fake-1", "瞬时错误不占任务号"
    assert fake.rewrite_prompt("看 {ref:C01} 和 {ref:S03}") == "看 [参考C01] 和 [参考S03]"
    must_raise(base.ProviderError, fake.caps, "nope")
    print("3. 假厂商全流程 ✓")

    # 4. 注册表：同名只建一次；未注册抛 KeyError
    mine = FakeVideo()
    providers.register("fake", lambda: mine)
    assert providers.get_video("fake") is mine and providers.get_video("fake") is mine
    must_raise(KeyError, providers.get_video, "nope")
    print("4. 注册表 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/render/test_providers.py`
Expected: `ModuleNotFoundError: No module named 'render.providers'`

- [ ] **Step 3: 写 `base.py`**

Create `backend/render/providers/base.py`:

```python
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
```

- [ ] **Step 4: 写 `fake.py`**

Create `backend/render/providers/fake.py`:

```python
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
```

- [ ] **Step 5: 写注册表**

Create `backend/render/providers/__init__.py`:

```python
"""视频厂商注册表。STORYBOARD_VIDEO_PROVIDER 选默认厂商（缺省 seedance）。

新增厂商：写 providers/<name>.py，在文件末尾 register 一行。测试用 register 换成自己的实例。
"""
import os

_FACTORIES: dict = {}
_INSTANCES: dict = {}


def register(name: str, factory) -> None:
    _FACTORIES[name] = factory
    _INSTANCES.pop(name, None)


def default_video_name() -> str:
    return os.environ.get("STORYBOARD_VIDEO_PROVIDER", "").strip() or "seedance"


def get_video(name=None):
    """按名字取厂商实例（同名只建一次）。未注册抛 KeyError；建不起来（如没配密钥）由工厂抛 ProviderError。"""
    name = name or default_video_name()
    if name not in _INSTANCES:
        factory = _FACTORIES.get(name)
        if factory is None:
            raise KeyError(f"未知的视频厂商：{name}")
        _INSTANCES[name] = factory()
    return _INSTANCES[name]


def names() -> list:
    """界面可选的厂商。假厂商只在被设为默认（测试、本地演示）时出现。"""
    return [n for n in sorted(_FACTORIES) if n != "fake" or default_video_name() == "fake"]


def _fake():
    from render.providers.fake import FakeVideo
    return FakeVideo()


register("fake", _fake)
```

- [ ] **Step 6: 运行，确认通过**

Run: `.venv/bin/python tests/render/test_providers.py`
Expected: 四段 ✓，最后 `ALL PASS`

- [ ] **Step 7: 提交**

```bash
git add render/providers/__init__.py render/providers/base.py render/providers/fake.py tests/render/test_providers.py
git commit -m "出片厂商统一接口：能力表、请求与任务状态、瞬时与明确两类错误、整数秒与预估、MP4 校验；假厂商与注册表"
```

---

### Task 2: 厂商无关提示词（四种声音模式）与生产包改走同一套组装

**Files:**
- Create: `backend/tests/render/golden_plan_yao.json`（由当前代码生成的快照）
- Create: `backend/render/compose.py`
- Create: `backend/render/providers/seedance.py`
- Modify: `backend/render/plan.py`（`clip_prompt` 函数体，约第 158–216 行）
- Test: `backend/tests/render/test_compose.py`

- [ ] **Step 1: 先给当前生产包输出拍快照（改代码之前）**

Run:
```bash
.venv/bin/python - <<'EOF'
import json, sys
sys.path.insert(0, ".")
from render.plan import build_plan
from adapters import seedance
doc = json.load(open("tests/real_text_yao/output_merged.json", encoding="utf-8"))
out = {"plan": build_plan(doc),
       "packs": [seedance.render_episode(doc, ep, 15.0) for ep in doc["episodes"]]}
open("tests/render/golden_plan_yao.json", "w", encoding="utf-8").write(
    json.dumps(out, ensure_ascii=False, indent=1) + "\n")
print("clips:", len(out["plan"]["clips"]), "packs:", len(out["packs"]))
EOF
```
Expected: 打印 `clips: <数字> packs: 4`，生成 `tests/render/golden_plan_yao.json`

- [ ] **Step 2: 写失败测试**

Create `backend/tests/render/test_compose.py`:

```python
#!/usr/bin/env python3
"""出片：提示词组装（生产包快照不变、四种声音模式、占位符改写、可播时长），切段、参考图、首帧、指纹、请求组装。

用法: python3 tests/render/test_compose.py
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from adapters import seedance as seedance_pack  # noqa: E402
from pipeline.quality import speech_seconds  # noqa: E402
from render import compose  # noqa: E402
from render.plan import assets_index, build_plan  # noqa: E402
from render.providers.seedance import rewrite_refs  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
GOLDEN = Path(__file__).resolve().parent / "golden_plan_yao.json"


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def part_prompt(doc):
    idx = assets_index(doc)
    shots = [s for ep in doc["episodes"] for s in ep["shots"]]

    # 1. 生产包改走 compose 之后逐字不变
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert build_plan(doc) == golden["plan"], "渲染任务清单与改造前不一致"
    packs = [seedance_pack.render_episode(doc, ep, 15.0) for ep in doc["episodes"]]
    assert packs == golden["packs"], "Markdown 生产包与改造前不一致"
    print("1. 生产包快照不变 ✓")

    # 2. 占位符：厂商无关层写 {ref:ID}，Seedance 按出现顺序改写为 @图片n
    clip = [s for s in shots if s.get("characters") and s.get("location_ref")][:2]
    text, ids = compose.neutral_prompt(clip, doc, idx)
    assert "{ref:" in text and "@图片" not in text
    assert ids == [sl["asset_id"] for sl in compose.ref_slots(clip, idx)]
    out = rewrite_refs(text)
    assert "{ref:" not in out and "@图片1" in out and f"@图片{len(ids)}" in out
    assert rewrite_refs("{ref:C01}{ref:S03}{ref:S03}") == "@图片1@图片2@图片3", "同一资产两次各占一张图"
    print("2. 占位符与改写 ✓")

    # 3. 四种声音模式
    talky = next(s for s in shots if s.get("dialogue"))
    line = talky["dialogue"][0]["text"]
    t, _ = compose.neutral_prompt([talky], doc, idx, mode="tts_all", slots=[])
    assert line not in t and "人物交谈但不发声" in t and "无人声" in t, "tts_all：台词不进提示词"
    t, _ = compose.neutral_prompt([talky], doc, idx, mode="dialogue_native", slots=[])
    assert line in t and "台词逐字念出" in t
    told = next(s for s in shots if (s.get("narration") or {}).get("text"))
    narr = told["narration"]["text"]
    t, _ = compose.neutral_prompt([told], doc, idx, mode="dialogue_native", slots=[])
    assert narr not in t, "dialogue_native：旁白不进提示词"
    t, _ = compose.neutral_prompt([told], doc, idx, mode="all_native", slots=[])
    assert narr in t and "旁白与台词逐字念出" in t
    t, _ = compose.neutral_prompt([talky], doc, idx, mode="silent", slots=[])
    assert "【声音】无声" in t and line not in t
    print("3. 四种声音模式 ✓")

    # 4. 出片按可播时长写时间轴；没有图的资产写文字描述；首帧占第一个参考位
    long = next(s for s in shots if speech_seconds(s) > s.get("duration_sec", 3) + 0.5)
    t, _ = compose.neutral_prompt([long], doc, idx, mode="tts_all", slots=[], timing="playable")
    assert f"，{round(compose.playable(long), 1)}秒，" in t.splitlines()[0]
    t, ids = compose.neutral_prompt([long], doc, idx, mode="tts_all", slots=[],
                                    described=["人物：某人（白发）"], first_frame=True)
    assert "【描述】人物：某人（白发）" in t and ids == [compose.FIRST]
    assert "【首帧】{ref:" + compose.FIRST + "}" in t
    print("4. 可播时长、文字描述、首帧位 ✓")


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    part_prompt(doc)
    # @@NEXT@@
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 运行，确认失败**

Run: `.venv/bin/python tests/render/test_compose.py`
Expected: `ModuleNotFoundError: No module named 'render.compose'`（或 `render.providers.seedance`）

- [ ] **Step 4: 写 `compose.py`（提示词部分）**

Create `backend/render/compose.py`:

```python
"""出片：分镜 → 片段 → 厂商无关提示词 → 厂商请求。

提示词分两层：这里产出厂商无关的结构，参考图写成占位符 {ref:资产ID}；厂商模块再改写成自己
的语法（Seedance：@图片n）。生产包（plan.py / adapters/seedance.py）走 mode=LEGACY 的同一套
组装，两边不会分叉。
"""
from pipeline.quality import DEFAULT_SPEECH_CPS, speech_seconds
from render.plan import TIME_ZH, collect_refs, shot_line

LEGACY = "legacy"          # 生产包写法：台词进提示词，只要音效
AUDIO_MODES = ("tts_all", "dialogue_native", "all_native", "silent")
FIRST = "__first__"        # 首帧图占用参考位时的占位 id


def ref(asset_id: str) -> str:
    return "{ref:" + asset_id + "}"


def playable(shot: dict, cps: float = DEFAULT_SPEECH_CPS) -> float:
    """可播时长：镜头时长与念完旁白台词所需的较大者（与 timeline.ts、quality 同一口径）。"""
    return max(shot.get("duration_sec", 3), speech_seconds(shot, cps))


def ref_slots(clip: list, assets_idx: dict) -> list:
    """一组镜头的参考位，按出场顺序：角色/生物、场景+机位、道具+状态。

    同一场景的两个机位是两个参考位（两张图）。
    """
    chars, locs, props = collect_refs(clip)
    out = []
    for cid, outfit in chars:
        if cid in assets_idx["creatures"]:
            name = assets_idx["creatures"][cid].get("name", cid)
            out.append({"asset_id": cid, "role": "creature", "variant": None,
                        "text": f"生物参考：{name}（{cid}），锁定生物外观"})
        else:
            name = assets_idx["characters"].get(cid, {}).get("name", cid)
            note = f"，着装 {outfit}" if outfit else ""
            out.append({"asset_id": cid, "role": "character", "variant": outfit,
                        "text": f"角色参考：{name}（{cid}{note}），锁定人物外观"})
    for lid, angle in locs:
        name = assets_idx["locations"].get(lid, {}).get("name", lid)
        out.append({"asset_id": lid, "role": "location", "variant": angle,
                    "text": f"场景参考：{name}（{lid}，{angle} 机位），锁定环境"})
    for pid, state in props:
        name = assets_idx["props"].get(pid, {}).get("name", pid)
        note = f"，状态 {state}" if state else ""
        out.append({"asset_id": pid, "role": "prop", "variant": state,
                    "text": f"道具参考：{name}（{pid}{note}）"})
    return out


def _shot_for(shot: dict, mode: str, timing: str, cps: float) -> dict:
    s = dict(shot)
    if timing == "playable":
        s["duration_sec"] = round(playable(shot, cps), 1)
    if mode in ("tts_all", "silent") and s.get("dialogue"):
        # 台词交给 TTS（或不要声音）：画面里人物照样说话，但不让模型发声
        s["dialogue"] = []
        s["action"] = (s.get("action") or "").rstrip("。，； ") + "，人物交谈但不发声"
    return s


def _sound(mode: str, sfx: list):
    s = "，".join(sfx)
    if mode == LEGACY:
        return f"【声音】{s}（仅音效，不要音乐，不要字幕）" if sfx else None
    if mode == "silent":
        return "【声音】无声"
    if mode == "tts_all":
        return (f"【声音】{s}（仅环境音效，无人声，无音乐，无字幕）" if sfx
                else "【声音】仅环境音，无人声，无音乐，无字幕")
    spoken = "台词逐字念出，不要旁白" if mode == "dialogue_native" else "旁白与台词逐字念出"
    return f"【声音】{s + '；' if s else ''}{spoken}，不要音乐，不要字幕"


def _orientation(ar: str) -> str:
    try:
        w, h = (float(x) for x in ar.split(":"))
    except ValueError:
        return "画幅"
    return "竖屏" if h > w else "横屏" if w > h else "方形画面"


def neutral_prompt(clip: list, doc: dict, assets_idx: dict, *, mode: str = LEGACY,
                   slots=None, described=(), first_frame: bool = False,
                   timing: str = "nominal", cps: float = DEFAULT_SPEECH_CPS) -> tuple:
    """一组镜头 → (带 {ref:ID} 占位符的提示词, 占位符依次对应的资产 id)。

    slots=None 列出全部参考位（生产包）；出片时传裁剪后的参考位，没有图或被裁掉的资产
    以 described 的文字描述代替。first_frame=True 时首帧图占第一个参考位。
    timing="playable" 按可播时长写时间轴（出片），"nominal" 按分镜标称时长（生产包）。
    """
    meta = doc["meta"]
    style = meta["style"]["style_prefix"]
    ar = meta.get("video", {}).get("aspect_ratio", "9:16")
    shots = [_shot_for(s, mode, timing, cps) for s in clip]
    total = round(sum(s.get("duration_sec", 3) for s in shots), 1)
    first = clip[0]
    tod = TIME_ZH.get(first.get("time_of_day", ""), "")
    weather = first.get("weather", "")
    if slots is None:
        slots = ref_slots(clip, assets_idx)

    sfx, constraints = [], []
    for s in clip:
        for x in s.get("sfx", []):
            if x not in sfx:
                sfx.append(x)
        for x in s.get("constraints", []):
            if x not in constraints:
                constraints.append(x)

    orient = "竖屏" if mode == LEGACY else _orientation(ar)
    head = (f"{style}，{total}秒，{ar}{orient}"
            + (f"，{tod}" if tod else "") + (f"，{weather}" if weather else ""))
    lines = [head, ""]
    t = 0.0
    for raw, s in zip(clip, shots):
        line, t = shot_line(s, t)
        narration = (raw.get("narration") or {}).get("text")
        if mode == "all_native" and narration:
            line = line.rstrip("。") + f"，旁白：“{narration}”。"
        lines.append(line)
    lines.append("")
    sound = _sound(mode, sfx)
    if sound:
        lines.append(sound)
    # 负面约束是 v0.5 新增的镜头级禁令，出图质量的一半毁在没有约束上
    if constraints:
        lines.append(f"【不要】{'；'.join(constraints)}")
    ids = []
    if first_frame:
        lines.append(f"【首帧】{ref(FIRST)} 本段开场画面，保持构图与人物位置")
        ids.append(FIRST)
    for sl in slots:
        lines.append(f"【参考】{ref(sl['asset_id'])} {sl['text']}")
        ids.append(sl["asset_id"])
    for d in described:
        if d:
            lines.append(f"【描述】{d}")
    return "\n".join(lines), ids
```

- [ ] **Step 5: 写 `seedance.py`（占位符改写）**

Create `backend/render/providers/seedance.py`:

```python
"""火山方舟 Seedance：提示词语法（@图片n），以及提交、查询、下载、计费。

接口与价格核实于 2026-10-31 的官方文档：首帧模式与参考图模式互斥；结果地址 24 小时有效；
失败任务不计费。
"""
import itertools
import re

_REF = re.compile(r"\{ref:([^{}]+)\}")


def rewrite_refs(text: str) -> str:
    """厂商无关占位符 {ref:ID} → Seedance 的 @图片n，按出现顺序编号。

    同一资产出现两次也各占一张图（同一场景的两个机位是两张图），所以按次序而不是按 ID
    编号；请求里的参考图按同一顺序排列。
    """
    n = itertools.count(1)
    return _REF.sub(lambda m: f"@图片{next(n)}", text)
```

- [ ] **Step 6: `plan.clip_prompt` 改走 compose**

In `backend/render/plan.py`, replace the whole `clip_prompt` function (from `def clip_prompt(clip: list, doc: dict, assets_idx: dict) -> tuple:` through its `return "\n".join(lines), refs`) with:

```python
def clip_prompt(clip: list, doc: dict, assets_idx: dict) -> tuple:
    """一个 clip → Seedance 时间轴提示词块 + 它引用的资产 ID 列表。

    组装在 render/compose.py（厂商无关，参考图是占位符），这里按 Seedance 语法改写。
    出片发给厂商的也是同一套组装，生产包与真实请求不会分叉。
    """
    from render import compose                      # compose 依赖本模块，延迟导入免循环
    from render.providers.seedance import rewrite_refs
    text, refs = compose.neutral_prompt(clip, doc, assets_idx)
    return rewrite_refs(text), refs
```

- [ ] **Step 7: 运行，确认通过**

Run: `.venv/bin/python tests/render/test_compose.py`
Expected: 四段 ✓，`ALL PASS`

Run regression: `.venv/bin/python tests/server/test_keyframes.py && .venv/bin/python tests/pipeline/test_offline.py`
Expected: 都是 `ALL PASS`

- [ ] **Step 8: 提交**

```bash
git add render/compose.py render/providers/seedance.py render/plan.py tests/render/test_compose.py tests/render/golden_plan_yao.json
git commit -m "出片提示词两层组装：厂商无关占位符与 Seedance @图片n 改写，四种声音模式与可播时长；生产包改走同一套组装，快照锁住输出不变"
```

---

### Task 3: 切段、参考图优先级、首帧来源、指纹、组装厂商请求

**Files:**
- Modify: `backend/render/keyframes.py`（文件末尾）
- Modify: `backend/render/compose.py`（追加）
- Modify: `backend/tests/render/test_compose.py`

- [ ] **Step 1: 写失败测试**

In `backend/tests/render/test_compose.py`, add these imports below the existing `from render.providers.seedance import rewrite_refs  # noqa: E402`:

```python
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
```

Add this function above `def main()`:

```python
def part_clips(doc):
    fake = FakeVideo()
    caps = fake.caps("fake-1")
    idx = assets_index(doc)

    # 5. 切段：按可播时长装箱，顺序不变；单镜超上限独立成段并标截断
    clips = compose.cut_clips(doc, caps)
    for ep in doc["episodes"]:
        mine = [c for c in clips if c["episode"] == ep["id"]]
        assert [s["id"] for c in mine for s in c["shots"]] == [s["id"] for s in ep["shots"]]
        assert [c["id"] for c in mine] == [f"{ep['id']}-C{i:02d}" for i in range(1, len(mine) + 1)]
    for c in clips:
        if c["truncated"]:
            assert len(c["shots"]) == 1 and compose.playable(c["shots"][0]) > caps.max_clip_sec
        else:
            assert c["duration"] <= caps.max_clip_sec + 1e-6
    assert any(c["truncated"] for c in clips), "《药》里有超过 10 秒的镜头"
    print("5. 切段 ✓")

    # 6. 参考图：主要角色 > 场景 > 次要角色与生物 > 道具；没有图只写文字
    rich = copy.deepcopy(doc)
    for kind in ("characters", "props"):
        for card in rich["assets"][kind]:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
    for card in rich["assets"]["locations"]:
        for a in card.get("angles") or []:
            a["uri"] = f"https://img/{card['id']}-{a['angle']}.png"
    ridx = assets_index(rich)
    c1, c2 = rich["assets"]["characters"][0]["id"], rich["assets"]["characters"][1]["id"]
    loc = next(card for card in rich["assets"]["locations"] if card.get("angles"))
    prop = rich["assets"]["props"][0]["id"]
    clip = [
        {"id": "T1", "duration_sec": 3, "action": "甲", "characters": [{"ref": c1}],
         "location_ref": loc["id"], "location_angle": loc["angles"][0]["angle"],
         "prop_refs": [{"ref": prop}]},
        {"id": "T2", "duration_sec": 3, "action": "乙",
         "characters": [{"ref": c1}, {"ref": c2}]},
    ]
    got = compose.pick_refs(clip, ridx, 2)
    assert [s["asset_id"] for s in got["kept"]] == [c1, loc["id"]], "主要角色与场景优先"
    assert {s["asset_id"] for s in got["dropped"]} == {c2, prop} and got["missing"] == []
    assert got["kept"][1]["source"] == f"https://img/{loc['id']}-{loc['angles'][0]['angle']}.png"
    assert len(compose.pick_refs(clip, ridx, 10)["kept"]) == 4
    for card in rich["assets"]["props"]:
        card["reference_images"] = [{"view": "front", "uri": "local/none.png"}]   # 非 http/data 不算有图
    got = compose.pick_refs(clip, assets_index(rich), 10)
    assert [s["asset_id"] for s in got["missing"]] == [prop]
    assert compose.describe(got["missing"][0], assets_index(rich)).startswith("道具：")
    print("6. 参考图优先级与文字描述 ✓")

    # 7. 首帧：关键帧优先；没有参考图时用上一段尾帧接力；有参考图时关键帧占参考位
    with tempfile.TemporaryDirectory() as d:
        kf_shot = clips[1]["shots"][0]["id"]
        png = Path(d) / f"{kf_shot}.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
        kw = dict(provider="fake", model="fake-1", resolution="720p", audio_mode="tts_all",
                  rewrite=fake.rewrite_prompt)
        built = compose.build_clips(doc, caps, keyframes={kf_shot: png}, **kw)
        assert built[1]["first_frame"] == f"keyframe:{kf_shot}" and built[1]["frame_mode"] == "frame"
        relay = [b for b in built if (b["first_frame"] or "").startswith("relay:")]
        assert relay and all(b["frame_mode"] == "frame" for b in relay)
        assert all(not b["first_frame"] for b in built
                   if b["id"].endswith("-C01") and b["shots"][0] != kf_shot), "每集第一段不接力"
        assert "{ref:" not in built[0]["prompt"], "已按厂商语法改写"

        # 有参考图：关键帧作为第一个参考位
        rich2 = copy.deepcopy(rich)
        for card in rich2["assets"]["characters"]:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
        rb = compose.build_clips(rich2, caps, keyframes={kf_shot: png}, **kw)
        target = next(b for b in rb if b["shots"][0] == kf_shot)
        if target["refs"]:
            assert target["frame_mode"] == "ref" and "[参考__first__]" in target["prompt"]
            assert len(target["refs"]) <= caps.max_refs - 1, "首帧占一个名额"

        # 8. 指纹：设置或分镜变了才变
        again = compose.build_clips(doc, caps, keyframes={kf_shot: png}, **kw)
        assert [b["fingerprint"] for b in again] == [b["fingerprint"] for b in built]
        lo = compose.build_clips(doc, caps, keyframes={kf_shot: png},
                                 **{**kw, "resolution": "480p"})
        assert all(a["fingerprint"] != b["fingerprint"] for a, b in zip(lo, built))
        edited = copy.deepcopy(doc)
        edited["episodes"][0]["shots"][0]["action"] += "（改）"
        eb = compose.build_clips(edited, caps, keyframes={kf_shot: png}, **kw)
        assert eb[0]["fingerprint"] != built[0]["fingerprint"]
        assert eb[1]["fingerprint"] == built[1]["fingerprint"], "只影响所在的段"
        must_raise(ValueError, compose.build_clips, doc, caps, keyframes={},
                   **{**kw, "audio_mode": "karaoke"})
        print("7. 首帧来源 ✓\n8. 指纹 ✓")

        # 9. 请求组装：按已保存分镜重建，指纹对不上抛 Stale
        session = {"provider": "fake", "model": "fake-1", "resolution": "720p",
                   "audio_mode": "tts_all"}
        clip_row = {k: v for k, v in built[1].items() if not k.startswith("_")}
        req, used = compose.request_for(doc, session, clip_row, keyframes={kf_shot: png},
                                        relay_frame=None, caps=caps, rewrite=fake.rewrite_prompt)
        assert isinstance(req, base.ClipRequest) and used == f"keyframe:{kf_shot}"
        assert req.first_frame.startswith("data:image/png;base64,") and req.refs == []
        assert req.prompt == built[1]["prompt"] and req.duration == built[1]["duration"]
        assert req.aspect == doc["meta"]["video"]["aspect_ratio"] and req.audio is True
        r2 = next(b for b in built if (b["first_frame"] or "").startswith("relay:"))
        row2 = {k: v for k, v in r2.items() if not k.startswith("_")}
        req2, used2 = compose.request_for(doc, session, row2, keyframes={kf_shot: png},
                                          relay_frame=None, caps=caps, rewrite=fake.rewrite_prompt)
        assert req2.first_frame is None and used2 is None, "上一段还没尾帧：不带首帧"
        jpg = Path(d) / "prev.last.jpg"
        jpg.write_bytes(b"\xff\xd8x")
        req3, used3 = compose.request_for(doc, session, row2, keyframes={kf_shot: png},
                                          relay_frame=jpg, caps=caps, rewrite=fake.rewrite_prompt)
        assert req3.first_frame.startswith("data:image/jpeg;base64,") and used3 == r2["first_frame"]
        must_raise(compose.Stale, compose.request_for, edited, session,
                   {k: v for k, v in built[0].items() if not k.startswith("_")},
                   keyframes={kf_shot: png}, relay_frame=None, caps=caps,
                   rewrite=fake.rewrite_prompt)
        silent = compose.request_for(doc, {**session, "audio_mode": "silent"},
                                     {**clip_row, "fingerprint": compose.build_clips(
                                         doc, caps, keyframes={kf_shot: png},
                                         **{**kw, "audio_mode": "silent"})[1]["fingerprint"]},
                                     keyframes={kf_shot: png}, relay_frame=None, caps=caps,
                                     rewrite=fake.rewrite_prompt)[0]
        assert silent.audio is False
        print("9. 请求组装 ✓")
```

Replace `    # @@NEXT@@` in `main()` with:

```python
    part_clips(doc)
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/render/test_compose.py`
Expected: 1–4 ✓，然后 `AttributeError: module 'render.compose' has no attribute 'cut_clips'`

- [ ] **Step 3: keyframes 导出文字描述函数**

Append to the end of `backend/render/keyframes.py`:

```python


# 出片（render/compose.py）给没有参考图的资产写文字描述，与静帧提示词同一套写法
describe_character, describe_creature = _character, _creature
describe_location, describe_prop = _location, _prop
```

- [ ] **Step 4: compose 追加切段、参考图、首帧、指纹、请求**

In `backend/render/compose.py`, replace the import block:

```python
from pipeline.quality import DEFAULT_SPEECH_CPS, speech_seconds
from render.plan import TIME_ZH, collect_refs, shot_line
```

with:

```python
import base64
import hashlib
import json
from pathlib import Path
from typing import Optional

from pipeline.quality import DEFAULT_SPEECH_CPS, speech_seconds
from render import keyframes as kf
from render.plan import TIME_ZH, assets_index, collect_refs, shot_line
from render.providers.base import ClipRequest, RefImage
```

Append to the end of `backend/render/compose.py`:

```python


# ---------- 切段 ----------

def cut_clips(doc: dict, caps, cps: float = DEFAULT_SPEECH_CPS) -> list:
    """按镜头顺序装箱：每段可播时长 ≤ caps.max_clip_sec。

    单镜超上限独立成段并标 truncated；不足 min_clip_sec 的段并入相邻段（并得进去的话）。
    返回 [{"id", "episode", "shots": [镜头 dict], "duration", "truncated"}]。
    """
    out = []
    for ep in doc.get("episodes") or []:
        segs, cur, cur_len = [], [], 0.0
        for s in ep.get("shots") or []:
            d = playable(s, cps)
            if d > caps.max_clip_sec:
                if cur:
                    segs.append([cur, cur_len, False])
                    cur, cur_len = [], 0.0
                segs.append([[s], d, True])
                continue
            if cur and cur_len + d > caps.max_clip_sec + 1e-9:
                segs.append([cur, cur_len, False])
                cur, cur_len = [], 0.0
            cur.append(s)
            cur_len += d
        if cur:
            segs.append([cur, cur_len, False])
        for i, (shots, d, trunc) in enumerate(_merge_short(segs, caps), 1):
            out.append({"id": f"{ep['id']}-C{i:02d}", "episode": ep["id"], "shots": shots,
                        "duration": round(d, 1), "truncated": trunc})
    return out


def _merge_short(segs: list, caps) -> list:
    out = []
    for shots, d, trunc in segs:
        prev = out[-1] if out else None
        if (prev and not trunc and not prev[2]
                and (d < caps.min_clip_sec or prev[1] < caps.min_clip_sec)
                and prev[1] + d <= caps.max_clip_sec + 1e-9):
            prev[0] = prev[0] + shots
            prev[1] += d
        else:
            out.append([list(shots), d, trunc])
    return out


# ---------- 参考图 ----------

def _usable(uri) -> bool:
    return isinstance(uri, str) and uri.startswith(("http://", "https://", "data:image/"))


def image_for(slot: dict, assets_idx: dict) -> Optional[str]:
    """资产卡上这个参考位的图（http(s) 地址或 data URI）；没有返回 None。

    角色按着装、道具按状态、场景按机位挑图，挑不到用该卡的第一张。
    """
    role, aid, var = slot["role"], slot["asset_id"], slot["variant"]
    if role == "location":
        card = assets_idx["locations"].get(aid) or {}
        imgs = [a for a in card.get("angles") or [] if _usable(a.get("uri"))]
        key = "angle"
    else:
        kind = {"character": "characters", "creature": "creatures", "prop": "props"}[role]
        card = assets_idx[kind].get(aid) or {}
        imgs = [i for i in card.get("reference_images") or [] if _usable(i.get("uri"))]
        key = "outfit" if role == "character" else "state"
    hit = next((i for i in imgs if var and i.get(key) == var), None) or (imgs[0] if imgs else None)
    return hit["uri"] if hit else None


def pick_refs(clip: list, assets_idx: dict, max_refs: int) -> dict:
    """参考位按优先级保留：本段主要角色 > 场景 > 次要角色与生物 > 道具。

    主要角色 = 本段出镜镜头数最多的角色（并列都算）。保留的按出场顺序排列（占位符编号
    与请求里的图片顺序一致）。返回 {"kept": 带 source 的参考位, "dropped": 有图但被裁的,
    "missing": 没有图的}。
    """
    slots = ref_slots(clip, assets_idx)
    counts = {}
    for s in clip:
        for c in s.get("characters") or []:
            counts[c["ref"]] = counts.get(c["ref"], 0) + 1
    top = max((counts.get(sl["asset_id"], 0) for sl in slots if sl["role"] == "character"),
              default=0)

    def tier(sl):
        if sl["role"] == "character" and counts.get(sl["asset_id"], 0) == top:
            return 0
        return {"location": 1, "character": 2, "creature": 2}.get(sl["role"], 3)

    found = [(i, sl, image_for(sl, assets_idx)) for i, sl in enumerate(slots)]
    ranked = sorted((x for x in found if x[2]), key=lambda x: (tier(x[1]), x[0]))
    keep = {i for i, _, _ in ranked[:max(max_refs, 0)]}
    return {"kept": [{**sl, "source": src} for i, sl, src in found if i in keep],
            "dropped": [sl for i, sl, src in found if src and i not in keep],
            "missing": [sl for i, sl, src in found if not src]}


def describe(slot: dict, assets_idx: dict) -> str:
    """没有参考图（或被裁掉）的资产：用资产卡的文字描述代替。"""
    aid, role, var = slot["asset_id"], slot["role"], slot["variant"]
    if role == "character" and aid in assets_idx["characters"]:
        return "人物：" + kf.describe_character(assets_idx["characters"][aid], var)
    if role == "creature" and aid in assets_idx["creatures"]:
        return "生物：" + kf.describe_creature(assets_idx["creatures"][aid])
    if role == "location" and aid in assets_idx["locations"]:
        return "场景：" + kf.describe_location(assets_idx["locations"][aid])
    if role == "prop" and aid in assets_idx["props"]:
        return "道具：" + kf.describe_prop(assets_idx["props"][aid], var)
    return ""


# ---------- 指纹与整段组装 ----------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def fingerprint(**parts) -> str:
    """输入指纹：镜头内容、提示词、参考图、首帧来源、厂商、档位、分辨率、声音模式。"""
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return _sha(blob.encode("utf-8"))


def build_clips(doc: dict, caps, *, provider: str, model: str, resolution: str,
                audio_mode: str, keyframes: dict, rewrite, cps: float = DEFAULT_SPEECH_CPS) -> list:
    """分镜 → 出片段（session.json 的 clips，不含状态）。

    keyframes：镜头 id → 关键帧图路径。首帧：段首镜头有关键帧用关键帧；否则在本段没有参考图、
    厂商能返回尾帧时，用同一集上一段的尾帧接力；都不满足就不带首帧。厂商不能首帧与参考图同用
    时（frame_with_refs=False），关键帧占第一个参考位（frame_mode="ref"）。
    下划线开头的键只在内存里用，不落盘。
    """
    if audio_mode not in AUDIO_MODES:
        raise ValueError(f"未知的声音模式：{audio_mode}")
    idx = assets_index(doc)
    out, prev = [], None
    for c in cut_clips(doc, caps, cps):
        shots = c["shots"]
        refs = pick_refs(shots, idx, caps.max_refs)
        sid = shots[0].get("id")
        first = None
        if caps.first_frame and sid in keyframes:
            first = f"keyframe:{sid}"
        elif (caps.first_frame and caps.returns_last_frame and prev is not None
              and prev["episode"] == c["episode"] and (caps.frame_with_refs or not refs["kept"])):
            first = f"relay:{prev['id']}"
        frame_mode = None
        if first:
            frame_mode = "ref" if refs["kept"] and not caps.frame_with_refs else "frame"
        if frame_mode == "ref" and len(refs["kept"]) >= caps.max_refs:
            refs = pick_refs(shots, idx, caps.max_refs - 1)
            if not refs["kept"]:
                frame_mode = "frame"
        described = [describe(sl, idx) for sl in refs["missing"] + refs["dropped"]]
        text, _ = neutral_prompt(shots, doc, idx, mode=audio_mode, slots=refs["kept"],
                                 described=described, first_frame=frame_mode == "ref",
                                 timing="playable", cps=cps)
        prompt = rewrite(text)
        kf_hash = (_sha(Path(keyframes[sid]).read_bytes())
                   if first and first.startswith("keyframe:") else None)
        fp = fingerprint(shots=shots, prompt=prompt,
                         refs=[_sha(sl["source"].encode("utf-8")) for sl in refs["kept"]],
                         first=first, keyframe=kf_hash, provider=provider, model=model,
                         resolution=resolution, audio_mode=audio_mode)
        out.append({"id": c["id"], "episode": c["episode"],
                    "shots": [s.get("id") for s in shots],
                    "duration": c["duration"], "truncated": c["truncated"], "prompt": prompt,
                    "refs": [sl["asset_id"] for sl in refs["kept"]],
                    "dropped_refs": [sl["asset_id"] for sl in refs["dropped"]],
                    "missing_refs": [sl["asset_id"] for sl in refs["missing"]],
                    "first_frame": first, "frame_mode": frame_mode, "fingerprint": fp,
                    "_slots": refs["kept"]})
        prev = c
    return out


# ---------- 厂商请求 ----------

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def data_uri(path: Path) -> str:
    mime = _MIME.get(Path(path).suffix.lower(), "image/jpeg")
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


class Stale(Exception):
    """分镜、关键帧或设置变了：这一段的指纹与会话里的对不上，不能按旧的确认去花钱。"""


def request_for(doc: dict, session: dict, clip: dict, *, keyframes: dict, relay_frame,
                caps, rewrite, cps: float = DEFAULT_SPEECH_CPS) -> tuple:
    """按已保存的分镜重建这一段的厂商请求。返回 (ClipRequest, 实际使用的首帧来源或 None)。

    relay_frame：上一段采用那次的尾帧文件（没有就是 None，此时不带首帧照常提交）。
    """
    built = build_clips(doc, caps, provider=session["provider"], model=session["model"],
                        resolution=session["resolution"], audio_mode=session["audio_mode"],
                        keyframes=keyframes, rewrite=rewrite, cps=cps)
    c = next((b for b in built if b["id"] == clip["id"]), None)
    if c is None or c["fingerprint"] != clip["fingerprint"]:
        raise Stale(clip["id"])
    refs = [RefImage(sl["asset_id"], sl["role"], sl["source"]) for sl in c["_slots"]]
    image, used = None, None
    if c["first_frame"] and c["first_frame"].startswith("keyframe:"):
        image, used = data_uri(Path(keyframes[c["shots"][0]])), c["first_frame"]
    elif c["first_frame"] and relay_frame is not None and Path(relay_frame).exists():
        image, used = data_uri(Path(relay_frame)), c["first_frame"]
    if c["frame_mode"] == "ref" and image:
        refs.insert(0, RefImage(FIRST, "first_frame", image))
        image = None
    aspect = (doc.get("meta") or {}).get("video", {}).get("aspect_ratio", "9:16")
    req = ClipRequest(prompt=c["prompt"], model=session["model"], duration=c["duration"],
                      resolution=session["resolution"], aspect=aspect,
                      audio=session["audio_mode"] != "silent" and caps.native_audio,
                      refs=refs, first_frame=image)
    return req, used
```

- [ ] **Step 5: 运行，确认通过**

Run: `.venv/bin/python tests/render/test_compose.py && .venv/bin/python tests/server/test_keyframes.py`
Expected: 1–9 ✓ 与 `ALL PASS`；关键帧测试 `ALL PASS`

- [ ] **Step 6: 提交**

```bash
git add render/compose.py render/keyframes.py tests/render/test_compose.py
git commit -m "出片切段与请求组装：按可播时长装箱、超长单镜截断、短段并入；参考图按主角/场景/配角/道具裁剪，无图写文字描述；关键帧首帧与同集尾帧接力，方舟互斥时关键帧占参考位；输入指纹与按已保存分镜重建请求"
```

---

### Task 4: 出片会话与状态迁移

**Files:**
- Create: `backend/render/session.py`
- Test: `backend/tests/render/test_session.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/render/test_session.py`:

```python
#!/usr/bin/env python3
"""出片会话：建立与校验、沿用尝试与过期判定、排队确认与上限、提交前复查、采用与静音、接力、重启恢复。

用法: python3 tests/render/test_session.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"

from render import providers, session as sess  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def clip(s, cid):
    return next(c for c in s["clips"] if c["id"] == cid)


def finish(root, fake, clip_id):
    """不经出片线程把一段走完：提交 → 成功 → 下载。"""
    snap = sess.begin_submit(root, clip_id)
    s = sess.load(root)
    req = base.ClipRequest(prompt=snap["prompt"], model=s["model"], duration=snap["duration"],
                           resolution=s["resolution"])
    tid = fake.submit(req)
    sess.submitted(root, clip_id, tid, None)
    st = fake.poll(tid)
    sess.poll_update(root, clip_id, st)
    files = fake.download(st, Path(root) / "clips" / f"{clip_id}.v{len(snap['attempts'])}.mp4")
    sess.downloaded(root, clip_id, files, fake.cost(st, req))


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    fake = FakeVideo()
    providers.register("fake", lambda: fake)
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name) / "render" / "v"
    build = lambda d=doc, **patch: sess.build(root, d, owner=OWNER, patch=patch, keyframes={})  # noqa: E731

    # 1. 建会话：默认设置、全部 planned、每段有预估；非法设置拒绝
    s = build()
    assert (root / "session.json").exists()
    assert (s["provider"], s["model"], s["resolution"], s["audio_mode"]) == \
        ("fake", "fake-1", "720p", "tts_all")
    assert s["budget_cny"] == 200.0 and s["confirm_over_cny"] == 20.0 and s["spent_cny"] == 0.0
    assert s["clips"] and all(c["state"] == "planned" and c["attempts"] == [] for c in s["clips"])
    caps = fake.caps("fake-1")
    assert all(c["estimate_cny"] == base.estimate_cny(c["duration"], caps, "720p") for c in s["clips"])
    must_raise(sess.SessionError, build, resolution="4k")
    must_raise(sess.SessionError, build, audio_mode="karaoke")
    must_raise(sess.SessionError, build, provider="nope")
    must_raise(sess.SessionError, build, bogus=1)
    v = sess.view(s)
    assert "owner" not in v and v["counts"] == {"planned": len(s["clips"])}
    assert v["remaining_cny"] == round(sum(c["estimate_cny"] for c in s["clips"]), 2)
    assert "fake" in v["options"]["providers"] and v["options"]["resolutions"] == ["480p", "720p"]
    print("1. 建会话与校验 ✓")

    # 2. 单段排队：低于确认线直接排；在跑时不能改设置；读取时刷新不动在跑的段
    first, second = s["clips"][0]["id"], s["clips"][1]["id"]
    s = sess.queue_run(root, [first])
    assert clip(s, first)["state"] == "queued"
    must_raise(sess.Conflict, sess.queue_run, root, [first])
    must_raise(sess.Conflict, build, resolution="480p")
    s = sess.build(root, doc, owner=OWNER, patch={}, keyframes={}, allow_in_flight=True)
    assert clip(s, first)["state"] == "queued"
    must_raise(sess.NotFound, sess.queue_run, root, ["E99-C01"])
    print("2. 单段排队 ✓")

    # 3. 走完一段：已花 = 实际费用，采用最新一次
    finish(root, fake, first)
    s = sess.load(root)
    c = clip(s, first)
    assert c["state"] == "done" and c["chosen"] == 0
    assert c["attempts"][0]["file"] == f"clips/{first}.v1.mp4"
    assert c["attempts"][0]["last_frame"] == f"clips/{first}.v1.last.jpg"
    assert s["spent_cny"] == c["attempts"][0]["cost_cny"] > 0
    print("3. 走完一段 ✓")

    # 4. 改设置或分镜 → 已出的段过期（旧视频仍在）；改回 → 恢复 done
    s = build(resolution="480p")
    assert clip(s, first)["state"] == "stale" and clip(s, first)["chosen"] == 0
    assert all(c["state"] == "planned" for c in s["clips"] if c["id"] != first)
    assert s["spent_cny"] > 0, "已花不随重建清零"
    s = build(resolution="720p")
    assert clip(s, first)["state"] == "done"
    edited = copy.deepcopy(doc)
    edited["episodes"][0]["shots"][0]["action"] += "（改）"
    s = build(edited)
    assert clip(s, first)["state"] == "stale"
    s = build()
    assert clip(s, first)["state"] == "done"
    print("4. 过期判定 ✓")

    # 5. 接力：上一段完成后给出尾帧路径；上一段在跑时等待
    c2 = clip(s, second)
    assert c2["first_frame"] == f"relay:{first}" and not sess.waiting_on_relay(s, c2)
    assert sess.relay_frame(root, s, c2) == root / f"clips/{first}.v1.last.jpg"
    s = sess.queue_run(root, [second])
    third = next(c for c in s["clips"] if c["first_frame"] == f"relay:{second}")
    assert sess.waiting_on_relay(s, third)
    print("5. 接力 ✓")

    # 6. 批量：必须带确认金额；不一致 409 附重算金额；超上限拒绝
    e = must_raise(sess.Conflict, sess.queue_run, root, None)
    total = e.expected_cny
    assert total == sess.view(sess.load(root))["remaining_cny"] > 0
    assert must_raise(sess.Conflict, sess.queue_run, root, None, total + 1).expected_cny == total
    assert total + sess.load(root)["spent_cny"] > 200
    must_raise(sess.BudgetExceeded, sess.queue_run, root, None, total)
    with sess.mutate(root) as s:
        s["budget_cny"] = 100000.0
    s = sess.queue_run(root, None, total)
    assert all(c["state"] == "queued" for c in s["clips"] if c["id"] != first)
    print("6. 批量确认与上限 ✓")

    # 7. 单段超过确认线也要带金额；提交前再查上限
    root2 = Path(tmp.name) / "render" / "v2"
    s2 = sess.build(root2, doc, owner=OWNER, patch={"confirm_over_cny": 1}, keyframes={})
    one = s2["clips"][0]["id"]
    e = must_raise(sess.Conflict, sess.queue_run, root2, [one])
    sess.queue_run(root2, [one], e.expected_cny)
    with sess.mutate(root2) as s2:
        s2["spent_cny"] = 199.99
    assert sess.begin_submit(root2, one) is None
    c = clip(sess.load(root2), one)
    assert c["state"] == "failed" and "超出单章上限" in c["error"] and c["attempts"] == []
    print("7. 单段确认线与提交前复查 ✓")

    # 8. 采用与静音
    s = sess.set_chosen(root, first, 0)
    assert clip(s, first)["state"] == "done"
    must_raise(sess.SessionError, sess.set_chosen, root, first, 5)
    must_raise(sess.Conflict, sess.set_chosen, root, second, 0)
    s = sess.set_mute(root, first, True)
    assert clip(s, first)["mute_native"] is True
    print("8. 采用与静音 ✓")

    # 9. 重启恢复：提交中断的尝试标失败、不重复提交；还有在跑的段返回 True
    snap = sess.begin_submit(root, second)
    assert snap["attempts"][-1]["state"] == "submitting"
    assert sess.recover(root) is True
    c = clip(sess.load(root), second)
    assert c["state"] == "failed" and "不确定厂商是否已受理" in c["error"]
    assert c["attempts"][-1]["state"] == "failed"
    print("9. 重启恢复 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/render/test_session.py`
Expected: `ImportError: cannot import name 'session' from 'render'`

- [ ] **Step 3: 写 `session.py`**

Create `backend/render/session.py`:

```python
"""出片会话：一个版本的出片状态（chapters/<cid>/render/<vid>/session.json）与全部状态迁移。

接口线程与出片线程都只通过这里改状态：同一会话的读改写用进程内锁串行，写入先写临时文件再改名。
段状态（设计文档 1.5）：planned → queued → running → downloading → done；failed；stale（指纹与
当前分镜不符，旧视频仍可播）。每段保留全部尝试，chosen 指向采用的那次。
"""
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from render import compose
from render.providers import base, default_video_name, get_video, names

SESSION_FILE = "session.json"
IN_FLIGHT = ("queued", "running", "downloading")
REMAINING = ("planned", "failed")
DEFAULT_BUDGET_CNY = 200.0
DEFAULT_CONFIRM_OVER_CNY = 20.0
SETTING_KEYS = ("provider", "model", "resolution", "audio_mode", "budget_cny", "confirm_over_cny")


class SessionError(ValueError):
    """请求本身不成立（422）。"""


class NotFound(SessionError):
    """会话或段不存在（404）。"""


class Conflict(SessionError):
    """与当前状态冲突（409），可附带服务端重算的金额。"""

    def __init__(self, message: str, expected_cny: Optional[float] = None):
        super().__init__(message)
        self.expected_cny = expected_cny


class BudgetExceeded(SessionError):
    """超出单章上限（422）。"""


_locks: dict = {}
_locks_guard = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _lock(root) -> threading.RLock:
    key = str(Path(root).resolve())
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


def load(root) -> Optional[dict]:
    try:
        return json.loads((Path(root) / SESSION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(root, s: dict) -> None:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    s["updated_at"] = _now()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=root, delete=False,
                                     suffix=".tmp") as f:
        f.write(json.dumps(s, ensure_ascii=False, indent=2) + "\n")
    os.replace(f.name, root / SESSION_FILE)


@contextmanager
def mutate(root):
    """读改写一个已有会话；块内抛异常则不写回。"""
    with _lock(root):
        s = load(root)
        if s is None:
            raise NotFound("还没有出片会话")
        yield s
        _save(root, s)


def _clip(s: dict, clip_id: str) -> dict:
    for c in s["clips"]:
        if c["id"] == clip_id:
            return c
    raise NotFound(f"没有这一段：{clip_id}")


def _provider(name: str):
    try:
        return get_video(name)
    except KeyError as e:
        raise SessionError(e.args[0])
    except base.ProviderError as e:
        raise SessionError(str(e))


# ---------- 设置与建立 ----------

def resolve_settings(old: Optional[dict], patch: dict) -> tuple:
    """合并旧设置与本次修改，校验后返回 (settings, provider, caps)。"""
    patch = {k: v for k, v in (patch or {}).items() if v is not None}
    unknown = set(patch) - set(SETTING_KEYS)
    if unknown:
        raise SessionError(f"未知的出片设置：{sorted(unknown)}")
    cur = {k: (old or {}).get(k) for k in SETTING_KEYS}
    cur.update(patch)
    provider = _provider(cur["provider"] or default_video_name())
    cur["provider"] = provider.name
    if cur["model"] not in provider.models:
        if "model" in patch:
            raise SessionError(f"{provider.name} 没有档位 {cur['model']}")
        cur["model"] = provider.default_model
    caps = provider.caps(cur["model"])
    if cur["resolution"] not in caps.resolutions:
        if "resolution" in patch:
            raise SessionError(f"这个档位不支持 {cur['resolution']}，可选：{'、'.join(caps.resolutions)}")
        cur["resolution"] = "720p" if "720p" in caps.resolutions else caps.resolutions[0]
    cur["audio_mode"] = cur["audio_mode"] or "tts_all"
    if cur["audio_mode"] not in compose.AUDIO_MODES:
        raise SessionError(f"未知的声音模式：{cur['audio_mode']}")
    cur["budget_cny"] = float(cur["budget_cny"] or DEFAULT_BUDGET_CNY)
    cur["confirm_over_cny"] = float(DEFAULT_CONFIRM_OVER_CNY if cur["confirm_over_cny"] is None
                                    else cur["confirm_over_cny"])
    return cur, provider, caps


def _carry(row: dict, old: Optional[dict]) -> dict:
    """沿用同一段（同 id、同镜头）的尝试记录，并按采用那次的指纹判定 done / stale。"""
    same = old is not None and old["shots"] == row["shots"]
    row["attempts"] = old["attempts"] if same else []
    row["chosen"] = old.get("chosen") if same else None
    row["mute_native"] = bool(old.get("mute_native")) if same else False
    row["error"] = None
    if row["chosen"] is not None:
        chosen = row["attempts"][row["chosen"]]
        row["state"] = "done" if chosen.get("fingerprint") == row["fingerprint"] else "stale"
    elif same and old["state"] == "failed" and old["fingerprint"] == row["fingerprint"]:
        row["state"], row["error"] = "failed", old.get("error")
    else:
        row["state"] = "planned"
    return row


def build(root, doc: dict, *, owner: dict, patch: dict, keyframes: dict,
          allow_in_flight: bool = False) -> dict:
    """按已保存的分镜切段、组装提示词，生成或重建会话。不花钱。

    改设置时（allow_in_flight=False）有段在排队或生成中就拒绝；读取时的刷新传 True，
    在跑的段原样保留（切段变了也保留到跑完）。已花金额与尝试记录跨重建保留。
    """
    root = Path(root)
    with _lock(root):
        old = load(root)
        settings, provider, caps = resolve_settings(old, patch)
        olds = {c["id"]: c for c in (old or {}).get("clips", [])}
        flying = {cid: c for cid, c in olds.items() if c["state"] in IN_FLIGHT}
        if flying and not allow_in_flight:
            raise Conflict("有段在排队或生成中，等它们结束再改设置")
        try:
            built = compose.build_clips(doc, caps, provider=settings["provider"],
                                        model=settings["model"], resolution=settings["resolution"],
                                        audio_mode=settings["audio_mode"], keyframes=keyframes,
                                        rewrite=provider.rewrite_prompt)
        except (KeyError, TypeError, ValueError) as e:
            raise SessionError(f"分镜结构不完整，无法切段：{e}")
        clips = []
        for b in built:
            if b["id"] in flying:
                clips.append(flying.pop(b["id"]))
                continue
            row = {k: v for k, v in b.items() if not k.startswith("_")}
            row["estimate_cny"] = base.estimate_cny(row["duration"], caps, settings["resolution"])
            clips.append(_carry(row, olds.get(b["id"])))
        clips.extend(flying.values())
        s = {"version": 1, "owner": owner, **settings,
             "spent_cny": (old or {}).get("spent_cny", 0.0), "clips": clips,
             "voices": (old or {}).get("voices", {}), "final": (old or {}).get("final"),
             "created_at": (old or {}).get("created_at") or _now()}
        _save(root, s)
        return s


def view(s: dict) -> dict:
    """给界面的会话：去掉归属，附状态计数、剩余与在跑预估、可选项。"""
    provider = _provider(s["provider"])
    caps = provider.caps(s["model"])
    counts = {}
    for c in s["clips"]:
        counts[c["state"]] = counts.get(c["state"], 0) + 1
    out = {k: v for k, v in s.items() if k != "owner"}
    out["counts"] = counts
    out["remaining_cny"] = round(sum(c["estimate_cny"] for c in s["clips"]
                                     if c["state"] in REMAINING), 2)
    out["reserved_cny"] = round(sum(c["estimate_cny"] for c in s["clips"]
                                    if c["state"] in IN_FLIGHT), 2)
    out["options"] = {"providers": names(), "models": provider.models,
                      "resolutions": caps.resolutions, "cny_per_sec": caps.cny_per_sec,
                      "max_clip_sec": caps.max_clip_sec, "max_refs": caps.max_refs,
                      "audio_modes": list(compose.AUDIO_MODES)}
    return out


# ---------- 接口侧操作 ----------

def queue_run(root, clip_ids: Optional[list] = None, expected_cny: Optional[float] = None) -> dict:
    """排队出片。clip_ids=None 为批量出剩余各段（planned / failed），必须带确认金额；
    单段超过确认线也要带。金额与服务端重算不一致 → Conflict（附重算金额）。"""
    with mutate(root) as s:
        if clip_ids is None:
            targets = [c for c in s["clips"] if c["state"] in REMAINING]
        else:
            targets = [_clip(s, cid) for cid in clip_ids]
            for c in targets:
                if c["state"] in IN_FLIGHT:
                    raise Conflict(f"{c['id']} 已在排队或生成中")
        if not targets:
            raise SessionError("没有要出的段")
        total = round(sum(c["estimate_cny"] for c in targets), 2)
        if (clip_ids is None or total > s["confirm_over_cny"]) and expected_cny is None:
            raise Conflict(f"本次约 ¥{total:.2f}，请确认金额后再出片", total)
        if expected_cny is not None and abs(expected_cny - total) > 0.005:
            raise Conflict(f"预估金额已变为 ¥{total:.2f}，请重新确认", total)
        reserved = sum(c["estimate_cny"] for c in s["clips"] if c["state"] in IN_FLIGHT)
        if s["spent_cny"] + reserved + total > s["budget_cny"] + 1e-9:
            raise BudgetExceeded(f"超出单章上限 ¥{s['budget_cny']:g}：已花 ¥{s['spent_cny']:.2f}，"
                                 f"在跑预留 ¥{reserved:.2f}，本次约 ¥{total:.2f}")
        for c in targets:
            c["state"], c["error"], c["queued_at"] = "queued", None, _now()
        return s


def set_chosen(root, clip_id: str, index: int) -> dict:
    with mutate(root) as s:
        c = _clip(s, clip_id)
        if c["state"] in IN_FLIGHT:
            raise Conflict("这一段正在生成，等它结束再换")
        if not (0 <= index < len(c["attempts"])) or c["attempts"][index].get("state") != "succeeded":
            raise SessionError("只能采用成功的那几次")
        c["chosen"] = index
        c["state"] = "done" if c["attempts"][index].get("fingerprint") == c["fingerprint"] else "stale"
        return s


def set_mute(root, clip_id: str, mute: bool) -> dict:
    with mutate(root) as s:
        _clip(s, clip_id)["mute_native"] = bool(mute)
        return s


# ---------- 出片线程侧迁移 ----------

def begin_submit(root, clip_id: str) -> Optional[dict]:
    """提交前：再查一次上限（实际花费可能超过预估），追加一次「提交中」的尝试，返回段的快照。
    不该提交（不在排队、超上限）返回 None；超上限的段转 failed。"""
    with mutate(root) as s:
        c = _clip(s, clip_id)
        if c["state"] != "queued":
            return None
        running = sum(x["estimate_cny"] for x in s["clips"] if x["state"] in ("running", "downloading"))
        if s["spent_cny"] + running + c["estimate_cny"] > s["budget_cny"] + 1e-9:
            c["state"], c["error"] = "failed", "超出单章上限，没有提交"
            return None
        c["attempts"].append({"task_id": None, "state": "submitting", "cost_cny": 0.0,
                              "file": None, "last_frame": None, "error": None, "at": _now(),
                              "fingerprint": c["fingerprint"], "first_frame_used": None})
        return json.loads(json.dumps(c))


def submitted(root, clip_id: str, task_id: str, first_frame_used: Optional[str]) -> None:
    with mutate(root) as s:
        c = _clip(s, clip_id)
        c["attempts"][-1].update(task_id=task_id, state="running", first_frame_used=first_frame_used)
        c["state"] = "running"


def submit_failed(root, clip_id: str, error: str, *, stale: bool = False) -> None:
    """提交没成：stale=True（分镜已改）撤回这次尝试、退回待确认；否则记失败。"""
    with mutate(root) as s:
        c = _clip(s, clip_id)
        pending = c["attempts"] and c["attempts"][-1]["state"] == "submitting"
        if stale:
            if pending:
                c["attempts"].pop()
            c["state"] = "stale" if c.get("chosen") is not None else "planned"
        else:
            if pending:
                c["attempts"][-1].update(state="failed", error=error)
            c["state"] = "failed"
        c["error"] = error


def poll_update(root, clip_id: str, st: base.TaskState, cost: float = 0.0) -> None:
    with mutate(root) as s:
        c = _clip(s, clip_id)
        a = c["attempts"][-1] if c["attempts"] else {}
        if c["state"] != "running" or a.get("task_id") != st.task_id:
            return
        if st.status == "succeeded":
            a.update(video_url=st.video_url, last_frame_url=st.last_frame_url, usage=st.usage)
            c["state"] = "downloading"
        elif st.status == "failed":
            a.update(state="failed", error=st.error or "厂商返回失败", cost_cny=cost)
            s["spent_cny"] = round(s["spent_cny"] + cost, 2)
            c["state"], c["error"] = "failed", a["error"]


def _rel(root, p) -> Optional[str]:
    return Path(p).resolve().relative_to(Path(root).resolve()).as_posix() if p else None


def downloaded(root, clip_id: str, files: dict, cost: float) -> None:
    with mutate(root) as s:
        c = _clip(s, clip_id)
        if c["state"] != "downloading":
            return
        a = c["attempts"][-1]
        a.update(state="succeeded", file=_rel(root, files["video"]),
                 last_frame=_rel(root, files.get("last_frame")), cost_cny=cost)
        s["spent_cny"] = round(s["spent_cny"] + cost, 2)
        c["chosen"] = len(c["attempts"]) - 1
        c["state"] = "done" if a["fingerprint"] == c["fingerprint"] else "stale"
        c["error"] = None


def download_failed(root, clip_id: str, error: str, cost: float) -> None:
    """已经生成、但下载或校验失败：生成费用照记。"""
    with mutate(root) as s:
        c = _clip(s, clip_id)
        c["attempts"][-1].update(state="failed", error=error, cost_cny=cost)
        s["spent_cny"] = round(s["spent_cny"] + cost, 2)
        c["state"], c["error"] = "failed", error


def _prev(s: dict, clip: dict) -> Optional[dict]:
    ff = clip.get("first_frame") or ""
    if not ff.startswith("relay:"):
        return None
    return next((c for c in s["clips"] if c["id"] == ff[len("relay:"):]), None)


def waiting_on_relay(s: dict, clip: dict) -> bool:
    """接力的段要等上一段跑完（成功就带尾帧，失败就不带）。"""
    prev = _prev(s, clip)
    return clip.get("frame_mode") == "frame" and prev is not None and prev["state"] in IN_FLIGHT


def relay_frame(root, s: dict, clip: dict) -> Optional[Path]:
    """上一段采用那次的尾帧文件；没有返回 None。"""
    prev = _prev(s, clip)
    if prev is None or prev.get("chosen") is None:
        return None
    rel = prev["attempts"][prev["chosen"]].get("last_frame")
    return Path(root) / rel if rel else None


def recover(root) -> bool:
    """进程重启后：提交中断（没拿到任务 id）的尝试标失败，不重复提交。返回是否还有在跑的段。"""
    with _lock(root):
        s = load(root)
        if s is None:
            return False
        changed = False
        for c in s["clips"]:
            a = c["attempts"][-1] if c["attempts"] else None
            if a and a["state"] == "submitting":
                a.update(state="failed",
                         error="提交时服务中断，不确定厂商是否已受理；请到厂商控制台核对后再重做")
                c["state"], c["error"] = "failed", a["error"]
                changed = True
        if changed:
            _save(root, s)
        return any(c["state"] in IN_FLIGHT for c in s["clips"])
```

- [ ] **Step 4: 运行，确认通过**

Run: `.venv/bin/python tests/render/test_session.py`
Expected: 1–9 ✓，`ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add render/session.py tests/render/test_session.py
git commit -m "出片会话：session.json 原子读写与进程内锁；建立与重建（沿用尝试、按采用那次的指纹判定过期）；批量与超线单段须确认金额、重算不一致 409、单章上限含在跑预留；提交前复查上限；采用与原声静音；接力等待与尾帧；重启时提交中断的尝试标失败"
```

---

### Task 5: 出片后台线程

**Files:**
- Create: `backend/render/runner.py`
- Test: `backend/tests/render/test_runner.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/render/test_runner.py`:

```python
#!/usr/bin/env python3
"""出片线程：提交 → 轮询 → 下载、瞬时错误重试、厂商失败、并发上限、接力顺序、分镜改动不提交、
下载校验、重启续跑不重复提交。用法: python3 tests/render/test_runner.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"

from render import compose, providers, session as sess  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from render.runner import Runner  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}


def clip(root, cid):
    return next(c for c in sess.load(root)["clips"] if c["id"] == cid)


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    current = {"doc": doc}
    fake = FakeVideo()
    providers.register("fake", lambda: fake)
    tmp = tempfile.TemporaryDirectory()
    data = Path(tmp.name)
    root = data / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    s = sess.build(root, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    ids = [c["id"] for c in s["clips"]]
    firsts = [c["id"] for c in s["clips"] if c["id"].endswith("-C01")]

    def builder(r, sess_now, c):
        return compose.request_for(current["doc"], sess_now, c, keyframes={},
                                   relay_frame=sess.relay_frame(r, sess_now, c),
                                   caps=fake.caps(sess_now["model"]), rewrite=fake.rewrite_prompt)

    slept = []
    runner = Runner(builder, sleep=slept.append, max_parallel=2)

    def drain(limit=200):
        for _ in range(limit):
            if not runner.watching():
                return
            runner.tick()
        raise AssertionError("没跑完")

    # 1. 一段走完：提交 → running → downloading → done，然后不再盯这个会话
    sess.queue_run(root, [ids[0]])
    runner.watch(root)
    runner.tick()
    assert clip(root, ids[0])["state"] == "running"
    runner.tick()
    assert clip(root, ids[0])["state"] == "downloading"
    runner.tick()
    c = clip(root, ids[0])
    assert c["state"] == "done" and (root / c["attempts"][0]["file"]).exists()
    assert runner.watching() == []
    print("1. 一段走完 ✓")

    # 2. 瞬时错误：重试 3 次内成功不算新尝试；3 次都失败记失败
    fake.transient_submits = 2
    sess.queue_run(root, [firsts[1]])
    runner.watch(root)
    runner.tick()
    c = clip(root, firsts[1])
    assert c["state"] == "running" and len(c["attempts"]) == 1 and slept == [1, 2]
    drain()
    fake.transient_submits = 3
    sess.queue_run(root, [firsts[2]])
    runner.watch(root)
    runner.tick()
    c = clip(root, firsts[2])
    assert c["state"] == "failed" and "已重试 3 次" in c["error"]
    fake.transient_submits = 0
    print("2. 瞬时错误重试 ✓")

    # 3. 厂商明确失败：原因原样、不计费
    spent = sess.load(root)["spent_cny"]
    fake.fail_with = "OutputVideoSensitiveContentDetected: 审核未通过"
    sess.queue_run(root, [firsts[2]])
    runner.watch(root)
    drain()
    c = clip(root, firsts[2])
    assert c["state"] == "failed" and c["error"] == fake.fail_with
    assert sess.load(root)["spent_cny"] == spent
    fake.fail_with = None
    print("3. 厂商失败 ✓")

    # 4. 并发上限：同时最多 2 段在跑
    sess.queue_run(root, [firsts[2], firsts[3]])
    sess.queue_run(root, [ids[1]])
    runner.watch(root)
    before = len(fake.submitted)
    runner.tick()
    assert len(fake.submitted) - before == 2
    assert sum(1 for c in sess.load(root)["clips"] if c["state"] == "running") == 2
    drain()
    print("4. 并发上限 ✓")

    # 5. 接力：上一段在跑时下一段等；上一段完成后带尾帧提交
    nxt = next(c for c in sess.load(root)["clips"] if c["first_frame"] == f"relay:{ids[1]}")
    third = next(c for c in sess.load(root)["clips"] if c["first_frame"] == f"relay:{nxt['id']}")
    sess.queue_run(root, [nxt["id"], third["id"]])
    runner.watch(root)
    before = len(fake.submitted)
    runner.tick()
    assert len(fake.submitted) - before == 1 and clip(root, third["id"])["state"] == "queued"
    assert fake.submitted[-1].first_frame.startswith("data:image/jpeg;base64,")
    drain()
    assert clip(root, third["id"])["attempts"][-1]["first_frame_used"] == f"relay:{nxt['id']}"
    print("5. 接力顺序 ✓")

    # 6. 排队后分镜改了：不提交，退回待确认
    target = ids[0]
    sess.queue_run(root, [target])
    edited = copy.deepcopy(doc)
    edited["episodes"][0]["shots"][0]["action"] += "（改）"
    current["doc"] = edited
    runner.watch(root)
    before = len(fake.submitted)
    runner.tick()
    c = clip(root, target)
    assert len(fake.submitted) == before and c["state"] == "stale" and "已改动" in c["error"]
    assert len(c["attempts"]) == 1, "撤回了这次尝试"
    current["doc"] = doc
    print("6. 分镜改动不提交 ✓")

    # 7. 下载到的不是视频：记失败，生成费用照记
    spent = sess.load(root)["spent_cny"]
    real_download = fake.download

    def broken(st, dest):
        files = real_download(st, dest)
        files["video"].write_bytes(b"<html>expired</html>")
        return files

    fake.download = broken
    sess.queue_run(root, [ids[1]])
    runner.watch(root)
    drain()
    c = clip(root, ids[1])
    assert c["state"] == "failed" and "不是可播放的视频" in c["error"]
    assert sess.load(root)["spent_cny"] > spent
    fake.download = real_download
    print("7. 下载校验 ✓")

    # 8. 重启续跑：已有任务 id 的接着查，不重复提交
    sess.queue_run(root, [ids[1]])
    runner.watch(root)
    runner.tick()
    assert clip(root, ids[1])["state"] == "running"
    before = len(fake.submitted)
    again = Runner(builder, sleep=slept.append)
    assert again.recover(data) == 1 and again.watching() == [root]
    for _ in range(10):
        again.tick()
    assert clip(root, ids[1])["state"] == "done" and len(fake.submitted) == before
    print("8. 重启续跑 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/render/test_runner.py`
Expected: `ModuleNotFoundError: No module named 'render.runner'`

- [ ] **Step 3: 写 `runner.py`**

Create `backend/render/runner.py`:

```python
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
```

- [ ] **Step 4: 运行，确认通过**

Run: `.venv/bin/python tests/render/test_runner.py && .venv/bin/python tests/render/test_session.py`
Expected: 两个都 `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add render/runner.py tests/render/test_runner.py
git commit -m "出片后台线程：每轮先查询与下载在跑的段、再在并发上限内提交排队的段；瞬时错误重试 3 次不算新尝试，厂商失败原样记录；接力段等上一段；排队后分镜改动不提交；下载做 MP4 校验；重启扫描续跑不重复提交"
```

---

### Task 6: 出片接口

**Files:**
- Modify: `backend/server/novels.py`（`delete_version` 与关键帧一节之后）
- Modify: `backend/server/app.py`（导入、`render_plan`、新增出片一节）
- Test: `backend/tests/server/test_render.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/server/test_render.py`:

```python
#!/usr/bin/env python3
"""出片接口：建会话与设置、关键帧作首帧、试段与出片线程推进、取文件、批量确认与上限、
过期与重做、采用、原声静音、删版本连带删除。

全程临时数据目录 + 假厂商，不联网、不花钱。用法: python3 tests/server/test_render.py
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
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"     # 不起后台线程，测试里手动 tick

from fastapi.testclient import TestClient  # noqa: E402
from render import providers  # noqa: E402
from render.providers.fake import FAKE_MP4, FakeVideo  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402

FAKE = FakeVideo()
providers.register("fake", lambda: FAKE)
DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def drain(limit=3000):
    runner = app_mod._render_runner
    for _ in range(limit):
        if not runner.watching():
            return
        runner.tick()
    raise AssertionError("出片线程没跑完")


def pick(s, cid):
    return next(x for x in s["clips"] if x["id"] == cid)


def main() -> int:
    app_mod._render_runner.sleep = lambda _s: None
    c = TestClient(app_mod.app)
    user = auth.register("alice", "secret1")
    uid = user["id"]
    H = {"Authorization": f"Bearer {auth.issue_token(uid)}"}
    nid = novels.create_novel(uid, "药")["id"]
    cid = novels.create_chapter(uid, nid, "第一章", text="原文")["id"]
    novels.create_version(uid, nid, cid, "v1", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v1", "succeeded", result=copy.deepcopy(DOC))
    R = f"/novels/{nid}/chapters/{cid}/versions/v1/render"

    # 1. 建会话：需要登录；默认设置；非法设置 422；没有分镜产物不能出片
    assert c.post(R + "/session").status_code == 401
    assert c.get(R + "/session", headers=H).status_code == 404
    r = c.post(R + "/session", headers=H, json={})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["provider"] == "fake" and s["audio_mode"] == "tts_all" and "owner" not in s
    assert s["clips"] and all(x["state"] == "planned" for x in s["clips"])
    assert s["options"]["resolutions"] == ["480p", "720p"]
    assert c.patch(R + "/session", headers=H, json={"resolution": "4k"}).status_code == 422
    novels.create_version(uid, nid, cid, "v2", {}, "原文")
    r = c.post(f"/novels/{nid}/chapters/{cid}/versions/v2/render/session", headers=H, json={})
    assert r.status_code == 422, "没有分镜产物不能出片"
    print("1. 建会话 ✓")

    # 2. 上传关键帧后读取：该段改用关键帧作首帧
    second = s["clips"][1]
    shot = second["shots"][0]
    r = c.put(f"/novels/{nid}/chapters/{cid}/versions/v1/keyframes/{shot}", content=PNG,
              headers={**H, "Content-Type": "image/png"})
    assert r.status_code == 200, r.text
    s = c.get(R + "/session", headers=H).json()
    assert pick(s, second["id"])["first_frame"] == f"keyframe:{shot}"
    assert pick(s, second["id"])["frame_mode"] == "frame"
    print("2. 关键帧作首帧 ✓")

    # 3. 试段 → 出片线程推进 → done；取文件；路径穿越被拒
    r = c.post(R + f"/clips/{second['id']}/run", headers=H, json={})
    assert r.status_code == 200, r.text
    assert pick(r.json(), second["id"])["state"] == "queued"
    drain()
    assert FAKE.submitted[-1].first_frame.startswith("data:image/png;base64,")
    s = c.get(R + "/session", headers=H).json()
    done = pick(s, second["id"])
    assert done["state"] == "done" and s["spent_cny"] == done["attempts"][0]["cost_cny"] > 0
    f = c.get(R + "/files/" + done["attempts"][0]["file"], headers=H)
    assert f.status_code == 200 and f.content == FAKE_MP4
    assert c.get(R + "/files/clips/nope.mp4", headers=H).status_code == 404
    assert c.get(R + "/files/%2e%2e/%2e%2e/versions/v1.json", headers=H).status_code == 404
    print("3. 试段与取文件 ✓")

    # 4. 批量：必须带确认金额；不一致 409；超上限 422；在跑时不能改设置
    r = c.post(R + "/run", headers=H, json={})
    assert r.status_code == 409 and r.json()["detail"]["expected_cny"] > 0
    total = r.json()["detail"]["expected_cny"]
    assert c.post(R + "/run", headers=H, json={"expected_cny": total + 1}).status_code == 409
    assert c.post(R + "/run", headers=H, json={"expected_cny": total}).status_code == 422
    assert c.patch(R + "/session", headers=H, json={"budget_cny": 100000}).status_code == 200
    r = c.post(R + "/run", headers=H, json={"expected_cny": total})
    assert r.status_code == 200, r.text
    assert c.patch(R + "/session", headers=H, json={"resolution": "480p"}).status_code == 409
    drain()
    s = c.get(R + "/session", headers=H).json()
    assert s["counts"] == {"done": len(s["clips"])}, s["counts"]
    print("4. 批量确认与上限 ✓")

    # 5. 分镜改动 → 过期（旧视频仍在）；重做采用新的一次；可换回旧的（仍标过期）
    edited = copy.deepcopy(DOC)
    sh = next(x for ep in edited["episodes"] for x in ep["shots"] if x["id"] == shot)
    sh["action"] += "（改）"
    novels.update_version_result(uid, nid, cid, "v1", edited, verification={}, status="succeeded")
    s = c.get(R + "/session", headers=H).json()
    assert pick(s, second["id"])["state"] == "stale" and pick(s, second["id"])["chosen"] == 0
    assert all(x["state"] == "done" for x in s["clips"] if x["id"] != second["id"])
    r = c.post(R + f"/clips/{second['id']}/run", headers=H, json={})
    assert r.status_code == 200, r.text
    drain()
    st = pick(c.get(R + "/session", headers=H).json(), second["id"])
    assert st["state"] == "done" and st["chosen"] == 1 and len(st["attempts"]) == 2
    r = c.put(R + f"/clips/{second['id']}/chosen", headers=H, json={"attempt": 0})
    assert r.status_code == 200 and pick(r.json(), second["id"])["state"] == "stale"
    assert c.put(R + f"/clips/{second['id']}/chosen", headers=H, json={"attempt": 9}).status_code == 422
    print("5. 过期、重做与采用 ✓")

    # 6. 原声静音
    r = c.patch(R + f"/clips/{second['id']}", headers=H, json={"mute_native": True})
    assert r.status_code == 200 and pick(r.json(), second["id"])["mute_native"] is True
    assert c.patch(R + "/clips/E99-C01", headers=H, json={"mute_native": True}).status_code == 404
    print("6. 原声静音 ✓")

    # 7. 删版本：会话目录一并删除
    root = novels.render_dir(uid, nid, cid, "v1")
    assert (root / "session.json").exists()
    novels.delete_version(uid, nid, cid, "v1")
    assert not root.exists()
    print("7. 删版本连带删除 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/server/test_render.py`
Expected: 第 1 段失败（`/render/session` 返回 404 而非 401），或 `AttributeError: module 'server.app' has no attribute '_render_runner'`

- [ ] **Step 3: `novels.py` 加会话目录**

In `backend/server/novels.py`, in `delete_version`, after the line
`        shutil.rmtree(_chapter_dir(user_id, nid, cid) / "keyframes" / vid, ignore_errors=True)`
add:

```python
        shutil.rmtree(_chapter_dir(user_id, nid, cid) / "render" / vid, ignore_errors=True)
```

After the `delete_keyframe` function (before the `# ---------- 旧数据迁移 ----------` line), add:

```python
# ---------- 出片会话目录（会话状态、片段、成片；不进 IR） ----------

def render_dir(user_id: str, nid: str, cid: str, vid: str) -> Path:
    """出片会话目录：和关键帧一样挂在版本上；删版本时一并删除。"""
    get_version(user_id, nid, cid, vid)
    return _chapter_dir(user_id, nid, cid) / "render" / _check_id(vid)


```

- [ ] **Step 4: `app.py` 导入与验证门**

In `backend/server/app.py`, below `from render import plan as render_plan_mod`, add:

```python
from render import compose as render_compose
from render import providers as render_providers
from render import runner as render_runner
from render import session as render_session
```

Replace the body of `render_plan` from `    doc = copy.deepcopy(req.result)` through the closing `        })` of the 422 raise (the block that builds `frozen`, runs `verify_document` twice and raises when `not report.ok`) with:

```python
    doc = copy.deepcopy(req.result)
    record = None
    if req.run_id:
        try:
            record = novels.find_version(user["id"], req.run_id)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if record is None:
            raise HTTPException(404, "版本不存在")
    report = _render_gate(doc, record)
```

Above `class RenderPlanRequest(BaseModel):` add:

```python
def _render_gate(doc: dict, record: Optional[dict]):
    """分镜未通过独立验证禁止进入付费渲染（渲染任务包与出片共用）。会改写 doc 的覆盖率字段。"""
    frozen = _frozen_of(record) if record else None
    probe = verification.verify_document(doc, frozen_units=frozen or None)
    verification.recompute_coverage_field(doc, probe.coverage)
    report = verification.verify_document(doc, frozen_units=frozen or None)
    if not report.ok:
        raise HTTPException(422, detail={
            "message": "分镜未通过独立验证，禁止进入付费渲染",
            "verification": report.to_dict(),
        })
    return report


```

- [ ] **Step 5: `app.py` 出片一节**

In `backend/server/app.py`, before the line `# ---------- 长期记忆：人物生命周期、主线剧情、创作限制 ----------`, add:

```python
# ---------- 出片（视频生成）：会话在 chapters/<cid>/render/<vid>/，不进 IR ----------

_R = "/novels/{nid}/chapters/{cid}/versions/{vid}/render"


def _keyframe_paths(uid: str, nid: str, cid: str, vid: str) -> dict:
    return {sid: novels.keyframe_file(uid, nid, cid, vid, sid)[0]
            for sid in novels.list_keyframes(uid, nid, cid, vid)}


def _render_ctx(user: dict, nid: str, cid: str, vid: str, gate: bool = True) -> tuple:
    """(会话目录, 已保存的分镜, 关键帧, 归属)。出片只用已保存的版本内容；gate 时过验证门。"""
    uid = user["id"]
    record = _novel_call(novels.get_version, uid, nid, cid, vid)
    root = _novel_call(novels.render_dir, uid, nid, cid, vid)
    doc = record.get("result") or {}
    if gate:
        if not doc.get("episodes"):
            raise HTTPException(422, "这个版本还没有分镜产物")
        _render_gate(copy.deepcopy(doc), record)
    owner = {"user_id": uid, "nid": nid, "cid": cid, "vid": vid}
    return root, doc, _keyframe_paths(uid, nid, cid, vid), owner


def _render_call(fn, *args, **kwargs):
    """把出片会话的业务异常翻成 HTTP 状态码。"""
    try:
        return fn(*args, **kwargs)
    except render_session.NotFound as e:
        raise HTTPException(404, str(e))
    except render_session.Conflict as e:
        raise HTTPException(409, detail={"message": str(e), "expected_cny": e.expected_cny})
    except render_session.SessionError as e:
        raise HTTPException(422, str(e))


def _render_request(root, s: dict, clip: dict):
    """出片线程提交前：按已保存的分镜与关键帧重建这一段的厂商请求。"""
    o = s["owner"]
    record = novels.get_version(o["user_id"], o["nid"], o["cid"], o["vid"])
    provider = render_providers.get_video(s["provider"])
    return render_compose.request_for(
        record.get("result") or {}, s, clip,
        keyframes=_keyframe_paths(o["user_id"], o["nid"], o["cid"], o["vid"]),
        relay_frame=render_session.relay_frame(root, s, clip),
        caps=provider.caps(s["model"]), rewrite=provider.rewrite_prompt)


_render_runner = render_runner.Runner(
    _render_request,
    poll_sec=float(os.environ.get("STORYBOARD_RENDER_POLL_SEC", "10")),
    max_parallel=int(os.environ.get("STORYBOARD_RENDER_PARALLEL", "2")))


@app.on_event("startup")
def _start_render_runner():
    """出片线程随服务启动，续上重启前没跑完的段。STORYBOARD_RENDER_RUNNER=0 关闭（测试里手动 tick）。"""
    if os.environ.get("STORYBOARD_RENDER_RUNNER", "1") == "0":
        return
    n = _render_runner.recover(auth.DATA_DIR)
    if n:
        print(f"[render] 续上 {n} 个出片会话", flush=True)
    _render_runner.start()


class RenderSettingsBody(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    resolution: Optional[str] = None
    audio_mode: Optional[str] = None
    budget_cny: Optional[float] = Field(None, gt=0, le=100000)
    confirm_over_cny: Optional[float] = Field(None, ge=0, le=100000)


class RenderRunBody(BaseModel):
    expected_cny: Optional[float] = Field(None, ge=0)


class RenderChosenBody(BaseModel):
    attempt: int = Field(ge=0)


class RenderClipBody(BaseModel):
    mute_native: bool


@app.post(_R + "/session")
def render_session_post(nid: str, cid: str, vid: str, body: Optional[RenderSettingsBody] = None,
                        user: dict = Depends(novel_user)):
    """过验证门、按设置切段，生成或重建会话（不花钱）。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    patch = body.model_dump(exclude_none=True) if body else {}
    s = _render_call(render_session.build, root, doc, owner=owner, patch=patch, keyframes=kfs)
    return _render_call(render_session.view, s)


@app.get(_R + "/session")
def render_session_get(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    """查询；按当前已保存的分镜重算指纹并标过期（在跑的段不动）。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid, gate=False)
    if render_session.load(root) is None:
        raise HTTPException(404, "还没有出片会话")
    s = _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                     allow_in_flight=True)
    return _render_call(render_session.view, s)


@app.patch(_R + "/session")
def render_session_patch(nid: str, cid: str, vid: str, body: RenderSettingsBody,
                         user: dict = Depends(novel_user)):
    """改设置（厂商、档位、分辨率、声音模式、上限）。有段在跑时 409。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    if render_session.load(root) is None:
        raise HTTPException(404, "还没有出片会话")
    s = _render_call(render_session.build, root, doc, owner=owner,
                     patch=body.model_dump(exclude_none=True), keyframes=kfs)
    return _render_call(render_session.view, s)


@app.post(_R + "/clips/{clip_id}/run")
def render_clip_run(nid: str, cid: str, vid: str, clip_id: str,
                    body: Optional[RenderRunBody] = None, user: dict = Depends(novel_user)):
    """出这一段（试段或重做）。超过确认线时要带 expected_cny。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                 allow_in_flight=True)
    s = _render_call(render_session.queue_run, root, [clip_id], body.expected_cny if body else None)
    _render_runner.watch(root)
    return _render_call(render_session.view, s)


@app.post(_R + "/run")
def render_run_all(nid: str, cid: str, vid: str, body: RenderRunBody,
                   user: dict = Depends(novel_user)):
    """批量出剩余各段：必须带用户确认的预估金额，服务端重算不一致 409。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                 allow_in_flight=True)
    s = _render_call(render_session.queue_run, root, None, body.expected_cny)
    _render_runner.watch(root)
    return _render_call(render_session.view, s)


@app.put(_R + "/clips/{clip_id}/chosen")
def render_clip_chosen(nid: str, cid: str, vid: str, clip_id: str, body: RenderChosenBody,
                       user: dict = Depends(novel_user)):
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid)
    s = _render_call(render_session.set_chosen, root, clip_id, body.attempt)
    return _render_call(render_session.view, s)


@app.patch(_R + "/clips/{clip_id}")
def render_clip_patch(nid: str, cid: str, vid: str, clip_id: str, body: RenderClipBody,
                      user: dict = Depends(novel_user)):
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid)
    s = _render_call(render_session.set_mute, root, clip_id, body.mute_native)
    return _render_call(render_session.view, s)


@app.get(_R + "/files/{path:path}")
def render_file(nid: str, cid: str, vid: str, path: str, user: dict = Depends(novel_user)):
    """取本版本出片目录下的文件（片段、尾帧）。拒绝路径穿越。"""
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target)


```

Also add these lines to the module docstring at the top of `app.py`, after the keyframes lines (`  GET/PUT/DELETE      /novels/{nid}/chapters/{cid}/versions/{vid}/keyframes/{shot_id}  取图 / 上传（原始图片体）/ 删`):

```
出片（视频生成，状态在 chapters/<cid>/render/<vid>/session.json，后台线程提交/轮询/下载）：
  POST/GET/PATCH      …/versions/{vid}/render/session           建立（过验证门）/ 查询（标过期）/ 改设置
  POST                …/versions/{vid}/render/clips/{clip}/run  出这一段（试段或重做）
  POST                …/versions/{vid}/render/run               批量出剩余各段（带确认金额，不一致 409）
  PUT / PATCH         …/render/clips/{clip}/chosen、…/clips/{clip}   采用某次 / 原声静音
  GET                 …/versions/{vid}/render/files/{path}      取片段与尾帧
```

- [ ] **Step 6: 运行，确认通过**

Run: `.venv/bin/python tests/server/test_render.py`
Expected: 1–7 ✓，`ALL PASS`

Run regression: `for t in tests/server/test_*.py tests/render/test_*.py; do .venv/bin/python $t | tail -1; done`
Expected: 每个文件 `ALL PASS`

- [ ] **Step 7: 提交**

```bash
git add server/app.py server/novels.py tests/server/test_render.py
git commit -m "出片接口：建立/查询/改设置会话（过验证门、读取时标过期）、试段与批量（确认金额 409、单章上限 422）、采用与原声静音、取片段文件防穿越；出片线程随服务启动并续跑；会话目录挂在版本上、删版本一并删除；渲染任务包与出片共用验证门"
```

---

### Task 7: Seedance 厂商

**Files:**
- Modify: `backend/render/providers/seedance.py`（替换为完整版）
- Modify: `backend/render/providers/__init__.py`（末尾注册）
- Test: `backend/tests/render/test_seedance.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/render/test_seedance.py`:

```python
#!/usr/bin/env python3
"""Seedance（火山方舟）：请求体、错误分级、状态映射、下载、计费、密钥。

用 httpx.MockTransport 模拟方舟，不联网、不花钱。用法: python3 tests/render/test_seedance.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render.providers import base  # noqa: E402
from render.providers.seedance import BASE_URL, MODELS, Seedance, rewrite_refs  # noqa: E402

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 8


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def ark(handler, key="k-secret"):
    return Seedance(key, client=httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler)))


def main() -> int:
    seen = []

    def accept(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "cgt-1"})

    # 1. 提交：参考图模式、首帧模式、整数秒、密钥只在请求头
    sd = ark(accept)
    req = base.ClipRequest(prompt="p @图片1", model="seedance-2.0-fast", duration=7.3,
                           resolution="720p", aspect="9:16", audio=True,
                           refs=[base.RefImage("C01", "character", "https://img/c01.png")])
    assert sd.submit(req) == "cgt-1"
    sent = seen[-1]
    body = json.loads(sent.content)
    assert sent.method == "POST" and sent.url.path == "/api/v3/contents/generations/tasks"
    assert sent.headers["authorization"] == "Bearer k-secret"
    assert body["model"] == MODELS["seedance-2.0-fast"]["id"]
    assert (body["duration"], body["resolution"], body["ratio"]) == (8, "720p", "9:16")
    assert body["return_last_frame"] is True and body["watermark"] is False
    assert body["generate_audio"] is True
    assert body["content"][0] == {"type": "text", "text": "p @图片1"}
    assert body["content"][1] == {"type": "image_url", "image_url": {"url": "https://img/c01.png"},
                                  "role": "reference_image"}
    framed = base.ClipRequest(prompt="p", model="seedance-2.0-mini", duration=3, resolution="480p",
                              audio=False, first_frame="data:image/png;base64,AAAA")
    sd.submit(framed)
    body = json.loads(seen[-1].content)
    assert body["duration"] == 4, "不足 4 秒按 4 秒"
    assert body["generate_audio"] is False
    assert body["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"},
                                  "role": "first_frame"}
    must_raise(base.ProviderError, sd.submit, base.ClipRequest(prompt="p", model="nope",
                                                               duration=5, resolution="720p"))
    print("1. 提交请求体 ✓")

    # 2. 错误分级：429/5xx/断连 → 瞬时；4xx → 厂商原因原样；密钥不进报错
    def status(code, payload=None):
        return ark(lambda r: httpx.Response(code, json=payload or {}))

    must_raise(base.TransientError, status(429).submit, req)
    must_raise(base.TransientError, status(503).submit, req)
    e = must_raise(base.ProviderError, status(400, {"error": {"code": "InvalidParameter",
                                                              "message": "duration 不合法"}}).submit, req)
    assert "InvalidParameter" in str(e) and "duration 不合法" in str(e) and "k-secret" not in str(e)

    def refused(request):
        raise httpx.ConnectError("connection refused", request=request)

    e = must_raise(base.TransientError, ark(refused).submit, req)
    assert "k-secret" not in str(e)
    print("2. 错误分级 ✓")

    # 3. 查询：状态映射、产物地址、用量
    def task(payload):
        return ark(lambda r: httpx.Response(200, json=payload))

    ok = {"id": "cgt-1", "status": "succeeded",
          "content": {"video_url": "https://tos.example/v.mp4", "last_frame_url": "https://tos.example/l.jpg"},
          "usage": {"completion_tokens": 108900, "total_tokens": 108900}}
    st = task(ok).poll("cgt-1")
    assert st.status == "succeeded" and st.video_url == "https://tos.example/v.mp4"
    assert st.last_frame_url == "https://tos.example/l.jpg" and st.usage == {"completion_tokens": 108900}
    assert task({"id": "x", "status": "queued"}).poll("x").status == "pending"
    assert task({"id": "x", "status": "running"}).poll("x").status == "running"
    st = task({"id": "x", "status": "failed",
               "error": {"code": "OutputVideoSensitiveContentDetected", "message": "审核未通过"}}).poll("x")
    assert st.status == "failed" and "审核未通过" in st.error
    st = task({"id": "x", "status": "expired"}).poll("x")
    assert st.status == "failed" and st.error
    print("3. 查询映射 ✓")

    # 4. 下载：视频与尾帧；结果地址不带方舟密钥；过期地址报厂商错误
    def files(request):
        assert "authorization" not in request.headers, "下载结果地址不带方舟密钥"
        return httpx.Response(200, content=MP4 if request.url.path.endswith(".mp4") else b"\xff\xd8jpg")

    succeeded = base.TaskState("cgt-1", "succeeded", video_url="https://tos.example/v.mp4",
                               last_frame_url="https://tos.example/l.jpg",
                               usage={"completion_tokens": 108900})
    with tempfile.TemporaryDirectory() as d:
        got = ark(files).download(succeeded, Path(d) / "clips" / "E01-C01.v1.mp4")
        assert base.is_playable_mp4(got["video"]) and got["last_frame"].read_bytes() == b"\xff\xd8jpg"
        must_raise(base.ProviderError, ark(lambda r: httpx.Response(403)).download,
                   succeeded, Path(d) / "x.mp4")
    print("4. 下载 ✓")

    # 5. 计费：有 usage 按 token × 单价；没有按秒估；失败 0；能力表
    fast = MODELS["seedance-2.0-fast"]["cny_per_m"]
    r720 = base.ClipRequest(prompt="", model="seedance-2.0-fast", duration=5, resolution="720p")
    assert sd.cost(succeeded, r720) == round(108900 * fast / 1e6, 2)
    caps = sd.caps("seedance-2.0-fast")
    assert sd.cost(base.TaskState("x", "succeeded"), r720) == base.estimate_cny(5, caps, "720p")
    assert sd.cost(base.TaskState("x", "failed"), r720) == 0.0
    assert caps.resolutions == ["480p", "720p"] and caps.max_refs == 9
    assert caps.min_clip_sec == 4 and caps.max_clip_sec == 15 and not caps.frame_with_refs
    assert abs(caps.cny_per_sec["720p"] - 21600 * fast / 1e6) < 1e-4
    assert "1080p" in sd.caps("seedance-2.0").resolutions
    must_raise(base.ProviderError, sd.caps, "nope")
    assert sd.rewrite_prompt("{ref:C01} {ref:S03}") == "@图片1 @图片2" == rewrite_refs("{ref:C01} {ref:S03}")
    print("5. 计费与能力表 ✓")

    # 6. 密钥：没配时报错说明去哪配（设为空串，.env 不会覆盖已有变量）
    os.environ["ARK_API_KEY"] = ""
    e = must_raise(base.ProviderError, Seedance.from_env)
    assert "ARK_API_KEY" in str(e)
    print("6. 密钥 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/render/test_seedance.py`
Expected: `ImportError: cannot import name 'BASE_URL' from 'render.providers.seedance'`

- [ ] **Step 3: 写完整的 `seedance.py`**

Replace the whole content of `backend/render/providers/seedance.py` with:

```python
"""火山方舟 Seedance：提示词语法（@图片n），以及提交、查询、下载、计费。

接口与价格核实于 2026-10-31 的官方文档：
- POST /contents/generations/tasks → {"id"}；GET /contents/generations/tasks/{id} → status、
  content.video_url / last_frame_url（24 小时有效）、usage.completion_tokens、error。
- 首帧模式（role=first_frame）与参考图模式（role=reference_image，2.0 最多 9 张）互斥。
- 计费按 completion_tokens × 单价；token ≈ 秒数 × 宽 × 高 × 24 / 1024；失败任务不计费。
密钥 ARK_API_KEY 写在 backend/.env，只放进请求头，不进日志与报错。
"""
import itertools
import os
import re
from pathlib import Path

import httpx

from pipeline.config import ROOT as BACKEND_ROOT
from pipeline.config import _load_dotenv
from render.providers.base import (Caps, ClipRequest, ProviderError, TaskState, TransientError,
                                   estimate_cny, last_frame_path, request_seconds)

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


def rewrite_refs(text: str) -> str:
    """厂商无关占位符 {ref:ID} → Seedance 的 @图片n，按出现顺序编号。

    同一资产出现两次也各占一张图（同一场景的两个机位是两张图），所以按次序而不是按 ID
    编号；请求里的参考图按同一顺序排列。
    """
    n = itertools.count(1)
    return _REF.sub(lambda m: f"@图片{next(n)}", text)


def _error_text(r: httpx.Response) -> str:
    try:
        err = (r.json() or {}).get("error") or {}
    except ValueError:
        return f"HTTP {r.status_code}：{r.text[:300]}"
    text = "：".join(x for x in (err.get("code"), err.get("message")) if x)
    return text or f"HTTP {r.status_code}"


class Seedance:
    name = "seedance"
    default_model = DEFAULT_MODEL

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
            raise ProviderError("没有配置方舟密钥：在 backend/.env 写 ARK_API_KEY=…")
        return cls(key)

    def _model(self, model: str) -> dict:
        m = MODELS.get(model)
        if m is None:
            raise ProviderError(f"未知的 Seedance 档位：{model}")
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

    def _call(self, method: str, url: str, **kw) -> dict:
        try:
            r = self._http.request(method, url, headers={"Authorization": f"Bearer {self._key}"}, **kw)
        except httpx.TransportError as e:
            raise TransientError(f"连接方舟失败：{type(e).__name__}")
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientError(f"方舟暂时不可用（HTTP {r.status_code}）")
        if r.status_code >= 400:
            raise ProviderError(_error_text(r))
        try:
            return r.json()
        except ValueError:
            raise TransientError("方舟返回的不是 JSON")

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
        tid = self._call("POST", "/contents/generations/tasks", json=body).get("id")
        if not tid:
            raise ProviderError("方舟没有返回任务 id")
        return tid

    def poll(self, task_id: str) -> TaskState:
        j = self._call("GET", f"/contents/generations/tasks/{task_id}")
        raw = j.get("status")
        status = _STATUS.get(raw, "running")
        content = j.get("content") or {}
        error = None
        if status == "failed":
            err = j.get("error") or {}
            error = ("：".join(x for x in (err.get("code"), err.get("message")) if x)
                     or {"expired": "任务超时", "cancelled": "任务已取消"}.get(raw, "生成失败"))
        return TaskState(task_id, status, video_url=content.get("video_url"),
                         last_frame_url=content.get("last_frame_url"), error=error,
                         usage={"completion_tokens": (j.get("usage") or {}).get("completion_tokens")}
                         if status == "succeeded" else {})

    def _fetch(self, url: str, dest: Path) -> None:
        """结果地址是对象存储的签名直链：不带方舟密钥，24 小时有效。"""
        if not url:
            raise ProviderError("方舟没有返回结果地址")
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        try:
            with self._http.stream("GET", url) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransientError(f"下载暂时失败（HTTP {r.status_code}）")
                if r.status_code >= 400:
                    raise ProviderError(f"下载失败（HTTP {r.status_code}）：结果地址 24 小时内有效")
                with open(part, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
        except httpx.TransportError as e:
            raise TransientError(f"下载连接失败：{type(e).__name__}")
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
```

- [ ] **Step 4: 注册 Seedance**

Append to the end of `backend/render/providers/__init__.py`:

```python


def _seedance():
    from render.providers.seedance import Seedance
    return Seedance.from_env()


register("seedance", _seedance)
```

- [ ] **Step 5: 运行，确认通过**

Run: `.venv/bin/python tests/render/test_seedance.py && .venv/bin/python tests/render/test_compose.py && .venv/bin/python tests/render/test_providers.py`
Expected: 三个都 `ALL PASS`

- [ ] **Step 6: 提交**

```bash
git add render/providers/seedance.py render/providers/__init__.py tests/render/test_seedance.py
git commit -m "Seedance 厂商：方舟任务提交（参考图与首帧两种模式、整数秒、不加水印、要尾帧）、查询状态映射、结果直链下载（不带密钥）、按 token 计费与刊例价能力表；429/5xx/断连为瞬时错误，4xx 原样报厂商原因；密钥从 backend/.env 读取"
```

---

### Task 8: 手动冒烟脚本、文档、设计文档写回裁定

**Files:**
- Create: `backend/render/smoke.py`
- Modify: `README.md`（「方式一」里离线回归那一行，及管理后台段落之后）
- Modify: `docs/specs/2026-10-28-video-generation-design.md`（末尾）

- [ ] **Step 1: 冒烟脚本**

Create `backend/render/smoke.py`:

```python
"""真实厂商冒烟（花真钱，上限 5 元）：用《药》第一段出一条最短的 Seedance 视频。

用法: cd backend && .venv/bin/python -m render.smoke [--model seedance-2.0-mini] [--resolution 480p]
                                                    [--out /tmp/seedance-smoke] [--yes]
打印方舟返回的 token 用量与按单价折算的金额——拿它与控制台账单核对，校准单价
（STORYBOARD_SEEDANCE_CNY_PER_M）。
"""
import argparse
import json
import sys
import time
from pathlib import Path

from render import compose
from render.providers import base
from render.providers.seedance import Seedance

LIMIT_CNY = 5.0
YAO = Path(__file__).resolve().parent.parent / "tests" / "real_text_yao" / "output_merged.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Seedance 真实冒烟（花钱）")
    ap.add_argument("--model", default="seedance-2.0-mini")
    ap.add_argument("--resolution", default="480p")
    ap.add_argument("--out", default="/tmp/seedance-smoke")
    ap.add_argument("--yes", action="store_true", help="不再询问，直接提交")
    a = ap.parse_args(argv)

    sd = Seedance.from_env()
    caps = sd.caps(a.model)
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    session = {"provider": "seedance", "model": a.model, "resolution": a.resolution,
               "audio_mode": "tts_all"}
    clip = compose.build_clips(doc, caps, provider="seedance", model=a.model,
                               resolution=a.resolution, audio_mode="tts_all", keyframes={},
                               rewrite=sd.rewrite_prompt)[0]
    req, _ = compose.request_for(doc, session, clip, keyframes={}, relay_frame=None, caps=caps,
                                 rewrite=sd.rewrite_prompt)
    req.duration = caps.min_clip_sec               # 冒烟只出最短的一条
    est = base.estimate_cny(req.duration, caps, a.resolution)
    print(req.prompt, "\n")
    print(f"{a.model} · {a.resolution} · {base.request_seconds(req.duration, caps)} 秒 · "
          f"预估 ¥{est:.2f}（冒烟上限 ¥{LIMIT_CNY:g}）")
    if est > LIMIT_CNY:
        print("超出冒烟上限，不提交")
        return 1
    if not a.yes and input("提交？[y/N] ").strip().lower() != "y":
        return 1

    tid = sd.submit(req)
    print("任务：", tid)
    while True:
        time.sleep(10)
        st = sd.poll(tid)
        print("状态：", st.status, flush=True)
        if st.status in ("succeeded", "failed"):
            break
    if st.status == "failed":
        print("失败：", st.error)
        return 1
    files = sd.download(st, Path(a.out) / f"{clip['id']}.mp4")
    print("视频：", files["video"], "（可播放）" if base.is_playable_mp4(files["video"]) else "（不可播放！）")
    print("尾帧：", files["last_frame"])
    print("用量：", st.usage, f"→ 折算 ¥{sd.cost(st, req):.2f}，请与控制台账单核对")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run (offline check only, no network): `.venv/bin/python -c "import render.smoke"`
Expected: no output, exit 0

- [ ] **Step 2: README**

In `README.md`, replace the offline-regression line
``离线回归（不调 LLM，用《药》归档回放编排逻辑）：`for t in tests/pipeline/test_*.py tests/server/test_*.py; do .venv/bin/python $t || break; done`（各自应打印 `ALL PASS`）``
with:

```markdown
离线回归（不调 LLM、不调视频厂商，用《药》归档回放）：`for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py; do .venv/bin/python $t || break; done`（各自应打印 `ALL PASS`）
```

After the 「**管理后台**」 paragraph (the one ending with `管理员看不到小说原文与分镜内容。` plus the soft-cap sentence), add:

```markdown

**出片（视频生成，后端）**：`backend/.env` 写 `ARK_API_KEY=…`（火山方舟），`STORYBOARD_VIDEO_PROVIDER` 选厂商（缺省 `seedance`；`fake` 为不联网的假厂商，本地演示用）。
每个版本一个出片会话（`/novels/{nid}/chapters/{cid}/versions/{vid}/render/...`）：建会话时过验证门、按厂商能力把镜头切成段（时长按能念完旁白台词的可播时长），
先试一段，满意后带上确认过的预估金额批量出剩余各段；单章上限默认 200 元，超过拒绝。后台线程提交、每 10 秒查询、成功即下载（结果地址 24 小时有效），
服务重启后续跑不重复提交。改了分镜或设置，已出的段标「过期」，旧视频仍可播。片段在 `chapters/<cid>/render/<vid>/clips/`。
费率为 2026-10 刊例价（fast 约 0.80 元/秒、mini 约 0.50 元/秒，720p），首次真实出片后用 `.venv/bin/python -m render.smoke` 的用量与账单核对、
必要时用 `STORYBOARD_SEEDANCE_CNY_PER_M` 校准。画布上的出片界面、配音与合成另见后续计划。
```

- [ ] **Step 3: 设计文档写回裁定**

Append to the end of `docs/specs/2026-10-28-video-generation-design.md`:

```markdown

---

## 6. 实施裁定（2026-10-31，出片后端 A1 计划）

1. **首帧与参考图互斥**（方舟官方文档）：`Caps.frame_with_refs`。为 `False` 时，本段有参考图则关键帧作为第一个参考位（提示词「【首帧】@图片1」，占一个名额）；尾帧接力只在本段没有参考图时使用。替代 1.3 第 5 条。
2. **参考图来源**：`RefImage.source` 为 http(s) 地址或 data URI（取资产卡 `reference_images[].uri`，场景取 `angles[].uri`），其他 uri 视为无图、只写文字描述。资产图上传入口留给 A2/B。
3. **能力按档位**：`VideoProvider.caps(model)`、`rewrite_prompt(text)`。
4. **会话目录**：`chapters/<cid>/render/<vid>/`（与关键帧同层），删版本一并删除。替代 1.4 的位置。
5. **计费**：成功按 `usage.completion_tokens × 单价`；失败记 0；已生成但下载失败照记。刊例价：2.0 为 46、fast 为 37、mini 为 23 元/百万 token；token ≈ 秒 × 宽 × 高 × 24 / 1024。
6. **提交中断**：重启时「提交中」且无任务 id 的尝试标失败、提示到控制台核对，不重复提交。
7. **出片费用暂不进管理后台流水账**。
8. **拆分**：本节之前的第 2 节（画布）为 A2 计划，第 3 节（配音与合成）为 A3 计划。
9. Seedance 2.5（4–30 秒、最多 30 张参考图）已上线，首版不接，档位表加一行即可。
```

- [ ] **Step 4: 全量回归**

Run:
```bash
for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py; do printf "%s: " $t; .venv/bin/python $t 2>&1 | tail -1; done
cd ../frontend && npm test 2>&1 | grep -c "ALL PASS"
```
Expected: 每个后端文件 `ALL PASS`；前端打印 `6`

- [ ] **Step 5: 提交**

```bash
git add render/smoke.py ../README.md ../docs/specs/2026-10-28-video-generation-design.md
git commit -m "出片文档：方舟密钥与厂商选择、会话流程与上限、费率依据与校准；真实厂商冒烟脚本（上限 5 元）；设计文档写回首帧参考图互斥等实施裁定"
```

- [ ] **Step 6: 手动冒烟（真实厂商，花钱，由用户执行）**

1. 确认 `backend/.env` 里有 `ARK_API_KEY`（不要打印它）。
2. `cd backend && .venv/bin/python -m render.smoke`：看提示词与预估（mini 480p 4 秒约 0.9 元），输入 `y` 提交。
3. 记下：任务是否成功、视频能否播放、`usage.completion_tokens` 与折算金额、控制台账单实际扣费。
4. 账单与折算不一致时，在 `backend/.env` 设 `STORYBOARD_SEEDANCE_CNY_PER_M`；结果（成功或报错原文）记在本计划末尾。
