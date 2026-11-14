"""Structured, in-process verification for storyboard artifacts."""
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from render.providers.base import scrub_secrets
from server.messages import compact, msg, ref, vendor

from .config import ROOT


SCHEMA_PATH = ROOT / "schema" / "storyboard.schema.json"
_UNIT_ID_RE = re.compile(r"^u(\d{4})$")
_ASSET_KINDS = ("characters", "locations", "props", "creatures")


_KEEP = ("code", "t")
# code 与 t 只有长这样才原样保留：代码如 verify.rule.X、类型标记如 money/ref/vendor/lines。
# 合法标识符只免去递归（照字符串处理），密钥脱敏照做：环境密钥本身也可能是合法标识符
# （如 abc123secret_token）；外部原文里同名键会借此带出密钥。
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[A-Za-z0-9_-]+)*$")


def scrub_params(v, *, keep: bool = True):
    """给界面的消息参数递归脱敏（密钥、Bearer 凭据）；返回新对象。
    keep=True：键 code/t 的值是合法标识符字符串时只抹密钥（消息对象用；正常代码与类型标记不含密钥，原样不变）；
    keep=False：不豁免任何键（原始报告字段用，其中不是受信消息对象）。
    外部原文要「先脱敏再截断」：截断可能把密钥切成抹不掉的半截。"""
    if isinstance(v, str):
        return scrub_secrets(v)
    if isinstance(v, list):
        return [scrub_params(x, keep=keep) for x in v]
    if isinstance(v, dict):
        # 键也要脱敏（字符串键过 scrub_secrets，不做路径改写以免误改协议字段名）；
        # 脱敏后两个键可能撞成同一个 ***，后写的覆盖先写的，可以接受。
        return {scrub_secrets(k) if isinstance(k, str) else k:
                scrub_secrets(x) if keep and k in _KEEP and isinstance(x, str) and _ID_RE.match(x)
                else scrub_params(x, keep=keep) for k, x in v.items()}
    return v


@dataclass
class Finding:
    rule_id: str
    severity: str
    object_path: str
    message: str = ""          # 回喂模型的原文（多为英文），不翻译；没给时由中文模板生成
    unit_refs: list[str] = field(default_factory=list)
    evidence_quote: str = ""
    expected: object = None
    actual: object = None
    suggested_patch: list[dict] = field(default_factory=list)
    params: dict = field(default_factory=dict)   # 给界面的参数，代码是 verify.rule.<rule_id>（spec 子计划 5 B）

    def __post_init__(self) -> None:
        # 代码未登记或参数与模板不符，在这里就抛错：每条规则的用例都会走到这一行
        self.params = scrub_params(self.params)
        m = msg(self.code, **self.params)
        if not self.message:
            # 软核查两条（NOVEL-*，不回喂模型）：模板与旧写法一字不差，直接用它。
            # 回喂模型的规则一律自己传原文，不由界面文案生成（ORDER-001，设计审查 Minor 2）
            self.message = m["message"]

    @property
    def code(self) -> str:
        return f"verify.rule.{self.rule_id}"

    def as_msg(self) -> dict:
        return {"code": self.code, "params": scrub_params(self.params)}

    def to_dict(self, *, shown: bool = True) -> dict:
        """shown=True：存档与接口用，多一个 msg 给界面按语言渲染。
        shown=False：回喂修复模型的形状，与改造前逐字一致（不含 msg、params）。"""
        out = {k: v for k, v in asdict(self).items()
               if k != "params" and v not in (None, "", [], {})}
        if shown:
            # 给界面与存档：整条逐字段脱敏（message、unit_refs、expected/actual、引文都可能带用户文字里的密钥）；
            # 回喂模型的 shown=False 一字不改
            out = scrub_params(out, keep=False)
            out["msg"] = self.as_msg()
        return out


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
            message: str = "", **kwargs) -> None:
        self.findings.append(Finding(rule_id, severity, object_path, message, **kwargs))

    def extend(self, other: "VerificationReport") -> None:
        self.findings.extend(other.findings)
        if other.coverage:
            self.coverage = other.coverage

    def to_dict(self, *, shown: bool = True) -> dict:
        """shown=False：尝试记录用（前端不显示，不带 msg，设计审查 Minor 1）。"""
        return {
            "status": "verified" if self.ok else "failed",
            "findings": [f.to_dict(shown=shown) for f in self.findings],
            "coverage": scrub_params(self.coverage, keep=False) if shown else self.coverage,
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

    def lines(self) -> list[dict]:
        """render() 的逐条消息版，给用户看（spec 子计划 5 C）；render() 照旧回喂模型。
        汇总（通过 / 未通过几条）放第一行，lines_of 截断时不会丢（设计审查 I3）；然后覆盖统计、逐条。"""
        out = [compact(msg("verify.report.pass")) if self.ok
               else compact(msg("verify.report.fail", n=len(self.errors)))]
        cov = self.coverage
        if cov.get("selected"):
            out.append(compact(msg("verify.report.coverage", selected=len(cov.get("selected", [])),
                                   covered=len(cov.get("covered", [])), waived=len(cov.get("waived", [])),
                                   failed=len(cov.get("failed", [])))))
        out += [compact(msg("verify.report.finding", severity=ref(f"verify.severity.{f.severity}"),
                            rule=f.rule_id, path=f.object_path, detail=f.as_msg()))
                for f in self.findings]
        return out


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
        report.add("SCHEMA-001", "high", path, error.message, params={"detail": vendor(scrub_secrets(error.message))})


def _validate_frozen_units(doc: dict, expected: list[dict],
                           report: VerificationReport) -> None:
    actual = (doc.get("source") or {}).get("units") or []
    if len(actual) != len(expected):
        report.add(
            "SOURCE-FROZEN-001", "critical", "/source/units",
            "model changed the deterministic source-unit count",
            expected=len(expected), actual=len(actual),
            params={"expected": len(expected), "actual": len(actual)})
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
                    expected=exp.get(key), actual=got.get(key),
                    params={"unit": exp.get("id", ""), "field": key})
        if got.get("skipped") and not (got.get("skip_reason") or "").strip():
            report.add(
                "SOURCE-WAIVER-001", "high", f"/source/units/{i}/skip_reason",
                "skipped source units require an explicit reviewable reason",
                unit_refs=[exp.get("id", "")], evidence_quote=exp.get("text", ""),
                params={"unit": exp.get("id", "")})


