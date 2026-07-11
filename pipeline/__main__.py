"""CLI：python3 -m pipeline convert <novel.txt> [-o storyboard.json] [选项]"""
import argparse
import json
import sys
from pathlib import Path

from . import validate
from .convert import ConversionError, ConvertParams, convert_text


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

    args = ap.parse_args(argv)
    text = Path(args.input).read_text(encoding="utf-8")
    params = ConvertParams(
        work_title=args.title, chapter=args.chapter,
        style_prefix=args.style_prefix, art_style=args.art_style,
        color_tone=args.color_tone, aspect_ratio=args.aspect_ratio,
        target_platform=args.platform, narration_mode=args.narration_mode,
        tts_voice=args.tts_voice)

    try:
        doc = convert_text(text, params)
    except ConversionError as e:
        print(f"\n转换失败：{e}\n{e.report}", file=sys.stderr)
        return 1

    out = Path(args.output)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    units = len(doc["source"]["units"])
    shots = sum(len(e.get("shots", [])) for e in doc["episodes"])
    print(f"\n完成：{units} 句 / {len(doc['episodes'])} 集 / {shots} 镜 → {out}")

    if args.render:
        ok, msg = validate.run_adapter(out, Path(args.render))
        print(msg.strip())
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
