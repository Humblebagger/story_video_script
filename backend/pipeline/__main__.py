"""CLI：
  python3 -m pipeline convert <novel.txt> [-o storyboard.json] [选项]
  python3 -m pipeline verify  <storyboard.json | 落盘的 run 记录> [--source 原文.txt]
"""
import argparse
import json
import sys
from pathlib import Path

from . import validate
from .convert import ConversionError, ConvertParams, convert_text
from .chat import LLMError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m pipeline",
        description="小说文本 → 分镜 IR JSON（自动分批、LLM 转换、校验重试、合并终检）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("convert", help="转换一份小说文本")
    c.add_argument("input", help="小说原文纯文本文件（UTF-8）")
    c.add_argument("-o", "--output", default="storyboard.json", help="输出 JSON 路径")
    c.add_argument("--title", default="未命名作品", help="作品名")
    c.add_argument("--chapter", default="全文", help="章节名")
    c.add_argument("--style-prefix", default=ConvertParams.style_prefix)
    c.add_argument("--art-style", default=ConvertParams.art_style)
    c.add_argument("--color-tone", default=ConvertParams.color_tone)
    c.add_argument("--aspect-ratio", default=ConvertParams.aspect_ratio)
    c.add_argument("--platform", default=ConvertParams.target_platform)
    c.add_argument("--narration-mode", default=ConvertParams.narration_mode,
                   choices=["selective", "original_text"])
    c.add_argument("--tts-voice", default=ConvertParams.tts_voice)
    c.add_argument("--render", metavar="DIR",
                   help="转换成功后附带渲染 Seedance 生产包到该目录（参考实现）")
    c.add_argument("--review", action="store_true",
                   help="开启 LLM 评审阶段（等效 STORYBOARD_REVIEW=1，弱模型建议开启）")
    c.add_argument("--strict", action="store_true",
                   help="软质量门（旁白密度/评审分）重试耗尽时直接失败"
                        "（默认择优降级交付并附质量报告）")

    v = sub.add_parser("verify", help="对已有产物重新跑一遍独立验证与指纹核对")
    v.add_argument("input", help="分镜 IR JSON，或 data/users/*/runs/*.json 落盘记录")
    v.add_argument("--source", help="原文纯文本；给了就一并核对源单元能否拼回原文")
    v.add_argument("--json", action="store_true", help="输出结构化报告而非人读文本")

    args = ap.parse_args(argv)
    if args.cmd == "verify":
        return _verify(args)

    text = Path(args.input).read_text(encoding="utf-8")
    params = ConvertParams(
        work_title=args.title, chapter=args.chapter,
        style_prefix=args.style_prefix, art_style=args.art_style,
        color_tone=args.color_tone, aspect_ratio=args.aspect_ratio,
        target_platform=args.platform, narration_mode=args.narration_mode,
        tts_voice=args.tts_voice)

    settings = None
    if args.review or args.strict:
        from .config import load_settings
        settings = load_settings()
        settings.review_enabled = settings.review_enabled or args.review
        settings.strict = settings.strict or args.strict

    warnings: list = []
    try:
        doc = convert_text(text, params, settings=settings,
                           warnings_out=warnings)
    except ConversionError as e:
        print(f"\n转换失败：{e}\n{e.report}", file=sys.stderr)
        return 1
    except LLMError as e:
        print(f"\n转换失败：{e}" + (f"\n{e.hint}" if e.hint else ""), file=sys.stderr)
        return 1

    out = Path(args.output)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    units = len(doc["source"]["units"])
    shots = sum(len(e.get("shots", [])) for e in doc["episodes"])
    print(f"\n完成：{units} 句 / {len(doc['episodes'])} 集 / {shots} 镜 → {out}")

    if warnings:
        report_path = out.with_name(out.stem + ".quality-report.txt")
        report_path.write_text("\n\n".join(warnings) + "\n", encoding="utf-8")
        print(f"⚠ 软质量门未达标，已择优降级交付（--strict 可改为直接失败），"
              f"质量报告：{report_path}", file=sys.stderr)

    if args.render:
        ok, msg = validate.run_adapter(out, Path(args.render))
        print(msg.strip())
        if not ok:
            return 1
    return 0


