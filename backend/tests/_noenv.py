"""测试不读真实的 .env：把所有 _load_dotenv 换成空操作，并设两道保险（import 本模块即生效）。

1. 绊线：pathlib.Path.read_text / builtins.open 碰到名为 .env 的文件就记一条违规并抛 AssertionError（不读内容）。
2. 退出核对：没有任何已加载模块还持有真实的 _load_dotenv，且没有违规；否则打印原因并以非 0 退出。
用法：在 `sys.path.insert(0, str(ROOT))` 之后、导入 server.* / render.* 之前
    sys.path.insert(0, str(ROOT / "tests")); import _noenv  # noqa: E402,F401
"""
import atexit
import builtins
import importlib
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipeline.config as _pc  # noqa: E402

REAL = _pc._load_dotenv
VIOLATIONS: list = []
CALLS: list = []


def _stub(*_a, **_k):
    CALLS.append(1)


def _is_env(p) -> bool:
    try:
        return pathlib.PurePath(os.fspath(p)).name == ".env"
    except TypeError:
        return False


_real_read_text = pathlib.Path.read_text
_real_open = builtins.open


def _read_text(self, *a, **k):
    if _is_env(self):
        VIOLATIONS.append(str(self.name))
        raise AssertionError("测试不得读取 .env")
    return _real_read_text(self, *a, **k)


def _open(file, *a, **k):
    if not isinstance(file, int) and _is_env(file):
        VIOLATIONS.append(".env")
        raise AssertionError("测试不得读取 .env")
    return _real_open(file, *a, **k)


def install() -> None:
    pathlib.Path.read_text = _read_text
    builtins.open = _open
    for name in ("pipeline.config", "render.providers.minimax", "render.providers.seedance", "render.providers.tts_volc"):
        setattr(importlib.import_module(name), "_load_dotenv", _stub)


def problems() -> list:
    out = [f"读取了 {v}" for v in VIOLATIONS]
    for name, mod in list(sys.modules.items()):
        if getattr(mod, "_load_dotenv", None) is REAL:
            out.append(f"{name} 仍持有真实的 _load_dotenv")
    return out


def _at_exit() -> None:
    bad = problems()
    if bad:
        print("✗ _noenv：" + "；".join(bad), file=sys.stderr)
        sys.stderr.flush()
        os._exit(1)


install()
atexit.register(_at_exit)
