#!/usr/bin/env python3
"""已改造模块里，给用户的错误出口不得再写中文字面量（spec §8）。用法: python3 tests/server/test_i18n_scan.py

逐子计划把模块加进 MODULES；app.py 只扫列出的函数。豁免：行尾 # i18n: internal / llm / todo(N)。
子计划 4 起还扫 `say(…)`、`job["log"].append(…)`、字典里 message/error/summary 键的值。
子计划 5 起还扫 `Finding(…)` 与 `report.add(…)`（验证报告的条目）。
"""
import ast
import re
import io
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CJK = re.compile(r"[\u4e00-\u9fff]")
MARK = re.compile(r"#\s*i18n:\s*(internal|llm|todo\(\d\))")
SINK_NAME = re.compile(r"(Error|Exception|Submit|Conflict|NotFound|Corrupt|Exceeded|Invalid|Stale|Busy)$")
SINK_CALLS = {"HTTPException", "note_error", "submit_failed", "download_failed", "TaskState", "say", "Finding"}
SINK_KW = {"error", "detail", "message", "step"}
SINK_DICT_KEYS = {"message", "error", "summary"}     # 字典字面量里这些键的值：SSE 事件、门的结果、历史条目
SINK_SUBSCRIPTS = {"error", "summary", "message"}    # obj["error"] = … 这类赋值

# 子计划 1 清零的模块；值为 None 表示全文件，集合表示只扫这些函数
MODULES: dict = {
    "render/providers/base.py": None,
    "render/providers/fake.py": None,
    "render/providers/seedance.py": None,
    "render/providers/minimax.py": None,
    "render/providers/__init__.py": None,
    "render/session.py": None,
    "render/free.py": None,
    "render/compose.py": None,
    "render/runner.py": None,
    "server/error_refs.py": None,
    "pipeline/chat.py": None,
    "pipeline/review.py": None,
    "pipeline/quality.py": None,
    "pipeline/errors.py": None,
    "pipeline/events.py": None,
    "pipeline/convert.py": None,
    "pipeline/graph.py": None,
    "pipeline/verification.py": None,
    "pipeline/repair.py": None,
    "pipeline/novel_memory.py": {"soft_findings"},
    "server/auth.py": None,
    "server/novels.py": None,
    "server/library.py": None,
    "server/store.py": None,
    "server/admin.py": None,
    "assistant/tools.py": None,
    "assistant/actions.py": None,
    "assistant/edits.py": None,
    "assistant/graph.py": None,
    "assistant/events.py": None,
    "server/usage.py": None,
    "server/pricing.py": None,
    "render/providers/tts_base.py": None,
    "render/providers/tts_volc.py": None,
    "render/voice.py": None,
    "render/mix.py": None,
    "render/export_fcpxml.py": None,
    "server/app.py": {"_render_ctx", "_render_call", "render_session_post", "render_session_get",
                      "render_session_patch", "_film_quote", "_film_run", "render_clip_run", "render_run_all",
                      "render_clip_chosen", "render_clip_patch", "_free_ctx", "render_free_create",
                      "render_free_patch", "render_free_delete", "render_free_run", "render_free_chosen",
                      "_film_cancel", "render_clip_cancel", "render_free_cancel", "_film_tasks", "render_tasks",
                      "_has_vendor_text", "_public_error", "_cancel_kind", "_job_where",
                      "render_file", "_tts", "_session_or_404", "render_voices", "render_voices_put",
                      "_compose_preview", "_compose_blockers", "_compose_quote", "_compose_start",
                      "_export_check", "render_compose_get", "render_export", "_compose_worker",
                      "render_compose_post", "render_bgm_put", "render_bgm_delete",
                      "current_user", "admin_user", "register", "login",
                      "novel_user", "_novel_call", "_clean_params", "_start_version",
                      "memory_asset_upsert", "render_plan", "get_job", "get_job_partial",
                      "_render_gate", "_gate_status", "render_keyframes", "_run_digest", "chapters_digest",
                      "_execute", "_run_version_job", "list_jobs", "_jobs_view",
                      "_admin_call", "admin_usage", "admin_usage_csv", "admin_pricing_put",
                      "admin_errors", "admin_error_get", "healthz", "admin_service",
                      "versions_get", "admin_job_debug", "_check_version_doc",
                      "_assistant_db", "assistant_clear", "_assistant_ctx", "_assistant_begin",
                      "_assistant_stream", "_assistant_model_or_503", "assistant_send",
                      "assistant_resume", "assistant_undo", "assistant_history"},
}


