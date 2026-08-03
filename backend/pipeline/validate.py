"""以子进程方式调用仓库现有校验/合并/渲染工具，复用其输出作为重试反馈。"""
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

from .config import ROOT

_TOOLS = ROOT / "tools"


def _run(args: List[str]) -> Tuple[bool, str]:
    proc = subprocess.run([sys.executable, *args], capture_output=True, text=True)
    return proc.returncode == 0, proc.stdout + proc.stderr


def run_lint(json_path: Path) -> Tuple[bool, str]:
    return _run([str(_TOOLS / "lint_storyboard.py"), str(json_path)])


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
