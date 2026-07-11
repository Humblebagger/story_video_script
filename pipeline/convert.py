"""编排器：文本 → 分批 → LLM 转换 → 校验（失败回喂重试）→ 合并 → 整章终检。"""
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from . import quality, review, validate
from .config import Settings, load_settings
from .llm import extract_json
from .prompt import build_user_message, load_system_prompt
from .splitter import split_batches


@dataclass
class ConvertParams:
    """用户输入模板的【制作参数】+ 作品信息。"""
    work_title: str = "未命名作品"
    chapter: str = "全文"
    style_prefix: str = "电影感写实风格，自然光影"
    art_style: str = "realistic"
    color_tone: str = "自然色调"
    aspect_ratio: str = "9:16"
    target_platform: str = "抖音"
    narration_mode: str = "selective"
    tts_voice: str = "male_mature"


class ConversionError(RuntimeError):
    def __init__(self, msg: str, report: str = ""):
        super().__init__(msg)
        self.report = report


def _continuation_blocks(outputs: List[dict]) -> (str, str):
    """由已完成批次推算下一批的【已有资产库】与【续批参数】。"""
    units = [u for doc in outputs for u in doc["source"]["units"]]
    next_unit = max(int(u["id"][1:]) for u in units) + 1
    next_para = max(int(u.get("para", 0)) for u in units) + 1
    next_ep = max(int(e["id"][1:]) for doc in outputs for e in doc["episodes"]) + 1
    # 后批输出须完整沿用资产库，故最近一批的 assets 即累计全量
    assets = json.dumps(outputs[-1]["assets"], ensure_ascii=False, indent=2)
    meta = json.dumps(outputs[0]["meta"], ensure_ascii=False, indent=2)
    continuation = (f"起始句子编号：u{next_unit:04d}；起始段落编号：{next_para}；"
                    f"起始分集编号：E{next_ep:02d}\n首批 meta（逐字沿用）：\n{meta}")
    return assets, continuation


def _check_batch(doc: dict, batch_text: str, settings: Settings,
                 workdir: Path, idx: int, attempt: int,
                 review_llm, log):
    """结构校验 → 质量门 → 可选评审。返回 (是否通过, 硬失败?, 报告, 择优键)。

    硬失败（schema/lint/保真不过）的产物合同已破坏，不可交付；
    软失败（密度门/评审分不过）的产物合法可用，仅质量不达标，
    择优键（越大越接近达标）供重试耗尽后降级交付时挑最优一版。
    """
    tmp = workdir / f"batch{idx}_attempt{attempt}.json"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    lint_ok, lint_out = validate.run_lint(tmp)
    fid_ok, fid_out = validate.run_fidelity(tmp, batch_text, workdir)
    if not (lint_ok and fid_ok):
        return False, True, lint_out.strip() + "\n" + fid_out.strip(), None

    gate_ok, gate_report, ratio = quality.narration_density_gate(
        doc, settings.narration_density_max)
    if not gate_ok:
        return False, False, gate_report, (1, -ratio)

    if settings.review_enabled and review_llm is not None:
        rev_ok, rev_report, overall = review.run_review(
            review_llm, batch_text, doc, settings.review_min_score)
        if rev_ok is None:
            log(f"批 {idx} {rev_report}")
        else:
            log(rev_report.splitlines()[0])
            if not rev_ok:
                # 评审失败排在密度失败之后择优（它已多过一道门）
                return False, False, rev_report, (2, overall)
    return True, False, "", None


