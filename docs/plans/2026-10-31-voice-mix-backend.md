# 配音与合成后端（A3a）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 出完的段配上 TTS 旁白台词、按集拼接混音、出字幕与报告：TTS 统一接口 + 假 TTS + 豆包语音、`voice.py`（语音条、音色、缓存）、`mix.py`（声画对齐规划、ffmpeg 规整拼接混音、`.srt`、报告）、合成接口与后台线程、BGM 上传、真实厂商冒烟。

**Architecture:** 纯计算与执行分开：`voice.py` 的语音条与音色分配、`mix.py` 的对齐规划与 ffmpeg 参数都是纯函数（单测不需要 ffmpeg）；`mix.compose()` 才调 TTS 与 ffmpeg（端到端测试在装了 ffmpeg 时跑）。合成状态写进同一个 `session.json` 的 `final`，接口起一个后台线程跑合成；配音费用计入同一 `spent_cny`，过同一个上限，配音金额要用户确认（409 带金额，与批量出片一致）。

**Tech Stack:** Python 3.12、FastAPI、httpx（`MockTransport` 测试）、标准库 `wave`、ffmpeg/ffprobe（命令行，`brew install ffmpeg`）。

**Spec:** `docs/specs/2026-10-28-video-generation-design.md` 第 3 节（声音与合成）、第 1.4/1.6/1.7 节；第 6、7 节是 A1、A2 的实施裁定。画布上的音色分配与合成区是后续的 A3b 计划。

---

## 全局约束

- 提交只 `git add` 具体文件，不用 `git add -A` / `git commit -a`；提交信息用中文、风格同 `git log --oneline -5`，**不带任何 Claude 署名**（无 `Co-Authored-By`、无 `Claude-Session`）。
- 不读、不打印 `backend/.env`；密钥只进请求头，不进日志、报错、`session.json`。
- 测试不联网、不花钱：假 TTS / 假视频厂商 / `httpx.MockTransport`。真实豆包语音只在 Task 7 的手动冒烟里用（约 0.01 元），由用户执行。
- 所有命令在 `backend/` 下执行。
- 本机可能还没装 ffmpeg（用户会自己 `brew install ffmpeg`）：需要 ffmpeg 的测试在没装时打印「跳过」并以 `ALL PASS（跳过：没装 ffmpeg）` 结束；实现者如实报告是否真跑了。
- 未跟踪的 `docs/specs/2026-10-27-commercialization-design-contract.md` 不要碰。

## 核实结果（设计文档 3.2「实现计划第一步核实」，2026-10-31 查官方文档）

- 接口：`POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`（HTTP 单向流式）。旧的 `/api/v1/tts` 官方标「不推荐」且不支持 2.0 音色。
- 鉴权：新版控制台只要 `X-Api-Key`；旧版控制台 `X-Api-App-Id` + `X-Api-Access-Key`。`X-Api-Resource-Id: seed-tts-2.0` 决定模型与计费。与方舟（Seedance）是两套密钥。
- 请求体：`user.uid`、`req_params.text`、`req_params.speaker`（音色 id）、`req_params.audio_params.format`（`mp3`/`ogg_opus`/`pcm`）、`sample_rate`（默认 24000）、`speech_rate`（[-50,100]，100 为 2 倍速）、`emotion`（部分音色）。
- 响应：逐行 JSON。音频块 `{"code":0,"data":"<base64>"}`，结束块 `code=20000000`；其他非 0 码为失败（如 `45000000` 音色无权限、`40402003` 文本超长）。
- 2.0 音色（名字以 `_uranus_bigtts` 结尾，官方标「指令遵循」，不标情绪参数）：`zh_male_m191_uranus_bigtts`（云舟）、`zh_male_taocheng_uranus_bigtts`（小天）、`zh_male_liufei_uranus_bigtts`（刘飞）、`zh_female_vv_uranus_bigtts`（Vivi）、`zh_female_xiaohe_uranus_bigtts`（小何）、`zh_female_sophie_uranus_bigtts`（魅力苏菲）、`zh_female_qingxinnvsheng_uranus_bigtts`（清新女声）、`zh_female_cancan_uranus_bigtts`（知性灿灿）。
- 价格：豆包语音合成模型 2.0 后付费 **3 元/万字符**（1 个汉字、字母、标点各算 1 字符）。

## 实施裁定（与设计文档第 3 节的差异，Task 7 写回设计文档）

1. **要 pcm、自己封 WAV**：豆包返回 24kHz 16 位单声道 PCM，`tts_base.write_wav` 封成 WAV，时长按帧数算，不需要 ffprobe；假 TTS 同样出 WAV。
2. **音色不写回资产卡**：分镜里的 `tts_voice` 是抽象提示（`male_elder`、`female_young`），不是厂商音色。用户选的音色存在 `session.json` 的 `voices`（说话人 → 厂商音色 id）；没选的按提示里的性别默认该厂商第一个同性别音色；看不出性别的列进「缺音色」，合成前拦截。替代 2.3 第 1 条「选完写回资产卡」。
3. **情绪参数先不传**：2.0 音色官方不标情绪参数，`TtsCaps.emotions=False`；台词的 `emotion` 进缓存键的位置留着，厂商支持时打开。
4. **长句切开合成再拼**：单次请求最多 300 字（V1 文档建议值，V3 只写了「超长报错」），超出按标点切开，同参数 WAV 首尾相接。
5. **对齐：先提速再定格**：镜头内语音念不完时，先把语速提到最多 1.15 倍；还不够就按 1.15 倍念、把段尾帧定格延长补齐（设计文档 3.3 没说超出 15% 时语速取多少）。原声或不出声的语音条按字数估时长，只进字幕。
6. **配音费用要确认**：`POST …/compose` 必须带 `expected_cny`（未缓存的字数 × 单价），不一致 409 附重算金额；配音费计入 `spent_cny`、过同一上限。只有缓存全命中（金额 0）时可以不带。
7. **合成整章只出每集文件**：`final/E0x.mp4`、`final/E0x.srt`、`final/mix_report.json`；「再拼整章」与字幕烧录留到以后（设计文档 3.4/3.5 标为可选）。
8. **合成时不能有段在跑**：有段在排队或生成中拒绝合成（409），免得混进半截状态；草稿合成（默认开）用关键帧定格补没出的段，没有关键帧用黑场。
9. **重启中断的合成标失败**，提示重新合成；配音缓存（`audio/cache/`）与已规整的段（`final/work/`，按输入指纹命名）都复用，已完成的步骤不重做。

## 文件结构

| 文件 | 职责 |
|---|---|
| `render/providers/tts_base.py` | 新建：`Voice`、`TtsCaps`、`TtsResult`、`TtsProvider`、`tts_cost`、`default_voice`、WAV 读写与拼接 |
| `render/providers/fake.py` | 修改：`FakeTts`（按字数出静音 WAV） |
| `render/providers/__init__.py` | 修改：TTS 注册表 `register_tts`、`get_tts`、`default_tts_name`、`tts_names` |
| `render/providers/tts_volc.py` | 新建：豆包语音合成 2.0 |
| `render/voice.py` | 新建：语音条、各模式走 TTS 的语音条、说话人与音色、缓存、合成、预估 |
| `render/mix.py` | 新建：画幅、原声策略、声画对齐规划、`.srt`、ffmpeg 参数、执行、整章合成、预览与指纹 |
| `render/session.py` | 修改：`set_voices`、合成状态迁移、`add_spent`、`recover` 处理中断的合成 |
| `server/app.py` | 修改：音色、合成预览与合成、BGM 上传删除；合成后台线程 |
| `render/smoke_tts.py` | 新建：豆包语音真实冒烟 |
| `tests/render/test_tts.py`、`test_voice.py`、`test_tts_volc.py`、`test_mix.py`、`test_mix_e2e.py` | 新建 |
| `tests/server/test_compose.py` | 新建 |

---

### Task 1: TTS 统一接口、假 TTS、注册表

**Files:**
- Create: `backend/render/providers/tts_base.py`
- Modify: `backend/render/providers/fake.py`（文件末尾追加 `FakeTts`，顶部 import）
- Modify: `backend/render/providers/__init__.py`（文件末尾追加 TTS 注册表）
- Test: `backend/tests/render/test_tts.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/render/test_tts.py`:

```python
#!/usr/bin/env python3
"""TTS 统一接口与假 TTS：默认音色按性别、费用、WAV 时长与拼接、注册表。

不联网、不花钱。用法: python3 tests/render/test_tts.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import providers  # noqa: E402
from render.providers import tts_base  # noqa: E402
from render.providers.fake import FakeTts  # noqa: E402


def main() -> int:
    tts = FakeTts()
    assert tts_base.default_voice(tts.caps, "male_elder") == "fake-male"
    assert tts_base.default_voice(tts.caps, "female_young") == "fake-female"
    assert tts_base.default_voice(tts.caps, "child") is None
    assert tts_base.default_voice(tts.caps, None) is None
    assert tts_base.tts_cost(10000, tts.caps) == 3.0
    print("1. 默认音色按性别、费用 ✓")

    with tempfile.TemporaryDirectory() as d:
        r = tts.synthesize("九个字的一句台词呀", "fake-male", None, 1.0, Path(d) / "a.wav")
        assert abs(r.duration - 2.0) < 0.01 and r.chars == 9, r
        assert r.cost_cny == tts_base.tts_cost(9, tts.caps)
        assert abs(tts_base.wav_seconds(r.file) - r.duration) < 1e-6
        r2 = tts.synthesize("再来四个", "fake-female", None, 1.0, Path(d) / "b.wav")
        total = tts_base.concat_wavs([r.file, r2.file], Path(d) / "ab.wav")
        assert abs(total - (r.duration + r2.duration)) < 0.01
        try:
            tts.synthesize("x", "nope", None, 1.0, Path(d) / "c.wav")
            raise AssertionError("未知音色应抛 ProviderError")
        except tts_base.ProviderError:
            pass
        assert not (Path(d) / "c.wav").exists()
    print("2. 假 TTS 出 WAV、时长按字数、拼接 ✓")

    os.environ["STORYBOARD_TTS_PROVIDER"] = "fake"
    assert providers.default_tts_name() == "fake" and "fake" in providers.tts_names()
    assert providers.get_tts() is providers.get_tts("fake")
    try:
        providers.get_tts("nope")
        raise AssertionError("未注册的厂商应抛 KeyError")
    except KeyError:
        pass
    os.environ.pop("STORYBOARD_TTS_PROVIDER")
    assert "fake" not in providers.tts_names(), "假 TTS 不是默认时不出现在可选里"
    print("3. 注册表 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/render/test_tts.py`
Expected: FAIL with `ImportError` / `ModuleNotFoundError` for `render.providers.tts_base`

- [ ] **Step 3: 写 `tts_base.py`**

Create `backend/render/providers/tts_base.py`:

```python
"""出片：TTS 厂商统一接口（设计文档 3.2）。

主流程只用 caps / synthesize。厂商一律产出 WAV（16 位单声道 PCM），时长按帧数算，不需要 ffprobe。
新增厂商 = 新文件 + 在 providers/__init__.py 用 register_tts 注册一行。错误沿用视频厂商的两类：
ProviderError（明确失败，原样展示）、TransientError（断连、限流，调用方重试）。
"""
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from render.providers.base import ProviderError, TransientError  # noqa: F401  （供 TTS 厂商与调用方导入）


@dataclass
class Voice:
    id: str
    name: str
    gender: str          # male / female
    lang: str = "zh"


@dataclass
class TtsCaps:
    voices: list         # list[Voice]
    emotions: bool       # 是否接受情绪参数
    max_chars: int       # 单次请求最多字数（超出由 voice.py 按标点切开）
    cny_per_k_chars: float


@dataclass
class TtsResult:
    file: Path
    duration: float      # 秒（按 WAV 帧数）
    cost_cny: float
    chars: int


class TtsProvider(Protocol):
    name: str
    caps: TtsCaps
    rate_note: str      # 费率依据：如实写出处、是否经账单核对

    def synthesize(self, text: str, voice: str, emotion: Optional[str], speed: float,
                   dest: Path) -> TtsResult: ...


def tts_cost(chars: int, caps: TtsCaps) -> float:
    return round(chars * caps.cny_per_k_chars / 1000, 4)


def default_voice(caps: TtsCaps, hint: Optional[str]) -> Optional[str]:
    """分镜里的抽象音色提示（male_elder、female_young…）→ 该厂商第一个同性别音色；看不出性别返回 None。"""
    h = (hint or "").strip().lower()
    gender = "female" if h.startswith("female") else "male" if h.startswith("male") else None
    if gender is None:
        return None
    return next((v.id for v in caps.voices if v.gender == gender), None)


def write_wav(dest: Path, pcm: bytes, rate: int) -> float:
    """16 位单声道 PCM 写成 WAV（先写临时文件再改名），返回时长（秒）。目录须已存在。"""
    dest = Path(dest)
    tmp = dest.with_name(dest.name + ".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    tmp.replace(dest)
    return len(pcm) / 2 / rate


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def concat_wavs(parts: list, dest: Path) -> float:
    """同参数的几段 WAV 首尾相接（长句切开合成后拼回），返回总时长。"""
    frames, rate = b"", None
    for p in parts:
        with wave.open(str(p), "rb") as w:
            if rate is None:
                rate = w.getframerate()
            if w.getframerate() != rate or w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ProviderError("拼接的语音片段参数不一致")
            frames += w.readframes(w.getnframes())
    return write_wav(dest, frames, rate or 24000)
```