def _cjk_consts(tree: ast.Module) -> set:
    """含中文的模块级常量名；赋值（含带注解的）与别名（A = B）用不动点传播。"""
    assigns = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            assigns.append(([t.id for t in node.targets if isinstance(t, ast.Name)], node.value))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            assigns.append(([node.target.id], node.value))
    out: set = set()
    changed = True
    while changed:
        changed = False
        for names, value in assigns:
            hit = any((isinstance(n, ast.Constant) and isinstance(n.value, str) and CJK.search(n.value))
                      or (isinstance(n, ast.Name) and n.id in out) for n in ast.walk(value))
            if hit and not set(names) <= out:
                out |= set(names)
                changed = True
    return out


def _has_cjk(node, consts: set) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and CJK.search(n.value):
            return True
        if isinstance(n, ast.Name) and n.id in consts:
            return True
    return False


def _name(func) -> str:
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def _sinks(node):
    """(子节点, 描述) 迭代：只产出错误出口里的值。"""
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if (isinstance(f, ast.Attribute) and f.attr == "append" and isinstance(f.value, ast.Subscript)
                    and isinstance(f.value.slice, ast.Constant) and f.value.slice.value == "log"):
                for a in n.args:
                    yield a, '["log"].append'
            if (isinstance(f, ast.Attribute) and f.attr == "add" and isinstance(f.value, ast.Name)
                    and f.value.id == "report"):
                for a in n.args:
                    yield a, "report.add"
                for k in n.keywords:
                    yield k.value, f"report.add({k.arg}=)"
            name = _name(n.func)
            if name in SINK_CALLS or SINK_NAME.search(name):
                for a in n.args:
                    yield a, name
                for k in n.keywords:
                    yield k.value, f"{name}({k.arg}=)"
            else:
                for k in n.keywords:
                    if k.arg in SINK_KW:
                        yield k.value, f"{name}({k.arg}=)"
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                pairs = (zip(t.elts, n.value.elts) if isinstance(t, ast.Tuple) and isinstance(n.value, ast.Tuple)
                         else [(t, n.value)])
                for tgt, val in pairs:
                    if (isinstance(tgt, ast.Subscript) and isinstance(tgt.slice, ast.Constant)
                            and tgt.slice.value in SINK_SUBSCRIPTS):
                        yield val, f'["{tgt.slice.value}"] ='
        elif isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value in SINK_DICT_KEYS:
                    yield v, f'{{"{k.value}": …}}'


def _marked_lines(src: str) -> set:
    """真正的注释里带豁免标记的行号（字符串里的不算）。"""
    out = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT and MARK.search(tok.string):
            out.add(tok.start[0])
    return out


def _stmt_range(stmt: ast.stmt) -> range:
    """语句的行范围；复合语句只取头部（到第一个子句前）。"""
    body = getattr(stmt, "body", None)
    end = body[0].lineno - 1 if isinstance(body, list) and body else (stmt.end_lineno or stmt.lineno)
    return range(stmt.lineno, max(end, stmt.lineno) + 1)


