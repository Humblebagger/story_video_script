"""内容检查用的文本工具：规范化、hash、切段、摘录。"""
import hashlib
import re
from typing import List

SEG_MAX = 6000
EXCERPT_MAX = 300
_NEWLINES = re.compile(r"\r\n?|\u2028|\u2029")


def normalize(text) -> str:
    """去首尾空白、统一换行。结论缓存按规范化后的文本算 hash。"""
    return _NEWLINES.sub("\n", str(text or "")).strip()


def text_hash(text) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def split_segments(text, limit: int = SEG_MAX) -> List[str]:
    """按段落边界装箱成每段不超过 limit 字；单个段落超长时硬切。空文本返回空列表。"""
    body = normalize(text)
    if not body:
        return []
    out, cur = [], ""
    for para in body.split("\n"):
        while len(para) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(para[:limit])
            para = para[limit:]
        joined = f"{cur}\n{para}" if cur else para
        if len(joined) > limit:
            out.append(cur)
            cur = para
        else:
            cur = joined
    if cur:
        out.append(cur)
    return out


def excerpt(text, limit: int = EXCERPT_MAX) -> str:
    return normalize(text)[:limit]
