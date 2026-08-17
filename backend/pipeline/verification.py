"""Structured, in-process verification for storyboard artifacts."""
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .config import ROOT


SCHEMA_PATH = ROOT / "schema" / "storyboard.schema.json"
_UNIT_ID_RE = re.compile(r"^u(\d{4})$")
_ASSET_KINDS = ("characters", "locations", "props", "creatures")


@dataclass
class Finding:
    rule_id: str
    severity: str
    object_path: str
    message: str
    unit_refs: list[str] = field(default_factory=list)
    evidence_quote: str = ""
    expected: object = None
    actual: object = None
    suggested_patch: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items()
                if v not in (None, "", [], {})}


@dataclass
class VerificationReport:
    findings: list[Finding] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity in ("critical", "high")]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity not in ("critical", "high")]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, rule_id: str, severity: str, object_path: str,
            message: str, **kwargs) -> None:
        self.findings.append(Finding(rule_id, severity, object_path, message, **kwargs))

    def extend(self, other: "VerificationReport") -> None:
        self.findings.extend(other.findings)
        if other.coverage:
            self.coverage = other.coverage

    def to_dict(self) -> dict:
        return {
            "status": "verified" if self.ok else "failed",
            "findings": [f.to_dict() for f in self.findings],
            "coverage": self.coverage,
        }

    def render(self) -> str:
        lines = []
        for f in self.findings:
            refs = f" units={','.join(f.unit_refs)}" if f.unit_refs else ""
            lines.append(
                f"{f.severity.upper()} [{f.rule_id}] {f.object_path}: {f.message}{refs}")
        selected = len(self.coverage.get("selected", []))
        covered = len(self.coverage.get("covered", []))
        waived = len(self.coverage.get("waived", []))
        failed = len(self.coverage.get("failed", []))
        if selected:
            lines.append(
                f"COVERAGE selected={selected} covered={covered} waived={waived} failed={failed}")
        lines.append("PASS" if self.ok else f"FAIL ({len(self.errors)} hard finding(s))")
        return "\n".join(lines)


def _hash_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _duplicate_ids(items: Iterable[dict]) -> list[str]:
    seen, duplicates = set(), []
    for item in items:
        value = item.get("id")
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _validate_schema(doc: dict, report: VerificationReport) -> None:
    try:
        import jsonschema
    except ImportError:
        report.add("SCHEMA-ENGINE-001", "critical", "/",
                   "jsonschema is unavailable; structural verification cannot run")
        return
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        path = "/" + "/".join(str(p) for p in error.absolute_path)
        report.add("SCHEMA-001", "high", path, error.message)


def _validate_frozen_units(doc: dict, expected: list[dict],
                           report: VerificationReport) -> None:
    actual = (doc.get("source") or {}).get("units") or []
    if len(actual) != len(expected):
        report.add(
            "SOURCE-FROZEN-001", "critical", "/source/units",
            "model changed the deterministic source-unit count",
            expected=len(expected), actual=len(actual))
    for i, exp in enumerate(expected):
        if i >= len(actual):
            break
        got = actual[i]
        for key in ("id", "text", "para"):
            if got.get(key) != exp.get(key):
                report.add(
                    "SOURCE-FROZEN-002", "critical", f"/source/units/{i}/{key}",
                    "model changed immutable source evidence",
                    unit_refs=[exp.get("id", "")],
                    evidence_quote=exp.get("text", ""),
                    expected=exp.get(key), actual=got.get(key))
        if got.get("skipped") and not (got.get("skip_reason") or "").strip():
            report.add(
                "SOURCE-WAIVER-001", "high", f"/source/units/{i}/skip_reason",
                "skipped source units require an explicit reviewable reason",
                unit_refs=[exp.get("id", "")], evidence_quote=exp.get("text", ""))


def _validate_identity(doc: dict, report: VerificationReport) -> None:
    units = (doc.get("source") or {}).get("units") or []
    for duplicate in _duplicate_ids(units):
        report.add("ID-UNIT-001", "critical", "/source/units",
                   f"duplicate unit id {duplicate}", unit_refs=[duplicate])

    episodes = doc.get("episodes") or []
    for duplicate in _duplicate_ids(episodes):
        report.add("ID-EPISODE-001", "high", "/episodes",
                   f"duplicate episode id {duplicate}")
    shots = [shot for ep in episodes for shot in ep.get("shots") or []]
    for duplicate in _duplicate_ids(shots):
        report.add("ID-SHOT-001", "high", "/episodes",
                   f"duplicate shot id {duplicate}")
    for kind in _ASSET_KINDS:
        cards = (doc.get("assets") or {}).get(kind) or []
        for duplicate in _duplicate_ids(cards):
            report.add("ID-ASSET-001", "high", f"/assets/{kind}",
                       f"duplicate asset id {duplicate}")


def _unit_number(unit_id: str) -> Optional[int]:
    match = _UNIT_ID_RE.fullmatch(unit_id or "")
    return int(match.group(1)) if match else None


