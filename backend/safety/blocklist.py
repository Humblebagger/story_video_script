"""明确违规词表：只在服务端，不进前端、不进语言包。命中即拦，不调模型。"""
import hashlib
import json
from pathlib import Path
from typing import List, Optional, Tuple

from safety.categories import CLASSIFIER_CODES
from safety.text import normalize

FILE = Path(__file__).with_name("blocklist.json")
_RAW = FILE.read_bytes()
_HASH = hashlib.sha256(_RAW).hexdigest()[:12]
_WORDS: List[Tuple[str, str]] = [
    (str(w["text"]).strip().lower(), str(w["category"]))
    for w in json.loads(_RAW.decode("utf-8"))["words"]
    if str(w.get("text", "")).strip() and w.get("category") in CLASSIFIER_CODES]


def words() -> List[Tuple[str, str]]:
    return list(_WORDS)


def file_hash() -> str:
    """词表文件的短 hash：并进策略版本，词表改了旧结论自动失效。"""
    return _HASH


def match(text) -> Optional[str]:
    """命中的第一条词的类别；没命中返回 None。不分大小写。"""
    low = normalize(text).lower()
    for word, category in _WORDS:
        if word in low:
            return category
    return None
