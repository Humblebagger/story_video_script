# 新增视频厂商 MiniMax H3 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 出片多一家厂商 MiniMax（H3 / Highspeed / Lite），与 Seedance 并存可切换；新建出片会话的缺省厂商改为 MiniMax（没配 MiniMax 密钥而配了方舟时回落 Seedance 并提示）。

**Architecture:** 先做厂商无关的扩展：`Caps` 增加短边表与图片计费字段，`estimate_cny` 计图片费，`compose.image_count` 统一张数，提交时在尝试里记实际发出的张数，合成尺寸由厂商的短边表决定，runner 文案去掉写死的厂商名。再新增 `providers/minimax.py`（提示词改写、图片检查与 ffmpeg 规范化、错误映射、轮询、下载重查与截尾帧、计费）。最后改缺省厂商、声音模式过滤与界面提示，补冒烟脚本与 README。

**Tech Stack:** Python 3.12 + httpx（`MockTransport` 测试）、ffmpeg/ffprobe（子进程）、React 19 + TypeScript（只改出片设置一行提示）。

**Spec:** `docs/specs/2026-11-12-minimax-provider-design.md`（d49fd45，已过设计审查）。本计划与 spec 冲突时以 spec 为准；spec 没写的细节见文末「实施裁定」。

---

## 全局约束（每个 Task 都必须遵守）

- 不读、不打印 `backend/.env`；密钥只进 `Authorization` 请求头，不进日志、报错、session.json。
- 不调用任何付费厂商；不运行 `backend/render/smoke.py`、`backend/assistant/smoke.py`；不向运行中的 5173 / 8000 服务发请求。
- 测试绝不联网、不读真实 `.env`：厂商接口一律用 `httpx.MockTransport`；缺省厂商的密钥判断给 `providers._has_key` 打桩；缺密钥用例先把对应环境变量置空串（`_load_dotenv` 用 `setdefault`，已有变量不会被覆盖）。
- 不动 `docs/specs/2026-10-27-commercialization-design-contract.md`（未跟踪文件）。
- git：只 `git add` 具体文件，禁止 `git add -A`、`git commit -a`、`git add -N`；提交信息用中文、描述性写法；**不得**带 `Co-Authored-By` 或任何 Claude 署名行；不 push。
- 每个 Task 结束前跑全部验证并通过：
  - 后端（照 README 的离线回归写法，另加助手测试目录）：
    ```bash
    cd backend && for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t || { echo "FAIL $t"; break; }; done
    ```
    每个文件应打印 `ALL PASS`，循环中途不出现 `FAIL`。
  - 涉及前端时（Task 4）：`cd frontend && npm test`（退出码 0）、`npm run lint`（0 error，warning 不多于基线 5 条）、`npm run build`（成功）。
  - 已知既有问题：`frontend/tests/film.test.tsx` 偶发 CPU 自旋卡死（HEAD 上也复现）。遇到时单独重跑判定：`npx vite build --ssr tests/film.test.tsx --outDir <仓库外临时目录> --logLevel error && timeout 60 node <同目录>/film.test.js`，记录在报告里，不算本任务失败。临时构建输出放仓库外，不在 `frontend/` 下留 `.ssrout-*`。

## 文件结构

| 文件 | 职责 | Task |
|---|---|---|
| `backend/render/providers/base.py` | `Caps` 加 `short_side`、`free_images`、`cny_per_image`；`ClipRequest` 加 `images`；`estimate_cny` 加 `images` | 1 |
| `backend/render/compose.py` | `image_count(item)`；`_PLACEHOLDER` 认「参考图N」；`audio_modes(caps)` | 1、3 |
| `backend/render/session.py` | 四处预估用张数；`submitted` 记 `images`；`resolve_settings` 声音回落；`view` 的 `audio_modes`、`default_note` | 1、2、3 |
| `backend/render/free.py` | 两处预估用张数 | 1 |
| `backend/render/mix.py` | `frame_size(..., short_side)`；`_size(s, doc)` 取厂商短边表 | 1 |
| `backend/render/runner.py` | `_stub` 带 `images`；提交时算张数；AmbiguousSubmit 文案用 `console_name` | 2 |
| `backend/render/providers/seedance.py` | `console_name = "方舟控制台"` | 2 |
| `backend/render/providers/fake.py` | `FakeVideo` 可选 `native_audio` 参数 | 3 |
| `backend/render/providers/minimax.py`（新） | MiniMax 厂商 | 3 |
| `backend/render/providers/__init__.py` | 注册 minimax；`_has_key`、`_default_choice`、`default_video_name`、`default_fell_back`；`names()` | 3、4 |
| `backend/render/smoke.py` | `--provider`、按厂商缺省、音轨与宽高输出 | 5 |
| `frontend/src/types.ts`、`frontend/src/components/FilmPanel.tsx` | `options.default_note` 一行提示 | 4 |
| `README.md` | 出片一节 | 5 |
| 测试 | `tests/render/test_providers.py`、`test_compose.py`、`test_mix.py`、`test_session.py`、`test_runner.py`、新 `test_minimax.py`；`frontend/tests/film.test.tsx` | 各 Task |

Task 顺序：1 → 2 → 3 → 4 → 5。每个 Task 结束时全部测试通过、行为对 Seedance 不变。

---

### Task 1: 厂商无关的估价、张数、短边与占位符

**Files:**
- Modify: `backend/render/providers/base.py`
- Modify: `backend/render/compose.py:26`（`_PLACEHOLDER`）及新增 `image_count`
- Modify: `backend/render/session.py:241,283`
- Modify: `backend/render/free.py:126,163`
- Modify: `backend/render/mix.py:24-50,286,356`
- Test: `backend/tests/render/test_providers.py`、`test_compose.py`、`test_mix.py`、`test_session.py`

- [ ] **Step 1: 写失败的测试**

`tests/render/test_providers.py` 在「1. 整数秒与预估」之后加一段（`caps` 为 `FakeVideo().caps("fake-1")`，720p 单价 1.0，`free_images=0`、`cny_per_image=0.0`）：

```python
    # 1b. 图片费：缺省字段为 0 时与旧版相同；超出免费张数的部分按张计
    assert base.estimate_cny(4.2, caps, "720p", images=9) == 5.0, "缺省不收图片费"
    priced = base.Caps(max_clip_sec=15, min_clip_sec=4, max_refs=9, first_frame=True, last_frame=False,
                       returns_last_frame=True, native_audio=False, frame_with_refs=False,
                       resolutions=["768P"], cny_per_sec={"768P": 0.5},
                       short_side={"768P": 768}, free_images=5, cny_per_image=0.2)
    assert base.estimate_cny(4, priced, "768P") == 2.0
    assert base.estimate_cny(4, priced, "768P", images=5) == 2.0, "前 5 张免费"
    assert base.estimate_cny(4, priced, "768P", images=7) == 2.4, "超出 2 张"
    assert base.ClipRequest(prompt="", model="m", duration=1, resolution="r").images is None
    print("1b. 图片费 ✓")
```

`tests/render/test_mix.py` 在现有 `frame_size` 断言（约 32–36 行）后加：

```python
    assert mix.frame_size("768P", "9:16", {"768P": 768}) == (768, 1366)
    assert mix.frame_size("2K", "9:16", {"2K": 1440}) == (1440, 2560)
    assert mix.frame_size("480P", "16:9", {"480P": 480}) == (854, 480)
    assert mix.frame_size("720p", "9:16", {}) == (720, 1280), "不传短边表时旧行为不变"
    assert mix.frame_size("768P", "9:16") == (720, 1280), "未知分辨率仍回落 720"
```

`tests/render/test_compose.py` 在「2. 占位符与改写」一节末尾（`print("2. ...")` 之前）加：