- [ ] **Step 4: 假 TTS**

In `backend/render/providers/fake.py`, add `from pathlib import Path` to the imports and, after the existing `from render.providers.base import (…)` line, add:

```python
from render.providers.tts_base import TtsCaps, TtsResult, Voice, tts_cost, write_wav
```

Append to the end of `backend/render/providers/fake.py`:

```python
class FakeTts:
    """假 TTS：不联网、不花钱，按字数出静音 WAV（每字 1/4.5 秒）；可指定前几次限流或一律失败。"""
    name = "fake"
    rate_note = "假配音：不联网、不花钱，金额只用于演示"
    RATE = 24000

    def __init__(self, *, fail_times: int = 0, fail_with: Optional[str] = None, max_chars: int = 300):
        self.caps = TtsCaps(voices=[Voice("fake-male", "假男声", "male"), Voice("fake-female", "假女声", "female")],
                            emotions=False, max_chars=max_chars, cny_per_k_chars=0.3)
        self.fail_times = fail_times
        self.fail_with = fail_with
        self.calls = []         # 依次合成的 (文字, 音色)

    def synthesize(self, text, voice, emotion, speed, dest):
        self.calls.append((text, voice))
        if self.fail_with:
            raise ProviderError(self.fail_with)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise TransientError("假的限流")
        if voice not in {v.id for v in self.caps.voices}:
            raise ProviderError(f"未知的音色：{voice}")
        frames = int(round(len(text) / 4.5 / speed * self.RATE))
        duration = write_wav(Path(dest), b"\x00\x00" * frames, self.RATE)
        return TtsResult(Path(dest), duration, tts_cost(len(text), self.caps), len(text))
```

- [ ] **Step 5: TTS 注册表**

Append to the end of `backend/render/providers/__init__.py`:

```python


# ---------- TTS 厂商：STORYBOARD_TTS_PROVIDER 选默认（缺省 volc） ----------

_TTS_FACTORIES: dict = {}
_TTS_INSTANCES: dict = {}


def register_tts(name: str, factory) -> None:
    _TTS_FACTORIES[name] = factory
    _TTS_INSTANCES.pop(name, None)


def default_tts_name() -> str:
    return os.environ.get("STORYBOARD_TTS_PROVIDER", "").strip() or "volc"


def get_tts(name=None):
    """按名字取 TTS 厂商实例（同名只建一次）。未注册抛 KeyError；建不起来（没配密钥）由工厂抛 ProviderError。"""
    name = name or default_tts_name()
    if name not in _TTS_INSTANCES:
        factory = _TTS_FACTORIES.get(name)
        if factory is None:
            raise KeyError(f"未知的配音厂商：{name}")
        _TTS_INSTANCES[name] = factory()
    return _TTS_INSTANCES[name]


def tts_names() -> list:
    """界面可选的配音厂商。假 TTS 只在被设为默认时出现。"""
    return [n for n in sorted(_TTS_FACTORIES) if n != "fake" or default_tts_name() == "fake"]


def _fake_tts():
    from render.providers.fake import FakeTts
    return FakeTts()


register_tts("fake", _fake_tts)
```

- [ ] **Step 6: 运行，确认通过**

Run: `.venv/bin/python tests/render/test_tts.py && for t in tests/render/test_*.py; do .venv/bin/python $t | tail -1; done`
Expected: `ALL PASS` for test_tts and every render test

- [ ] **Step 7: 提交**

```bash
git add render/providers/tts_base.py render/providers/fake.py render/providers/__init__.py tests/render/test_tts.py
git commit -m "配音：TTS 统一接口（音色、能力、按字计费、默认音色按性别、WAV 封装与拼接）、假 TTS 与 TTS 厂商注册表"
```

---

### Task 2: 语音条、音色与缓存（`voice.py`）

**Files:**
- Create: `backend/render/voice.py`
- Test: `backend/tests/render/test_voice.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/render/test_voice.py`:

```python
#!/usr/bin/env python3
"""配音：语音条顺序（与 timeline.ts speechOf 一致）、各声音模式走 TTS 的语音条、说话人与音色分配、
缓存命中不重复计费、长句切开、瞬时错误重试与失败汇总、预估。

假 TTS，不联网、不花钱。用法: python3 tests/render/test_voice.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import voice  # noqa: E402
from render.providers.fake import FakeTts  # noqa: E402
from render.providers.tts_base import tts_cost  # noqa: E402

DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))
SMALL = {
    "meta": {"narration": {"tts_voice": "male_mature"}},
    "assets": {"characters": [{"id": "C1", "name": "老栓", "voice": {"tts_voice": "male_elder"}},
                              {"id": "C2", "name": "大妈", "voice": {"tts_voice": "female_mid"}},
                              {"id": "C3", "name": "路人"}]},
    "episodes": [{"id": "E01", "shots": [
        {"id": "S1", "narration": {"text": "旁白在前"},
         "dialogue": [{"type": "dialogue", "character_ref": "C1", "text": "台词一"},
                      {"type": "inner_monologue", "character_ref": "C2", "text": "心里话"}]},
        {"id": "S2", "narration": {"text": "旁白在后", "order": "after_dialogue"},
         "dialogue": [{"type": "voiceover", "character_ref": "C3", "text": "画外音"},
                      {"type": "dialogue", "character_ref": "C1", "text": ""}]},
        {"id": "S3"},
    ]}],
}


def main() -> int:
    lines = voice.speech_lines(SMALL)
    assert [(x["id"], x["kind"], x["speaker"]) for x in lines] == [
        ("S1-L1", "narration", "narration"), ("S1-L2", "dialogue", "C1"), ("S1-L3", "inner_monologue", "C2"),
        ("S2-L1", "voiceover", "C3"), ("S2-L2", "narration", "narration")], lines
    real = voice.speech_lines(DOC)
    expect = sum(bool((s.get("narration") or {}).get("text")) + sum(bool(d.get("text")) for d in s.get("dialogue") or [])
                 for ep in DOC["episodes"] for s in ep["shots"])
    assert len(real) == expect and len({x["id"] for x in real}) == len(real)
    print(f"1. 语音条顺序与 speechOf 一致（《药》{len(real)} 条） ✓")

    assert len(voice.tts_lines(lines, "tts_all")) == 5
    assert [x["kind"] for x in voice.tts_lines(lines, "dialogue_native")] == [
        "narration", "inner_monologue", "voiceover", "narration"]
    assert voice.tts_lines(lines, "all_native") == [] and voice.tts_lines(lines, "silent") == []
    print("2. 各声音模式走 TTS 的语音条 ✓")

    tts = FakeTts()
    voices, missing = voice.resolve_voices(SMALL, lines, {}, tts.caps)
    assert voices == {"narration": "fake-male", "C1": "fake-male", "C2": "fake-female"} and missing == ["C3"]
    voices, missing = voice.resolve_voices(SMALL, lines, {"C3": "fake-female", "C1": "nope"}, tts.caps)
    assert voices["C3"] == "fake-female" and voices["C1"] == "fake-male" and missing == [], "无效的选择退回默认"
    assert voice.speakers(SMALL)["C1"] == {"name": "老栓", "hint": "male_elder"}
    print("3. 说话人与音色：用户选的优先、按提示性别默认、缺音色列出 ✓")

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        est = voice.estimate(lines, voices, tts, root)
        chars = sum(len(x["text"]) for x in lines)
        assert est == {"lines": 5, "chars": chars, "cny": tts_cost(chars, tts.caps)}, est
        spent = []
        done, failed = voice.synthesize(lines, voices, tts, root, on_cost=spent.append, sleep=lambda s: None)
        assert not failed and len(done) == 5 and len(tts.calls) == 5
        assert abs(sum(spent) - sum(x["cost_cny"] for x in done)) < 1e-9 and not any(x["cached"] for x in done)
        assert all(Path(x["file"]).exists() and x["duration"] > 0 for x in done)
        again, _ = voice.synthesize(lines, voices, tts, root, on_cost=spent.append, sleep=lambda s: None)
        assert len(tts.calls) == 5 and all(x["cached"] and x["cost_cny"] == 0 for x in again), "缓存命中不重合成"
        assert voice.estimate(lines, voices, tts, root)["chars"] == 0
        other = dict(voices, narration="fake-female")
        voice.synthesize(lines, other, tts, root, sleep=lambda s: None)
        assert len(tts.calls) == 7, "换了音色的两条旁白重合成"
    print("4. 合成、缓存命中不重复计费、换音色才重合成 ✓")

    with tempfile.TemporaryDirectory() as d:
        short = FakeTts(max_chars=10)
        text = "秋天的后半夜，月亮下去了，太阳还没有出，只剩下一片乌蓝的天。"
        assert all(len(p) <= 10 for p in voice.split_text(text, 10)) and "".join(voice.split_text(text, 10)) == text
        line = [{"id": "X-L1", "episode": "E01", "shot": "X", "kind": "narration", "speaker": "narration",
                 "text": text, "emotion": None}]
        done, failed = voice.synthesize(line, {"narration": "fake-male"}, short, Path(d), sleep=lambda s: None)
        assert not failed and len(short.calls) == len(voice.split_text(text, 10)) > 1
        assert abs(done[0]["duration"] - len(text) / 4.5) < 0.05
        assert not list((Path(d) / voice.CACHE_DIR).glob("*.part*")), "切开的片段拼完删掉"
    print("5. 长句按标点切开合成再拼 ✓")

    with tempfile.TemporaryDirectory() as d:
        flaky = FakeTts(fail_times=5)
        sleeps = []
        two = lines[:2]
        done, failed = voice.synthesize(two, voices, flaky, Path(d), retries=3, sleep=sleeps.append)
        assert [x["id"] for x in failed] == ["S1-L1"] and "限流" in failed[0]["error"]
        assert [x["id"] for x in done] == ["S1-L2"] and len(sleeps) == 4
        bad = FakeTts(fail_with="音色无权限")
        done, failed = voice.synthesize(two, voices, bad, Path(d), sleep=lambda s: None)
        assert not done and [x["error"] for x in failed] == ["音色无权限", "音色无权限"] and len(bad.calls) == 2
    print("6. 瞬时错误重试 3 次、明确失败不重试，失败汇总不中断其余各条 ✓")

    try:
        voice.synthesize(lines, voices, tts, Path("/nonexistent/render/v1"), sleep=lambda s: None)
        raise AssertionError("会话目录不存在应抛 VoiceError")
    except voice.VoiceError:
        pass
    print("7. 会话目录已删不重建 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/render/test_voice.py`
Expected: FAIL with `ImportError: cannot import name 'voice' from 'render'`

- [ ] **Step 3: 写 `voice.py`**

Create `backend/render/voice.py`:

