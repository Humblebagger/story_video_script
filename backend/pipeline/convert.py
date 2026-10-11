"""编排器：文本 → 分批 → LLM 转换 → 校验（失败回喂重试）→ 合并 → 整章终检。"""
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import validate, verification
from .chat import ChatInvoker
from .config import Settings, load_settings
from .errors import ConversionError
from .graph import build_batch_graph, run_batch
from .manifest import build_manifest, finish_manifest, sum_usage
from .prompt import build_user_message
from .source_units import build_frozen_units, manifest_units, prompt_units
from .splitter import normalize_source_text, split_batches


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


def convert_text(text: str,
                 params: Optional[ConvertParams] = None,
                 settings: Optional[Settings] = None,
                 llm=None,
                 batches: Optional[List[str]] = None,
                 workdir: Optional[Path] = None,
                 log=print,
                 warnings_out: Optional[List[str]] = None,
                 seed_assets: Optional[dict] = None,
                 manifest_out: Optional[dict] = None) -> dict:
    """小说纯文本 → 通过三层校验的分镜 JSON（dict）。

    llm 可注入任何 BaseChatModel（测试用 FakeChat）。
    batches 可显式指定分批切片（缺省用 splitter 自动切）。
    硬校验（schema/lint/保真）不通过且重试耗尽时抛 ConversionError
    （.report 含完整校验报告）；软质量门（旁白密度/评审分）重试耗尽时
    择优降级交付，质量报告追加进 warnings_out（settings.strict 时同样抛错）。
    seed_assets 为历史资产库（assets 对象），传入后首批即带【已有资产库】，
    模型须沿用其 ID 与描述——用于续写同一部小说的下一章时保持角色/场景一致。
    """
    params = params or ConvertParams()
    settings = settings or load_settings()
    raw_text = text
    if settings.normalize_input:
        # 剔除后全链路（分批/LLM/保真检查）一律以清洗后文本为"原文"；
        # 显式传入的 batches 同步清洗，保证批拼接仍等于 text
        text, removed = normalize_source_text(text)
        if batches is not None:
            batches = [normalize_source_text(b)[0] for b in batches]
        if removed:
            log(f"输入归一化：剔除 {removed} 个零宽/BOM 噪声字符"
                f"（STORYBOARD_NORMALIZE_INPUT=0 关闭）")
    if llm is None:
        chat = ChatInvoker(settings, log=log)
    else:
        # 注入的 BaseChatModel（含测试替身）：共用一个用量回调，账才是一本
        chat = ChatInvoker(settings, chat=llm, log=log)
    review_chat = chat
    if settings.review_enabled and settings.review_model \
            and settings.review_model != settings.model and llm is None:
        # 评审用另一档模型时单独建一个，但共用同一个 UsageCallback
        review_chat = ChatInvoker(settings, model=settings.review_model,
                                  usage=chat.usage, log=log)
    if batches is None:
        batches = split_batches(text, settings.batch_target_chars,
                                settings.single_batch_max_chars)
    if settings.freeze_source_units and "".join(batches) != text:
        raise ConversionError("分批范围不确定：所有批次必须按顺序精确拼回归一化原文")

    frozen = build_frozen_units(text, batches) if settings.freeze_source_units else []
    frozen_manifest = manifest_units(frozen)
    run_manifest = build_manifest(raw_text, text, batches, frozen_manifest,
                                  params, settings)
    if manifest_out is not None:
        manifest_out.clear()
        manifest_out.update(run_manifest)
        # 后续 attempt/终检/哈希都原地写入调用方持有的同一个对象。
        run_manifest = manifest_out
    workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="storyboard_"))
    workdir.mkdir(parents=True, exist_ok=True)
    attempt_records = run_manifest["attempts"]
    log(f"输入 {len(text)} 字符 → {len(batches)} 批（工作目录 {workdir}）")
    graph = build_batch_graph(chat=chat, review_chat=review_chat,
                              settings=settings, params=params, workdir=workdir,
                              attempt_records=attempt_records, log=log)

    outputs: List[dict] = []
    batch_paths: List[Path] = []
    for i, batch in enumerate(batches, 1):
        if outputs:
            assets_block, cont_block = _continuation_blocks(outputs)
        elif seed_assets:
            # 跨转换沿用资产库（如续写同一部小说的下一章）：句子/分集编号仍从头起，
            # 只让模型沿用已有 C/S/P/A 卡的 ID 与描述，从根上防跨章角色漂移
            assets_block = json.dumps(seed_assets, ensure_ascii=False, indent=2)
            cont_block = "无"
        else:
            assets_block = cont_block = "无"
        expected_units = prompt_units(frozen, i) if settings.freeze_source_units else None
        user = build_user_message(params, batch, assets_block, cont_block,
                                  expected_units)
        log(f"批 {i}/{len(batches)}（{len(batch)} 字符）：调用 LLM…")
        doc, batch_warnings = run_batch(graph, user=user, batch_text=batch,
                                        idx=i, frozen_units=expected_units)
        run_manifest["usage"] = sum_usage(attempt_records)
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

    merged_doc = json.loads(merged_path.read_text(encoding="utf-8"))
    expected_all = ([u.prompt_dict() for u in frozen]
                    if settings.freeze_source_units else None)
    probe = verification.verify_document(
        merged_doc, frozen_units=expected_all, original_text=text)
    verification.recompute_coverage_field(merged_doc, probe.coverage)
    merged_path.write_text(json.dumps(merged_doc, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    final_report = verification.verify_document(
        merged_doc, frozen_units=expected_all, original_text=text)

    lint_ok, lint_out = validate.run_lint(merged_path)
    fid_ok, fid_out = validate.run_fidelity(merged_path, text, workdir)
    log(lint_out.strip())
    log(fid_out.strip())
    log(final_report.render())
    if not final_report.ok:
        run_manifest["state"] = "failed"
        run_manifest["verification"] = final_report.to_dict()
        raise ConversionError("合并后结构化终检未通过", final_report.render())
    if not (lint_ok and fid_ok):
        run_manifest["state"] = "failed"
        run_manifest["verification"] = final_report.to_dict()
        raise ConversionError("合并后整章终检未通过", lint_out + "\n" + fid_out)
    finish_manifest(run_manifest, merged_doc, final_report, "verified")
    return merged_doc