def _validate_evidence(doc: dict, report: VerificationReport) -> dict:
    unit_list = (doc.get("source") or {}).get("units") or []
    units = {u.get("id"): u for u in unit_list if u.get("id")}
    visual, narrated, dialogue = set(), set(), set()
    inferred = total_shots = 0

    for epi, episode in enumerate(doc.get("episodes") or []):
        for si, shot in enumerate(episode.get("shots") or []):
            base = f"/episodes/{epi}/shots/{si}"
            total_shots += 1
            source = shot.get("source") or {}
            refs = source.get("unit_refs") or []
            missing = [ref for ref in refs if ref not in units]
            for ref in missing:
                report.add("REF-UNIT-001", "high", base + "/source/unit_refs",
                           f"shot references unknown source unit {ref}", unit_refs=[ref])
            valid_refs = [ref for ref in refs if ref in units]
            visual.update(valid_refs)
            derivation = source.get("derivation")
            if derivation == "inferred":
                inferred += 1
                if not (source.get("inference_note") or "").strip():
                    report.add("EVIDENCE-INFERENCE-001", "high", base + "/source/inference_note",
                               "inferred shots require a concrete derivation note",
                               unit_refs=valid_refs)
            if derivation != "transition" and not valid_refs:
                report.add("EVIDENCE-SHOT-001", "high", base + "/source/unit_refs",
                           "non-transition shots require source evidence")

            numbers = [_unit_number(ref) for ref in valid_refs]
            if len(numbers) > 3 or (numbers and None not in numbers and
                                    numbers != list(range(numbers[0], numbers[0] + len(numbers)))):
                report.add("EVIDENCE-RANGE-001", "medium", base + "/source/unit_refs",
                           "shot evidence should normally be 1-3 adjacent units",
                           unit_refs=valid_refs)

            source_text = "".join(units[ref].get("text", "") for ref in valid_refs)
            for di, item in enumerate(shot.get("dialogue") or []):
                spoken = item.get("text") or ""
                if spoken and _squash(spoken) not in _squash(source_text):
                    report.add(
                        "FID-DIALOGUE-001", "critical", base + f"/dialogue/{di}/text",
                        "dialogue is not a verbatim excerpt of its cited source units",
                        unit_refs=valid_refs, evidence_quote=source_text, actual=spoken)
                elif spoken:
                    for ref in valid_refs:
                        if _squash(spoken) in _squash(units[ref].get("text", "")):
                            dialogue.add(ref)

            narration = shot.get("narration") or {}
            narration_refs = narration.get("unit_refs") or []
            for ref in narration_refs:
                if ref not in units:
                    report.add("REF-NARRATION-001", "high", base + "/narration/unit_refs",
                               f"narration references unknown source unit {ref}", unit_refs=[ref])
                else:
                    narrated.add(ref)
            narration_text = narration.get("text") or ""
            cited_text = "".join(units[r].get("text", "") for r in narration_refs if r in units)
            if narration_text and cited_text and _squash(narration_text) not in _squash(cited_text):
                report.add(
                    "FID-NARRATION-001", "medium", base + "/narration/text",
                    "narration text is not a direct excerpt of its cited source units",
                    unit_refs=[r for r in narration_refs if r in units],
                    evidence_quote=cited_text, actual=narration_text)

    mode = (doc.get("meta") or {}).get("narration", {}).get("mode", "original_text")
    covered = narrated | dialogue
    if mode != "original_text":
        covered |= visual
    selected = [u.get("id") for u in unit_list if u.get("id")]
    waived = [u.get("id") for u in unit_list if u.get("id") and u.get("skipped")]
    failed = [uid for uid in selected if uid not in covered and uid not in waived]
    if failed:
        report.add("COVERAGE-001", "critical", "/coverage/unmapped_units",
                   "source units are not carried by narration, dialogue, or visuals",
                   unit_refs=failed)
    coverage = {
        "selected": selected,
        "covered": [uid for uid in selected if uid in covered],
        "waived": waived,
        "failed": failed,
        "inferred_shot_ratio": round(inferred / total_shots, 2) if total_shots else 0,
    }
    declared = doc.get("coverage") or {}
    if sorted(declared.get("unmapped_units") or []) != sorted(failed):
        report.add("COVERAGE-DECLARED-001", "high", "/coverage/unmapped_units",
                   "declared coverage differs from deterministic coverage",
                   expected=failed, actual=declared.get("unmapped_units") or [])
    if abs(float(declared.get("inferred_shot_ratio") or 0)
           - coverage["inferred_shot_ratio"]) > 0.011:
        report.add("COVERAGE-DECLARED-002", "medium", "/coverage/inferred_shot_ratio",
                   "declared inferred ratio differs from deterministic result",
                   expected=coverage["inferred_shot_ratio"],
                   actual=declared.get("inferred_shot_ratio"))
    return coverage


def verify_document(doc: dict, frozen_units: Optional[list[dict]] = None,
                    original_text: Optional[str] = None) -> VerificationReport:
    report = VerificationReport()
    _validate_schema(doc, report)
    _validate_identity(doc, report)
    if frozen_units is not None:
        _validate_frozen_units(doc, frozen_units, report)
    if original_text is not None:
        joined = "".join(u.get("text", "") for u in
                         (doc.get("source") or {}).get("units") or [])
        if _squash(joined) != _squash(original_text):
            report.add("FID-SOURCE-001", "critical", "/source/units",
                       "source units do not reconstruct the normalized input")
    report.coverage = _validate_evidence(doc, report)
    return report


def recompute_coverage_field(doc: dict, coverage: dict) -> None:
    doc["coverage"] = {
        "unmapped_units": list(coverage.get("failed", [])),
        "inferred_shot_ratio": coverage.get("inferred_shot_ratio", 0),
    }


def verification_identity(report: VerificationReport) -> str:
    return _hash_json(report.to_dict())
