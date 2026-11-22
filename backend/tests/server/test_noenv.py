#!/usr/bin/env python3
"""_noenv 的 .env 绊线：各读取入口碰到名为 .env 的文件都被拦下并记违规。
只用临时目录里的假 .env，绝不碰真实 backend/.env。用法: python3 tests/server/test_noenv.py"""
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _noenv  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        fake = Path(d) / ".env"
        fake.write_text("K=V\n", encoding="utf-8")
        entries = {
            "Path.read_text": lambda: fake.read_text(),
            "Path.read_bytes": lambda: fake.read_bytes(),
            "Path.open": lambda: fake.open(),
            "open(str)": lambda: open(str(fake)),
            "open(bytes)": lambda: open(os.fsencode(fake)),
            "io.open": lambda: io.open(fake),
        }
        for name, fn in entries.items():
            _noenv.VIOLATIONS.clear()
            try:
                fn()
            except AssertionError:
                pass
            else:
                raise AssertionError(f"{name} 没被拦住")
            assert _noenv.VIOLATIONS == [".env"], (name, _noenv.VIOLATIONS)
        _noenv.VIOLATIONS.clear()
        other = Path(d) / "a.txt"
        other.write_text("x", encoding="utf-8")
        assert other.read_text() == "x" and other.read_bytes() == b"x"        # 别的文件照读
        with open(other) as f, io.open(other) as g, other.open() as h:
            assert f.read() == g.read() == h.read() == "x"
    assert _noenv.problems() == []
    print("✓ .env 绊线覆盖各读取入口")
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