def _convert_batch(llm, system: str, user: str, batch_text: str, params,
                   settings: Settings, workdir: Path, idx: int,
                   review_llm, log) -> Tuple[dict, List[str]]:
    """返回 (产物, 质量警告列表)。警告非空即降级交付。"""
    messages = [{"role": "user", "content": user}]
    last_report = ""
    candidates = []  # 软失败但结构合法的历次尝试：(择优键, 第几次, 产物, 报告)
    for attempt in range(settings.max_retries + 1):
        raw = llm.complete(system, messages)
        try:
            doc = extract_json(raw)
        except ValueError as e:
            last_report = f"输出无法解析为 JSON：{e}"
            log(f"批 {idx} 第 {attempt + 1} 次生成：{last_report}")
        else:
            quality.apply_meta_overrides(doc, params)
            ok, hard, last_report, key = _check_batch(
                doc, batch_text, settings, workdir, idx, attempt + 1,
                review_llm, log)
            if ok:
                log(f"批 {idx} 校验通过（第 {attempt + 1} 次生成）")
                return doc, []
            if not hard:
                candidates.append((key, attempt + 1, doc, last_report))
            log(f"批 {idx} 第 {attempt + 1} 次生成未通过"
                f"{'校验' if hard else '质量门'}")
        if attempt < settings.max_retries:
            log(f"批 {idx} 回喂校验报告重试（{attempt + 2}/{settings.max_retries + 1}）…")
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content":
                             "你的输出未通过自动校验，报告如下：\n\n" + last_report +
                             "\n\n请修正全部问题后重新输出完整 JSON"
                             "（只输出一个 JSON 对象，不要解释文字，不要代码块标记）。"})

    if candidates and not settings.strict:
        key, best_attempt, doc, report = max(candidates, key=lambda c: c[0])
        log(f"批 {idx} 软质量门重试耗尽，择优降级交付第 {best_attempt} 次生成"
            f"（产物结构合法、逐字保真；--strict 可改为直接失败）")
        warning = (f"批 {idx} 软质量门重试 {settings.max_retries} 次后仍未达标，"
                   f"择优交付第 {best_attempt} 次生成（共 {len(candidates)} 个合法候选）。"
                   f"产物结构合法、逐字保真，仅转换质量未达阈值：\n{report}")
        return doc, [warning]

    (workdir / f"batch{idx}_failure_report.txt").write_text(
        last_report + "\n", encoding="utf-8")
    raise ConversionError(
        f"批 {idx} 重试 {settings.max_retries} 次后仍未通过校验"
        f"（已通过批次与失败报告保留在 {workdir}）", last_report)


def convert_text(text: str,
                 params: Optional[ConvertParams] = None,
                 settings: Optional[Settings] = None,
                 llm=None,
                 batches: Optional[List[str]] = None,
                 workdir: Optional[Path] = None,
                 log=print,
                 warnings_out: Optional[List[str]] = None) -> dict:
    """小说纯文本 → 通过三层校验的分镜 JSON（dict）。

    llm 可注入任何带 complete(system, messages) -> str 的对象（测试用 mock）。
    batches 可显式指定分批切片（缺省用 splitter 自动切）。
    硬校验（schema/lint/保真）不通过且重试耗尽时抛 ConversionError
    （.report 含完整校验报告）；软质量门（旁白密度/评审分）重试耗尽时
    择优降级交付，质量报告追加进 warnings_out（settings.strict 时同样抛错）。
    """
    params = params or ConvertParams()
    settings = settings or load_settings()
    if llm is None:
        from .llm import LLMClient
        llm = LLMClient(settings)
        review_llm = llm
        if settings.review_enabled and settings.review_model \
                and settings.review_model != settings.model:
            from dataclasses import replace
            review_llm = LLMClient(replace(settings, model=settings.review_model))
    else:
        review_llm = llm  # 注入的客户端（含测试 mock）同时承担评审调用
    if batches is None:
        batches = split_batches(text, settings.batch_target_chars,
                                settings.single_batch_max_chars)
    workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="storyboard_"))
    workdir.mkdir(parents=True, exist_ok=True)
    system = load_system_prompt()
    log(f"输入 {len(text)} 字符 → {len(batches)} 批（工作目录 {workdir}）")

    outputs: List[dict] = []
    batch_paths: List[Path] = []
    for i, batch in enumerate(batches, 1):
        if outputs:
            assets_block, cont_block = _continuation_blocks(outputs)
        else:
            assets_block = cont_block = "无"
        user = build_user_message(params, batch, assets_block, cont_block)
        log(f"批 {i}/{len(batches)}（{len(batch)} 字符）：调用 LLM…")
        doc, batch_warnings = _convert_batch(llm, system, user, batch, params,
                                             settings, workdir, i, review_llm, log)
        if batch_warnings and warnings_out is not None:
            warnings_out.extend(batch_warnings)
        path = workdir / f"batch{i}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        outputs.append(doc)
        batch_paths.append(path)

    if len(batch_paths) == 1:
        merged_path = batch_paths[0]
    else:
        merged_path = workdir / "merged.json"
        ok, out = validate.run_merge(batch_paths, merged_path)
        log(out.strip())
        if not ok:
            raise ConversionError("分批结果合并失败（资产跨批不一致）", out)

    lint_ok, lint_out = validate.run_lint(merged_path)
    fid_ok, fid_out = validate.run_fidelity(merged_path, text, workdir)
    log(lint_out.strip())
    log(fid_out.strip())
    if not (lint_ok and fid_ok):
        raise ConversionError("合并后整章终检未通过", lint_out + "\n" + fid_out)
    return json.loads(merged_path.read_text(encoding="utf-8"))
