"""价格表：每百万 token 的美元单价。

金额在查询时按当前价格表现算——改了价格，历史金额随之重算，页面注明「按当前价格表估算」。
默认价来自 2026-10 Anthropic 官方价目；走网关或用别的模型时在后台改。
"""
import copy
import json
import math
from typing import Optional

from server.auth import DATA_DIR
from server.messages import UserError
from server.store import now_iso

class PricingError(UserError, ValueError):
    """价格表校验不过（400）。"""


PRICING_FILE = DATA_DIR / "pricing.json"
KEYS = ("input", "output", "cache_read", "cache_write")
VENDOR_MAX = 40

DEFAULT = {
    "currency": "USD",
    "note": "每百万 token 单价（美元）",
    "updated_at": None,
    "models": {
        "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5, "vendor": "Anthropic"},
        "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5, "vendor": "Anthropic"},
        "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.2, "cache_write": 5.0, "vendor": "Anthropic"},
        "claude-haiku-5-5": {"input": 0.1, "output": 0.5, "cache_read": 0.01, "cache_write": 0.125, "vendor": "Anthropic"},
    },
}


def load() -> dict:
    if PRICING_FILE.exists():
        try:
            return json.loads(PRICING_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return copy.deepcopy(DEFAULT)


def _validate(table: dict) -> dict:
    models = table.get("models")
    if not isinstance(models, dict) or not models:
        raise PricingError.of("admin.pricing.empty")
    clean = {}
    for name, price in models.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(price, dict):
            raise PricingError.of("admin.pricing.bad_row", name=str(name))
        row = {}
        for k in KEYS:
            v = price.get(k)
            if (not isinstance(v, (int, float)) or isinstance(v, bool)
                    or not math.isfinite(v) or v < 0):
                raise PricingError.of("admin.pricing.bad_price", name=name, key=k)
            row[k] = float(v)
        vendor = price.get("vendor")
        if "vendor" in price:
            if not isinstance(vendor, str) or len(vendor.strip()) > VENDOR_MAX:
                raise PricingError.of("admin.pricing.bad_row", name=name)
            if vendor.strip():
                row["vendor"] = vendor.strip()
        clean[name.strip()] = row
    return clean


def save(table: dict) -> dict:
    out = {"currency": "USD", "note": DEFAULT["note"], "updated_at": now_iso(),
           "models": _validate(table)}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PRICING_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PRICING_FILE)
    return out


def cost(row: dict, table: dict) -> Optional[float]:
    """一条用量记录的金额；模型没定价返回 None。"""
    price = (table.get("models") or {}).get(row.get("model") or "")
    if price is None:
        return None
    return sum((row.get(k) or 0) * price.get(k, 0) for k in KEYS) / 1e6