```python
    assert compose.image_count({"refs": ["C01", "S01"], "first_frame": "keyframe:E01-S01"}) == 3
    assert compose.image_count({"refs": ["C01"], "first_frame": None}) == 1
    assert compose.image_count({"refs": [], "first_frame": "relay:E01-C01"}) == 1
    assert compose.image_count({"refs": []}) == 0
    assert compose.strip_placeholders("看参考图3和 {ref:C01} 与 @图片2") == "看和  与 "
    assert compose.strip_placeholders("参考图参考图12") == "参考图", "清一层拼出新的不再是占位符时停"
```

（若 `compose` 在该测试里以别名导入，按文件现有写法改名。最后一条按 `参考图\d+` 规则：`参考图参考图12` → 清掉 `参考图12` 得 `参考图`，再清无变化。）

`tests/render/test_session.py` 在「1. 建会话与校验」一节加（FakeVideo 的 `cny_per_image=0`，所以金额与旧断言一致；这里验证调用点传了张数）：

```python
    seen_images = []
    real_est = base.estimate_cny
    base.estimate_cny = lambda d, c, r, images=0: (seen_images.append(images), real_est(d, c, r, images))[1]
    try:
        s2 = build()
    finally:
        base.estimate_cny = real_est
    from render import compose as _compose
    assert seen_images and seen_images[:len(s2["clips"])] == [_compose.image_count(c) for c in s2["clips"]]
```

注意：`session.py` 用的是 `base.estimate_cny(...)`（模块属性访问），打桩才生效；如实现改成 `from ... import estimate_cny`，改回模块属性访问。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && .venv/bin/python tests/render/test_providers.py; .venv/bin/python tests/render/test_mix.py; .venv/bin/python tests/render/test_compose.py; .venv/bin/python tests/render/test_session.py
```
Expected：`estimate_cny() got an unexpected keyword argument 'images'`、`frame_size() takes 2 positional arguments`、`module 'render.compose' has no attribute 'image_count'` 等失败。

- [ ] **Step 3: 实现**

`backend/render/providers/base.py`：

```python
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
```

`ClipRequest` 末尾加：

```python
    images: Optional[int] = None               # 只用于计费：提交时实际发出的图片张数（submit 不读）
```

`estimate_cny`：

```python
def estimate_cny(duration: float, caps: Caps, resolution: str, images: int = 0) -> float:
    """预估金额：整数秒 × 单价，加超出免费张数的图片费。"""
    extra = max(0, int(images or 0) - caps.free_images) * caps.cny_per_image
    return round(request_seconds(duration, caps) * caps.cny_per_sec.get(resolution, 0.0) + extra, 2)
```

`backend/render/compose.py`：

```python
_PLACEHOLDER = re.compile(r"\{ref:[^}]*\}|@图片\d+|参考图\d+")
```

并在 `strip_placeholders` 之后加：

```python
def image_count(item: dict) -> int:
    """一段（或自由节点）请求里的图片张数：参考位（含风格图）加首帧。

    ref 模式下首帧在组装请求时才插到第一个参考位，落盘的 refs 里没有它，所以一律「refs + 有首帧加 1」。
    接力尾帧缺失时实际不发首帧，预估会多算一张（偏向多估，与时长取整同类）。"""
    return len(item.get("refs") or []) + (1 if item.get("first_frame") else 0)
```

`backend/render/session.py`：
- 241 行 `_sync_free`：`n["estimate_cny"] = base.estimate_cny(n["duration"], caps, resolution, compose.image_count(n))`
- 283 行 `build`：`row["estimate_cny"] = base.estimate_cny(row["duration"], caps, settings["resolution"], compose.image_count(row))`

`backend/render/free.py`：
- 126 行：`node["estimate_cny"] = base.estimate_cny(node["duration"], caps, s["resolution"], compose.image_count(node))`
- 163 行：`n["estimate_cny"] = base.estimate_cny(n["duration"], caps, s["resolution"], compose.image_count(n))`
（`free.py` 已 `from render import compose`；没有就补导入。）

`backend/render/mix.py`：

```python
from render.providers import get_video

def frame_size(resolution: str, aspect: str, short_side: Optional[dict] = None) -> tuple:
    """(宽, 高)：短边先查厂商给的短边表，再查 SHORT_SIDE（480p/720p/1080p），都没有按 720；长边按画幅，取偶数。"""
    short = (short_side or {}).get(resolution) or SHORT_SIDE.get(resolution, 720)
    ...（其余不变）


def _short_side(s: dict) -> dict:
    """会话所用厂商档位的短边表；取不到（厂商未注册、缺密钥）时为空表，按 SHORT_SIDE 回落。"""
    try:
        return dict(get_video(s["provider"]).caps(s["model"]).short_side or {})
    except Exception:
        return {}


def _size(s: dict, doc: dict) -> tuple:
    aspect = ((doc.get("meta") or {}).get("video") or {}).get("aspect_ratio") or "9:16"
    return frame_size(s["resolution"], aspect, _short_side(s))
```

把 286 行（`compose_fingerprint`）与 356 行（`compose`）的 `size = frame_size(s["resolution"], ...)` 都换成 `size = _size(s, doc)`。Seedance 与假厂商的短边表为空，尺寸与指纹不变。

- [ ] **Step 4: 跑测试确认通过**

先跑 Step 2 的四个文件，再跑全局约束里的后端全量回归（重点确认 `test_compose.py` 第 0 节黄金文件、`test_mix_e2e.py`、`tests/server/test_compose.py` 不变）。

- [ ] **Step 5: 提交**

```bash
git add backend/render/providers/base.py backend/render/compose.py backend/render/session.py backend/render/free.py backend/render/mix.py backend/tests/render/test_providers.py backend/tests/render/test_mix.py backend/tests/render/test_compose.py backend/tests/render/test_session.py
git commit -m "出片厂商无关扩展：能力表加短边、免费图片张数与超出单价，预估按段的图片张数计图片费；新增 image_count 统一四处预估的张数；合成与导出尺寸先查厂商短边表；占位符清洗认「参考图N」；Seedance 与假厂商行为不变"
```

---

### Task 2: 记录实际发出的张数、计费桩带张数、控制台名

**Files:**
- Modify: `backend/render/session.py:431`（`submitted`）
- Modify: `backend/render/runner.py:183-186,207-216,240-258`
- Modify: `backend/render/providers/seedance.py`（`console_name`）
- Test: `backend/tests/render/test_session.py`、`backend/tests/render/test_runner.py`

- [ ] **Step 1: 写失败的测试**

`test_session.py` 末尾（`print("\nALL PASS")` 之前）加：

```python
    # 19. 提交时在尝试里记实际发出的图片张数；不传时不写
    s = build(budget_cny=100000)
    cid = next(c["id"] for c in s["clips"] if c["state"] in ("planned", "failed"))
    sess.queue_run(root, [cid], expected_cny=clip(s, cid)["estimate_cny"])
    assert sess.begin_submit(root, cid) is not None
    sess.submitted(root, cid, "t-img", None, images=7)
    assert clip(sess.load(root), cid)["attempts"][-1]["images"] == 7
    print("19. 尝试记录图片张数 ✓")
```

（`queue_run` 的确认金额参数以本文件第 2、6 节的实际写法为准；若此时有段在跑导致 `build` 带设置被拒，改用一个新的临时根目录建会话。目的只是：`submitted(..., images=7)` 后最后一次尝试有 `images == 7`。）

`test_runner.py`：
1. 第 13 节断言改为厂商无关文案：
   ```python
   assert c["error"].startswith("提交时连接中断，不确定厂商是否已受理：请到厂商控制台核对") and "ReadTimeout" in c["error"]
   ```
   并在同节加一段：给 `fake` 设 `fake.console_name = "某某控制台"` 后再来一次 AmbiguousSubmit，断言错误以「请到某某控制台核对」开头；结束时 `del fake.console_name`。
2. 末尾加一节「计费桩带张数」：
   ```python
   # 16. 提交时算出实际张数写进尝试；计费时 _stub 把它带给 cost
   costs = []
   real_cost = fake.cost
   fake.cost = lambda st, req: (costs.append(req.images), real_cost(st, req))[1]
   r9, i9 = fresh("images")
   sess.queue_run(r9, [i9[0]])
   rn = quick()
   rn.watch(r9)
   for _ in range(5):
       rn.tick()
   a = clip(r9, i9[0])["attempts"][-1]
   sent = fake.submitted[-1]
   assert a["images"] == len(sent.refs) + (1 if sent.first_frame else 0)
   assert costs and costs[-1] == a["images"]
   fake.cost = real_cost
   print("16. 尝试记张数、计费桩带张数 ✓")
   ```
   （`fresh`、`quick` 是本文件第 13 节附近已有的辅助函数；按其实际签名调用。）

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && .venv/bin/python tests/render/test_session.py; .venv/bin/python tests/render/test_runner.py
```
Expected：`submitted() got an unexpected keyword argument 'images'`；第 13 节文案断言失败。

