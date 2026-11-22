#!/usr/bin/env python3
"""内容限制的基础件：规范化与 hash、切段、摘录、词表匹配。用法: python3 tests/safety/test_text_blocklist.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

from safety import blocklist, categories, text  # noqa: E402


def main() -> int:
    # 0. _noenv 明确关掉内容检查，不被 shell 里继承的 1 带偏
    import os
    import subprocess
    out = subprocess.run([sys.executable, "-c", "import _noenv, os; print(os.environ['STORYBOARD_SAFETY'])"],
                         cwd=str(ROOT / "tests"), env={**os.environ, "STORYBOARD_SAFETY": "1"},
                         capture_output=True, text=True)
    assert out.stdout.strip() == "0", (out.stdout, out.stderr)
    print("0. _noenv 关闭内容检查 ✓")

    # 1. 规范化：去首尾空白、统一换行；hash 只看规范化后的文本
    assert text.normalize("  a\r\nb\rc\n ") == "a\nb\nc"
    assert text.text_hash("a\r\nb") == text.text_hash(" a\nb \n") and len(text.text_hash("x")) == 64
    assert text.text_hash("a") != text.text_hash("b")
    assert text.normalize("a\u2028b\u2029c") == "a\nb\nc"
    assert text.text_hash("a\u2028b") == text.text_hash("a\nb") == text.text_hash("a\r\nb")
    assert text.text_hash("a\u2029b") == text.text_hash("a\nb")
    src = Path(text.__file__).read_text(encoding="utf-8")
    assert "\u2028" not in src and "\u2029" not in src, "源码里不留字面的行分隔符"
    print("1. 规范化与 hash ✓")

    # 2. 切段：不超过上限、段落边界优先、拼回去等于原文；单段超长硬切
    paras = ["甲" * 2500, "乙" * 2500, "丙" * 2500]
    segs = text.split_segments("\n".join(paras), limit=6000)
    assert [len(s) for s in segs] == [5001, 2500] and "\n".join(segs) == "\n".join(paras), [len(s) for s in segs]
    long = text.split_segments("丁" * 13000, limit=6000)
    assert [len(s) for s in long] == [6000, 6000, 1000]
    assert text.split_segments("短文") == ["短文"] and text.split_segments("  ") == []
    print("2. 切段 ✓")

    # 3. 摘录不超过 300 字
    assert text.excerpt("字" * 500) == "字" * 300 and text.excerpt(" a ") == "a"
    print("3. 摘录 ✓")

    # 4. 类别：分类器可用的五类 + 模型拒答专用的一类
    assert categories.CLASSIFIER_CODES == ("sexual", "minor_sexual", "drugs", "political", "extremism")
    assert categories.CODES == categories.CLASSIFIER_CODES + ("unspecified",)
    assert isinstance(categories.POLICY_VERSION, str) and categories.POLICY_VERSION
    print("4. 类别 ✓")

    # 5. 词表：命中返回类别（不分大小写），没命中 None；词表里的类别都在表内；文件 hash 稳定
    assert blocklist.match("这里有 Child Porn 字样") == "minor_sexual"
    assert blocklist.match("他推门进屋，天色已晚。") is None
    assert all(c in categories.CLASSIFIER_CODES for _w, c in blocklist.words())
    assert blocklist.file_hash() == blocklist.file_hash() and len(blocklist.file_hash()) == 12
    print("5. 词表 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
