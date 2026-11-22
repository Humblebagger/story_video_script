"""测试不读真实的 .env：把所有 _load_dotenv 换成空操作，并清掉 shell 里的厂商密钥环境变量，另设两道保险（import 本模块即生效）。

1. 绊线：Path.read_text / read_bytes / open、builtins.open、io.open（含 bytes 路径）碰到名为 .env 的文件就记一条违规并抛 AssertionError（不读内容）。
2. 退出核对：没有任何已加载模块还持有真实的 _load_dotenv，且没有违规；否则打印原因并以非 0 退出。
用法：在 `sys.path.insert(0, str(ROOT))` 之后、导入 server.* / render.* 之前
    sys.path.insert(0, str(ROOT / "tests")); import _noenv  # noqa: E402,F401
"""
import atexit
import builtins
import importlib
import io
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
        return pathlib.PurePath(os.fsdecode(os.fspath(p))).name == ".env"
    except (TypeError, ValueError):
        return False


_real_read_text = pathlib.Path.read_text
_real_read_bytes = pathlib.Path.read_bytes
_real_path_open = pathlib.Path.open
_real_open = builtins.open
_real_io_open = io.open


def _trip(p, a=(), k=None):
    mode = str((a[0] if a else (k or {}).get("mode", "r")))
    if "+" not in mode and any(c in mode for c in "wax"):       # 只豁免纯写（测试在临时目录造假 .env）；带 + 的读写模式要拦
        return
    if not isinstance(p, int) and _is_env(p):
        VIOLATIONS.append(".env")
        raise AssertionError("测试不得读取 .env")


def _read_text(self, *a, **k):
    _trip(self)
    return _real_read_text(self, *a, **k)


def _read_bytes(self, *a, **k):
    _trip(self)
    return _real_read_bytes(self, *a, **k)


def _path_open(self, *a, **k):
    _trip(self, a, k)
    return _real_path_open(self, *a, **k)


def _open(file, *a, **k):
    _trip(file, a, k)
    return _real_open(file, *a, **k)


def _io_open(file, *a, **k):
    _trip(file, a, k)
    return _real_io_open(file, *a, **k)


VENDOR_ENVS = ("MINIMAX_API_KEY", "ARK_API_KEY", "VOLC_TTS_API_KEY", "VOLC_TTS_APP_ID", "VOLC_TTS_ACCESS_KEY")


def install() -> None:
    os.environ["STORYBOARD_SAFETY"] = "0"   # 内容检查在测试里缺省关掉（要测它的脚本自己设回 1）
    for k in VENDOR_ENVS:           # shell 里的厂商密钥不能影响「只有假厂商」之类的断言；要用的测试自己设
        os.environ.pop(k, None)
    pathlib.Path.read_text = _read_text
    pathlib.Path.read_bytes = _read_bytes
    pathlib.Path.open = _path_open
    builtins.open = _open
    io.open = _io_open
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