- [ ] **Step 3: 实现**

`session.submitted`：

```python
def submitted(root, clip_id: str, task_id: str, first_frame_used: Optional[str],
              style_ref: Optional[str] = None, images: Optional[int] = None) -> None:
    with mutate(root) as s:
        c = _item(s, clip_id)
        c["attempts"][-1].update(task_id=task_id, state="running", first_frame_used=first_frame_used,
                                 style_ref=style_ref)
        if images is not None:
            c["attempts"][-1]["images"] = int(images)
        c["state"] = "running"
```

`runner.py`：

```python
    @staticmethod
    def _stub(s: dict, c: dict) -> base.ClipRequest:
        """计费用的最小请求：档位、分辨率、时长，以及提交时实际发出的图片张数（旧尝试没有记为 None）。"""
        last = (c.get("attempts") or [{}])[-1]
        return base.ClipRequest(prompt=c["prompt"], model=s["model"], duration=c["duration"],
                                resolution=s["resolution"], images=last.get("images"))
```

`_submit` 里：
- AmbiguousSubmit 分支文案：
  ```python
  where = getattr(provider, "console_name", "") or "厂商控制台"
  sess.submit_failed(root, c["id"], f"提交时连接中断，不确定厂商是否已受理：请到{where}核对，"
                     "确认没有生成再重做（" + str(e) + "）", uncertain=True)
  ```
- 写回：
  ```python
  sess.submitted(root, c["id"], tid, used, style_ref=getattr(req, "style_ref", None),
                 images=len(req.refs) + (1 if req.first_frame else 0))
  ```
- `_download` 里注释「结果地址 24 小时有效，下一轮再下」改为「结果地址限时有效，下一轮再下」。

`seedance.py` 类属性加 `console_name = "方舟控制台"`。

- [ ] **Step 4: 跑测试确认通过**；再跑后端全量回归（`tests/server/test_render.py`、`test_render_free.py`、`test_free_runner.py` 走 runner 与 submitted）。

- [ ] **Step 5: 提交**

```bash
git add backend/render/session.py backend/render/runner.py backend/render/providers/seedance.py backend/tests/render/test_session.py backend/tests/render/test_runner.py
git commit -m "出片提交时在尝试里记下实际发出的图片张数，计费桩把它带给厂商的 cost；提交结果不明的提示改用厂商自报的控制台名（方舟控制台），没有时写厂商控制台"
```

---

### Task 3: MiniMax 厂商模块

**Files:**
- Create: `backend/render/providers/minimax.py`
- Modify: `backend/render/providers/__init__.py`（注册）
- Modify: `backend/render/providers/fake.py`（`native_audio` 参数，供 Task 4 用；本 Task 一并加）
- Create: `backend/tests/render/test_minimax.py`
- Modify: `backend/tests/render/test_providers.py`（注册表能取到 minimax）

- [ ] **Step 1: 写失败的测试 `backend/tests/render/test_minimax.py`**