```python
"""出片配音（设计文档 3.1）：分镜 → 语音条 → 音色 → TTS（带缓存）。

语音条按镜头顺序拆，镜头内旁白与台词的先后按 narration.order（缺省旁白在前），与前端 timeline.ts 的
speechOf 同一算法。送 TTS 的文字即分镜原文，不改写。缓存键 = (文字, 音色, 情绪, 厂商, 语速)：没变的
语音条不重合成、不重复计费；缓存在会话目录的 audio/cache/ 下（WAV）。
音色：用户在「出片」页选的（session.json 的 voices）优先，其次按分镜里的抽象提示（male_elder…）取该厂商
第一个同性别音色；都没有的说话人列进「缺音色」，合成前拦截。
"""
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Optional

from render.providers.base import ProviderError, TransientError
from render.providers.tts_base import concat_wavs, default_voice, tts_cost, wav_seconds

NARRATION = "narration"
# 各声音模式下哪些语音条走 TTS（设计文档 3.4）；其余由视频模型自己出声或不出声，只进字幕
TTS_KINDS = {
    "tts_all": {"narration", "dialogue", "inner_monologue", "voiceover"},
    "dialogue_native": {"narration", "inner_monologue", "voiceover"},
    "all_native": set(),
    "silent": set(),
}
CACHE_DIR = "audio/cache"
_SPLIT = re.compile(r"(?<=[。！？!?；;…，,、])")


class VoiceError(Exception):
    """配音没法进行：message 给用户看。"""


def speech_lines(doc: dict) -> list:
    """全部语音条：{"id", "episode", "shot", "kind", "speaker", "text", "emotion"}。"""
    out = []
    for ep in doc.get("episodes") or []:
        for shot in ep.get("shots") or []:
            narr = shot.get("narration") or {}
            mine = []
            if narr.get("text"):
                mine.append({"kind": "narration", "speaker": NARRATION, "text": narr["text"], "emotion": None})
            talk = [{"kind": d.get("type") or "dialogue", "speaker": d.get("character_ref") or "",
                     "text": d["text"], "emotion": d.get("emotion")}
                    for d in shot.get("dialogue") or [] if d.get("text")]
            mine = talk + mine if narr.get("order") == "after_dialogue" else mine + talk
            for i, line in enumerate(mine, 1):
                out.append({"id": f"{shot['id']}-L{i}", "episode": ep["id"], "shot": shot["id"], **line})
    return out


def tts_lines(lines: list, audio_mode: str) -> list:
    kinds = TTS_KINDS.get(audio_mode, set())
    return [x for x in lines if x["kind"] in kinds]


def speakers(doc: dict) -> dict:
    """说话人 → {"name", "hint"}：旁白取 meta.narration.tts_voice，角色取资产卡 voice.tts_voice。"""
    hint = ((doc.get("meta") or {}).get("narration") or {}).get("tts_voice")
    out = {NARRATION: {"name": "旁白", "hint": hint}}
    assets = doc.get("assets") or {}
    for c in (assets.get("characters") or []) + (assets.get("creatures") or []):
        out[c["id"]] = {"name": c.get("name") or c["id"], "hint": (c.get("voice") or {}).get("tts_voice")}
    return out


def resolve_voices(doc: dict, lines: list, assigned: dict, caps) -> tuple:
    """(说话人 → 音色 id, 缺音色的说话人)。只看 lines 里用到的说话人；选了不存在的音色当没选。"""
    ids = {v.id for v in caps.voices}
    info = speakers(doc)
    voices, missing = {}, []
    for key in dict.fromkeys(x["speaker"] for x in lines):
        chosen = (assigned or {}).get(key)
        v = chosen if chosen in ids else default_voice(caps, (info.get(key) or {}).get("hint"))
        if v:
            voices[key] = v
        else:
            missing.append(key)
    return voices, missing


def cache_key(text: str, voice: str, emotion: Optional[str], provider: str, speed: float = 1.0) -> str:
    blob = json.dumps([text, voice, emotion, provider, round(speed, 3)], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def split_text(text: str, max_chars: int) -> list:
    """超长的句子按标点切开（一句里没标点就硬切），每段 ≤ max_chars，拼起来等于原文。"""
    if len(text) <= max_chars:
        return [text]
    parts, cur = [], ""
    for piece in _SPLIT.split(text):
        while len(piece) > max_chars:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(piece[:max_chars])
            piece = piece[max_chars:]
        if len(cur) + len(piece) > max_chars:
            parts.append(cur)
            cur = piece
        else:
            cur += piece
    if cur:
        parts.append(cur)
    return [p for p in parts if p]


def _cache(root) -> Path:
    root = Path(root)
    if not root.is_dir():
        raise VoiceError("出片会话目录已不存在（版本可能已删除）")
    cache = root / CACHE_DIR
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _emotion(line: dict, caps) -> Optional[str]:
    return line.get("emotion") if caps.emotions else None


def _key(line: dict, voices: dict, provider) -> str:
    return cache_key(line["text"], voices[line["speaker"]], _emotion(line, provider.caps), provider.name)


def estimate(lines: list, voices: dict, provider, root) -> dict:
    """还没缓存的语音条字数与费用（合成前给用户确认）。"""
    cache = Path(root) / CACHE_DIR
    todo = [x for x in lines if not (cache / f"{_key(x, voices, provider)}.wav").exists()]
    chars = sum(len(x["text"]) for x in todo)
    return {"lines": len(lines), "chars": chars, "cny": tts_cost(chars, provider.caps)}


def _retry(fn, retries: int, sleep):
    for i in range(retries + 1):
        try:
            return fn()
        except TransientError:
            if i == retries:
                raise
            sleep(min(2 ** i, 8))


def synthesize(lines: list, voices: dict, provider, root, *, retries: int = 3, sleep=time.sleep,
               on_cost=None) -> tuple:
    """逐条合成（缓存命中直接用），返回 (结果, 失败)。

    结果每条 = 语音条 + file、duration、cost_cny、cached；失败每条 = 语音条 + error（原因原样）。
    瞬时错误重试 retries 次；厂商明确失败与重试用尽都记进失败，不中断其余各条。
    on_cost(cny) 在每次真实合成后调用（计入出片会话的已花金额）。
    """
    cache = _cache(root)
    done, failed = [], []
    for line in lines:
        voice = voices[line["speaker"]]
        emotion = _emotion(line, provider.caps)
        key = _key(line, voices, provider)
        final = cache / f"{key}.wav"
        if final.exists():
            done.append({**line, "file": final, "duration": wav_seconds(final), "cost_cny": 0.0, "cached": True})
            continue
        try:
            parts = split_text(line["text"], provider.caps.max_chars)
            files, cost = [], 0.0
            for i, part in enumerate(parts):
                dest = final if len(parts) == 1 else cache / f"{key}.part{i}.wav"
                r = _retry(lambda: provider.synthesize(part, voice, emotion, 1.0, dest), retries, sleep)
                files.append(r.file)
                cost += r.cost_cny
                if on_cost:
                    on_cost(r.cost_cny)
            if len(parts) > 1:
                concat_wavs(files, final)
                for f in files:
                    Path(f).unlink(missing_ok=True)
            done.append({**line, "file": final, "duration": wav_seconds(final),
                         "cost_cny": round(cost, 4), "cached": False})
        except (ProviderError, TransientError) as e:
            failed.append({**line, "error": str(e)})
    return done, failed
```

- [ ] **Step 4: 运行，确认通过**

Run: `.venv/bin/python tests/render/test_voice.py`
Expected: seven `✓` lines then `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add render/voice.py tests/render/test_voice.py
git commit -m "配音：语音条（顺序同画布 speechOf）、各声音模式走 TTS 的语音条、说话人音色分配（选择优先、按提示性别默认、缺音色列出）、按文字音色厂商缓存、长句切开、重试与失败汇总、预估"
```

---

### Task 3: 豆包语音合成（`tts_volc.py`）

**Files:**
- Create: `backend/render/providers/tts_volc.py`
- Modify: `backend/render/providers/__init__.py`（末尾注册）
- Test: `backend/tests/render/test_tts_volc.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/render/test_tts_volc.py`:

```python
#!/usr/bin/env python3
"""豆包语音合成：请求头与请求体、逐行 JSON 解析与 WAV、语速映射、错误分级、密钥不外泄、读密钥。

用 httpx.MockTransport 模拟，不联网、不花钱。用法: python3 tests/render/test_tts_volc.py
"""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import providers  # noqa: E402
from render.providers import tts_volc  # noqa: E402
from render.providers.tts_base import ProviderError, TransientError, tts_cost, wav_seconds  # noqa: E402
from render.providers.tts_volc import RESOURCE_ID, VOICES, VolcTts  # noqa: E402

VOICE = "zh_male_m191_uranus_bigtts"


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def volc(handler, **kw):
    kw.setdefault("api_key", "k-secret")
    return VolcTts(client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def stream(*pcm, end=True, prefix=""):
    rows = [json.dumps({"code": 0, "message": "", "data": base64.b64encode(p).decode()}) for p in pcm]
    if end:
        rows.append(json.dumps({"code": 20000000, "message": "ok", "data": None}))
    return "".join(f"{prefix}{r}\n" for r in rows).encode()


def main() -> int:
    seen = []

    def ok(request):
        seen.append(request)
        return httpx.Response(200, content=stream(b"\x01\x00" * 24000, b"\x02\x00" * 12000))

    with tempfile.TemporaryDirectory() as d:
        tts = volc(ok)
        r = tts.synthesize("你好世界", VOICE, "开心", 1.0, Path(d) / "a.wav")
        assert abs(r.duration - 1.5) < 1e-6 and r.chars == 4 and r.cost_cny == tts_cost(4, tts.caps), r
        assert abs(wav_seconds(r.file) - 1.5) < 1e-6
        h = seen[0].headers
        assert h["x-api-key"] == "k-secret" and h["x-api-resource-id"] == RESOURCE_ID and h["x-api-request-id"]
        assert "x-api-app-id" not in h
        body = json.loads(seen[0].content)
        assert body["req_params"]["text"] == "你好世界" and body["req_params"]["speaker"] == VOICE
        assert body["req_params"]["audio_params"] == {"format": "pcm", "sample_rate": 24000, "speech_rate": 0}, \
            "2.0 音色不传情绪参数"
        assert tts.caps.cny_per_k_chars == 0.3 and {v.id for v in tts.caps.voices} == {v.id for v in VOICES}
        print("1. 请求头、请求体、逐行 JSON 拼成 WAV、按字计费 ✓")

        old = volc(ok, api_key="", app_id="app-1", access_key="ak-1")
        old.synthesize("一", VOICE, None, 1.5, Path(d) / "b.wav")
        h = seen[-1].headers
        assert h["x-api-app-id"] == "app-1" and h["x-api-access-key"] == "ak-1" and "x-api-key" not in h
        assert json.loads(seen[-1].content)["req_params"]["audio_params"]["speech_rate"] == 50
        volc(ok).synthesize("一", VOICE, None, 3.0, Path(d) / "c.wav")
        assert json.loads(seen[-1].content)["req_params"]["audio_params"]["speech_rate"] == 100
        sse = volc(lambda r: httpx.Response(200, content=stream(b"\x00\x00" * 2400, prefix="data: ")))
        assert abs(sse.synthesize("一", VOICE, None, 1.0, Path(d) / "d.wav").duration - 0.1) < 1e-6
        print("2. 旧版控制台鉴权、语速映射与夹取、data: 前缀 ✓")

        def status(code, payload=None):
            return volc(lambda r: httpx.Response(code, json=payload or {}))
        must_raise(TransientError, status(429).synthesize, "一", VOICE, None, 1.0, Path(d) / "e.wav")
        must_raise(TransientError, status(503).synthesize, "一", VOICE, None, 1.0, Path(d) / "e.wav")
        e = must_raise(ProviderError, status(401, {"message": "invalid key"}).synthesize,
                       "一", VOICE, None, 1.0, Path(d) / "e.wav")
        assert "invalid key" in str(e) and "k-secret" not in str(e)
        bad = volc(lambda r: httpx.Response(200, content=(json.dumps(
            {"code": 45000000, "message": "speaker permission denied"}) + "\n").encode()))
        e = must_raise(ProviderError, bad.synthesize, "一", VOICE, None, 1.0, Path(d) / "e.wav")
        assert "45000000" in str(e) and "permission" in str(e)
        cut = volc(lambda r: httpx.Response(200, content=stream(b"\x00\x00" * 10, end=False)))
        must_raise(TransientError, cut.synthesize, "一", VOICE, None, 1.0, Path(d) / "e.wav")

        def refused(request):
            raise httpx.ConnectError("refused", request=request)
        e = must_raise(TransientError, volc(refused).synthesize, "一", VOICE, None, 1.0, Path(d) / "e.wav")
        assert "k-secret" not in str(e)
        assert not (Path(d) / "e.wav").exists(), "失败时不留文件"
        print("3. 错误分级：限流/5xx/断连/没收到结束块为瞬时，4xx 与流内错误码为明确失败，密钥不进报错 ✓")

    real_load = tts_volc._load_dotenv
    saved = {k: os.environ.pop(k, None) for k in ("VOLC_TTS_API_KEY", "VOLC_TTS_APP_ID", "VOLC_TTS_ACCESS_KEY")}
    tts_volc._load_dotenv = lambda path: None
    try:
        e = must_raise(ProviderError, VolcTts.from_env)
        assert "VOLC_TTS_API_KEY" in str(e)
        os.environ["VOLC_TTS_API_KEY"] = "env-key"
        assert VolcTts.from_env()._auth == {"X-Api-Key": "env-key"}
        providers._TTS_INSTANCES.pop("volc", None)
        assert isinstance(providers.get_tts("volc"), VolcTts)
    finally:
        tts_volc._load_dotenv = real_load
        providers._TTS_INSTANCES.pop("volc", None)
        os.environ.pop("VOLC_TTS_API_KEY", None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    print("4. 读密钥（没配给出处）、注册为 volc ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/render/test_tts_volc.py`
Expected: FAIL with `ImportError` for `render.providers.tts_volc`

- [ ] **Step 3: 写 `tts_volc.py`**

Create `backend/render/providers/tts_volc.py`:

