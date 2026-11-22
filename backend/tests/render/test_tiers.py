#!/usr/bin/env python3
"""出片档位映射表：中性 id ↔（厂商，档位）、界面可选档位、后台对照表。用法: python3 tests/render/test_tiers.py"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# 测试不读真实的 .env：各处 _load_dotenv 换成空操作
import pipeline.config as _pc  # noqa: E402
import render.providers.minimax as _mm  # noqa: E402
import render.providers.seedance as _sd  # noqa: E402
_pc._load_dotenv = _mm._load_dotenv = _sd._load_dotenv = lambda *_a, **_k: None

os.environ.pop("MINIMAX_API_KEY", None)
os.environ.pop("ARK_API_KEY", None)
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"

from render import providers, tiers  # noqa: E402
from render.providers import minimax, seedance  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from server import messages as M, public as P  # noqa: E402

# 1. 双向换算；不认识的
assert tiers.resolve("a-standard") == ("minimax", "minimax-h3") and tiers.resolve("b-lite") == ("seedance", "seedance-2.0-mini")
assert tiers.tier_of("seedance", "seedance-2.0-fast") == "b-fast" and tiers.tier_of("minimax", "nope") is None
try:
    tiers.resolve("minimax-h3")
    raise AssertionError("应抛 KeyError")
except KeyError:
    pass
# 2. 表与厂商模块对得上
for tid, p, m in tiers.TIERS:
    table = {"minimax": minimax.MODELS, "seedance": seedance.MODELS, "fake": {"fake-1": {}}}[p]
    assert m in table, (tid, p, m)
assert {m for _, p, m in tiers.TIERS if p == "minimax"} == set(minimax.MODELS)
assert {m for _, p, m in tiers.TIERS if p == "seedance"} == set(seedance.MODELS)
assert len({t for t, _, _ in tiers.TIERS}) == len(tiers.TIERS)
# 3. 显示名是登记过的消息，id 与显示名里没有厂商词
for tid, _, _ in tiers.TIERS:
    assert M.registered(tiers.label(tid)["code"]) and not P.find_vendor_words([tid, M.render_zh(tiers.label(tid)["code"], {})])
# 4. options：没配密钥的厂商不列；假厂商设为默认时列 demo；字段齐全
providers.register("fake", lambda: FakeVideo())
(o,) = tiers.options()
assert o["id"] == "demo" and o["resolutions"] == ["480p", "720p"] and o["default_resolution"] == "720p"
assert o["cny_per_sec"] == {"480p": 0.5, "720p": 1.0} and "tts_all" in o["audio_modes"] and o["label"] == tiers.label("demo")
# 5. 配了密钥（假值，不联网）就列出来
os.environ["MINIMAX_API_KEY"] = "k-test"
assert [x["id"] for x in tiers.options()] == ["a-standard", "a-fast", "a-lite", "demo"]
# 6. 后台表：带厂商与密钥状态
rows = {r["id"]: r for r in tiers.admin_table()}
assert rows["a-standard"] == {"id": "a-standard", "provider": "minimax", "model": "minimax-h3",
                              "vendor_label": minimax.MODELS["minimax-h3"]["label"], "key_configured": True}
assert rows["b-fast"]["vendor_label"] == seedance.MODELS["seedance-2.0-fast"]["label"] and rows["demo"]["vendor_label"] == "fake"
assert rows["b-fast"]["key_configured"] is False and rows["demo"]["key_configured"] is True

print("ALL PASS")
