#!/usr/bin/env python3
"""原文保真度检查：source.units[].text 顺序拼接后必须与小说原文逐字一致。

用法: python3 tools/check_fidelity.py <storyboard.json> <input.txt>

<input.txt> 支持两种格式：
  - 用户输入模板（自动提取「章节：」行之后的正文）
  - 纯正文文本

比较时忽略空白字符（空格/换行/制表符），其余字符必须完全一致。
"""
import json
import re
import sys
from pathlib import Path


def extract_passage(text: str) -> str:
    m = re.search(r"^章节：.*$", text, flags=re.M)
    return text[m.end():] if m else text


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def main(json_path: str, input_path: str) -> int:
    doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
    original = squash(extract_passage(Path(input_path).read_text(encoding="utf-8")))
    joined = squash("".join(u["text"] for u in doc.get("source", {}).get("units", [])))

    if joined == original:
        print(f"PASS 原文保真：{len(doc['source']['units'])} 个 unit 拼接后与原文逐字一致（{len(original)} 字符）")
        return 0

    # 定位第一个差异点，给出上下文
    i = 0
    for i, (a, b) in enumerate(zip(joined, original)):
        if a != b:
            break
    else:
        i = min(len(joined), len(original))
    lo, hi = max(0, i - 15), i + 15
    print("FAIL 原文保真：unit 拼接与原文不一致")
    print(f"  首个差异位置 {i}")
    print(f"  units 侧: …{joined[lo:hi]}…")
    print(f"  原文 侧: …{original[lo:hi]}…")
    print(f"  长度: units={len(joined)} 原文={len(original)}")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