def _verify(args) -> int:
    """对已经落盘的产物重新独立验证。

    清单里记了输入哈希、提示词与 schema 的哈希、产物哈希，但在此之前没有任何
    东西读它——提示词改过一版之后回头编辑或渲染一份旧产物，是在静默混用两套契约。
    """
    from . import verification
    from .manifest import file_sha256, sha256_json
    from .config import ROOT

    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    record = raw if "result" in raw and "id" in raw else None
    doc = record["result"] if record else raw
    if not isinstance(doc, dict) or not doc.get("episodes"):
        print(f"不是分镜 IR，也不是可识别的 run 记录：{args.input}", file=sys.stderr)
        return 2
    manifest = (record or {}).get("manifest") or {}

    frozen = ((manifest.get("scope") or {}).get("units")
              or [{k: u.get(k) for k in ("id", "text", "para")}
                  for u in (doc.get("source") or {}).get("units") or []])
    source_text = (Path(args.source).read_text(encoding="utf-8")
                   if args.source else None)
    notes = []
    if source_text is not None:
        # convert 入口默认剔除零宽字符，产物的句单元是清洗后的文本；拿未清洗的原文
        # 去比会误报 FID-SOURCE-001。产物自己不含零宽字符，就按同一口径清洗原文；
        # 产物保留了它们（关掉归一化转出来的，如《药》归档）则原样比
        from .splitter import ZERO_WIDTH_RE, normalize_source_text
        units_text = "".join(u.get("text") or "" for u in frozen)
        if not ZERO_WIDTH_RE.search(units_text):
            source_text, removed = normalize_source_text(source_text)
            if removed:
                notes.append(f"原文含 {removed} 个零宽字符，已按 convert 入口的口径"
                             "清洗后再比对（产物句单元本就不含它们）")

    # 先按确定性口径重算 coverage 再复验：文档里声明的那份不作数
    probe = verification.verify_document(doc, frozen_units=frozen,
                                         original_text=source_text)
    checked = json.loads(json.dumps(doc))
    verification.recompute_coverage_field(checked, probe.coverage)
    report = verification.verify_document(checked, frozen_units=frozen,
                                          original_text=source_text)

    drift = []
    contracts = manifest.get("contracts") or {}
    for key, path in (("prompt_sha256", ROOT / "prompts" / "novel_to_storyboard.md"),
                      ("schema_sha256", ROOT / "schema" / "storyboard.schema.json")):
        if contracts.get(key) and contracts[key] != file_sha256(path):
            drift.append(f"{path.name} 已与生成这份产物时不同"
                         f"（当时 {contracts[key][:12]}…，现在 {file_sha256(path)[:12]}…）")
    stored = manifest.get("artifact_sha256")
    fingerprint = sha256_json(doc)
    if stored and stored != fingerprint:
        drift.append(f"产物指纹与清单不符（清单 {stored[:12]}…，实际 {fingerprint[:12]}…）"
                     "——多半是转换之后被人工编辑过")

    if args.json:
        print(json.dumps({"verification": report.to_dict(), "drift": drift,
                          "artifact_sha256": fingerprint},
                         ensure_ascii=False, indent=2))
    else:
        for line in notes:
            print(f"NOTE {line}")
        print(report.render())
        for line in drift:
            print(f"DRIFT {line}")
        if not drift and contracts:
            print("DRIFT 无：提示词、schema 与产物指纹都和清单对得上")
        elif not contracts:
            print("DRIFT 未知：这份产物没有转换清单（旧记录或裸 IR），只做了结构验证")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