def scan(rel: str, funcs) -> list:
    path = ROOT / rel
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    consts = _cjk_consts(tree)
    marked = _marked_lines(src)
    parent = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    roots = [tree] if funcs is None else [n for n in ast.walk(tree)
                                          if isinstance(n, ast.FunctionDef) and n.name in funcs]
    hits = []
    for root in roots:
        for val, where in _sinks(root):
            if not _has_cjk(val, consts):
                continue
            node = val
            while node in parent and not isinstance(node, ast.stmt):
                node = parent[node]
            span = _stmt_range(node) if isinstance(node, ast.stmt) else range(val.lineno, (val.end_lineno or val.lineno) + 1)
            if marked & set(span) or marked & set(range(val.lineno, (val.end_lineno or val.lineno) + 1)):
                continue
            stmt = lines[val.lineno - 1]
            hits.append(f"{rel}:{val.lineno} {where}: {stmt.strip()[:100]}")
    return sorted(set(hits))


def main() -> int:
    # 扫描器自检：能抓到各种写法，豁免注释有效
    probe = ROOT / "tests" / "server" / "_i18n_probe.py"

    def probe_hits(code: str) -> int:
        probe.write_text(code, encoding="utf-8")
        try:
            return len(scan("tests/server/_i18n_probe.py", None))
        finally:
            probe.unlink()

    cases = [
        ('X = "中文"\ndef f(e):\n    raise ValueError("中文")\n    raise ValueError(f"中{e}")\n'
         '    c["error"] = X\n    a.update(error="错")\n    raise ValueError("内部")  # i18n: internal\n', 4),
        # 字符串里的标记不算豁免；真注释算
        ('raise ValueError("中文 # i18n: internal")\n', 1),
        ('raise ValueError("中文")  # i18n: internal\n', 0),
        # 多行语句：标记在收尾行也豁免；没标记仍命中
        ('raise ValueError(\n    "中文",\n)  # i18n: internal\n', 0),
        ('raise ValueError(\n    "中文",\n)\n', 1),
        # 带注解的常量、别名、拼接
        ('class Busy(Exception): pass\nraise Busy("中文")\n', 1),
        ('E: str = "中文"\nraise ValueError(E)\n', 1),
        ('E = "中文"\nA = E\nB = A\nraise ValueError(B)\n', 1),
        ('E = "中文"\nraise ValueError("x" + E)\n', 1),
        ('E = "english"\nraise ValueError(E)\n', 0),
        # 子计划 4：SSE 事件与门结果的字典、历史条目的下标赋值、进度事件出口
        ('def f(e):\n    yield {"event": "error", "data": {"message": f"出错：{e}"}}\n', 1),
        ('def f(t):\n    t["ok"], t["summary"] = False, "中断"\n', 1),
        ('def f(job):\n    job["log"].append("中文")\n    say("中文")\n', 2),
        ('def f(job):\n    job["debug_log"].append("中文")\n    log("中文")\n', 0),
        ('d = {"message": "中文"}  # i18n: llm\n', 0),
        ('d = {"target": "全书梗概"}\n', 0),
        # 子计划 5：验证报告的两个出口（回喂模型的原文标 # i18n: llm；给界面的走代码）
        ('def f(r, x):\n    r.add("A", "high", "/", "中文")\n    report.add("A", "high", "/", f"中文{x}")\n', 1),
        ('def f(p):\n    Finding("A", "medium", p, "中文")\n', 1),
        ('def f(p):\n    report.add("A", "high", p, "english")\n    Finding("A", "medium", p, params={"x": 1})\n', 0),
        ('def f(p):\n    report.add("ORDER-001", "medium", p, "中文")  # i18n: llm\n', 0),
    ]
    for i, (code, want) in enumerate(cases):
        got = probe_hits(code)
        assert got == want, f"自检用例 {i} 应命中 {want} 处，实际 {got}"

    bad = []
    for rel, funcs in MODULES.items():
        bad += scan(rel, funcs)
    assert not bad, "这些错误出口还写着中文：\n" + "\n".join(bad)
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