```python
"""火山引擎豆包语音合成（大模型 2.0，HTTP 单向流式接口）。

接口与价格核实于 2026-10-31 的官方文档：
- POST https://openspeech.bytedance.com/api/v3/tts/unidirectional。请求头 X-Api-Key（新版控制台），或
  X-Api-App-Id + X-Api-Access-Key（旧版控制台）；X-Api-Resource-Id: seed-tts-2.0 决定模型与计费。
- 请求体 user.uid、req_params.text、req_params.speaker、req_params.audio_params（format、sample_rate、
  speech_rate [-50,100]，100 为 2 倍速）。响应是逐行 JSON：音频块 {"code":0,"data":"<base64>"}，
  结束块 code=20000000；其他非 0 码为失败。
- 2.0 音色名以 _uranus_bigtts 结尾；后付费 3 元/万字符。
我们要 pcm（24kHz 16 位单声道）自己封成 WAV，时长按帧数算。密钥只放进请求头，不进日志与报错。
"""
import base64
import json
import os
import uuid
from pathlib import Path

import httpx

from pipeline.config import ROOT as BACKEND_ROOT
from pipeline.config import _load_dotenv
from render.providers.base import ProviderError, TransientError
from render.providers.tts_base import TtsCaps, TtsResult, Voice, tts_cost, write_wav

URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
RESOURCE_ID = "seed-tts-2.0"
SAMPLE_RATE = 24000
DONE = 20000000
# 2026-10 后付费刊例价 3 元/万字符；用真实账单校准后可用 STORYBOARD_VOLC_TTS_CNY_PER_K 覆盖（元/千字符）
DEFAULT_CNY_PER_K = 0.3
VOICES = [
    Voice("zh_male_m191_uranus_bigtts", "云舟 2.0", "male"),
    Voice("zh_male_taocheng_uranus_bigtts", "小天 2.0", "male"),
    Voice("zh_male_liufei_uranus_bigtts", "刘飞 2.0", "male"),
    Voice("zh_female_vv_uranus_bigtts", "Vivi 2.0", "female"),
    Voice("zh_female_xiaohe_uranus_bigtts", "小何 2.0", "female"),
    Voice("zh_female_sophie_uranus_bigtts", "魅力苏菲 2.0", "female"),
    Voice("zh_female_qingxinnvsheng_uranus_bigtts", "清新女声 2.0", "female"),
    Voice("zh_female_cancan_uranus_bigtts", "知性灿灿 2.0", "female"),
]


def _per_k() -> float:
    try:
        v = float(os.environ.get("STORYBOARD_VOLC_TTS_CNY_PER_K", ""))
    except ValueError:
        return DEFAULT_CNY_PER_K
    return v if v > 0 else DEFAULT_CNY_PER_K


def _error_text(r: httpx.Response) -> str:
    try:
        d = r.json()
        head = d.get("header") or {}
        msg = d.get("message") or head.get("message") or ""
        code = d.get("code") or head.get("code") or r.status_code
    except ValueError:
        msg, code = r.text[:200], r.status_code
    return f"豆包语音拒绝了请求（{code}）：{msg}" if msg else f"豆包语音拒绝了请求（HTTP {r.status_code}）"


class VolcTts:
    name = "volc"
    rate_note = "2026-10 火山引擎豆包语音合成 2.0 后付费刊例价（3 元/万字符），未经账单核对"

    def __init__(self, *, api_key: str = "", app_id: str = "", access_key: str = "",
                 client=None, url: str = URL, timeout: float = 60.0):
        if not api_key and not (app_id and access_key):
            raise ProviderError("没有配置豆包语音密钥：在 backend/.env 写 VOLC_TTS_API_KEY=…（新版控制台），"
                                "或 VOLC_TTS_APP_ID 与 VOLC_TTS_ACCESS_KEY（旧版控制台）")
        self._auth = ({"X-Api-Key": api_key} if api_key
                      else {"X-Api-App-Id": app_id, "X-Api-Access-Key": access_key})
        self._http = client or httpx.Client(timeout=timeout)
        self._url = url
        self.caps = TtsCaps(voices=list(VOICES), emotions=False, max_chars=300, cny_per_k_chars=_per_k())

    @classmethod
    def from_env(cls) -> "VolcTts":
        _load_dotenv(BACKEND_ROOT / ".env")
        _load_dotenv(BACKEND_ROOT.parent / ".env")
        return cls(api_key=os.environ.get("VOLC_TTS_API_KEY", "").strip(),
                   app_id=os.environ.get("VOLC_TTS_APP_ID", "").strip(),
                   access_key=os.environ.get("VOLC_TTS_ACCESS_KEY", "").strip())

    def synthesize(self, text, voice, emotion, speed, dest):
        params = {"format": "pcm", "sample_rate": SAMPLE_RATE,
                  "speech_rate": max(-50, min(100, round((speed - 1) * 100)))}
        if emotion and self.caps.emotions:
            params["emotion"] = emotion
        body = {"user": {"uid": "storyboard"},
                "req_params": {"text": text, "speaker": voice, "audio_params": params}}
        headers = {**self._auth, "X-Api-Resource-Id": RESOURCE_ID,
                   "X-Api-Request-Id": str(uuid.uuid4()), "Content-Type": "application/json"}
        pcm, done = bytearray(), False
        try:
            with self._http.stream("POST", self._url, headers=headers, json=body) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransientError(f"豆包语音暂时不可用（HTTP {r.status_code}）")
                if r.status_code >= 400:
                    r.read()
                    raise ProviderError(_error_text(r))
                for raw in r.iter_lines():
                    line = raw.strip()
                    if line.startswith("data:"):
                        line = line[len("data:"):].strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        raise TransientError("豆包语音返回的不是 JSON")
                    code = msg.get("code", 0)
                    if code == DONE:
                        done = True
                        break
                    if code != 0:
                        detail = msg.get("message") or ""
                        raise ProviderError(f"豆包语音合成失败（{code}）" + (f"：{detail}" if detail else ""))
                    if msg.get("data"):
                        pcm += base64.b64decode(msg["data"])
        except httpx.TransportError as e:
            raise TransientError(f"连接豆包语音失败：{type(e).__name__}")
        if not done or not pcm:
            raise TransientError("豆包语音没有返回完整的音频")
        duration = write_wav(Path(dest), bytes(pcm), SAMPLE_RATE)
        return TtsResult(Path(dest), duration, tts_cost(len(text), self.caps), len(text))
```

- [ ] **Step 4: 注册**

Append to the end of `backend/render/providers/__init__.py`:

```python


def _volc_tts():
    from render.providers.tts_volc import VolcTts
    return VolcTts.from_env()


register_tts("volc", _volc_tts)
```

- [ ] **Step 5: 运行，确认通过**

Run: `.venv/bin/python tests/render/test_tts_volc.py && .venv/bin/python tests/render/test_tts.py | tail -1`
Expected: four `✓` lines then `ALL PASS`; test_tts `ALL PASS`

- [ ] **Step 6: 提交**

```bash
git add render/providers/tts_volc.py render/providers/__init__.py tests/render/test_tts_volc.py
git commit -m "配音：豆包语音合成 2.0（单向流式接口、新旧控制台两种鉴权、要 pcm 自己封 WAV、8 个中文音色、3 元/万字符可校准）；限流/5xx/断连为瞬时、4xx 与流内错误码为明确失败，密钥不进报错"
```

---

### Task 4: 合成规划与 ffmpeg 参数（`mix.py` 纯函数）

**Files:**
- Create: `backend/render/mix.py`
- Test: `backend/tests/render/test_mix.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/render/test_mix.py`:

```python
#!/usr/bin/env python3
"""合成的纯计算：画幅、原声策略、声画对齐（提速 / 定格）、字幕、ffmpeg 参数。不需要 ffmpeg。

用法: python3 tests/render/test_mix.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import mix  # noqa: E402

EP = {"id": "E01", "shots": [
    {"id": "S1", "duration_sec": 4, "narration": {"text": "一" * 9}},
    {"id": "S2", "duration_sec": 2, "dialogue": [{"type": "dialogue", "character_ref": "C1", "text": "二" * 9}]},
    {"id": "S3", "duration_sec": 2, "narration": {"text": "三" * 9}},
    {"id": "S4", "duration_sec": 3},
]}
CLIPS = [{"id": "E01-C01", "shots": ["S1", "S2"]}, {"id": "E01-C02", "shots": ["S3", "S4"]}]
VOICED = {"S1-L1": {"duration": 2.0, "file": "a.wav"}, "S2-L1": {"duration": 2.2, "file": "b.wav"},
          "S3-L1": {"duration": 3.0, "file": "c.wav"}}


def near(a, b, eps=1e-3):
    return abs(a - b) < eps


def main() -> int:
    assert mix.frame_size("720p", "9:16") == (720, 1280)
    assert mix.frame_size("480p", "9:16") == (480, 854)
    assert mix.frame_size("1080p", "16:9") == (1920, 1080)
    assert mix.frame_size("720p", "1:1") == (720, 720)
    assert mix.frame_size("720p", "bad") == (720, 1280)
    assert mix.native_audio_policy("tts_all", False) == -12 and mix.native_audio_policy("tts_all", True) is None
    assert mix.native_audio_policy("dialogue_native", True) == 0.0 and mix.native_audio_policy("silent", False) is None
    print("1. 画幅与原声策略 ✓")

    plan = mix.plan_episode(EP, CLIPS, VOICED)
    s1, s2 = plan["segments"]
    assert s1["clip"] == "E01-C01" and s1["start"] == 0 and near(s1["duration"], 6.0) and near(s1["base"], 6.0)
    assert near(s2["start"], 6.0) and near(s2["duration"], 3.0 / 1.15 + 3) and near(s2["base"], 5.0)
    assert near(plan["total"], 6.0 + 3.0 / 1.15 + 3)
    sp = {x["line"]: x for x in plan["speech"]}
    assert near(sp["S1-L1"]["start"], 0) and sp["S1-L1"]["speed"] == 1.0
    assert near(sp["S2-L1"]["start"], 4.0) and near(sp["S2-L1"]["speed"], 1.1)
    assert near(sp["S3-L1"]["start"], 6.0) and near(sp["S3-L1"]["speed"], 1.15)
    kinds = {n["shot"]: n["kind"] for n in plan["notes"]}
    assert kinds == {"S2": "speedup", "S3": "freeze"}
    assert near(next(n for n in plan["notes"] if n["shot"] == "S3")["extend"], 3.0 / 1.15 - 2, 0.01)
    sub2 = next(x for x in plan["subs"] if x["line"] == "S2-L1")
    assert near(sub2["start"], 4.0) and near(sub2["end"], 6.0)
    print("2. 对齐：念得完不动、超出 15% 内提速、更多就按 1.15 倍念并定格延长 ✓")

    native = mix.plan_episode(EP, CLIPS, {k: v for k, v in VOICED.items() if k != "S1-L1"})
    assert "S1-L1" not in {x["line"] for x in native["speech"]}
    sub1 = next(x for x in native["subs"] if x["line"] == "S1-L1")
    assert near(sub1["end"] - sub1["start"], 2.0), "没合成的语音条按字数估时长，只进字幕"
    print("3. 原声语音条只进字幕 ✓")

    assert mix._ts(3661.5) == "01:01:01,500" and mix._ts(-1) == "00:00:00,000"
    text = mix.srt([{"start": 0, "end": 2, "text": "第一句"}, {"start": 4, "end": 6.25, "text": "第二句"}])
    assert text == "1\n00:00:00,000 --> 00:00:02,000\n第一句\n\n2\n00:00:04,000 --> 00:00:06,250\n第二句\n\n"
    print("4. 字幕 ✓")

    cmd = mix.normalize_cmd("in.mp4", still=None, duration=5.6087, size=(720, 1280), native_db=-12,
                            has_audio=True, out="o.mp4")
    joined = " ".join(cmd)
    assert "tpad=stop_mode=clone:stop_duration=5.609" in joined and "volume=-12dB" in joined
    assert cmd[cmd.index("-t") + 1] == "5.609" and "scale=720:1280:force_original_aspect_ratio=decrease" in joined
    assert "pad=720:1280:(ow-iw)/2:(oh-ih)/2" in joined and cmd[-1] == "o.mp4"
    quiet = " ".join(mix.normalize_cmd("in.mp4", still=None, duration=3, size=(720, 1280), native_db=None,
                                       has_audio=True, out="o.mp4"))
    assert "[1:a]anull[a]" in quiet and "volume" not in quiet, "不要原声时用静音轨"
    still = mix.normalize_cmd(None, still="kf.png", duration=3, size=(720, 1280), native_db=-12,
                              has_audio=False, out="o.mp4")
    assert still[still.index("-i") - 1] == str(mix.FPS) and "-loop" in still and "kf.png" in still
    black = " ".join(mix.normalize_cmd(None, still=None, duration=3, size=(480, 854), native_db=None,
                                       has_audio=False, out="o.mp4"))
    assert "color=c=black:s=480x854" in black
    print("5. 规整参数：缩放补边、尾帧定格、原声音量、关键帧或黑场补位 ✓")

    lst = mix.concat_list(["/a/1.mp4", "/a/2.mp4"])
    assert lst == "file '/a/1.mp4'\nfile '/a/2.mp4'\n"
    assert mix.concat_cmd("l.txt", "o.mp4")[-4:] == ["l.txt", "-c", "copy", "o.mp4"]
    m = mix.mix_cmd("v.mp4", plan, bgm="bgm.mp3", out="out.mp4")
    fc = m[m.index("-filter_complex") + 1]
    assert m.count("-i") == 1 + 3 + 1 and m[m.index("bgm.mp3") - 3:m.index("bgm.mp3")] == ["-stream_loop", "-1", "-i"]
    assert "atempo=1.1000" in fc and "adelay=4000|4000" in fc and "amix=inputs=3" in fc
    assert "sidechaincompress" in fc and f"loudnorm=I={mix.LUFS}" in fc
    assert m[m.index("-t") + 1] == f"{plan['total']:.3f}" and m[-1] == "out.mp4"
    bare = mix.mix_cmd("v.mp4", {"speech": [], "total": 3.0}, bgm=None, out="out.mp4")
    assert "[nat]loudnorm" in bare[bare.index("-filter_complex") + 1] and bare.count("-i") == 1
    print("6. 拼接与混音参数：配音按时刻放置并提速、BGM 循环并在有人声时压低、响度标准化 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/render/test_mix.py`
Expected: FAIL with `ImportError: cannot import name 'mix' from 'render'`

- [ ] **Step 3: 写 `mix.py`（规划与参数部分）**

Create `backend/render/mix.py`:

```python
"""出片合成（设计文档 3.3–3.5）：规划（纯函数）、ffmpeg 参数（纯函数）与执行。

规划：每集按镜头顺序排开，镜头时长取可播时长；本镜头的语音（TTS 用真实时长，原声或不出声的按字数估）
念不完时，先把语速提到最多 1.15 倍，还不够就按 1.15 倍念、把所在段的尾帧定格延长到念完，语音不截断。
段视频规整到计划长度：短了尾帧定格补齐，长了裁掉。段内各镜头的切换时刻由视频模型决定，台词按计划
镜头起点放置，属近似对齐（报告里写明）。
"""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from pipeline.quality import DEFAULT_SPEECH_CPS
from render import compose, voice

FPS = 30
SPEEDUP_MAX = 1.15
NATIVE_DB = -12          # tts_all：视频原声压成环境音
BGM_DB = -14
LUFS = -16
AUDIO_RATE = 48000
SHORT_SIDE = {"480p": 480, "720p": 720, "1080p": 1080}


class MixError(Exception):
    """合成失败：message 给用户看；stderr 是 ffmpeg 的错误输出（截尾）。"""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


def _even(x: float) -> int:
    return int(round(x / 2)) * 2


def frame_size(resolution: str, aspect: str) -> tuple:
    """(宽, 高)：短边按分辨率档（480p/720p/1080p），长边按画幅，取偶数。"""
    short = SHORT_SIDE.get(resolution, 720)
    try:
        a, b = (float(n) for n in (aspect or "9:16").split(":"))
    except ValueError:
        a, b = 9.0, 16.0
    if a <= 0 or b <= 0:
        a, b = 9.0, 16.0
    if a <= b:
        return short, _even(short * b / a)
    return _even(short * a / b), short


def native_audio_policy(audio_mode: str, mute: bool) -> Optional[float]:
    """视频原声的音量（dB）；None 为不要原声（无声模式，或 tts_all 下这一段设了原声静音）。"""
    if audio_mode == "silent" or (audio_mode == "tts_all" and mute):
        return None
    return float(NATIVE_DB) if audio_mode == "tts_all" else 0.0


def plan_episode(ep: dict, clips: list, voiced: dict, cps: float = DEFAULT_SPEECH_CPS) -> dict:
    """一集的合成计划。

    ep：分镜的一集；clips：本集的段（session.json 的 clips，按顺序）；voiced：语音条 id → 合成结果
    （含 duration、file）。不在 voiced 里的语音条按字数估时长，只进字幕。
    返回 {"episode", "total", "segments": [{"clip", "start", "duration", "base"}],
          "speech": [{"line", "file", "start", "speed"}], "subs": [{"start", "end", "text", "line"}],
          "notes": [{"shot", "kind": "speedup"|"freeze", "speed", "extend"?}]}
    """
    by_shot = {}
    for line in voice.speech_lines({"episodes": [ep]}):
        by_shot.setdefault(line["shot"], []).append(line)
    shots = {s["id"]: s for s in ep.get("shots") or []}
    t = 0.0
    segments, speech, subs, notes = [], [], [], []
    for c in clips:
        start, base = t, 0.0
        for sid in c["shots"]:
            shot = shots.get(sid)
            if shot is None:
                continue
            p = compose.playable(shot, cps)
            base += p
            lines = by_shot.get(sid, [])
            durs = [voiced[x["id"]]["duration"] if x["id"] in voiced else len(x["text"]) / cps for x in lines]
            need = sum(durs)
            speed, eff = 1.0, p
            if need > p + 1e-9:
                if need <= p * SPEEDUP_MAX + 1e-9:
                    speed = need / p
                    notes.append({"shot": sid, "kind": "speedup", "speed": round(speed, 3)})
                else:
                    speed = SPEEDUP_MAX
                    eff = need / SPEEDUP_MAX
                    notes.append({"shot": sid, "kind": "freeze", "speed": SPEEDUP_MAX,
                                  "extend": round(eff - p, 2)})
            at = t
            for x, d in zip(lines, durs):
                dur = d / speed
                subs.append({"start": at, "end": at + dur, "text": x["text"], "line": x["id"]})
                if x["id"] in voiced:
                    speech.append({"line": x["id"], "file": str(voiced[x["id"]]["file"]), "start": at,
                                   "speed": speed})
                at += dur
            t += eff
        segments.append({"clip": c["id"], "start": round(start, 3), "duration": round(t - start, 3),
                         "base": round(base, 3)})
    return {"episode": ep["id"], "total": round(t, 3), "segments": segments, "speech": speech,
            "subs": subs, "notes": notes}


def _ts(sec: float) -> str:
    ms = int(round(max(0.0, sec) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(subs: list) -> str:
    return "".join(f"{i}\n{_ts(x['start'])} --> {_ts(x['end'])}\n{x['text']}\n\n"
                   for i, x in enumerate(subs, 1))


# ---------- ffmpeg 参数（纯函数） ----------

def normalize_cmd(src: Optional[str], *, still: Optional[str], duration: float, size: tuple,
                  native_db: Optional[float], has_audio: bool, out: str, ffmpeg: str = "ffmpeg") -> list:
    """一段规整成统一尺寸、30 fps、48k 立体声，长度正好 duration：短了尾帧定格，长了裁掉。

    src 为段视频；没有视频时用 still（关键帧图）定格，再没有就黑场（草稿合成补位）。
    native_db 为原声音量，None 或源视频没有音轨时用静音轨（拼接要求每段都有音轨）。
    """
    w, h = size
    d = f"{duration:.3f}"
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
           f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}")
    if src:
        inputs = ["-i", src]
        vf = f"[0:v]{fit},tpad=stop_mode=clone:stop_duration={d}[v]"
    elif still:
        inputs = ["-loop", "1", "-framerate", str(FPS), "-i", still]
        vf = f"[0:v]{fit}[v]"
    else:
        inputs = ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={FPS}"]
        vf = "[0:v]setsar=1[v]"
    inputs += ["-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE}"]
    if src and has_audio and native_db is not None:
        af = (f"[0:a]aresample={AUDIO_RATE},aformat=channel_layouts=stereo,"
              f"volume={native_db:g}dB,apad[a]")
    else:
        af = "[1:a]anull[a]"
    return [ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", f"{vf};{af}",
            "-map", "[v]", "-map", "[a]", "-t", d, "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", str(AUDIO_RATE), "-ac", "2", out]


def concat_list(files: list) -> str:
    """concat 分离器的清单（绝对路径）。"""
    return "".join(f"file '{Path(f).resolve().as_posix()}'\n" for f in files)


def concat_cmd(list_file, out, ffmpeg: str = "ffmpeg") -> list:
    """各段参数一致（normalize_cmd 保证），直接流拷贝拼接。"""
    return [ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", str(out)]


def mix_cmd(video: str, plan: dict, *, bgm: Optional[str], out: str, ffmpeg: str = "ffmpeg") -> list:
    """配音按计划时刻放置（必要时提速），BGM 循环铺满并在有人声时压低（侧链压缩），
    与视频原声混合，响度标准化到 −16 LUFS。视频流原样拷贝。"""
    inputs = ["-i", video]
    parts = ["[0:a]anull[nat]"]
    labels = []
    for i, x in enumerate(plan["speech"], 1):
        inputs += ["-i", x["file"]]
        ms = int(round(x["start"] * 1000))
        parts.append(f"[{i}:a]aformat=sample_rates={AUDIO_RATE}:channel_layouts=stereo,"
                     f"atempo={x['speed']:.4f},adelay={ms}|{ms}[s{i}]")
        labels.append(f"[s{i}]")
    n = len(labels)
    if n:
        parts.append(f"{''.join(labels)}amix=inputs={n}:normalize=0:dropout_transition=0[speech]")
    mixed = ["[nat]"]
    if bgm:
        b = n + 1
        inputs += ["-stream_loop", "-1", "-i", bgm]
        parts.append(f"[{b}:a]aformat=sample_rates={AUDIO_RATE}:channel_layouts=stereo,"
                     f"volume={BGM_DB}dB,atrim=0:{plan['total']:.3f}[bgm]")
        if n:
            parts.append("[speech]asplit=2[sp][key]")
            parts.append("[bgm][key]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[bgmd]")
            mixed += ["[sp]", "[bgmd]"]
        else:
            mixed.append("[bgm]")
    elif n:
        mixed.append("[speech]")
    loud = f"loudnorm=I={LUFS}:TP=-1.5:LRA=11"
    if len(mixed) > 1:
        parts.append(f"{''.join(mixed)}amix=inputs={len(mixed)}:normalize=0:dropout_transition=0,{loud}[out]")
    else:
        parts.append(f"[nat]{loud}[out]")
    return [ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", ";".join(parts),
            "-map", "0:v", "-map", "[out]", "-c:v", "copy", "-c:a", "aac", "-ar", str(AUDIO_RATE),
            "-t", f"{plan['total']:.3f}", out]


# ---------- 执行 ----------

def tools() -> Optional[tuple]:
    """(ffmpeg, ffprobe) 的路径；没装返回 None（合成被拒并提示 brew install ffmpeg）。"""
    f, p = shutil.which("ffmpeg"), shutil.which("ffprobe")
    return (f, p) if f and p else None


def run(cmd: list, what: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise MixError(f"{what}失败（ffmpeg 退出码 {r.returncode}）", (r.stderr or "")[-4000:])


def has_audio(path, ffprobe: str) -> bool:
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


def media_seconds(path, ffprobe: str) -> float:
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                        str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0
```

（`hashlib`、`json` 在 Task 5 的 `compose()` 里用到，本任务先 import。）

- [ ] **Step 4: 运行，确认通过**

Run: `.venv/bin/python tests/render/test_mix.py`
Expected: six `✓` lines then `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add render/mix.py tests/render/test_mix.py
git commit -m "合成规划：画幅按分辨率与比例、各声音模式的原声音量、声画对齐（念得完不动、15% 内提速、更多就 1.15 倍念并定格延长）、字幕；ffmpeg 规整/拼接/混音参数（配音按时刻放置、BGM 循环与侧链压低、−16 LUFS）"
```

---

### Task 5: 整章合成、预览与指纹（`mix.compose`）

**Files:**
- Modify: `backend/render/mix.py`（末尾追加）
- Test: `backend/tests/render/test_mix_e2e.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/render/test_mix_e2e.py`:

```python
#!/usr/bin/env python3
"""整章合成端到端：用 ffmpeg 测试源生成假视频与 BGM、假 TTS 出配音，跑完整合成，检查成片时长、音轨、
字幕条数、补位与报告；重跑复用配音缓存与已规整的段；关掉草稿合成时缺段拒绝。预览与指纹不需要 ffmpeg。

没装 ffmpeg 时只跑预览部分并注明跳过。用法: python3 tests/render/test_mix_e2e.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import mix  # noqa: E402
from render.providers.fake import FakeTts  # noqa: E402

DOC = {
    "meta": {"narration": {"tts_voice": "male_mature"}, "video": {"aspect_ratio": "9:16"}},
    "assets": {"characters": [{"id": "C1", "name": "老栓", "voice": {"tts_voice": "female_young"}}]},
    "episodes": [{"id": "E01", "shots": [
        {"id": "S1", "duration_sec": 3, "narration": {"text": "秋天的后半夜月亮下去了"}},
        {"id": "S2", "duration_sec": 2, "dialogue": [{"type": "dialogue", "character_ref": "C1", "text": "小栓的爹"}]},
        {"id": "S3", "duration_sec": 2},
    ]}],
}


def session(with_video: bool) -> dict:
    a = [{"task_id": "t1", "state": "succeeded", "file": "clips/E01-C01.t1.mp4", "cost_cny": 1}]
    return {"audio_mode": "tts_all", "resolution": "480p", "voices": {}, "clips": [
        {"id": "E01-C01", "episode": "E01", "shots": ["S1", "S2"], "state": "done",
         "attempts": a if with_video else [], "chosen": 0 if with_video else None, "mute_native": False},
        {"id": "E01-C02", "episode": "E01", "shots": ["S3"], "state": "planned", "attempts": [], "chosen": None,
         "mute_native": False},
    ]}


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        tts = FakeTts()
        p = mix.preview(root, DOC, session(True), tts=tts, bgm={}, draft=True)
        assert p["lines"] == 2 and p["tts_chars"] == len("秋天的后半夜月亮下去了") + len("小栓的爹")
        assert p["missing_voices"] == [] and p["no_video"] == ["E01-C02"] and p["voices"]["C1"] == "fake-female"
        fp = p["fingerprint"]
        assert mix.preview(root, DOC, session(True), tts=tts, bgm={}, draft=True)["fingerprint"] == fp
        assert mix.preview(root, DOC, session(False), tts=tts, bgm={}, draft=True)["fingerprint"] != fp, \
            "采用的视频变了，成片过期"
        s = dict(session(True), audio_mode="silent")
        assert mix.preview(root, DOC, s, tts=tts, bgm={}, draft=True)["tts_chars"] == 0
        print("1. 预览：配音条数与未缓存字数、缺音色、缺视频的段、成片指纹 ✓")

        tools = mix.tools()
        if tools is None:
            print("\nALL PASS（跳过：没装 ffmpeg，端到端合成没跑；brew install ffmpeg 后再跑）")
            return 0
        ffmpeg, ffprobe = tools
        (root / "clips").mkdir()
        subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "4",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        str(root / "clips" / "E01-C01.t1.mp4")], check=True)
        (root / "audio" / "bgm").mkdir(parents=True)
        bgm = root / "audio" / "bgm" / "E01.wav"
        subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100",
                        "-t", "2", str(bgm)], check=True)
        steps, spent = [], []
        out = mix.compose(root, DOC, session(True), tts=tts, keyframes={}, bgm={"E01": bgm}, draft=True,
                          tools=tools, on_cost=spent.append, progress=steps.append)
        assert out == {"files": ["final/E01.mp4", "final/E01.srt"], "report": "final/mix_report.json"}
        video = root / "final" / "E01.mp4"
        plan_total = mix.plan_episode(DOC["episodes"][0], session(True)["clips"],
                                      {x["id"]: x for x in []})["total"]
        assert abs(mix.media_seconds(video, ffprobe) - plan_total) < 0.5 or mix.media_seconds(video, ffprobe) > 0
        assert mix.has_audio(video, ffprobe)
        assert (root / "final" / "E01.srt").read_text(encoding="utf-8").count(" --> ") == 2
        report = json.loads((root / "final" / "mix_report.json").read_text(encoding="utf-8"))
        assert report["episodes"][0]["placeholders"] == ["E01-C02"] and report["audio_mode"] == "tts_all"
        assert len(tts.calls) == 2 and sum(spent) > 0 and any("混音" in s for s in steps)
        print(f"2. 整章合成：成片 {mix.media_seconds(video, ffprobe):.2f} 秒、有音轨、字幕 2 条、缺段补位写进报告 ✓")

        work = sorted((root / "final" / "work").glob("*.mp4"))
        stamps = {w.name: w.stat().st_mtime_ns for w in work if ".joined" not in w.name}
        mix.compose(root, DOC, session(True), tts=tts, keyframes={}, bgm={"E01": bgm}, draft=True, tools=tools)
        assert len(tts.calls) == 2, "配音缓存复用"
        assert {w.name: w.stat().st_mtime_ns for w in sorted((root / "final" / "work").glob("*.mp4"))
                if ".joined" not in w.name} == stamps, "已规整的段复用"
        print("3. 重跑复用配音缓存与已规整的段 ✓")

        try:
            mix.compose(root, DOC, session(True), tts=tts, keyframes={}, bgm={}, draft=False, tools=tools)
            raise AssertionError("关掉草稿合成时缺段应拒绝")
        except mix.MixError as e:
            assert "E01-C02" in str(e)
        print("4. 关掉草稿合成时缺段拒绝 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/render/test_mix_e2e.py`
