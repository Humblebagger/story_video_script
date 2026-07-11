#!/usr/bin/env python3
"""NovelStoryboard v0.4 校验器。

用法: python3 tools/lint_storyboard.py <storyboard.json>

两层检查:
  1. JSON Schema 结构校验（需要 pip install jsonschema，未安装则跳过并提示）
  2. 跨引用与忠实性检查（schema 表达不了的部分）:
     - 镜头引用的 unit / 角色 / 场景 / 道具 / outfit 必须真实存在
     - inferred 镜头必须有 inference_note
     - 旁白覆盖率: 每个非 skipped 的 unit 必须被至少一个镜头的 narration 引用
     - coverage 字段与实际计算结果一致
"""
import json
import re
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "storyboard.schema.json"


def main(path: str) -> int:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    errors, warnings = [], []

    # ---- 1. JSON Schema 校验 ----
    try:
        import jsonschema
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for e in validator.iter_errors(doc):
            errors.append(f"[schema] {'/'.join(map(str, e.absolute_path))}: {e.message}")
    except ImportError:
        warnings.append("jsonschema 未安装，跳过结构校验（pip install jsonschema）")

    # ---- 2. 跨引用检查 ----
    units = {u["id"]: u for u in doc.get("source", {}).get("units", [])}
    chars = {c["id"]: c for c in doc.get("assets", {}).get("characters", [])}
    locs = {s["id"] for s in doc.get("assets", {}).get("locations", [])}
    props = {p["id"]: p for p in doc.get("assets", {}).get("props", [])}
    creatures = {a["id"] for a in doc.get("assets", {}).get("creatures", [])}

    narrated_units = set()
    dialogue_covered = set()  # dialogue 类句子可由角色台词承载，无需旁白重读
    visual_covered = set()    # 出现在镜头 source.unit_refs 中即画面承载（selective/none 模式计入覆盖）
    narration_mode = doc.get("meta", {}).get("narration", {}).get("mode", "original_text")
    total_shots = inferred_shots = 0

    for ep in doc.get("episodes", []):
        # music 情绪曲线检查
        music = ep.get("music")
        if music:
            shot_ids = [s.get("id") for s in ep.get("shots", [])]
            pos = {sid: i for i, sid in enumerate(shot_ids)}
            prev_end = -1
            for seg in music.get("curve", []):
                f, t = seg.get("from_shot"), seg.get("to_shot")
                for ref in (f, t):
                    if ref not in pos:
                        errors.append(f"[{ep.get('id')}] music.curve 引用不存在于本集的镜头: {ref}")
                for ref in seg.get("unit_refs", []):
                    if ref not in units:
                        errors.append(f"[{ep.get('id')}] music.curve.unit_refs 引用不存在的句子: {ref}")
                if f in pos and t in pos:
                    if pos[f] > pos[t]:
                        errors.append(f"[{ep.get('id')}] music.curve 区间倒序: {f} > {t}")
                    if pos[f] != prev_end + 1:
                        warnings.append(f"[{ep.get('id')}] music.curve 段落不连续（{f} 之前有缝隙或重叠）")
                    prev_end = pos[t]
            if music.get("curve") and prev_end != len(shot_ids) - 1:
                warnings.append(f"[{ep.get('id')}] music.curve 未覆盖到本集最后一镜")

        for shot in ep.get("shots", []):
            sid = shot.get("id", "?")
            total_shots += 1

            if not shot.get("id", "").startswith(f"{ep.get('id', '')}-"):
                warnings.append(f"[{sid}] 镜头 ID 前缀与所属集 {ep.get('id')} 不一致")

            src = shot.get("source", {})
            for ref in src.get("unit_refs", []):
                if ref not in units:
                    errors.append(f"[{sid}] source.unit_refs 引用不存在的句子: {ref}")
                else:
                    visual_covered.add(ref)
            if src.get("derivation") == "inferred" and not src.get("inference_note"):
                errors.append(f"[{sid}] derivation=inferred 但缺少 inference_note")
            if src.get("derivation") == "inferred":
                inferred_shots += 1

            loc = shot.get("location_ref")
            if loc and loc not in locs:
                errors.append(f"[{sid}] location_ref 引用不存在的场景: {loc}")

            for pr in shot.get("prop_refs", []):
                ref = pr.get("ref") if isinstance(pr, dict) else pr
                if ref not in props:
                    errors.append(f"[{sid}] prop_refs 引用不存在的道具: {ref}")
                    continue
                state = pr.get("state") if isinstance(pr, dict) else None
                state_ids = {s["id"] for s in props[ref].get("states", [])}
                if state_ids and not state:
                    errors.append(f"[{sid}] 道具 {ref} 有状态集，引用必须填 state（可选: {sorted(state_ids)}）")
                elif state_ids and state not in state_ids:
                    errors.append(f"[{sid}] 道具 {ref} 不存在 state '{state}'（可选: {sorted(state_ids)}）")
                elif not state_ids and state:
                    errors.append(f"[{sid}] 道具 {ref} 无 states，引用不应填 state")

            for ch in shot.get("characters", []):
                ref = ch.get("ref")
                if ref in creatures:
                    if ch.get("outfit"):
                        errors.append(f"[{sid}] 生物 {ref} 引用不应填 outfit")
                    continue
                if ref not in chars:
                    errors.append(f"[{sid}] characters.ref 引用不存在的角色/生物: {ref}")
                    continue
                outfit = ch.get("outfit", "default")
                outfit_ids = {o["id"] for o in chars[ref].get("outfits", [])}
                if outfit_ids and outfit not in outfit_ids:
                    errors.append(f"[{sid}] 角色 {ref} 不存在 outfit '{outfit}'（可选: {sorted(outfit_ids)}）")

            for d in shot.get("dialogue", []):
                cref = d.get("character_ref")
                if cref and cref not in chars:
                    errors.append(f"[{sid}] dialogue.character_ref 引用不存在的角色: {cref}")

            narr = shot.get("narration", {})
            for ref in narr.get("unit_refs", []):
                if ref not in units:
                    errors.append(f"[{sid}] narration.unit_refs 引用不存在的句子: {ref}")
                narrated_units.add(ref)

            if any(d.get("verbatim", True) for d in shot.get("dialogue", [])):
                for ref in src.get("unit_refs", []):
                    if units.get(ref, {}).get("kind") == "dialogue":
                        dialogue_covered.add(ref)

    # ---- 3. 覆盖率（口径随旁白模式）----
    # original_text: 每句必须被旁白朗读或台词承载（逐句朗读形态）
    # selective/condensed/none: 画面承载（source.unit_refs）同样算覆盖
    covered = narrated_units | dialogue_covered
    if narration_mode != "original_text":
        covered |= visual_covered
    unmapped = [uid for uid, u in units.items()
                if not u.get("skipped") and uid not in covered]
    if unmapped:
        errors.append(f"[coverage] 以下句子未被任何镜头旁白覆盖且未标 skipped: {unmapped}")

    declared = doc.get("coverage", {})
    if declared:
        if sorted(declared.get("unmapped_units", [])) != sorted(unmapped):
            warnings.append(f"[coverage] 声明的 unmapped_units 与实际不符，实际: {unmapped}")
        if total_shots:
            actual_ratio = round(inferred_shots / total_shots, 2)
            if abs(declared.get("inferred_shot_ratio", 0) - actual_ratio) > 0.011:
                warnings.append(f"[coverage] inferred_shot_ratio 声明 {declared.get('inferred_shot_ratio')}，实际 {actual_ratio}")

    # ---- 汇报 ----
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    ratio = round(inferred_shots / total_shots, 2) if total_shots else 0
    visual_only = (visual_covered - narrated_units - dialogue_covered) & set(units)
    print(f"\n旁白模式 {narration_mode}；镜头 {total_shots} 个（inferred {inferred_shots} 个，占比 {ratio}）；"
          f"句子 {len(units)} 个，已覆盖 {len(covered & set(units))} 个"
          f"（旁白 {len(narrated_units & set(units))}，台词承载 {len(dialogue_covered)}，纯画面承载 {len(visual_only)}）。")
    print("PASS" if not errors else f"FAIL（{len(errors)} 个错误）")
    return 0 if not errors else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
