#!/usr/bin/env python3
"""分镜检查（lint）的 --json 输出（spec 子计划 5b B、C）：每条错误的规则名与参数、同一次运行的 text 与文本模式逐字相同、
WARN 的规则名、validate.run_lint_report、命令行默认输出不变。回喂模型的原文见 test_lint_feed_snapshot.py。
不调模型、不联网。用法: python3 tests/pipeline/test_lint_json.py"""
import ast
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name           # 必须在导入 server.* / pipeline.* 之前
os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"  # 保险：漏了桩也到不了真实模型服务
os.environ["ANTHROPIC_API_KEY"] = "sk-test-not-real"
import pipeline.config as _pc  # noqa: E402
_pc._load_dotenv = lambda *_a, **_k: None                # 不读真实的 backend/.env

import lint_snapshot as SNAP  # noqa: E402
from pipeline import validate  # noqa: E402
from test_lint_feed_snapshot import dump, lint_text  # noqa: E402

LINT = ROOT / "tools" / "lint_storyboard.py"
OPTS_P01 = ["charred", "fresh_bleeding", "lotus_wrapped", "paper_wrapped", "split_open"]

# 每条错误规则 --json 给的 params（与 lint_snapshot.CASES 一一对应）
EXPECT_PARAMS = {
    "schema": {"path": "/episodes/0/shots/0/shot_size",
               "detail": "'huge' is not one of ['extreme_wide', 'wide', 'full', 'medium', 'medium_close', 'close_up', 'extreme_close_up', 'insert']"},
    "ref_image_outfit": {"card": "C01", "outfit": "summer", "options": ["default"]},
    "ref_image_state": {"card": "P01", "state": "melted", "options": OPTS_P01},
    "asset_empty_constraint": {"card": "C01"},
    "curve_shot": {"episode": "E01", "shot": "E09-SH001"},
    "curve_unit": {"episode": "E01", "unit": "u9999"},
    "curve_reversed": {"episode": "E01", "start": "E01-SH010", "end": "E01-SH001"},
    "shot_unit": {"shot": "E01-SH001", "unit": "u9999"},
    "inferred_no_note": {"shot": "E01-SH001"},
    "beats_duration": {"shot": "E01-SH001", "total": "4.5", "duration": "5"},
    "beat_no_action": {"shot": "E01-SH001", "beat": 2},
    "shot_empty_constraint": {"shot": "E01-SH001"},
    "location_ref": {"shot": "E01-SH001", "location": "S99"},
    "prop_ref": {"shot": "E01-SH001", "prop": "P99"},
    "prop_state_required": {"shot": "E01-SH001", "prop": "P01", "options": OPTS_P01},
    "prop_state_unknown": {"shot": "E01-SH001", "prop": "P01", "state": "melted", "options": OPTS_P01},
    "prop_state_unexpected": {"shot": "E01-SH001", "prop": "P02"},
    "creature_outfit": {"shot": "E01-SH001", "creature": "A01"},
    "character_ref": {"shot": "E01-SH001", "character": "C99"},
    "outfit_unknown": {"shot": "E01-SH001", "character": "C01", "outfit": "summer", "options": ["default"]},
    "dialogue_character": {"shot": "E01-SH004", "character": "C99"},
    "narration_unit": {"shot": "E01-SH001", "unit": "u9999"},
    "coverage_unmapped": {"n": 1, "units": ["u0068"]},
}
WARN_RULES = ["curve_gap", "curve_incomplete", "shot_id_prefix", "coverage_declared_units", "coverage_declared_ratio"]


def lint_json(doc: dict):
    """--json 模式：返回 (退出码, 解析后的 JSON, stderr)。"""
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([sys.executable, str(LINT), "--json", str(dump(doc, d))], capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout), r.stderr


def source_rules() -> dict:
    """源码里 errors.append / warnings.append 的规则名；每处都必须是 _item("规则名", …)。"""
    out = {"errors": [], "warnings": []}
    for node in ast.walk(ast.parse(LINT.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name) and node.func.value.id in out):
            arg = node.args[0]
            ok = (isinstance(arg, ast.Call) and getattr(arg.func, "id", "") == "_item"
                  and isinstance(arg.args[0], ast.Constant))
            assert ok, f"{node.func.value.id}.append 第 {node.lineno} 行没有用 _item(规则名, …)"
            out[node.func.value.id].append(arg.args[0].value)
    return out