def _validate_identity(doc: dict, report: VerificationReport) -> None:
    units = (doc.get("source") or {}).get("units") or []
    for duplicate in _duplicate_ids(units):
        report.add("ID-UNIT-001", "critical", "/source/units",
                   f"duplicate unit id {duplicate}", unit_refs=[duplicate],
                   params={"id": duplicate})

    episodes = doc.get("episodes") or []
    for duplicate in _duplicate_ids(episodes):
        report.add("ID-EPISODE-001", "high", "/episodes",
                   f"duplicate episode id {duplicate}", params={"id": duplicate})
    shots = [shot for ep in episodes for shot in ep.get("shots") or []]
    for duplicate in _duplicate_ids(shots):
        report.add("ID-SHOT-001", "high", "/episodes",
                   f"duplicate shot id {duplicate}", params={"id": duplicate})
    for kind in _ASSET_KINDS:
        cards = (doc.get("assets") or {}).get(kind) or []
        for duplicate in _duplicate_ids(cards):
            report.add("ID-ASSET-001", "high", f"/assets/{kind}",
                       f"duplicate asset id {duplicate}", params={"id": duplicate})


def _unit_number(unit_id: str) -> Optional[int]:
    match = _UNIT_ID_RE.fullmatch(unit_id or "")
    return int(match.group(1)) if match else None


def _validate_evidence(doc: dict, report: VerificationReport) -> dict:
    unit_list = (doc.get("source") or {}).get("units") or []
    units = {u.get("id"): u for u in unit_list if u.get("id")}
    visual, narrated, dialogue = set(), set(), set()
    inferred = total_shots = 0
    # 讲述顺序游标：忠实转换里镜头应顺着原文往下走。转场镜头没有证据，不参与判定。
    prev_number = None
    prev_label = ""

    for epi, episode in enumerate(doc.get("episodes") or []):
        for si, shot in enumerate(episode.get("shots") or []):
            base = f"/episodes/{epi}/shots/{si}"
            total_shots += 1
            source = shot.get("source") or {}
            refs = source.get("unit_refs") or []
            missing = [ref for ref in refs if ref not in units]
            for ref in missing:
                report.add("REF-UNIT-001", "high", base + "/source/unit_refs",
                           f"shot references unknown source unit {ref}", unit_refs=[ref], params={"unit": ref})
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

            # 讲述顺序：原有的 RANGE 规则只看单个镜头内部相不相邻，管不到镜头之间。
            # 第 3 镜引 u0050、第 4 镜引 u0010 以前完全合法——那是把原文倒着讲。
            # 判 medium：闪回/插叙是正当手法，但忠实转换里出现就该被人看一眼。
            first = next((n for n in numbers if n is not None), None)
            if first is not None:
                if prev_number is not None and first < prev_number:
                    report.add(
                        "ORDER-001", "medium", base + "/source/unit_refs",
                        f"镜头回跳到更早的原文（上一处 {prev_label} 引至 u{prev_number:04d}）",  # i18n: llm
                        params={"prev": prev_label, "unit": f"u{prev_number:04d}"},
                        unit_refs=valid_refs, expected=f">= u{prev_number:04d}",
                        actual=f"u{first:04d}")
                prev_number = max(n for n in numbers if n is not None)
                prev_label = shot.get("id") or base

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
                               f"narration references unknown source unit {ref}", unit_refs=[ref], params={"unit": ref})
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
                   unit_refs=failed, params={"n": len(failed)})
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
    return _hash_json(report.to_dict(shown=False))


def tool_lines(text: str) -> list:
    """检查工具（lint、保真、合并）的子进程输出 → 给用户看的逐条（计划 R6）：一行按语言渲染的标题，
    加每条 ERROR 行一项（原文，原样显示，每项截断 300 字）。WARN、汇总、PASS 行不要：失败区只列错误。
    没有 ERROR 行时（保真检查只打 FAIL 与缩进的差异）取 FAIL 行与缩进行的前 10 行；仍认不出就整段作一项。"""
    rows = [ln.rstrip() for ln in scrub_secrets(text).splitlines()]
    errs = [ln[len("ERROR "):].strip() for ln in rows if ln.startswith("ERROR ")]
    if not errs:
        errs = [ln.strip() for ln in rows if ln.startswith("FAIL") or ln.startswith("  ")][:10]
    if not errs and text.strip():
        errs = [scrub_secrets(text.strip())]
    return [compact(msg("verify.report.tool"))] + [compact(msg("verify.report.tool_error", text=vendor(e)))
                                                   for e in errs]
