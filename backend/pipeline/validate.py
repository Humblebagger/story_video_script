"""以子进程方式调用仓库现有校验/合并/渲染工具，复用其输出作为重试反馈。"""
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .config import ROOT

_TOOLS = ROOT / "tools"


def _run(args: List[str]) -> Tuple[bool, str]:
    proc = subprocess.run([sys.executable, *args], capture_output=True, text=True)
    return proc.returncode == 0, proc.stdout + proc.stderr


def run_lint(json_path: Path) -> Tuple[bool, str]:
    return _run([str(_TOOLS / "lint_storyboard.py"), str(json_path)])


@dataclass
class LintReport:
    """lint 一次 --json 运行的结果（spec 子计划 5b C、D）。
    text：与 run_lint（文本模式）的「stdout + stderr」逐字相同，回喂模型、日志、失败报告只用它；
    errors：逐条错误 {rule, params, text}，只给界面翻译；拿不到可信的结构化输出（崩溃、输出认不出、version 不符）时为 None。"""
    ok: bool
    text: str
    errors: Optional[list] = None


def _universal_newlines(s: str) -> str:
    r"""与 subprocess.run(text=True) 对 stdout 做的换行还原相同：\r\n、\r 都换成 \n。
    --json 里的 \r 被转义成 \\r，躲过了这一步，json.loads 之后要补做，text 才与文本模式逐字相同（设计审查 I1）。"""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def run_lint_report(json_path: Path) -> LintReport:
    proc = subprocess.run([sys.executable, str(_TOOLS / "lint_storyboard.py"), "--json", str(json_path)],
                          capture_output=True, text=True)
    ok = proc.returncode == 0
    try:
        data = json.loads(proc.stdout)
        text = data["text"]
        if not isinstance(text, str):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        # 没有 JSON（崩溃时 stdout 为空、只有 stderr 的回溯）：与文本模式一样原样拼起来
        return LintReport(ok, proc.stdout + proc.stderr)
    text = _universal_newlines(text) + proc.stderr
    errors = data.get("errors")
    if data.get("version") != 1 or not isinstance(errors, list):
        return LintReport(ok, text)        # 形状不认识：逐条不可信，退回按行拆分；回喂仍用 text
    return LintReport(ok, text, errors)


def run_fidelity(json_path: Path, original_text: str, workdir: Path) -> Tuple[bool, str]:
    txt = Path(workdir) / f"_fidelity_{Path(json_path).stem}.txt"
    txt.write_text(original_text, encoding="utf-8")
    return _run([str(_TOOLS / "check_fidelity.py"), str(json_path), str(txt)])


def run_merge(batch_paths: List[Path], out_path: Path) -> Tuple[bool, str]:
    return _run([str(_TOOLS / "merge_storyboard.py"),
                 *[str(p) for p in batch_paths], "-o", str(out_path)])


def run_adapter(json_path: Path, out_dir: Path) -> Tuple[bool, str]:
    return _run([str(ROOT / "adapters" / "seedance.py"), str(json_path),
                 "--out", str(out_dir)])
