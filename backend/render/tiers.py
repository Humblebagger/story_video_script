"""出片档位：给普通用户的中性 id ↔（厂商，厂商内档位）。映射只在这里；接口只收发中性 id，会话文件里仍存厂商与档位
（spec 2026-11-21-vendor-name-cleanup §5）。新增厂商或档位：在 TIERS 加一行，并在 server/messages.py 登记 tier.<id>。"""
from typing import Optional

from render import providers
from render.providers import base

# (档位 id, 厂商, 厂商内档位)；顺序即界面上的顺序
TIERS = (
    ("a-standard", "minimax", "minimax-h3"),
    ("a-fast", "minimax", "minimax-h3-highspeed"),
    ("a-lite", "minimax", "minimax-h3-lite"),
    ("b-standard", "seedance", "seedance-2.0"),
    ("b-fast", "seedance", "seedance-2.0-fast"),
    ("b-lite", "seedance", "seedance-2.0-mini"),
    ("demo", "fake", "fake-1"),
)


def label(tier_id: str) -> dict:
    return {"code": "tier." + tier_id.replace("-", "_"), "params": {}}


def resolve(tier_id: str) -> tuple:
    """中性 id → (厂商, 厂商内档位)；不认识抛 KeyError。"""
    for tid, p, m in TIERS:
        if tid == tier_id:
            return p, m
    raise KeyError(tier_id)


def tier_of(provider: Optional[str], model: Optional[str]) -> Optional[str]:
    """(厂商, 厂商内档位) → 中性 id；表里没有（下线了的档位、测试里临时注册的厂商）返回 None。"""
    return next((tid for tid, p, m in TIERS if (p, m) == (provider, model)), None)


def _has_key(provider: str) -> bool:
    return provider not in providers._KEY_ENV or providers._has_key(provider)


def options() -> list:
    """界面可选的档位：厂商在可选名单里（假厂商只在被设为默认时）、密钥已配、对象建得起来。
    每项带那一档的分辨率、缺省分辨率、每秒价格、可选的声音模式——换档时界面不用先应用就能把这些一起选好。"""
    from render import compose      # 放函数里：compose 不依赖本模块，避免导入环
    usable = set(providers.names())
    out = []
    for tid, p, m in TIERS:
        if p not in usable or not _has_key(p):
            continue
        try:
            caps = providers.get_video(p).caps(m)
        except (KeyError, base.ProviderError):
            continue
        res = list(caps.resolutions)
        out.append({"id": tid, "label": label(tid), "resolutions": res,
                    "default_resolution": "720p" if "720p" in res else res[0],
                    "cny_per_sec": dict(caps.cny_per_sec), "audio_modes": compose.audio_modes(caps)})
    return out


def _vendor_label(provider: str, model: str) -> str:
    """厂商自己的档位名：读各厂商模块的静态档位表，不建厂商对象、不需要密钥。只给管理员接口用。"""
    if provider == "minimax":
        from render.providers import minimax
        return minimax.MODELS[model]["label"]
    if provider == "seedance":
        from render.providers import seedance
        return seedance.MODELS[model]["label"]
    return provider


def admin_table() -> list:
    """给管理员：每个档位背后是谁、厂商自己怎么叫它、密钥配了没有。只在 /admin 接口里用。"""
    return [{"id": tid, "provider": p, "model": m, "vendor_label": _vendor_label(p, m), "key_configured": _has_key(p)}
            for tid, p, m in TIERS]