```python
#!/usr/bin/env python3
"""MiniMax H3：能力表、改写与请求体、图片检查与规范化、错误映射、状态映射、下载重查与截尾帧、计费、密钥。

用 httpx.MockTransport 模拟接口，不联网、不花钱。用法: python3 tests/render/test_minimax.py
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render.providers import base  # noqa: E402
from render.providers import minimax as mm  # noqa: E402
from render.providers.minimax import BASE_URL, MODELS, MiniMax, plan_normalize, rewrite_refs  # noqa: E402

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 8
PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
HAS_FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def mmx(handler, key="k-secret"):
    return MiniMax(key, client=httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler)))


def png_uri(w, h, mime="image/png"):
    """用 ffmpeg 生成 w×h 的 PNG data URI。"""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "a.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=red:s={w}x{h}",
                        "-frames:v", "1", str(p)], check=True)
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def dims(uri):
    raw = base64.b64decode(uri.split(",", 1)[1])
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.img"
        p.write_bytes(raw)
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height", "-of", "csv=p=0", str(p)],
                             capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def main() -> int:
    os.environ.pop("STORYBOARD_MINIMAX_PRICE_SCALE", None)
    os.environ.pop("STORYBOARD_MINIMAX_NATIVE_AUDIO", None)
    seen = []

    def accept(request):
        seen.append(request)
        return httpx.Response(200, json={"task_id": "106916112212032", "base_resp": {"status_code": 0}})

    # 1. 能力表：三档的分辨率顺序（默认在前）、单价、图片费、短边；尾帧恒为 True；默认不出原声
    m = mmx(accept)
    h3, hs, lite = m.caps("minimax-h3"), m.caps("minimax-h3-highspeed"), m.caps("minimax-h3-lite")
    assert h3.resolutions == ["768P", "2K"] and hs.resolutions == ["768P", "480P"] == lite.resolutions
    assert h3.cny_per_sec == {"768P": 0.5, "2K": 0.8}
    assert hs.cny_per_sec == {"768P": 0.4, "480P": 0.26} and lite.cny_per_sec == {"768P": 0.26, "480P": 0.16}
    assert (h3.free_images, h3.cny_per_image, lite.cny_per_image) == (5, 0.2, 0.13)
    assert h3.short_side == {"768P": 768, "2K": 1440} and lite.short_side == {"768P": 768, "480P": 480}
    assert h3.returns_last_frame is True and h3.first_frame and not h3.frame_with_refs
    assert (h3.min_clip_sec, h3.max_clip_sec, h3.max_refs) == (4, 15, 9)
    assert h3.native_audio is False
    os.environ["STORYBOARD_MINIMAX_NATIVE_AUDIO"] = "1"
    assert m.caps("minimax-h3").native_audio is True
    os.environ.pop("STORYBOARD_MINIMAX_NATIVE_AUDIO")
    os.environ["STORYBOARD_MINIMAX_PRICE_SCALE"] = "0.5"
    assert m.caps("minimax-h3").cny_per_sec["768P"] == 0.25 and m.caps("minimax-h3").cny_per_image == 0.1
    os.environ["STORYBOARD_MINIMAX_PRICE_SCALE"] = "abc"
    assert m.caps("minimax-h3").cny_per_sec["768P"] == 0.5, "解析失败按 1.0"
    os.environ.pop("STORYBOARD_MINIMAX_PRICE_SCALE")
    must_raise(base.ProviderError, m.caps, "MiniMax-H3-Max")
    assert m.default_model == "minimax-h3" and set(m.models) == set(MODELS)
    assert m.console_name == "MiniMax 开放平台" and "未经账单核对" in m.rate_note
    print("1. 能力表 ✓")

    # 2. 改写与请求体
    assert rewrite_refs("【首帧】{ref:__first__} 开场\n【参考】{ref:C01} 林冲\n【参考】{ref:C01} 再一次") == \
        "【首帧】参考图1 开场\n【参考】参考图2 林冲\n【参考】参考图3 再一次"
    assert m.rewrite_prompt("{ref:A}{ref:B}") == "参考图1参考图2"
    req = base.ClipRequest(prompt="p 参考图1 参考图2", model="minimax-h3", duration=7.3, resolution="768P",
                           aspect="9:16", refs=[base.RefImage("C01", "character", "https://img/c01.png"),
                                                base.RefImage("S01", "location", "https://img/s01.png")])
    assert m.submit(req) == "106916112212032"
    sent = seen[-1]
    body = json.loads(sent.content)
    assert sent.method == "POST" and sent.url.path == "/v2/video_generation"
    assert sent.headers["authorization"] == "Bearer k-secret"
    assert body["model"] == "MiniMax-H3" and (body["duration"], body["resolution"], body["ratio"]) == (8, "768P", "9:16")
    assert body["aigc_watermark"] is False and "response_format" not in body and "callback_url" not in body
    assert body["content"][0] == {"type": "text", "text": "p 参考图1 参考图2"}
    assert [c["image_url"]["url"] for c in body["content"][1:]] == ["https://img/c01.png", "https://img/s01.png"]
    assert all(c["role"] == "reference_image" and c["type"] == "image_url" for c in body["content"][1:])
    framed = base.ClipRequest(prompt="p", model="minimax-h3-lite", duration=4, resolution="480P", aspect="9:16",
                              first_frame="https://img/kf.png")
    m.submit(framed)
    body = json.loads(seen[-1].content)
    assert "ratio" not in body, "图生由图决定画幅，不传 ratio"
    assert body["content"][1] == {"type": "image_url", "image_url": {"url": "https://img/kf.png"}, "role": "first_frame"}
    text_only = base.ClipRequest(prompt="p", model="minimax-h3-lite", duration=4, resolution="480P", aspect="9:16")
    m.submit(text_only)
    assert json.loads(seen[-1].content)["ratio"] == "9:16", "Lite 文生也显式给比例"
    must_raise(base.ProviderError, m.submit,
               base.ClipRequest(prompt="x" * 7001, model="minimax-h3", duration=4, resolution="768P"))
    must_raise(base.ProviderError, m.submit,
               base.ClipRequest(prompt="p", model="minimax-h3", duration=4, resolution="768P", aspect="5:4"))
    must_raise(base.ProviderError, m.submit,
               base.ClipRequest(prompt="p", model="minimax-h3", duration=4, resolution="1080p"))
    n_before = len(seen)
    print("2. 改写与请求体 ✓")

    # 3. 图片：http(s) 原样；MIME 转小写；不支持的格式报错；过小、过宽的图规范化；临时目录用完即删
    up = "data:IMAGE/PNG;base64," + base64.b64encode(PNG_1x1).decode()
    if HAS_FF:
        made = []
        real_td = mm.tempfile.TemporaryDirectory

        class Spy(real_td):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                made.append(Path(self.name))
        mm.tempfile.TemporaryDirectory = Spy
        try:
            m.submit(base.ClipRequest(prompt="p 参考图1 参考图2", model="minimax-h3", duration=4, resolution="768P",
                                      refs=[base.RefImage("C01", "character", png_uri(100, 100)),
                                            base.RefImage("S01", "location", png_uri(3000, 800))]))
        finally:
            mm.tempfile.TemporaryDirectory = real_td
        imgs = [c["image_url"]["url"] for c in json.loads(seen[-1].content)["content"][1:]]
        for u in imgs:
            w, h = dims(u)
            assert 256 <= w <= 5760 and 256 <= h <= 5760 and 0.4 <= w / h <= 2.5, (w, h)
        assert made and not any(p.exists() for p in made), "规范化的临时目录提交后不存在"
        m.submit(base.ClipRequest(prompt="p 参考图1", model="minimax-h3", duration=4, resolution="768P",
                                  refs=[base.RefImage("C01", "character", up)]))
        assert json.loads(seen[-1].content)["content"][1]["image_url"]["url"].startswith("data:image/")
    else:
        print("   （本机没有 ffmpeg/ffprobe：跳过规范化用例）")
    orig_tool = mm._tool
    mm._tool = lambda name: None                       # 没装 ffmpeg：不规范化、原样发出（MIME 仍转小写）
    try:
        m.submit(base.ClipRequest(prompt="p 参考图1", model="minimax-h3", duration=4, resolution="768P",
                                  refs=[base.RefImage("C01", "character", up)]))
    finally:
        mm._tool = orig_tool
    assert json.loads(seen[-1].content)["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    e = must_raise(base.ProviderError, m.submit,
                   base.ClipRequest(prompt="p", model="minimax-h3", duration=4, resolution="768P",
                                    refs=[base.RefImage("C01", "character", "data:image/gif;base64,R0lG")]))
    assert "C01" in str(e) and "image/gif" in str(e)
    assert plan_normalize(1000, 1600) is None
    assert plan_normalize(100, 100) == (256, 256, 256, 256)
    assert plan_normalize(3000, 800) == (3000, 800, 3000, 1200)
    assert plan_normalize(400, 2000) == (400, 2000, 800, 2000)
    w, h, pw, ph = plan_normalize(8000, 3000)
    assert pw <= 5760 and ph <= 5760 and 0.4 <= pw / ph <= 2.5
    print("3. 图片检查与规范化 ✓")

    # 4. 错误映射（§8.1 判定表，每行至少一例）
    def answer(resp=None, exc=None):
        def h(request):
            if exc:
                raise exc
            return resp
        return mmx(h)
    q = base.ClipRequest(prompt="p", model="minimax-h3", duration=4, resolution="768P")
    for ex in (httpx.ConnectError("x"), httpx.ConnectTimeout("x"), httpx.PoolTimeout("x")):
        must_raise(base.TransientError, answer(exc=ex).submit, q)                       # 1
    must_raise(base.AmbiguousSubmit, answer(exc=httpx.ReadTimeout("x")).submit, q)        # 2
    must_raise(base.TransientError, answer(exc=httpx.ReadTimeout("x")).poll, "t")
    must_raise(base.TransientError, answer(httpx.Response(429, json={})).submit, q)       # 3
    must_raise(base.TransientError, answer(httpx.Response(529, json={})).submit, q)       # 3：529 先于 5xx
    must_raise(base.AmbiguousSubmit, answer(httpx.Response(500, json={})).submit, q)      # 4
    must_raise(base.TransientError, answer(httpx.Response(502, json={})).poll, "t")
    e = must_raise(base.ProviderError, answer(httpx.Response(402, json={})).submit, q)    # 5
    assert "余额不足" in str(e)
    e = must_raise(base.ProviderError, answer(httpx.Response(200, json={"base_resp": {"status_code": 1008,
                   "status_msg": "insufficient balance"}})).submit, q)                     # 9 + 5
    assert "余额不足" in str(e)
    e = must_raise(base.ProviderError, answer(httpx.Response(401, json={"error": {"type": "authorized_error",
                   "message": "invalid api key (1004)"}})).submit, q)                      # 6
    assert "密钥无效" in str(e) and "k-secret" not in str(e)
    e = must_raise(base.ProviderError, answer(httpx.Response(422, json={"error": {"code": 1026,
                   "message": "video description contains sensitive content"}})).submit, q)  # 7
    assert "审核" in str(e)
    e = must_raise(base.ProviderError, answer(httpx.Response(200, json={"error": {"message":
                   "video description contains sensitive content (1026)"}})).submit, q)    # 9：码在说明里
    assert "审核" in str(e)
    e = must_raise(base.ProviderError, answer(httpx.Response(400, json={"error": {"code": 2013,
                   "message": "prompt is required"}})).submit, q)                          # 8
    assert "2013" in str(e) and "prompt is required" in str(e)
    must_raise(base.AmbiguousSubmit, answer(httpx.Response(200, text="<html>")).submit, q)  # 10
    must_raise(base.AmbiguousSubmit, answer(httpx.Response(200, json={"base_resp": {"status_code": 0}})).submit, q)
    must_raise(base.TransientError, answer(httpx.Response(200, text="<html>")).poll, "t")
    print("4. 错误映射 ✓")

    # 5. 查询：状态映射、task 结构、usage 原样、失败原因
    def task(status, **extra):
        return mmx(lambda r: httpx.Response(200, json={"task": {"task_id": "t", "status": status, **extra},
                                                       "base_resp": {"status_code": 0}}))
    assert task("queued").poll("t").status == "pending"
    assert task("running").poll("t").status == "running"
    assert task("weird").poll("t").status == "running"
    st = task("succeeded", content={"url": "https://cdn/x.mp4"}, usage={"input_image_count": 7}).poll("t")
    assert (st.status, st.video_url, st.last_frame_url) == ("succeeded", "https://cdn/x.mp4", None)
    assert st.usage == {"input_image_count": 7}
    st = task("failed", error={"code": "1026", "message": "sensitive"}).poll("t")
    assert st.status == "failed" and "审核" in st.error
    st = task("failed", error={"code": "2056", "message": "boom"}).poll("t")
    assert st.error == "2056：boom"
    assert task("cancelled").poll("t").error == "任务已取消"
    poll_seen = []
    mmx(lambda r: (poll_seen.append(r), httpx.Response(200, json={"task": {"status": "running"}}))[1]).poll("abc")
    assert poll_seen[0].url.path == "/v2/query/video_generation/abc"
    print("5. 查询 ✓")

    # 6. 下载：正常；地址过期后重查再下；重查仍失败报错；尾帧截取与降级
    with tempfile.TemporaryDirectory() as d:
        clips = Path(d) / "clips"
        hits = []

        def cdn(request):
            hits.append(str(request.url))
            if request.url.path == "/v2/query/video_generation/t":
                return httpx.Response(200, json={"task": {"status": "succeeded", "content": {"url": "https://cdn/new.mp4"}}})
            if request.url.host == "cdn" and request.url.path == "/old.mp4":
                return httpx.Response(403)
            assert "authorization" not in request.headers, "下载直链不带密钥"
            return httpx.Response(200, content=MP4)
        orig_tool = mm._tool
        mm._tool = lambda name: None
        try:
            files = mmx(cdn).download(base.TaskState("t", "succeeded", video_url="https://cdn/ok.mp4"),
                                      clips / "E01-C01.v1.mp4")
            assert files["video"].read_bytes() == MP4 and files["last_frame"] is None, "没 ffmpeg 不截尾帧"
            files = mmx(cdn).download(base.TaskState("t", "succeeded", video_url="https://cdn/old.mp4"),
                                      clips / "E01-C02.v1.mp4")
            assert files["video"].exists() and any(h.endswith("/new.mp4") for h in hits)
            dead = mmx(lambda r: httpx.Response(403) if r.url.host == "cdn"
                       else httpx.Response(200, json={"task": {"status": "succeeded", "content": {"url": "https://cdn/x.mp4"}}}))
            e = must_raise(base.ProviderError, dead.download,
                           base.TaskState("t", "succeeded", video_url="https://cdn/x.mp4"), clips / "E01-C03.v1.mp4")
            assert "7 天" in str(e)
            must_raise(base.TransientError, mmx(lambda r: httpx.Response(503)).download,
                       base.TaskState("t", "succeeded", video_url="https://cdn/y.mp4"), clips / "E01-C04.v1.mp4")
        finally:
            mm._tool = orig_tool
        if HAS_FF:
            real = Path(d) / "real.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x568:d=1",
                            "-pix_fmt", "yuv420p", str(real)], check=True)
            payload = real.read_bytes()
            files = mmx(lambda r: httpx.Response(200, content=payload)).download(
                base.TaskState("t", "succeeded", video_url="https://cdn/r.mp4"), clips / "E01-C05.v1.mp4")
            assert files["last_frame"] and files["last_frame"].name == "E01-C05.v1.last.jpg"
            assert files["last_frame"].stat().st_size > 0
            files = mmx(lambda r: httpx.Response(200, content=MP4)).download(
                base.TaskState("t", "succeeded", video_url="https://cdn/bad.mp4"), clips / "E01-C06.v1.mp4")
            assert files["last_frame"] is None, "截不到尾帧不让本段失败"
            assert not (clips / "E01-C06.v1.last.jpg").exists()
    print("6. 下载与尾帧 ✓")

    # 7. 计费：失败为 0；≤ 5 张不加钱；7 张加 2 张；优先 usage.input_image_count，没有时用 req.images
    r = base.ClipRequest(prompt="", model="minimax-h3", duration=5, resolution="768P")
    ok = base.TaskState("t", "succeeded")
    assert m.cost(base.TaskState("t", "failed"), r) == 0.0
    assert m.cost(ok, r) == 2.5
    r.images = 5
    assert m.cost(ok, r) == 2.5
    r.images = 7
    assert m.cost(ok, r) == 2.9
    assert m.cost(base.TaskState("t", "succeeded", usage={"input_image_count": 9}), r) == 3.3
    lr = base.ClipRequest(prompt="", model="minimax-h3-lite", duration=4, resolution="480P", images=6)
    assert m.cost(ok, lr) == round(4 * 0.16 + 0.13, 2)
    assert base.estimate_cny(5, m.caps("minimax-h3"), "768P", images=7) == 2.9
    print("7. 计费 ✓")

    # 8. 密钥与地址：没配时报错说明去哪配；可换地址
    os.environ["MINIMAX_API_KEY"] = ""
    e = must_raise(base.ProviderError, MiniMax.from_env)
    assert "MINIMAX_API_KEY" in str(e)
    os.environ["MINIMAX_API_KEY"] = "k-env"
    os.environ["STORYBOARD_MINIMAX_BASE_URL"] = "https://api.example.io"
    try:
        inst = MiniMax.from_env()
        assert str(inst._http.base_url).rstrip("/") == "https://api.example.io"
    finally:
        os.environ["MINIMAX_API_KEY"] = ""
        os.environ.pop("STORYBOARD_MINIMAX_BASE_URL", None)
    assert len(seen) >= n_before
    print("8. 密钥与地址 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

（`os.environ["MINIMAX_API_KEY"] = ""` 先于 `from_env`，所以 `_load_dotenv` 的 `setdefault` 不会灌入真实值；测试结束时保持空串。）

`tests/render/test_providers.py` 第 4 节末尾加：

```python
    os.environ["MINIMAX_API_KEY"] = ""          # 先置空串：.env 不会覆盖已有变量
    e = must_raise(base.ProviderError, providers.get_video, "minimax")
    assert "MINIMAX_API_KEY" in str(e)