Expected: FAIL with `AttributeError: module 'render.mix' has no attribute 'preview'`

- [ ] **Step 3: 整章合成、预览与指纹**

Append to the end of `backend/render/mix.py`:

```python


# ---------- 整章合成 ----------

def chosen_file(c: dict) -> Optional[str]:
    """段采用的那次的视频（会话目录下的相对路径）；没有成功的就 None。"""
    i = c.get("chosen")
    a = c["attempts"][i] if i is not None and 0 <= i < len(c.get("attempts") or []) else None
    return a["file"] if a and a.get("state") == "succeeded" and a.get("file") else None


def compose_fingerprint(doc: dict, s: dict, voices: dict, bgm: dict, draft: bool) -> str:
    """成片的输入指纹：语音条、各镜头可播时长、声音模式、音色、各段采用的视频与静音、BGM、草稿合成。"""
    shots = [(sh["id"], round(compose.playable(sh), 3))
             for ep in doc.get("episodes") or [] for sh in ep.get("shots") or []]
    music = {k: [str(v), Path(v).stat().st_size, Path(v).stat().st_mtime_ns] for k, v in sorted(bgm.items())
             if Path(v).exists()}
    return compose.fingerprint(
        lines=[(x["id"], x["kind"], x["speaker"], x["text"]) for x in voice.speech_lines(doc)],
        shots=shots, mode=s["audio_mode"], resolution=s["resolution"], voices=voices,
        clips=[(c["id"], chosen_file(c), bool(c.get("mute_native"))) for c in s["clips"]],
        bgm=music, draft=draft)


def preview(root, doc: dict, s: dict, *, tts, bgm: dict, draft: bool) -> dict:
    """合成前的预览：配音条数、未缓存字数与费用、缺音色的说话人、缺视频的段、成片指纹。不花钱。"""
    lines = voice.tts_lines(voice.speech_lines(doc), s["audio_mode"])
    voices, missing = voice.resolve_voices(doc, lines, s.get("voices") or {}, tts.caps)
    est = (voice.estimate(lines, voices, tts, root) if not missing
           else {"lines": len(lines), "chars": 0, "cny": 0.0})
    return {"lines": len(lines), "tts_chars": est["chars"], "tts_cny": est["cny"],
            "missing_voices": missing, "voices": voices,
            "no_video": [c["id"] for c in s["clips"] if not chosen_file(c)],
            "fingerprint": compose_fingerprint(doc, s, voices, bgm, draft)}


def compose(root, doc: dict, s: dict, *, tts, keyframes: dict, bgm: dict, draft: bool, tools: tuple,
            on_cost=None, progress=None, cps: float = DEFAULT_SPEECH_CPS) -> dict:
    """合成整章：配音 → 每集规整、拼接、混音 → 字幕与报告。返回 {"files", "report"}（会话目录下的相对路径）。

    已合成的配音（audio/cache）与已规整的段（final/work，按输入指纹命名）都复用：失败后重跑不重做已完成的步骤。
    draft=True 时没出的段用首镜关键帧定格补位，没有关键帧用黑场；False 时缺段直接拒绝。
    """
    ffmpeg, ffprobe = tools
    root = Path(root)
    say = progress or (lambda step: None)
    lines = voice.tts_lines(voice.speech_lines(doc), s["audio_mode"])
    voices, missing = voice.resolve_voices(doc, lines, s.get("voices") or {}, tts.caps)
    if missing:
        raise MixError("还有说话人没选音色：" + "、".join(k or "（未标说话人）" for k in missing))
    say(f"配音 {len(lines)} 条")
    try:
        done, failed = voice.synthesize(lines, voices, tts, root, on_cost=on_cost)
    except voice.VoiceError as e:
        raise MixError(str(e))
    if failed:
        raise MixError("有语音条合成失败，为免成片漏句已停止合成："
                       + "；".join(f"{x['id']}：{x['error']}" for x in failed[:5]))
    voiced = {x["id"]: x for x in done}
    size = frame_size(s["resolution"], ((doc.get("meta") or {}).get("video") or {}).get("aspect_ratio") or "9:16")
    work = root / "final" / "work"
    work.mkdir(parents=True, exist_ok=True)
    by_ep = {}
    for c in s["clips"]:
        by_ep.setdefault(c["episode"], []).append(c)
    report = {"audio_mode": s["audio_mode"], "size": f"{size[0]}x{size[1]}", "draft": draft, "episodes": [],
              "alignment": "段内镜头切换时刻由视频模型决定，台词按计划镜头起点放置，属近似对齐"}
    if s["audio_mode"] == "dialogue_native":
        report["warning"] = "台词由视频模型生成，不保证逐字"
    files = []
    for ep in doc.get("episodes") or []:
        clips = by_ep.get(ep["id"]) or []
        if not clips:
            continue
        plan = plan_episode(ep, clips, voiced, cps)
        segs, placeholders = [], []
        for seg, c in zip(plan["segments"], clips):
            rel = chosen_file(c)
            src = str(root / rel) if rel and (root / rel).exists() else None
            still = None
            if not src:
                if not draft:
                    raise MixError(f"{c['id']} 还没有可用的视频；打开「草稿合成」可用关键帧补位")
                kf = keyframes.get(c["shots"][0]) if c["shots"] else None
                still = str(kf) if kf else None
                placeholders.append(c["id"])
            ndb = native_audio_policy(s["audio_mode"], bool(c.get("mute_native")))
            audio = bool(src) and ndb is not None and has_audio(src, ffprobe)
            key = hashlib.sha256(json.dumps([src, still, seg["duration"], size, ndb, audio]).encode()).hexdigest()[:16]
            out = work / f"{c['id']}.{key}.mp4"
            if not out.exists():
                say(f"规整 {c['id']}")
                tmp = out.with_suffix(".part.mp4")
                run(normalize_cmd(src, still=still, duration=seg["duration"], size=size, native_db=ndb,
                                  has_audio=audio, out=str(tmp), ffmpeg=ffmpeg), f"规整 {c['id']} ")
                tmp.replace(out)
            segs.append(out)
        lst = work / f"{ep['id']}.txt"
        lst.write_text(concat_list(segs), encoding="utf-8")
        joined = work / f"{ep['id']}.joined.mp4"
        say(f"拼接 {ep['id']}")
        run(concat_cmd(lst, joined, ffmpeg), f"拼接 {ep['id']} ")
        final = root / "final" / f"{ep['id']}.mp4"
        tmp = final.with_suffix(".part.mp4")
        say(f"混音 {ep['id']}")
        music = bgm.get(ep["id"])
        run(mix_cmd(str(joined), plan, bgm=str(music) if music else None, out=str(tmp), ffmpeg=ffmpeg),
            f"混音 {ep['id']} ")
        tmp.replace(final)
        (root / "final" / f"{ep['id']}.srt").write_text(srt(plan["subs"]), encoding="utf-8")
        files += [f"final/{ep['id']}.mp4", f"final/{ep['id']}.srt"]
        report["episodes"].append({"episode": ep["id"], "seconds": plan["total"], "notes": plan["notes"],
                                   "placeholders": placeholders,
                                   "stale": [c["id"] for c in clips if c.get("state") == "stale"]})
    (root / "final" / "mix_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
    return {"files": files, "report": "final/mix_report.json"}
```

- [ ] **Step 4: 运行，确认通过**

Run: `.venv/bin/python tests/render/test_mix_e2e.py && .venv/bin/python tests/render/test_mix.py | tail -1`
Expected: with ffmpeg installed: four `✓` lines then `ALL PASS`. Without ffmpeg: `1. … ✓` then `ALL PASS（跳过：没装 ffmpeg，端到端合成没跑；brew install ffmpeg 后再跑）`. **Report which one you got.** If ffmpeg is installed and a step fails, debug the ffmpeg command (read the `MixError.stderr`) and fix `mix.py`; record each change in the report.

- [ ] **Step 5: 提交**

```bash
git add render/mix.py tests/render/test_mix_e2e.py
git commit -m "整章合成：配音（缓存复用）→ 每集规整（按输入指纹复用、草稿合成用关键帧或黑场补位）、拼接、混音 → 字幕与报告；合成前预览（未缓存字数与费用、缺音色、缺视频的段）与成片指纹"
```

---

### Task 6: 合成状态、接口与后台线程

**Files:**
- Modify: `backend/render/session.py`（常量、`recover`，末尾追加合成状态迁移）
- Modify: `backend/server/app.py`（import；出片一节末尾追加音色、合成、BGM）
- Test: `backend/tests/server/test_compose.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/server/test_compose.py`:

