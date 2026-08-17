"""Deterministic source segmentation and immutable source-unit identities."""
import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, List


_SECTION_RE = re.compile(r"^[一二三四五六七八九十百0-9]{1,4}$")
_SPEECH_LEAD_RE = re.compile(
    r"(?:说|说道|道|问|问道|答|答道|喊|喊道|叫|叫道|嚷|嚷道|喝道|叹道|笑道|骂道|吼道)[：:,，]?\s*$"
)
_OPEN_QUOTES = {"“": "”", "‘": "’", "「": "」", "『": "』"}
_END_PUNCTUATION = set("。！？?!")


@dataclass(frozen=True)
class FrozenUnit:
    id: str
    text: str
    para: int
    start: int
    end: int
    batch: int
    sha256: str

    def prompt_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "para": self.para}

    def manifest_dict(self) -> dict:
        return {
            **self.prompt_dict(),
            "start": self.start,
            "end": self.end,
            "batch": self.batch,
            "sha256": self.sha256,
        }


def _has_speech_lead(text: str) -> bool:
    return text.rstrip().endswith(("：", ":")) or bool(_SPEECH_LEAD_RE.search(text))


def _sentence_ranges(line: str) -> Iterable[tuple[int, int]]:
    """Yield deterministic sentence ranges within one non-empty source line.

    Quoted punctuation stays with its attribution. A quote preceded by a speech
    lead ("he said: '...'") closes the current sentence when another sentence
    follows on the same line. This is intentionally conservative: stable source
    identities matter more than reproducing every literary ambiguity.
    """
    start = 0
    stack: list[tuple[str, int]] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch in _OPEN_QUOTES:
            stack.append((_OPEN_QUOTES[ch], i))
        elif stack and ch == stack[-1][0]:
            _, quote_start = stack.pop()
            if not stack and quote_start > start and i + 1 < len(line):
                if _has_speech_lead(line[start:quote_start]):
                    yield start, i + 1
                    start = i + 1
        elif ch in _END_PUNCTUATION and not stack:
            yield start, i + 1
            start = i + 1
        i += 1
    if line[start:].strip():
        yield start, len(line)


def build_frozen_units(text: str, batches: List[str]) -> List[FrozenUnit]:
    """Build immutable units for batches whose exact concatenation is text."""
    if "".join(batches) != text:
        raise ValueError("explicit batches must concatenate exactly to normalized source text")

    units: list[FrozenUnit] = []
    text_offset = 0
    para = 0
    for batch_index, batch in enumerate(batches, 1):
        for match in re.finditer(r"[^\r\n]+", batch):
            raw_line = match.group(0)
            if not raw_line.strip():
                continue
            para += 1
            left_trim = len(raw_line) - len(raw_line.lstrip())
            line = raw_line.strip()
            line_start = text_offset + match.start() + left_trim
            ranges = [(0, len(line))] if _SECTION_RE.fullmatch(line) else list(_sentence_ranges(line))
            for local_start, local_end in ranges:
                fragment = line[local_start:local_end]
                leading = len(fragment) - len(fragment.lstrip())
                trailing = len(fragment) - len(fragment.rstrip())
                unit_text = fragment.strip()
                if not unit_text:
                    continue
                start = line_start + local_start + leading
                end = line_start + local_end - trailing
                units.append(FrozenUnit(
                    id=f"u{len(units) + 1:04d}",
                    text=unit_text,
                    para=para,
                    start=start,
                    end=end,
                    batch=batch_index,
                    sha256=hashlib.sha256(unit_text.encode("utf-8")).hexdigest(),
                ))
        text_offset += len(batch)
    return units


def prompt_units(units: Iterable[FrozenUnit], batch: int) -> list[dict]:
    return [u.prompt_dict() for u in units if u.batch == batch]


def manifest_units(units: Iterable[FrozenUnit]) -> list[dict]:
    return [u.manifest_dict() for u in units]