```
（文件头补 `import os`。）

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && .venv/bin/python tests/render/test_minimax.py
```
Expected：`ModuleNotFoundError: No module named 'render.providers.minimax'`。

- [ ] **Step 3: 实现 `backend/render/providers/minimax.py`**

```python
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
RATIOS = ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16")
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


def _reject(code, msg, status=None, body: str = "") -> ProviderError:
    key = code if code in MSG else _HTTP_CODE.get(status)
    if key in MSG:
        return ProviderError(MSG[key])
    text = "：".join(str(x) for x in (code, msg) if x)
    return ProviderError(text or f"HTTP {status}：{body[:300]}")


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
        raw = base64.b64decode(m.group(2))
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
            raise _reject(code, msg, r.status_code, r.text)
        if code:                                      # 2xx 但厂商明确报了错：没建任务
            raise _reject(code, msg)
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
                error = (MSG.get(code) or "：".join(str(x) for x in (code, err.get("message")) if x)
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
```

`backend/render/providers/__init__.py` 在 seedance 注册之后加：

```python
def _minimax():
    from render.providers.minimax import MiniMax
    return MiniMax.from_env()


register("minimax", _minimax)
```

`backend/render/providers/fake.py`：`FakeVideo.__init__` 增加关键字参数 `native_audio: bool = True`，传给 `Caps(..., native_audio=native_audio, ...)`（其余不变）。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd backend && .venv/bin/python tests/render/test_minimax.py && .venv/bin/python tests/render/test_providers.py
```
再跑后端全量回归。注意 `names()` 现在会多列出 minimax（`test_session.py` 只断言包含 fake，不受影响）。

- [ ] **Step 5: 提交**

```bash
git add backend/render/providers/minimax.py backend/render/providers/__init__.py backend/render/providers/fake.py backend/tests/render/test_minimax.py backend/tests/render/test_providers.py
git commit -m "新增视频厂商 MiniMax H3（H3、Highspeed、Lite 三档）：参考写成「参考图N」与图片顺序对应，图生不传画幅、参考生与文生显式给画幅；本机图片校验格式与体积并在临时目录用 ffmpeg 补边缩放，用完即删；错误按判定表归类，余额不足、密钥无效、审核拦截给专门提示，2xx 内的业务错误按明确拒绝；下载地址过期重查一次，下载后截尾帧供接力；计费按秒加超出 5 张的图片费，优先用厂商返回的张数"
```

---

### Task 4: 缺省厂商改为 MiniMax、声音模式过滤、界面提示

**Files:**
- Modify: `backend/render/providers/__init__.py`（`_has_key`、`_default_choice`、`default_video_name`、`default_fell_back`、`names`）
- Modify: `backend/render/compose.py`（`audio_modes(caps)`）
- Modify: `backend/render/session.py:157-182`（`resolve_settings`）、`:314-344`（`view`）
- Modify: `frontend/src/types.ts:805-817`、`frontend/src/components/FilmPanel.tsx:86-95`
- Test: `backend/tests/render/test_providers.py`、`backend/tests/render/test_session.py`、`frontend/tests/film.test.tsx`

- [ ] **Step 1: 写失败的测试**

`tests/render/test_providers.py` 加一节：

```python
    # 5. 缺省厂商：显式设置照用；只有 MiniMax 密钥 → minimax；只有方舟 → 回落 seedance；都没有 → minimax
    saved_env = os.environ.pop("STORYBOARD_VIDEO_PROVIDER", None)
    real_has = providers._has_key
    try:
        for keys, want, fell in (({"minimax"}, "minimax", False), ({"minimax", "seedance"}, "minimax", False),
                                 ({"seedance"}, "seedance", True), (set(), "minimax", False)):
            providers._has_key = lambda n, ks=keys: n in ks
            assert providers.default_video_name() == want, (keys, want)
            assert providers.default_fell_back() is fell, (keys, fell)
        os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
        providers._has_key = lambda n: (_ for _ in ()).throw(AssertionError("显式设置时不该查密钥"))
        assert providers.default_video_name() == "fake" and providers.default_fell_back() is False
        assert "fake" in providers.names()
        os.environ.pop("STORYBOARD_VIDEO_PROVIDER")
        providers._has_key = lambda n: False
        assert "fake" not in providers.names() and {"minimax", "seedance"} <= set(providers.names())
    finally:
        providers._has_key = real_has
        if saved_env is None:
            os.environ.pop("STORYBOARD_VIDEO_PROVIDER", None)
        else:
            os.environ["STORYBOARD_VIDEO_PROVIDER"] = saved_env
    print("5. 缺省厂商与回落 ✓")
