"""长文自动分批：在段落（行）边界切分，优先在章节分节符处断开。

保证各批拼接后与原文逐字节一致（含换行与不可见字符），这是保真度检查的前提。
"""
import re
from typing import List

# 单独成行的章节数字/分节符（"一""二""3"等）
_SECTION_RE = re.compile(r"^\s*[一二三四五六七八九十百0-9]{1,4}\s*$")


def split_batches(text: str, target_chars: int = 2500,
                  single_max_chars: int = 3200) -> List[str]:
    if len(text) <= single_max_chars:
        return [text]

    lines = text.splitlines(keepends=True)
    batches: List[str] = []
    cur: List[str] = []
    cur_len = 0
    section_cut_min = max(target_chars // 2, 1000)  # 分节符处提前断批的最小体量

    for line in lines:
        at_section = _SECTION_RE.match(line) and line.strip()
        if cur and (cur_len >= target_chars or (at_section and cur_len >= section_cut_min)):
            batches.append("".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line)
    if cur:
        # 尾批过小则并入上一批，避免产生无意义的小批
        if batches and cur_len < target_chars // 4:
            batches[-1] += "".join(cur)
        else:
            batches.append("".join(cur))

    assert "".join(batches) == text, "分批拼接与原文不一致（splitter 内部错误）"
    return batches