def main() -> int:
    # 1. 23 条错误规则各一条触发用例：规则名、参数、原文；同一次运行的 text 与文本模式逐字相同
    assert [r for r, _ in SNAP.CASES] == list(EXPECT_PARAMS)
    for rule, mutate in SNAP.CASES:
        d = SNAP.base()
        mutate(d)
        rc, data, err = lint_json(d)
        want_rc, _sha, want_lines = SNAP.LINT[rule]
        assert (rc, err, data["version"], data["ok"]) == (want_rc, "", 1, False), (rule, rc, err)
        assert data["text"] == lint_text(d)[1], f"{rule}：--json 的 text 必须与文本模式逐字相同"
        assert [e["rule"] for e in data["errors"]] == [rule], (rule, data["errors"])
        e = data["errors"][0]
        assert e["params"] == EXPECT_PARAMS[rule], (rule, e["params"])
        assert "ERROR " + e["text"] in want_lines, (rule, e["text"])
        assert [w["text"] for w in data["warnings"]] == [ln[len("WARN  "):] for ln in want_lines if ln.startswith("WARN")]
    print("1. 23 条规则：规则名、参数、原文；text 与文本模式一致 ✓")

    # 2. 源码里 23 处 errors.append、6 处 warnings.append 都带规则名，错误规则与本文件的期望一一对应
    rules = source_rules()
    assert len(rules["errors"]) == 23 and sorted(rules["errors"]) == sorted(EXPECT_PARAMS), rules["errors"]
    assert sorted(rules["warnings"]) == sorted(WARN_RULES + ["schema_unavailable"]), rules["warnings"]
    imported = set()
    for node in ast.walk(ast.parse(LINT.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"json", "re", "sys", "pathlib", "jsonschema"}, f"lint 只用标准库（加 jsonschema），实际导入 {imported}"
    print("2. 源码每处 append 都有规则名；lint 只用标准库 ✓")

    # 3. WARN：带规则名；只有 WARN 时 ok 为真、errors 为空；jsonschema 缺失也有规则名
    d = SNAP.base()
    SNAP.warn_case(d)
    rc, data, _ = lint_json(d)
    assert (rc, data["ok"], data["errors"]) == (0, True, [])
    assert [w["rule"] for w in data["warnings"]] == WARN_RULES and data["text"] == lint_text(d)[1]
    spec = importlib.util.spec_from_file_location("lint_storyboard_json", LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    saved = sys.modules.get("jsonschema")
    sys.modules["jsonschema"] = None
    buf = io.StringIO()
    try:
        with tempfile.TemporaryDirectory() as w, contextlib.redirect_stdout(buf):
            assert mod.main(str(dump(SNAP.base(), w)), as_json=True) == 0
    finally:
        if saved is None:
            sys.modules.pop("jsonschema", None)
        else:
            sys.modules["jsonschema"] = saved
    data = json.loads(buf.getvalue())
    assert [w["rule"] for w in data["warnings"]] == ["schema_unavailable"] and data["text"] == SNAP.NO_JSONSCHEMA_TEXT
    assert buf.getvalue().isascii(), "--json 只输出 ASCII"
    print("3. WARN 的规则名 ✓")

    # 4. run_lint_report：text 与 run_lint 逐字相同；输出认不出时 errors 为 None，原样退回 stdout + stderr
    for rule in ("location_ref", "coverage_unmapped"):
        d = SNAP.base()
        dict(SNAP.CASES)[rule](d)
        with tempfile.TemporaryDirectory() as w:
            p = dump(d, w)
            r = validate.run_lint_report(p)
            assert (r.ok, r.text) == validate.run_lint(p) and [e["rule"] for e in r.errors] == [rule]
    with tempfile.TemporaryDirectory() as w:
        r = validate.run_lint_report(dump(SNAP.base(), w))
        assert r == validate.LintReport(True, SNAP.PASS_TEXT, [])
        bad = Path(w) / "bad.json"
        bad.write_text("{不是 JSON", encoding="utf-8")
        r = validate.run_lint_report(bad)
        assert r.ok is False and r.errors is None and (r.ok, r.text) == validate.run_lint(bad) and "Traceback" in r.text
    # 编号里带 \r 或 \r\n：文本模式的 \r 被 subprocess 的换行还原吃掉，--json 里的要在 run_lint_report 里补做（设计审查 I1）
    for weird in ("u99\r9", "u99\r\n9"):
        d = SNAP.base()
        d["episodes"][0]["shots"][0]["narration"]["unit_refs"].append(weird)
        with tempfile.TemporaryDirectory() as w:
            p = dump(d, w)
            r = validate.run_lint_report(p)
            assert (r.ok, r.text) == validate.run_lint(p), repr(r.text)
            assert "\r" not in r.text and "narration_unit" in [e["rule"] for e in r.errors]
    real_run = validate.subprocess.run

    class _Proc:
        returncode, stdout, stderr = 1, '{"errors": []}', "E"
    try:
        validate.subprocess.run = lambda *a, **k: _Proc()
        assert validate.run_lint_report(Path("x")) == validate.LintReport(False, '{"errors": []}E', None), "缺 text 时退回原文"
        _Proc.stdout = '{"version": 2, "ok": false, "errors": [], "text": "T\\r\\n"}'
        assert validate.run_lint_report(Path("x")) == validate.LintReport(False, "T\nE", None), "version 不符：逐条不可信，text 照用"
    finally:
        validate.subprocess.run = real_run
    print("4. run_lint_report 与 run_lint 一致、认不出时退回原文 ✓")

    # 5. 命令行：默认文本输出不带 JSON；参数不对时打印用法、退出码 2
    rc, out, _ = lint_text(SNAP.base())
    assert (rc, out) == (0, SNAP.PASS_TEXT)
    r = subprocess.run([sys.executable, str(LINT)], capture_output=True, text=True)
    assert r.returncode == 2 and "--json" in r.stdout
    r = subprocess.run([sys.executable, str(LINT), "--json"], capture_output=True, text=True)
    assert r.returncode == 2
    print("5. 命令行默认文本输出与用法 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