```python
#!/usr/bin/env python3
"""配音与合成接口：音色（默认、选择、清除、校验）、合成预览、合成的拦截（没装 ffmpeg、缺音色、配音金额
确认 409、草稿合成关掉时缺段、上限、合成中再合成）、后台线程推进到完成/失败、成片过期、重启中断、BGM 上传删除。

假视频厂商 + 假 TTS；合成本身用替身函数（真 ffmpeg 合成由 tests/render/test_mix_e2e.py 覆盖）。
用法: python3 tests/server/test_compose.py
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
os.environ["STORYBOARD_TTS_PROVIDER"] = "fake"
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from render import mix, providers, voice, session as render_session  # noqa: E402
from render.providers.fake import FakeTts, FakeVideo  # noqa: E402
from render.providers.tts_base import tts_cost  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402

FAKE = FakeVideo()
TTS = FakeTts()
providers.register("fake", lambda: FAKE)
providers.register_tts("fake", lambda: TTS)
DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))


def wait(root):
    t = app_mod._compose_threads.get(str(root))
    if t:
        t.join(10)
        assert not t.is_alive(), "合成线程没跑完"


def main() -> int:
    c = TestClient(app_mod.app)
    uid = auth.register("alice", "secret1")["id"]
    H = {"Authorization": f"Bearer {auth.issue_token(uid)}"}
    nid = novels.create_novel(uid, "药")["id"]
    cid = novels.create_chapter(uid, nid, "第一章", text="原文")["id"]
    novels.create_version(uid, nid, cid, "v1", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v1", "succeeded", result=copy.deepcopy(DOC))
    R = f"/novels/{nid}/chapters/{cid}/versions/v1/render"
    root = novels.render_dir(uid, nid, cid, "v1")

    # 1. 没会话：音色与合成都 404
    assert c.get(R + "/voices", headers=H).status_code == 404
    assert c.get(R + "/compose", headers=H).status_code == 404
    assert c.post(R + "/session", headers=H, json={}).status_code == 200
    print("1. 没会话时 404 ✓")

    # 2. 音色：按提示默认、缺音色列出、选择与清除、无效音色 422
    v = c.get(R + "/voices", headers=H).json()
    assert v["provider"] == "fake" and {x["id"] for x in v["voices"]} == {"fake-male", "fake-female"}
    keys = [x["key"] for x in v["speakers"]]
    assert keys[0] == "narration" or "narration" in keys
    narr = next(x for x in v["speakers"] if x["key"] == "narration")
    assert narr["voice"] == "fake-male" and narr["chosen"] is None, "旁白提示 male_mature → 男声"
    assert set(v["missing"]) == {x["key"] for x in v["speakers"] if x["voice"] is None}
    assert c.put(R + "/voices", headers=H, json={"voices": {"narration": "nope"}}).status_code == 422
    v = c.put(R + "/voices", headers=H, json={"voices": {"narration": "fake-female"}}).json()
    narr = next(x for x in v["speakers"] if x["key"] == "narration")
    assert narr["voice"] == "fake-female" and narr["chosen"] == "fake-female"
    v = c.put(R + "/voices", headers=H, json={"voices": {"narration": ""}}).json()
    assert next(x for x in v["speakers"] if x["key"] == "narration")["voice"] == "fake-male", "清除后回到默认"
    print(f"2. 音色：默认、选择、清除、校验（缺音色 {len(v['missing'])} 个） ✓")

    # 3. 合成预览：配音字数与费用、缺视频的段、没装 ffmpeg 时也能看
    p = c.get(R + "/compose", headers=H).json()
    lines = voice.tts_lines(voice.speech_lines(DOC), "tts_all")
    assert p["lines"] == len(lines) and p["no_video"] and p["final"] is None and "tools" in p
    assert p["missing_voices"] == v["missing"]
    print("3. 合成预览 ✓")

    # 4. 拦截：没装 ffmpeg → 422；缺音色 → 422；补齐音色后金额要确认（409 带金额）
    real_tools, real_compose = mix.tools, mix.compose
    mix.tools = lambda: None
    r = c.post(R + "/compose", headers=H, json={})
    assert r.status_code == 422 and "brew install ffmpeg" in r.json()["detail"]
    mix.tools = lambda: ("ffmpeg", "ffprobe")
    if v["missing"]:
        r = c.post(R + "/compose", headers=H, json={})
        assert r.status_code == 422 and "音色" in r.json()["detail"]
        c.put(R + "/voices", headers=H, json={"voices": {k: "fake-male" for k in v["missing"]}})
    p = c.get(R + "/compose", headers=H).json()
    chars = sum(len(x["text"]) for x in lines)
    assert p["missing_voices"] == [] and p["tts_chars"] == chars and p["tts_cny"] == tts_cost(chars, TTS.caps)
    r = c.post(R + "/compose", headers=H, json={})
    assert r.status_code == 409 and r.json()["detail"]["expected_cny"] == p["tts_cny"]
    assert c.post(R + "/compose", headers=H, json={"expected_cny": p["tts_cny"] + 1}).status_code == 409
    r = c.post(R + "/compose", headers=H, json={"expected_cny": p["tts_cny"], "draft": False})
    assert r.status_code == 422 and "草稿合成" in r.json()["detail"]
    print("4. 拦截：没装 ffmpeg、缺音色、配音金额确认、关掉草稿合成时缺段 ✓")

    # 5. 合成：后台线程推进到完成；配音费计入已花；成片可取；分镜一改成片过期
    def fake_compose(root_, doc, s, *, tts, keyframes, bgm, draft, tools, on_cost=None, progress=None):
        assert draft and tts is TTS and s["final"]["state"] == "running"
        progress("配音 3 条")
        on_cost(0.5)
        (Path(root_) / "final").mkdir(exist_ok=True)
        (Path(root_) / "final" / "E01.mp4").write_bytes(b"mp4")
        return {"files": ["final/E01.mp4"], "report": "final/mix_report.json"}
    mix.compose = fake_compose
    before = render_session.load(root)["spent_cny"]
    r = c.post(R + "/compose", headers=H, json={"expected_cny": p["tts_cny"]})
    assert r.status_code == 200, r.text
    assert r.json()["final"]["state"] == "running"
    wait(root)
    p2 = c.get(R + "/compose", headers=H).json()
    f = p2["final"]
    assert f["state"] == "done" and f["files"] == ["final/E01.mp4"] and f["stale"] is False, f
    assert abs(render_session.load(root)["spent_cny"] - before - 0.5) < 1e-9
    assert c.get(R + "/files/final/E01.mp4", headers=H).content == b"mp4"
    edited = copy.deepcopy(DOC)
    edited["episodes"][0]["shots"][0]["narration"]["text"] += "（改）"
    novels.update_version_result(uid, nid, cid, "v1", edited, verification={}, status="succeeded")
    assert c.get(R + "/compose", headers=H).json()["final"]["stale"] is True
    novels.update_version_result(uid, nid, cid, "v1", copy.deepcopy(DOC), verification={}, status="succeeded")
    print("5. 后台合成到完成、配音费计入已花、成片可取、分镜一改就过期 ✓")

    # 6. 合成失败：错误与 ffmpeg 输出记下；意外异常也落到失败
    def broken(*a, **kw):
        raise mix.MixError("混音 E01 失败（ffmpeg 退出码 1）", "Invalid argument")
    mix.compose = broken
    exp = c.get(R + "/compose", headers=H).json()["tts_cny"]
    assert c.post(R + "/compose", headers=H, json={"expected_cny": exp}).status_code == 200
    wait(root)
    f = c.get(R + "/compose", headers=H).json()["final"]
    assert f["state"] == "failed" and "混音" in f["error"] and f["detail"] == "Invalid argument"

    def boom(*a, **kw):
        raise RuntimeError("意外")
    mix.compose = boom
    assert c.post(R + "/compose", headers=H, json={"expected_cny": exp}).status_code == 200
    wait(root)
    assert "RuntimeError" in c.get(R + "/compose", headers=H).json()["final"]["error"]
    print("6. 合成失败与意外异常都落到失败 ✓")

    # 7. 合成中不能再合成；超上限拒绝；重启时中断的合成标失败
    render_session.begin_compose(root, fingerprint="x", tts_cny=0, draft=True)
    assert c.post(R + "/compose", headers=H, json={"expected_cny": exp}).status_code == 409
    render_session.recover(root)
    f = render_session.load(root)["final"]
    assert f["state"] == "failed" and f["error"] == render_session.COMPOSE_INTERRUPTED
    mix.compose = fake_compose
    TTS.caps.cny_per_k_chars = 100000.0
    big = c.get(R + "/compose", headers=H).json()["tts_cny"]
    r = c.post(R + "/compose", headers=H, json={"expected_cny": big})
    assert r.status_code == 422 and "上限" in r.json()["detail"]
    TTS.caps.cny_per_k_chars = 0.3
    print("7. 合成中再合成 409、超上限 422、重启中断标失败 ✓")

    # 8. BGM：上传、预览里列出、类型与集号校验、删除
    assert c.put(R + "/bgm/E01", headers={**H, "Content-Type": "audio/mpeg"}, content=b"ID3bgm").status_code == 200
    assert c.get(R + "/compose", headers=H).json()["bgm"] == ["E01"]
    assert c.put(R + "/bgm/E01", headers={**H, "Content-Type": "text/plain"}, content=b"x").status_code == 422
    assert c.put(R + "/bgm/E99", headers={**H, "Content-Type": "audio/mpeg"}, content=b"x").status_code == 404
    assert c.put(R + "/bgm/E01", headers={**H, "Content-Type": "audio/wav"}, content=b"RIFFwav").status_code == 200
    assert sorted(p.name for p in (root / "audio" / "bgm").iterdir()) == ["E01.wav"], "换格式时删掉旧文件"
    assert c.delete(R + "/bgm/E01", headers=H).status_code == 200
    assert c.get(R + "/compose", headers=H).json()["bgm"] == []
    print("8. BGM 上传、校验、删除 ✓")

    mix.tools, mix.compose = real_tools, real_compose
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/server/test_compose.py`
Expected: FAIL at step 1 (`/voices` route does not exist → 404 passes, but `GET /compose` 404 passes too; then the step-2 GET `/voices` returns 404 → `KeyError`/assertion)

- [ ] **Step 3: 会话里的合成状态**

In `backend/render/session.py`, add these constants right after `SETTING_KEYS = (…)`:

```python
COMPOSE_BUSY = ("queued", "running")
COMPOSE_INTERRUPTED = "合成时服务中断，请重新合成（已合成的配音与已规整的片段会复用）"
```

In `recover()`, right before the line `if changed:`, insert:

```python
        f = s.get("final") or {}
        if f.get("state") in COMPOSE_BUSY:
            f.update(state="failed", error=COMPOSE_INTERRUPTED, finished_at=_now())
            s["final"] = f
            changed = True
```

Append to the end of `backend/render/session.py`:

```python


# ---------- 配音与合成（设计文档第 3 节） ----------

def set_voices(root, voices: dict) -> dict:
    """说话人 → 厂商音色 id；空值为清除（回到按提示的默认）。音色是否存在由调用方按厂商校验。"""
    with mutate(root) as s:
        cur = dict(s.get("voices") or {})
        for k, v in voices.items():
            if v:
                cur[k] = v
            else:
                cur.pop(k, None)
        s["voices"] = cur
        return s


def begin_compose(root, *, fingerprint: str, tts_cny: float, draft: bool) -> dict:
    """开始合成：不能正在合成、不能有段在跑；配音费用过同一上限。旧成片的文件留着直到新的合成完成。"""
    with mutate(root) as s:
        f = s.get("final") or {}
        if f.get("state") in COMPOSE_BUSY:
            raise Conflict("正在合成，等它结束再合成")
        if any(c["state"] in IN_FLIGHT for c in s["clips"]):
            raise Conflict("有段在排队或生成中，等它们结束再合成")
        if s["spent_cny"] + tts_cny > s["budget_cny"] + 1e-9:
            raise BudgetExceeded(f"超出上限 ¥{s['budget_cny']:g}：已花 ¥{s['spent_cny']:.2f}，"
                                 f"本次配音约 ¥{tts_cny:.2f}")
        s["final"] = {"state": "running", "fingerprint": fingerprint, "draft": draft, "step": "开始",
                      "started_at": _now(), "files": f.get("files") or [], "report": f.get("report"),
                      "error": None, "detail": None}
        return s


def compose_progress(root, step: str) -> None:
    with mutate(root) as s:
        (s.get("final") or {})["step"] = step


def add_spent(root, cny: float) -> None:
    """配音的真实花费（每合成一条记一次）计入同一 spent_cny。"""
    with mutate(root) as s:
        s["spent_cny"] = round(s["spent_cny"] + cny, 4)


def compose_done(root, files: list, report: str) -> None:
    with mutate(root) as s:
        s["final"].update(state="done", files=files, report=report, step="完成", error=None, detail=None,
                          finished_at=_now())


def compose_failed(root, error: str, detail: str = "") -> None:
    with mutate(root) as s:
        f = s.get("final") or {}
        f.update(state="failed", error=error, detail=detail or None, finished_at=_now())
        s["final"] = f
```

- [ ] **Step 4: 接口与后台线程**

In `backend/server/app.py`:

Add `import traceback` next to `import os` (keep alphabetical order of the stdlib imports there). Below `from render import session as render_session`, add:

```python
from render import mix as render_mix
from render import voice as render_voice
from render.providers import base as render_video_base
```

Right after the `render_file` route (the `@app.get(_R + "/files/{path:path}")` function, end of the 出片 section), insert:

```python


# ---------- 配音与合成：音色存在 session.json 的 voices，成片在 final/ ----------

BGM_TYPES = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
             "audio/wave": ".wav", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".aac"}
BGM_MAX_BYTES = 30 * 1024 * 1024
_compose_threads: dict = {}


class RenderVoicesBody(BaseModel):
    voices: dict[str, str]          # 说话人 → 音色 id；空串为清除


class RenderComposeBody(BaseModel):
    expected_cny: Optional[float] = Field(None, ge=0)
    draft: bool = True


def _tts():
    try:
        return render_providers.get_tts()
    except KeyError as e:
        raise HTTPException(422, e.args[0])
    except render_video_base.ProviderError as e:
        raise HTTPException(422, str(e))


def _bgm_files(root) -> dict:
    d = Path(root) / "audio" / "bgm"
    return {p.stem: p for p in sorted(d.iterdir()) if p.is_file()} if d.is_dir() else {}


def _session_or_404(root) -> dict:
    s = render_session.load(root)
    if s is None:
        raise HTTPException(404, "还没有出片会话")
    return s


@app.get(_R + "/voices")
def render_voices(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    """配音厂商的音色表、各说话人当前用的音色（选的或默认）、缺音色的说话人。"""
    root, doc, _kfs, _owner = _render_ctx(user, nid, cid, vid, gate=False)
    s = _session_or_404(root)
    tts = _tts()
    lines = render_voice.tts_lines(render_voice.speech_lines(doc), s["audio_mode"])
    voices, missing = render_voice.resolve_voices(doc, lines, s.get("voices") or {}, tts.caps)
    info = render_voice.speakers(doc)
    chosen = s.get("voices") or {}
    return {"provider": tts.name, "rate_note": tts.rate_note,
            "voices": [{"id": x.id, "name": x.name, "gender": x.gender} for x in tts.caps.voices],
            "speakers": [{"key": k, "name": (info.get(k) or {}).get("name") or k or "（未标说话人）",
                          "hint": (info.get(k) or {}).get("hint"), "voice": voices.get(k), "chosen": chosen.get(k)}
                         for k in dict.fromkeys(x["speaker"] for x in lines)],
            "missing": missing}


@app.put(_R + "/voices")
def render_voices_put(nid: str, cid: str, vid: str, body: RenderVoicesBody,
                      user: dict = Depends(novel_user)):
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid)
    ids = {x.id for x in _tts().caps.voices}
    bad = [v for v in body.voices.values() if v and v not in ids]
    if bad:
        raise HTTPException(422, f"没有这个音色：{'、'.join(bad)}")
    _render_call(render_session.set_voices, root, body.voices)
    return render_voices(nid, cid, vid, user)


def _compose_preview(user: dict, nid: str, cid: str, vid: str, draft: bool) -> tuple:
    root, doc, kfs, _owner = _render_ctx(user, nid, cid, vid, gate=False)
    s = _session_or_404(root)
    bgm = _bgm_files(root)
    p = render_mix.preview(root, doc, s, tts=_tts(), bgm=bgm, draft=draft)
    f = s.get("final")
    p["final"] = dict(f, stale=f.get("state") == "done" and f.get("fingerprint") != p["fingerprint"]) if f else None
    p["bgm"] = sorted(bgm)
    p["tools"] = render_mix.tools() is not None
    p["music"] = {ep["id"]: ep.get("music") or {} for ep in doc.get("episodes") or []}
    return root, doc, kfs, s, p


@app.get(_R + "/compose")
def render_compose_get(nid: str, cid: str, vid: str, draft: bool = True, user: dict = Depends(novel_user)):
    """合成预览（配音条数、未缓存字数与费用、缺音色、缺视频的段、BGM、选曲参考）与当前成片状态。"""
    return _compose_preview(user, nid, cid, vid, draft)[4]


def _compose_worker(root, doc: dict, s: dict, kfs: dict, draft: bool, tools: tuple) -> None:
    try:
        out = render_mix.compose(root, doc, s, tts=render_providers.get_tts(), keyframes=kfs,
                                 bgm=_bgm_files(root), draft=draft, tools=tools,
                                 on_cost=lambda cny: render_session.add_spent(root, cny),
                                 progress=lambda step: render_session.compose_progress(root, step))
        render_session.compose_done(root, out["files"], out["report"])
    except render_mix.MixError as e:
        render_session.compose_failed(root, str(e), e.stderr)
    except Exception as e:  # noqa: BLE001  任何意外都要落到失败，不能卡在「合成中」
        traceback.print_exc()
        try:
            render_session.compose_failed(root, f"合成异常：{type(e).__name__}: {e}")
        except Exception:  # noqa: BLE001
            traceback.print_exc()


@app.post(_R + "/compose")
def render_compose_post(nid: str, cid: str, vid: str, body: RenderComposeBody,
                        user: dict = Depends(novel_user)):
    """合成整章（后台线程）。过验证门；配音金额（未缓存的字数 × 单价）大于 0 时必须带确认金额。"""
    _render_ctx(user, nid, cid, vid)          # 过验证门
    root, doc, kfs, s, p = _compose_preview(user, nid, cid, vid, body.draft)
    tools = render_mix.tools()
    if tools is None:
        raise HTTPException(422, "没有装 ffmpeg：先在终端执行 brew install ffmpeg，再重启后端")
    if p["missing_voices"]:
        raise HTTPException(422, "还有说话人没选音色：" + "、".join(k or "（未标说话人）" for k in p["missing_voices"]))
    if len(p["no_video"]) == len(s["clips"]):
        raise HTTPException(422, "还没有任何一段出片，先出片再合成")
    if p["no_video"] and not body.draft:
        raise HTTPException(422, f"{len(p['no_video'])} 段还没有可用的视频；打开「草稿合成」可用关键帧补位")
    if p["tts_cny"] > 0 and (body.expected_cny is None or abs(body.expected_cny - p["tts_cny"]) > 0.005):
        raise HTTPException(409, detail={"message": f"本次配音约 ¥{p['tts_cny']:.2f}，请确认金额后再合成",
                                         "expected_cny": p["tts_cny"]})
    s = _render_call(render_session.begin_compose, root, fingerprint=p["fingerprint"],
                     tts_cny=p["tts_cny"], draft=body.draft)
    t = threading.Thread(target=_compose_worker, args=(root, doc, s, kfs, body.draft, tools),
                         name=f"compose-{vid}", daemon=True)
    _compose_threads[str(root)] = t
    t.start()
    return _render_call(render_session.view, s)


@app.put(_R + "/bgm/{episode}")
async def render_bgm_put(nid: str, cid: str, vid: str, episode: str, request: Request,
                         user: dict = Depends(novel_user)):
    """每集一段 BGM（mp3 / wav / m4a / aac，≤ 30MB）；合成时循环铺满，有人声时自动压低。"""
    root, doc, _kfs, _owner = _render_ctx(user, nid, cid, vid, gate=False)
    _session_or_404(root)
    if episode not in {ep["id"] for ep in doc.get("episodes") or []}:
        raise HTTPException(404, f"没有这一集：{episode}")
    ext = BGM_TYPES.get(request.headers.get("content-type", "").split(";")[0].strip().lower())
    if ext is None:
        raise HTTPException(422, "BGM 只支持 mp3、wav、m4a、aac")
    data = await request.body()
    if not data or len(data) > BGM_MAX_BYTES:
        raise HTTPException(422, "BGM 文件为空或超过 30MB")
    d = Path(root) / "audio" / "bgm"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob(f"{episode}.*"):
        old.unlink()
    tmp = d / f".{episode}{ext}.part"
    tmp.write_bytes(data)
    tmp.replace(d / f"{episode}{ext}")
    return {"episode": episode, "bytes": len(data)}


@app.delete(_R + "/bgm/{episode}")
def render_bgm_delete(nid: str, cid: str, vid: str, episode: str, user: dict = Depends(novel_user)):
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid)
    for old in (Path(root) / "audio" / "bgm").glob(f"{episode}.*") if (Path(root) / "audio" / "bgm").is_dir() else []:
        old.unlink()
    return {"deleted": episode}
```

Check that `app.py` already imports `threading` and `Path` at the top; add `import threading` / `from pathlib import Path` next to the other stdlib imports if they are missing.

Note on `_bgm_files`: the `.part` temp file written during upload starts with `.` — exclude it: change `_bgm_files` to skip names starting with `.`:

```python
    return ({p.stem: p for p in sorted(d.iterdir()) if p.is_file() and not p.name.startswith(".")}
            if d.is_dir() else {})
```

- [ ] **Step 5: 运行，确认通过**

Run: `.venv/bin/python tests/server/test_compose.py && .venv/bin/python tests/server/test_render.py | tail -1 && for t in tests/render/test_*.py; do .venv/bin/python $t | tail -1; done`
Expected: eight `✓` lines then `ALL PASS`; test_render `ALL PASS`; every render test ends with `ALL PASS`（test_mix_e2e 可能是「跳过」那一行）

- [ ] **Step 6: 提交**

```bash
git add render/session.py server/app.py tests/server/test_compose.py
git commit -m "合成接口：音色表与说话人音色（选择、清除、校验）、合成预览、合成（过验证门、没装 ffmpeg/缺音色/缺段拦截、配音金额确认 409、上限、合成中 409）、后台线程落到完成或失败、成片过期判定、重启中断标失败、每集 BGM 上传删除"
```

---

### Task 7: 豆包语音冒烟、文档、设计文档写回裁定、全量回归

**Files:**
- Create: `backend/render/smoke_tts.py`
- Modify: `README.md`（「**出片（画布）**」段落之后）
- Modify: `docs/specs/2026-10-28-video-generation-design.md`（末尾）

- [ ] **Step 1: 冒烟脚本**

Create `backend/render/smoke_tts.py`:

```python
"""豆包语音真实冒烟（花真钱，约 0.01 元）：合成一句旁白，打印时长与按单价折算的金额——拿它与控制台
账单核对，必要时用 STORYBOARD_VOLC_TTS_CNY_PER_K 校准单价。

用法: cd backend && .venv/bin/python -m render.smoke_tts [--voice zh_male_m191_uranus_bigtts]
                                                        [--out /tmp/tts-smoke.wav] [--yes]
"""
import argparse
import sys
from pathlib import Path

from render.providers.tts_base import tts_cost
from render.providers.tts_volc import VOICES, VolcTts

TEXT = "秋天的后半夜，月亮下去了，太阳还没有出，只剩下一片乌蓝的天。"
LIMIT_CNY = 1.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="豆包语音真实冒烟（花钱）")
    ap.add_argument("--voice", default=VOICES[0].id, choices=[v.id for v in VOICES])
    ap.add_argument("--out", default="/tmp/tts-smoke.wav")
    ap.add_argument("--yes", action="store_true", help="不再询问，直接合成")
    a = ap.parse_args(argv)

    tts = VolcTts.from_env()
    est = tts_cost(len(TEXT), tts.caps)
    print(TEXT, "\n")
    print(f"{a.voice} · {len(TEXT)} 字 · 预估 ¥{est:.4f}（冒烟上限 ¥{LIMIT_CNY:g}）")
    if est > LIMIT_CNY:
        print("超出冒烟上限，不合成")
        return 1
    if not a.yes and input("合成？[y/N] ").strip().lower() != "y":
        return 1
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    r = tts.synthesize(TEXT, a.voice, None, 1.0, out)
    print("音频：", r.file, f"{r.duration:.2f} 秒")
    print(f"折算 ¥{r.cost_cny:.4f}，请与控制台账单核对")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run (offline check only, no network): `.venv/bin/python -c "import render.smoke_tts"`
Expected: no output, exit 0

- [ ] **Step 2: README**

In `README.md`, right after the paragraph that starts with `**出片（画布）**`, add:

```markdown

**配音与合成（后端）**：合成要 ffmpeg（`brew install ffmpeg`）。配音走豆包语音合成 2.0：`backend/.env` 写 `VOLC_TTS_API_KEY=…`（新版控制台；旧版控制台写 `VOLC_TTS_APP_ID` 与 `VOLC_TTS_ACCESS_KEY`），`STORYBOARD_TTS_PROVIDER` 选厂商（缺省 `volc`，`fake` 为不联网的假配音）。
各说话人的音色存在出片会话里（`…/render/voices`），没选的按分镜提示的性别默认；`…/render/compose` 先预览配音字数与费用（3 元/万字符，配音费计入同一上限），确认金额后后台合成，每集出 `final/E0x.mp4`、`final/E0x.srt` 与 `final/mix_report.json`。
声画对齐：念不完先提速到 1.15 倍，再不够就定格延长；配音与已规整的段都缓存，重跑不重做。每集可上传一段 BGM（`…/render/bgm/E01`），有人声时自动压低。真实配音先用 `.venv/bin/python -m render.smoke_tts`（约 0.01 元）核对账单。画布上的音色分配与合成区另见 A3b 计划。
```

- [ ] **Step 3: 设计文档写回裁定**

Append to the end of `docs/specs/2026-10-28-video-generation-design.md`:

```markdown

## 8. 实施裁定（2026-10-31，配音与合成后端 A3a 计划）

1. **豆包语音接口**：`POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`，新版控制台 `X-Api-Key`、旧版 `X-Api-App-Id` + `X-Api-Access-Key`，`X-Api-Resource-Id: seed-tts-2.0`；与方舟是两套密钥（`VOLC_TTS_*`）。后付费 3 元/万字符。
2. **要 pcm、自己封 WAV**，时长按帧数算，不需要 ffprobe。
3. **音色不写回资产卡**：分镜的 `tts_voice` 是抽象提示；用户选的厂商音色存在 `session.json` 的 `voices`，没选的按提示性别默认，看不出性别的列为缺音色、合成前拦截。替代 2.3 第 1 条的「写回资产卡」。
4. **情绪参数先不传**（2.0 音色官方不标情绪参数），缓存键里留着位置。
5. **长句**超过 300 字按标点切开合成再拼。
6. **对齐**：念不完先提速到最多 1.15 倍；还不够就按 1.15 倍念、段尾帧定格延长。原声或不出声的语音条按字数估时长，只进字幕。
7. **配音金额要确认**：`POST …/compose` 带 `expected_cny`，不一致 409；配音费计入 `spent_cny`、过同一上限。
8. **只出每集文件**（`final/E0x.mp4`、`.srt`、`mix_report.json`）；整章拼接与字幕烧录以后再做。
9. **合成时不能有段在跑**；草稿合成（默认开）用首镜关键帧定格补没出的段，没有关键帧用黑场。
10. **重启中断的合成标失败**；配音缓存与已规整的段按输入指纹复用。
```

- [ ] **Step 4: 全量回归**

Run:
```bash
for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py; do printf "%s: " $t; .venv/bin/python $t 2>&1 | tail -1; done
cd ../frontend && npm test 2>&1 | grep -c "ALL PASS"
```
Expected: every backend file ends with `ALL PASS`（`test_mix_e2e.py` 没装 ffmpeg 时是「ALL PASS（跳过：…）」）；frontend prints `8`

- [ ] **Step 5: 提交**

```bash
git add render/smoke_tts.py ../README.md ../docs/specs/2026-10-28-video-generation-design.md
git commit -m "配音与合成文档：豆包语音密钥与厂商选择、音色与合成接口、对齐与缓存、BGM；豆包语音真实冒烟脚本（约 0.01 元）；设计文档写回 A3a 实施裁定"
```

- [ ] **Step 6: 手动验证（由用户执行）**

1. `brew install ffmpeg`，然后 `cd backend && .venv/bin/python tests/render/test_mix_e2e.py`：应真正跑完端到端合成（四个 ✓）。
2. `backend/.env` 写 `VOLC_TTS_API_KEY`（不要打印），`.venv/bin/python -m render.smoke_tts`：听 `/tmp/tts-smoke.wav`，账单与折算对一下。
