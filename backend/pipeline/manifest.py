"""Deterministic conversion manifest helpers."""
import hashlib
import json
from pathlib import Path

from .config import ROOT


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def build_manifest(raw_text: str, normalized_text: str, batches: list[str],
                   units: list[dict], params, settings) -> dict:
    offsets = []
    start = 0
    for index, batch in enumerate(batches, 1):
        offsets.append({
            "index": index,
            "start": start,
            "end": start + len(batch),
            "chars": len(batch),
            "sha256": sha256_text(batch),
        })
        start += len(batch)
    return {
        "version": 1,
        "state": "running",
        "input": {
            "raw_sha256": sha256_text(raw_text),
            "normalized_sha256": sha256_text(normalized_text),
            "raw_chars": len(raw_text),
            "normalized_chars": len(normalized_text),
        },
        "scope": {
            "frozen": bool(settings.freeze_source_units),
            "batches": offsets,
            "units": units,
        },
        "contracts": {
            "prompt_sha256": file_sha256(ROOT / "prompts" / "novel_to_storyboard.md"),
            "schema_sha256": file_sha256(ROOT / "schema" / "storyboard.schema.json"),
            "model": settings.model,
            "temperature": settings.temperature,
        },
        "params_sha256": sha256_json(params.__dict__),
        "attempts": [],
        "verification": None,
        "artifact_sha256": None,
    }


def finish_manifest(manifest: dict, doc: dict, report, state: str) -> None:
    manifest["state"] = state
    manifest["verification"] = report.to_dict() if report is not None else None
    manifest["artifact_sha256"] = sha256_json(doc)
