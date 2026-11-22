#!/usr/bin/env python3
"""价格表与用量流水账：落账、坏行容忍、分组汇总、计价、每千字成本、当月花费、按天序列。

全程使用临时数据目录。用法: python3 tests/server/test_usage.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前
# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None

from server import pricing, usage  # noqa: E402

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
U1, U2 = "a" * 12, "b" * 12


def tok(i=0, o=0, cr=0, cw=0, calls=1):
    return {"calls": calls, "input": i, "output": o, "cache_read": cr, "cache_write": cw}


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def main() -> int:
    # 1. 价格表：默认表、计价、未定价、保存校验
    table = pricing.load()
    assert table["currency"] == "USD" and "claude-sonnet-5" in table["models"]
    row = {"model": "claude-sonnet-5", **tok(1_000_000, 1_000_000, 1_000_000, 1_000_000)}
    assert abs(pricing.cost(row, table) - (2.0 + 10.0 + 0.2 + 2.5)) < 1e-9
    assert pricing.cost({"model": "nope", **tok(5)}, table) is None
    must_raise(ValueError, pricing.save, {"models": {"m": {"input": -1, "output": 0,
                                                          "cache_read": 0, "cache_write": 0}}})
    must_raise(ValueError, pricing.save, {"models": {"m": {"input": 1}}})
    e = must_raise(pricing.PricingError, pricing.save, {"models": {"m": {"input": -1, "output": 0,
                                                                         "cache_read": 0, "cache_write": 0}}})
    assert e.code == "admin.pricing.bad_price" and e.params == {"name": "m", "key": "input"}
    assert must_raise(pricing.PricingError, pricing.save, {"models": {}}).code == "admin.pricing.empty"
    e = must_raise(pricing.PricingError, pricing.save, {"models": {"m": "x"}})
    assert e.code == "admin.pricing.bad_row" and e.params == {"name": "m"}
    # vendor：往返保存、去空白、空串视为未填；非字符串、超长被拒；无 vendor 的旧表照常
    p4 = {"input": 1, "output": 2, "cache_read": 0, "cache_write": 0}
    out = pricing.save({"models": {"a": {**p4, "vendor": "  Acme  "}, "b": {**p4, "vendor": "  "},
                                   "c": dict(p4)}})
    assert out["models"]["a"]["vendor"] == "Acme"
    assert "vendor" not in out["models"]["b"] and "vendor" not in out["models"]["c"]
    assert pricing.load()["models"]["a"]["vendor"] == "Acme"
    for bad_vendor in (5, None, ["x"], "v" * 41):
        e = must_raise(pricing.PricingError, pricing.save, {"models": {"m": {**p4, "vendor": bad_vendor}}})
        assert e.code == "admin.pricing.bad_row" and e.params == {"name": "m"}, bad_vendor
    assert pricing.save({"models": {"m": {**p4, "vendor": "v" * 40}}})["models"]["m"]["vendor"] == "v" * 40
    assert abs(pricing.cost({"model": "a", **tok(1_000_000)}, pricing.save(
        {"models": {"a": {**p4, "vendor": "X"}}})) - 1.0) < 1e-9
    assert all(m.get("vendor") == "Anthropic" for m in pricing.DEFAULT["models"].values())
    saved = pricing.save({"models": {"claude-sonnet-5": {"input": 3, "output": 15,
                                                         "cache_read": 0.3, "cache_write": 3.75}}})
    assert saved["currency"] == "USD" and saved["updated_at"]
    assert pricing.load()["models"]["claude-sonnet-5"]["input"] == 3
    table = pricing.load()
    print("1. 价格表：默认 / 计价 / 未定价 / 保存校验 ✓")

    # 2. 落账与读取；坏行跳过
    usage.record(user_id=U1, purpose="convert", model="claude-sonnet-5",
                 usage=tok(1_000_000, 0), ok=True, chars=4000,
                 novel_id="n1", chapter_id="c1", version_id="v1",
                 at="2026-10-30T08:00:00+00:00")
    usage.record(user_id=U1, purpose="convert", model="claude-sonnet-5",
                 usage=tok(0, 100_000), ok=False, chars=2000,
                 at="2026-10-29T08:00:00+00:00")
    usage.record(user_id=U2, purpose="digest", model="mystery", usage=tok(10, 10),
                 ok=True, at="2026-10-02T08:00:00+00:00")
    usage.record(user_id=U2, purpose="convert", model="claude-sonnet-5",
                 usage=tok(0, 200_000), ok=True, chars=1000,
                 at="2026-09-20T08:00:00+00:00", mixed_models=["claude-sonnet-5", "x"])
    with open(usage.USAGE_FILE, "a", encoding="utf-8") as f:
        f.write('{"broken": \n')
    rows = usage.read()
    assert len(rows) == 4, "坏行应跳过"
    assert rows[3]["mixed_models"] == ["claude-sonnet-5", "x"]
    assert len(usage.read(since=datetime(2026, 10, 1, tzinfo=timezone.utc))) == 3
    assert len(usage.read(user_id=U2)) == 2
    print("2. 落账 / 读取 / 时间与用户过滤 / 坏行容忍 ✓")

    # 3. 分组汇总：用户、天、模型；未定价单独计数、不计入金额
    by_user = {r["key"]: r for r in usage.aggregate(rows, "user", table)}
    assert by_user[U1]["calls"] == 2 and by_user[U1]["input"] == 1_000_000
    assert abs(by_user[U1]["cost_usd"] - (3.0 + 1.5)) < 1e-9
    assert by_user[U2]["unpriced"] == 1 and abs(by_user[U2]["cost_usd"] - 3.0) < 1e-9
    assert by_user[U2]["records"] == 2 and by_user[U1]["records"] == 2, "records 按记录计数（含未定价）"
    days = [r["key"] for r in usage.aggregate(rows, "day", table)]
    assert days == sorted(days), "按天升序"
    by_model = {r["key"]: r for r in usage.aggregate(rows, "model", table)}
    assert by_model["mystery"]["cost_usd"] == 0 and by_model["mystery"]["unpriced"] == 1
    e = must_raise(usage.UsageError, usage.aggregate, rows, "bogus", table)
    assert isinstance(e, ValueError) and e.code == "usage.bad_group" and e.params == {"group": "bogus"}
    print("3. 按用户 / 天 / 模型汇总，未定价不计金额 ✓")

    # 4. 每千字成本：只算成功的 convert、有字数、已定价
    pk = usage.per_k_chars(rows, table)
    # U1 成功一次：$3 / 4000 字 → $0.75/千字；U2 成功一次：$3 / 1000 字 → $3/千字
    assert pk["n"] == 2 and abs(pk["mean"] - 1.875) < 1e-9 and abs(pk["p90"] - 3.0) < 1e-9
    assert usage.per_k_chars([], table) == {"n": 0, "mean": None, "p90": None}
    print("4. 每千字成本均值与 P90 ✓")

    # 5. 当月花费与按天序列
    assert abs(usage.month_spent(U1, table, now=NOW) - 4.5) < 1e-9
    assert usage.month_spent(U2, table, now=NOW) == 0, "9 月的不算、未定价的不算"
    series = usage.daily_series(rows, 3, table, now=NOW)
    assert [d["day"] for d in series] == ["2026-10-28", "2026-10-29", "2026-10-30"]
    assert [round(d["cost_usd"], 2) for d in series] == [0, 1.5, 3.0]
    print("5. 当月花费 / 按天序列补零 ✓")

    # 6. 未定价模型列表
    assert usage.unpriced_models(rows, table) == ["mystery"]
    print("6. 未定价模型 ✓")

    # 7. 半行恢复：崩溃留下无换行的残行，下一条不能被粘进去；时间戳异常的行跳过
    with open(usage.USAGE_FILE, "a", encoding="utf-8") as f:
        f.write('{"at": "2026-10-30T09:0')
    usage.record(user_id=U1, purpose="convert", model="claude-sonnet-5",
                 usage=tok(7), ok=True, at="2026-10-30T09:30:00+00:00")
    assert usage.read(user_id=U1)[-1]["input"] == 7, "残行后的新记录不能丢"
    with open(usage.USAGE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": "2026-10-30T10:00:00", "user_id": U1}) + "\n")  # 无时区
    got = usage.read(since=datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert got and all(r["at"] != "2026-10-30T10:00:00" for r in got), \
        "无时区的行在带时区的 since 比较时被跳过而不是抛错"
    from server import audit
    with open(audit.AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write('{"at": "x')
    audit.write({"id": "a", "username": "a"}, "probe")
    assert audit.read()[0]["action"] == "probe", "审计残行后的新记录不能丢"
    print("7. 半行恢复 / 异常时间戳跳过 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
