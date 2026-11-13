#!/usr/bin/env python3
"""已改造模块里，给用户的错误出口不得再写中文字面量（spec §8）。用法: python3 tests/server/test_i18n_scan.py

逐子计划把模块加进 MODULES；app.py 只扫列出的函数。豁免：行尾 # i18n: internal / llm / todo(N)。
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CJK = re.compile(r"[\u4e00-\u9fff]")
MARK = re.compile(r"#\s*i18n:\s*(internal|llm|todo\(\d\))")
SINK_NAME = re.compile(r"(Error|Exception|Submit|Conflict|NotFound|Corrupt|Exceeded|Invalid|Stale)$")
SINK_CALLS = {"HTTPException", "note_error", "submit_failed", "download_failed", "TaskState"}
SINK_KW = {"error", "detail", "message", "step"}

# 子计划 1 清零的模块；值为 None 表示全文件，集合表示只扫这些函数
MODULES: dict = {}


def _cjk_consts(tree: ast.Module) -> set:
    out = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                                                and CJK.search(n.value) for n in ast.walk(node.value)):
            out |= {t.id for t in node.targets if isinstance(t, ast.Name)}
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
                            and tgt.slice.value == "error"):
                        yield val, '["error"] ='


def scan(rel: str, funcs) -> list:
    path = ROOT / rel
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    consts = _cjk_consts(tree)
    roots = [tree] if funcs is None else [n for n in ast.walk(tree)
                                          if isinstance(n, ast.FunctionDef) and n.name in funcs]
    hits = []
    for root in roots:
        for val, where in _sinks(root):
            if not _has_cjk(val, consts):
                continue
            span = lines[val.lineno - 1:(val.end_lineno or val.lineno)]
            stmt = lines[val.lineno - 1]
            if any(MARK.search(x) for x in span) or MARK.search(stmt):
                continue
            hits.append(f"{rel}:{val.lineno} {where}: {stmt.strip()[:100]}")
    return sorted(set(hits))


def main() -> int:
    # 扫描器自检：能抓到四种写法，豁免注释有效
    probe = ROOT / "tests" / "server" / "_i18n_probe.py"
    probe.write_text('X = "中文"\n'
                     'def f(e):\n'
                     '    raise ValueError("中文")\n'
                     '    raise ValueError(f"中{e}")\n'
                     '    c["error"] = X\n'
                     '    a.update(error="错")\n'
                     '    raise ValueError("内部")  # i18n: internal\n', encoding="utf-8")
    try:
        got = scan("tests/server/_i18n_probe.py", None)
        assert len(got) == 4, got
    finally:
        probe.unlink()

    bad = []
    for rel, funcs in MODULES.items():
        bad += scan(rel, funcs)
    assert not bad, "这些错误出口还写着中文：\n" + "\n".join(bad)
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