```

`tests/render/test_session.py` 末尾加：

```python
    # 20. 声音模式按厂商能力过滤；换厂商时继承的旧模式回落 tts_all；只读刷新不改写；明确指定不支持的模式报错
    mute = FakeVideo(native_audio=False)
    mute.name = "mute"
    providers.register("mute", lambda: mute)
    tmp2 = tempfile.TemporaryDirectory()
    r2 = Path(tmp2.name) / "render" / "v"
    b2 = lambda **patch: sess.build(r2, doc, owner=OWNER, patch=patch, keyframes={})  # noqa: E731
    s = b2(audio_mode="all_native")
    assert s["provider"] == "fake" and s["audio_mode"] == "all_native"
    assert sess.view(s)["options"]["audio_modes"] == ["tts_all", "dialogue_native", "all_native", "silent"]
    s = b2(provider="mute")
    assert s["provider"] == "mute" and s["audio_mode"] == "tts_all", "换厂商时不支持的旧模式回落"
    assert sess.view(s)["options"]["audio_modes"] == ["tts_all", "silent"]
    e = must_raise(sess.SessionError, b2, audio_mode="dialogue_native")
    assert "全部配音" in str(e)
    # 只读刷新：旧会话里存着不支持的模式（例如手改、或厂商能力变了），patch 为空时不改写
    with sess.mutate(r2) as cur:
        cur["audio_mode"] = "all_native"
    before = (r2 / "session.json").read_text(encoding="utf-8")
    s = b2()
    assert s["audio_mode"] == "all_native"
    assert json.loads((r2 / "session.json").read_text(encoding="utf-8"))["audio_mode"] == "all_native"
    assert before  # 读到过
    print("20. 声音模式过滤与回落 ✓")

    # 21. default_note：会话是 seedance 且缺省发生回落时给文字，其余为空
    sd_fake = FakeVideo()
    sd_fake.name = "seedance"
    providers.register("seedance", lambda: sd_fake)
    saved_env = os.environ.pop("STORYBOARD_VIDEO_PROVIDER")
    real_has = providers._has_key
    try:
        providers._has_key = lambda n: n == "seedance"
        r3 = Path(tmp2.name) / "render" / "v3"
        s = sess.build(r3, doc, owner=OWNER, patch={}, keyframes={})
        assert s["provider"] == "seedance"
        assert "MINIMAX_API_KEY" in sess.view(s)["options"]["default_note"]
        providers._has_key = lambda n: True
        assert sess.view(s)["options"]["default_note"] == "", "配了 MiniMax 就不提示"
        assert sess.build(r3, doc, owner=OWNER, patch={}, keyframes={})["provider"] == "seedance", \
            "已有会话不迁移"
    finally:
        providers._has_key = real_has
        os.environ["STORYBOARD_VIDEO_PROVIDER"] = saved_env
        from render.providers import _seedance
        providers.register("seedance", _seedance)
    assert sess.view(sess.load(root))["options"]["default_note"] == "", "显式设置（fake）时不提示"
    print("21. 缺省回落提示与已有会话不迁移 ✓")

    # 22. 切到 minimax：默认档位与分辨率（不联网：只建会话，不提交）
    import httpx
    from render.providers.minimax import BASE_URL, MiniMax
    mmx = MiniMax("k", client=httpx.Client(base_url=BASE_URL,
                                           transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    providers.register("minimax", lambda: mmx)
    s = b2(provider="minimax")
    assert (s["provider"], s["model"], s["resolution"], s["audio_mode"]) == ("minimax", "minimax-h3", "768P", "tts_all")
    from render.providers import _minimax
    providers.register("minimax", _minimax)
    print("22. 切到 MiniMax 的默认设置 ✓")
```

（`tmp2.cleanup()` 放到函数末尾；第 20 节里 `b2(provider="mute")` 带的 patch 只有 provider，`audio_mode` 由继承来。`_seedance` / `_minimax` 是 `providers/__init__.py` 里的模块级工厂函数。）

`frontend/tests/film.test.tsx` 在建好会话、出片设置可见的某一节之后加一节（沿用文件里改 `film` 再触发重读的现有写法，例如与「10. 验证门拦截」相同的方式）：

```tsx
// 10f. 缺省回落提示：options.default_note 非空时出片设置区显示这一行，为空时不显示
film = { ...film!, options: { ...film!.options, default_note: '没有配置 MINIMAX_API_KEY，新会话先用 Seedance' } }
// …按本文件现有方式触发出片会话重读并等待渲染…
must((container.textContent ?? '').includes('没有配置 MINIMAX_API_KEY'), '有 default_note 时显示提示')
film = { ...film!, options: { ...film!.options, default_note: '' } }
// …再次重读…
must(!(container.textContent ?? '').includes('没有配置 MINIMAX_API_KEY'), '为空时不显示')
console.log('10f. 缺省回落提示 ✓')
```

（变量名 `film`、`container`、`must` 以文件实际为准；若设置区在 `<details>` 里默认折叠，`textContent` 仍包含其内容。）

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && .venv/bin/python tests/render/test_providers.py; .venv/bin/python tests/render/test_session.py
cd ../frontend && npm test
```
Expected：`module 'render.providers' has no attribute 'default_fell_back'`；`audio_modes` 断言失败；前端 10f 断言失败（或 TS 报 `default_note` 不在类型里）。

- [ ] **Step 3: 实现**

`backend/render/providers/__init__.py`（顶部 docstring 同步：缺省 minimax，没配 MiniMax 而配了方舟时回落 seedance）：

```python
_KEY_ENV = {"minimax": "MINIMAX_API_KEY", "seedance": "ARK_API_KEY"}


def _has_key(name: str) -> bool:
    """这家厂商的密钥是否已配置。先把 backend/.env 读进进程环境（与各厂商 from_env 同一个加载函数，
    只放进环境、不读出不打印），再看变量是否非空。.env 只在这里加载：测试给它打桩就不会碰真实 .env。"""
    from pipeline.config import ROOT, _load_dotenv
    _load_dotenv(ROOT / ".env")
    _load_dotenv(ROOT.parent / ".env")
    return bool(os.environ.get(_KEY_ENV.get(name, ""), "").strip())


def _default_choice() -> tuple:
    """(缺省厂商, 是否发生了回落)。显式设置 STORYBOARD_VIDEO_PROVIDER 照用；否则有 MiniMax 密钥用 minimax，
    只有方舟密钥回落 seedance，都没有仍取 minimax（缺密钥的提示指向推荐厂商）。只影响新建的出片会话。"""
    explicit = os.environ.get("STORYBOARD_VIDEO_PROVIDER", "").strip()
    if explicit:
        return explicit, False
    if _has_key("minimax"):
        return "minimax", False
    if _has_key("seedance"):
        return "seedance", True
    return "minimax", False


def default_video_name() -> str:
    return _default_choice()[0]


def default_fell_back() -> bool:
    return _default_choice()[1]


def names() -> list:
    """界面可选的厂商。假厂商只在被显式设为默认（测试、本地演示）时出现。"""
    fake_on = os.environ.get("STORYBOARD_VIDEO_PROVIDER", "").strip() == "fake"
    return [n for n in sorted(_FACTORIES) if n != "fake" or fake_on]
```

`backend/render/compose.py`（`AUDIO_MODES` 之后）：

```python
def audio_modes(caps) -> list:
    """这家厂商可选的声音模式：不出原声时只剩「全部配音」「静音」。"""
    return [m for m in AUDIO_MODES if caps.native_audio or m in ("tts_all", "silent")]
```

`session.resolve_settings`：在 `cur["audio_mode"] not in compose.AUDIO_MODES` 的检查之后加：

```python
    if cur["audio_mode"] not in compose.audio_modes(caps):
        old_ = old or {}
        switched = (("provider" in patch and patch["provider"] != old_.get("provider"))
                    or ("model" in patch and patch["model"] != old_.get("model")))
        if "audio_mode" in patch:
            raise SessionError("这家厂商不出原声，可选：全部配音、静音")
        if switched or old is None:
            cur["audio_mode"] = "tts_all"
        # 其它情况（只读刷新、patch 为空）不改写：避免把会话改得与已出片段不一致、触发过期；
        # compose 侧 caps.native_audio 为 False 时本就不请求原声
```

（注意 `patch` 在函数开头已去掉 None 值；`old is None` 时新会话的缺省本就是 `tts_all`，这一行只是兜底。）

`session.view` 的 `options`：
- `"audio_modes": compose.audio_modes(caps),`
- 新增 `"default_note": _default_note(s),`，并在 `view` 之前定义：

```python
DEFAULT_NOTE = "没有配置 MINIMAX_API_KEY，新会话先用 Seedance；配好后新建的会话会默认用 MiniMax"


def _default_note(s: dict) -> str:
    """缺省厂商回落到 Seedance（没配 MiniMax 而配了方舟）且这个会话用的是 seedance 时给一行提示。"""
    if s.get("provider") != "seedance":
        return ""
    from render.providers import default_fell_back
    return DEFAULT_NOTE if default_fell_back() else ""
```

（`session.py` 顶部已 `from render.providers import ...`，可直接把 `default_fell_back` 加进那行导入，去掉函数内导入；但测试里给 `providers._has_key` 打桩依赖的是 `providers` 模块内的查找，`default_fell_back` 内部调用 `_default_choice` → `_has_key` 走模块全局，打桩有效。）

`frontend/src/types.ts` 的会话 `options` 加：

```ts
    /** 缺省厂商回落到 Seedance 时的一行提示（文字由后端给）；没有回落为空串 */
    default_note?: string
```

`frontend/src/components/FilmPanel.tsx`：在厂商选择 `</label>` 之后、`{otherProvider ? (` 之前加：

```tsx
      {s.options.default_note ? <p className="tlc__kfnote">{s.options.default_note}</p> : null}
```

不加 i18n 文案（与 `rate_note` 同样由后端给文字）。

- [ ] **Step 4: 跑测试确认通过**

后端全量回归；前端 `npm test`、`npm run lint`、`npm run build`。

- [ ] **Step 5: 提交**

```bash
git add backend/render/providers/__init__.py backend/render/compose.py backend/render/session.py backend/tests/render/test_providers.py backend/tests/render/test_session.py frontend/src/types.ts frontend/src/components/FilmPanel.tsx frontend/tests/film.test.tsx
git commit -m "新建出片会话的缺省厂商改为 MiniMax：显式设置照用，没配 MiniMax 而配了方舟时回落 Seedance 并在出片设置里提示一行，已有会话不迁移；声音模式按厂商能力过滤，不出原声的厂商只给全部配音与静音，换厂商时继承的旧模式回落全部配音，只读刷新不改写"
```

---

### Task 5: 冒烟脚本与 README

**Files:**
- Modify: `backend/render/smoke.py`
- Modify: `README.md`（出片一节，约 66–71 行）

本 Task 不运行冒烟脚本（花钱）。只做静态检查：`cd backend && .venv/bin/python -c "import render.smoke"` 能导入、`.venv/bin/python -m render.smoke --help` 能打印帮助（不提交、不联网）。

- [ ] **Step 1: 改 `backend/render/smoke.py`**

```python
"""视频厂商真实冒烟（花真钱，上限 5 元）：用《药》第一段出一条最短的视频。

用法: cd backend && .venv/bin/python -m render.smoke [--provider minimax|seedance] [--model …] [--resolution …]
                                                    [--out /tmp/video-smoke] [--yes] [--style 图]
缺省厂商与新建出片会话一致（MiniMax；没配 MiniMax 而配了方舟时为 Seedance）。
打印厂商返回的用量与按单价折算的金额、成片是否带音轨与实际宽高——拿它们与控制台账单、spec §5.1 的短边表核对。
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from render import compose
from render.providers import base, default_video_name, get_video

LIMIT_CNY = 5.0
YAO = Path(__file__).resolve().parent.parent / "tests" / "real_text_yao" / "output_merged.json"
DEFAULTS = {"seedance": ("seedance-2.0-mini", "480p"), "minimax": ("minimax-h3-lite", "480P")}


def _probe(video: Path) -> str:
    """ffprobe 看实际宽高与是否带音轨；没装 ffprobe 时说明一下。"""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return "（本机没有 ffprobe，无法判断音轨与宽高）"
    v = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip()
    a = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip()
    return f"实际宽高 {v.replace(',', '×') or '读不出'} · {'带音轨' if a else '不带音轨'}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="视频厂商真实冒烟（花钱）")
    ap.add_argument("--provider", choices=sorted(DEFAULTS), default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--resolution", default=None)
    ap.add_argument("--out", default="/tmp/video-smoke")
    ap.add_argument("--yes", action="store_true", help="不再询问，直接提交")
    ap.add_argument("--style", default=None, help="风格参考图路径（可选）")
    a = ap.parse_args(argv)
    name = a.provider or default_video_name()
    if name not in DEFAULTS:
        print(f"冒烟只支持 {'、'.join(sorted(DEFAULTS))}，当前缺省为 {name}；用 --provider 指定")
        return 1
    model = a.model or DEFAULTS[name][0]
    resolution = a.resolution or DEFAULTS[name][1]
    style = None
    if a.style:
        sp = Path(a.style)
        style = {"source": compose.data_uri(sp), "hash": hashlib.sha256(sp.read_bytes()).hexdigest()}

    vp = get_video(name)
    caps = vp.caps(model)
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    session = {"provider": name, "model": model, "resolution": resolution, "audio_mode": "tts_all"}
    clip = compose.build_clips(doc, caps, provider=name, model=model, resolution=resolution,
                               audio_mode="tts_all", keyframes={}, rewrite=vp.rewrite_prompt, style=style)[0]
    req, _ = compose.request_for(doc, session, clip, keyframes={}, relay_frame=None, caps=caps,
                                 rewrite=vp.rewrite_prompt, style=style)
    req.duration = caps.min_clip_sec               # 冒烟只出最短的一条
    req.images = len(req.refs) + (1 if req.first_frame else 0)
    est = base.estimate_cny(req.duration, caps, resolution, req.images)
    print("厂商：", name)
    print(req.prompt, "\n")
    print("风格图：", clip.get("style"))
    print(f"{model} · {resolution} · {base.request_seconds(req.duration, caps)} 秒 · {req.images} 张图 · "
          f"预估 ¥{est:.2f}（冒烟上限 ¥{LIMIT_CNY:g}）")
    if est > LIMIT_CNY:
        print("超出冒烟上限，不提交")
        return 1
    if not a.yes and input("提交？[y/N] ").strip().lower() != "y":
        return 1

    Path(a.out).mkdir(parents=True, exist_ok=True)  # 下载不建上级目录，先建好再花钱
    tid = vp.submit(req)
    print("任务：", tid)
    while True:
        time.sleep(10)
        st = vp.poll(tid)
        print("状态：", st.status, flush=True)
        if st.status in ("succeeded", "failed"):
            break
    if st.status == "failed":
        print("失败：", st.error)
        return 1
    files = vp.download(st, Path(a.out) / f"{clip['id']}.mp4")
    print("视频：", files["video"], "（可播放）" if base.is_playable_mp4(files["video"]) else "（不可播放！）")
    print("成片：", _probe(files["video"]))
    print("尾帧：", files["last_frame"])
    print("用量：", st.usage, f"→ 折算 ¥{vp.cost(st, req):.2f}，请与控制台账单核对")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 改 README 出片一节**

把「**出片（视频生成，后端）**」那段开头改为（其余句子保留，Seedance 的费率说明改为「Seedance 费率为 2026-10 刊例价……」放在厂商列表里）：

```markdown
**出片（视频生成，后端）**：两家厂商并存，在出片设置里切换。`backend/.env` 写密钥：
- `MINIMAX_API_KEY=…`（MiniMax 海螺 H3，**缺省厂商**）；可选 `STORYBOARD_MINIMAX_BASE_URL`（缺省 `https://api.minimax.cn`，为国际站预留）、`STORYBOARD_MINIMAX_PRICE_SCALE`（按账单校准单价的系数）、`STORYBOARD_MINIMAX_NATIVE_AUDIO=1`（真跑确认成片带原声后再开，开前只给「全部配音」「静音」）。费率为 2026-11 刊例价（H3 768P 0.50、2K 0.80 元/秒；Highspeed、Lite 更便宜；每段前 5 张参考图免费，超出每张 0.20 元，Lite 0.13 元），未经账单核对。MiniMax 不返回尾帧，下载后用 ffmpeg 截取供下一段接力；参考图超出尺寸或比例限制时用 ffmpeg 补边缩放后再发。
- `ARK_API_KEY=…`（火山方舟 Seedance）。没配 MiniMax 而配了方舟时，新建的出片会话缺省用 Seedance，出片设置里会提示。

`STORYBOARD_VIDEO_PROVIDER` 可显式指定缺省厂商（`fake` 为不联网的假厂商，本地演示用）。已有的出片会话保持原厂商，不迁移。
```

并把「结果地址 24 小时有效」改为「结果地址限时有效」，冒烟命令改为 `.venv/bin/python -m render.smoke [--provider minimax|seedance]`。

- [ ] **Step 3: 静态检查**

```bash
cd backend && .venv/bin/python -c "import render.smoke" && .venv/bin/python -m render.smoke --help
```
Expected：打印帮助，含 `--provider {minimax,seedance}`。然后跑后端全量回归。

- [ ] **Step 4: 提交**

```bash
git add backend/render/smoke.py README.md
git commit -m "冒烟脚本支持两家厂商：--provider 缺省与新建出片会话一致，档位与分辨率按厂商取最便宜的，预估计入图片费，输出成片实际宽高与是否带音轨；README 出片一节写明 MiniMax 为缺省厂商、各配置项与回落规则"
```

---

## 实施裁定

1. **图片张数的唯一口径**：预估一律 `compose.image_count(item)`；实际记账用提交时 `len(req.refs) + (1 if req.first_frame else 0)` 写进尝试的 `images`，`cost` 优先厂商 `usage.input_image_count`。旧尝试没有 `images` 字段时按 0 张计（只影响 MiniMax，旧尝试都是 Seedance 出的）。
2. **合成尺寸取厂商短边表的位置**：放在 `mix._size(s, doc)`，通过 `get_video(s["provider"]).caps(s["model"]).short_side` 取；取不到（厂商未注册、缺密钥）时为空表、回落 `SHORT_SIDE`。Seedance 与假厂商短边表为空，尺寸与合成指纹不变。
3. **`names()` 不再调用 `default_video_name()`**：假厂商只在 `STORYBOARD_VIDEO_PROVIDER == "fake"` 时出现。这与旧语义等价（假厂商只能被显式设为默认），并避免列出厂商时去读 `.env`。
4. **错误码归一**：`code` / `type` / `base_resp.status_code` 统一成数字字符串；`type` 别名（`insufficient_balance_error`→1008、`authorized_error`→1004、`rate_limit_error`→1002）与说明里的「(1026)」都能识别。2xx 内的 1002（限流）按瞬时错误可重试，因为限流时厂商没建任务。
5. **422 一律按审核提示**：spec 把 422 与 1026 并列；422 带其它码时，若码在 `MSG` 里用对应提示，否则按「码：说明」原文（`_reject` 先看码再看 HTTP 状态）。
6. **下载重查**：重查本身遇到瞬时错误时向上抛 `TransientError`（runner 下一轮再试，不消耗结果）；遇到明确错误或仍没有地址才报「已过期且重新查询失败」。
7. **请求体体积**：按「文本 UTF-8 字节 + 各图片地址字符串长度」估算，超过 60MB 报错，不自动压缩。
8. **ref 模式里的首帧标签**：`RefImage.role == "first_frame"` 的那张在报错里写「首帧」，其余写「参考图 <资产 id>」，方便用户定位是哪张图。
9. **`plan_normalize` 的取整**：缩放结果取偶数并夹在 5760 以内；补边一律向上取偶数，保证补边后比例落回 [0.4, 2.5]、两边都 ≥ 256。
10. **冒烟脚本的厂商范围**：`--provider` 只接受 `minimax`、`seedance`；缺省厂商为其它（如显式设成 fake）时提示用 `--provider` 指定后退出。
11. **前端只改一行**：`default_note` 由后端给文字，不加 i18n 键；声音模式下拉本来读 `options.audio_modes`，前端测试里写死四种模式的 fixture（`film.test`、`compose.test`、`graph-view.test`）是假会话的数据，不需要改。
12. **`resolve_settings` 新建会话时**（`old is None`）若缺省 `tts_all` 不在可选里（不会发生，`tts_all` 恒可选）也回落 `tts_all`，作为兜底分支一并处理。
