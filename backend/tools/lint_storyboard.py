#!/usr/bin/env python3
"""NovelStoryboard v0.4 / v0.5 校验器。

用法: python3 tools/lint_storyboard.py <storyboard.json>
      python3 tools/lint_storyboard.py --json <storyboard.json>   （机器读：每条错误带规则名与参数）

两层检查:
  1. JSON Schema 结构校验（需要 pip install jsonschema，未安装则跳过并提示）
  2. 跨引用与忠实性检查（schema 表达不了的部分）:
     - 镜头引用的 unit / 角色 / 场景 / 道具 / outfit 必须真实存在
     - 镜头分了 beats，各拍时长之和必须等于镜头时长
     - inferred 镜头必须有 inference_note
     - 旁白覆盖率: 每个非 skipped 的 unit 必须被至少一个镜头的 narration 引用
     - coverage 字段与实际计算结果一致
"""
import json
import re
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "storyboard.schema.json"


def _item(rule: str, text: str, **params) -> dict:
    """一条错误或警告。text 是文本模式打印的原文（转换流水线拿它回喂修复模型，一字不改）；
    rule 与 params 只给 --json 的读者（界面按规则翻译，见 spec 子计划 5b）。"""
    return {"rule": rule, "params": params, "text": text}


def main(path: str, as_json: bool = False) -> int:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    errors, warnings = [], []

    # ---- 1. JSON Schema 校验 ----
    try:
        import jsonschema
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for e in validator.iter_errors(doc):
            errors.append(_item("schema", f"[schema] {'/'.join(map(str, e.absolute_path))}: {e.message}",
                                path="/" + "/".join(map(str, e.absolute_path)), detail=e.message))
    except ImportError:
        warnings.append(_item("schema_unavailable", "jsonschema 未安装，跳过结构校验（pip install jsonschema）"))

    # ---- 2. 跨引用检查 ----
    units = {u["id"]: u for u in doc.get("source", {}).get("units", [])}
    chars = {c["id"]: c for c in doc.get("assets", {}).get("characters", [])}
    locs = {s["id"] for s in doc.get("assets", {}).get("locations", [])}
    props = {p["id"]: p for p in doc.get("assets", {}).get("props", [])}
    creatures = {a["id"] for a in doc.get("assets", {}).get("creatures", [])}

    # 设定图是「画师修正稿反过来约束后续每一帧」这条链的锚点，指错变体等于垫错衣服。
    # 这类引用 schema 表达不了（要跨到同一张卡的 outfits/states 里查），只能在这儿查。
    for card in chars.values():
        outfit_ids = {o["id"] for o in card.get("outfits", [])}
        for img in card.get("reference_images", []):
            tag = img.get("outfit")
            if tag and tag not in outfit_ids:
                errors.append(_item(
                    "ref_image_outfit",
                    f"[{card['id']}] 参考图标注的 outfit '{tag}' 不存在"
                    f"（可选: {sorted(outfit_ids) or '本卡无 outfits'}）",
                    card=card["id"], outfit=tag, options=sorted(outfit_ids)))
    for card in props.values():
        state_ids = {s["id"] for s in card.get("states", [])}
        for img in card.get("reference_images", []):
            tag = img.get("state")
            if tag and tag not in state_ids:
                errors.append(_item(
                    "ref_image_state",
                    f"[{card['id']}] 参考图标注的 state '{tag}' 不存在"
                    f"（可选: {sorted(state_ids) or '本卡无 states'}）",
                    card=card["id"], state=tag, options=sorted(state_ids)))

    for kind in ("characters", "locations", "props", "creatures"):
        for card in doc.get("assets", {}).get(kind, []):
            for c in card.get("constraints", []):
                if not (c or "").strip():
                    errors.append(_item("asset_empty_constraint", f"[{card.get('id')}] constraints 里有空约束项",
                                        card=card.get("id")))

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
                        errors.append(_item("curve_shot", f"[{ep.get('id')}] music.curve 引用不存在于本集的镜头: {ref}",
                                            episode=ep.get("id"), shot=ref))
                for ref in seg.get("unit_refs", []):
                    if ref not in units:
                        errors.append(_item("curve_unit", f"[{ep.get('id')}] music.curve.unit_refs 引用不存在的句子: {ref}",
                                            episode=ep.get("id"), unit=ref))
                if f in pos and t in pos:
                    if pos[f] > pos[t]:
                        errors.append(_item("curve_reversed", f"[{ep.get('id')}] music.curve 区间倒序: {f} > {t}",
                                            episode=ep.get("id"), start=f, end=t))
                    if pos[f] != prev_end + 1:
                        warnings.append(_item("curve_gap", f"[{ep.get('id')}] music.curve 段落不连续（{f} 之前有缝隙或重叠）",
                                              episode=ep.get("id"), shot=f))
                    prev_end = pos[t]
            if music.get("curve") and prev_end != len(shot_ids) - 1:
                warnings.append(_item("curve_incomplete", f"[{ep.get('id')}] music.curve 未覆盖到本集最后一镜",
                                      episode=ep.get("id")))

        for shot in ep.get("shots", []):
            sid = shot.get("id", "?")
            total_shots += 1

            if not shot.get("id", "").startswith(f"{ep.get('id', '')}-"):
                warnings.append(_item("shot_id_prefix", f"[{sid}] 镜头 ID 前缀与所属集 {ep.get('id')} 不一致",
                                      shot=sid, episode=ep.get("id")))

            src = shot.get("source", {})
            for ref in src.get("unit_refs", []):
                if ref not in units:
                    errors.append(_item("shot_unit", f"[{sid}] source.unit_refs 引用不存在的句子: {ref}",
                                        shot=sid, unit=ref))
                else:
                    visual_covered.add(ref)
            if src.get("derivation") == "inferred" and not src.get("inference_note"):
                errors.append(_item("inferred_no_note", f"[{sid}] derivation=inferred 但缺少 inference_note", shot=sid))
            if src.get("derivation") == "inferred":
                inferred_shots += 1

            # v0.5 镜头内阶段：分了拍，时长就必须对得上，否则下游按哪个走全凭猜
            beats = shot.get("beats")
            if beats is not None:
                total = sum(b.get("duration_sec") or 0 for b in beats)
                dur = shot.get("duration_sec") or 0
                if abs(total - dur) > 0.05:
                    errors.append(_item(
                        "beats_duration",
                        f"[{sid}] beats 各拍时长之和 {total:g}s 与镜头 duration_sec {dur:g}s 不符",
                        shot=sid, total=f"{total:g}", duration=f"{dur:g}"))
                for i, b in enumerate(beats, 1):
                    if not (b.get("action") or "").strip():
                        errors.append(_item("beat_no_action", f"[{sid}] beats 第 {i} 拍缺少 action", shot=sid, beat=i))

            for c in shot.get("constraints", []):
                if not (c or "").strip():
                    errors.append(_item("shot_empty_constraint", f"[{sid}] constraints 里有空约束项", shot=sid))

            loc = shot.get("location_ref")
            if loc and loc not in locs:
                errors.append(_item("location_ref", f"[{sid}] location_ref 引用不存在的场景: {loc}",
                                    shot=sid, location=loc))

            for pr in shot.get("prop_refs", []):
                ref = pr.get("ref") if isinstance(pr, dict) else pr
                if ref not in props:
                    errors.append(_item("prop_ref", f"[{sid}] prop_refs 引用不存在的道具: {ref}", shot=sid, prop=ref))
                    continue
                state = pr.get("state") if isinstance(pr, dict) else None
                state_ids = {s["id"] for s in props[ref].get("states", [])}
                if state_ids and not state:
                    errors.append(_item("prop_state_required",
                                        f"[{sid}] 道具 {ref} 有状态集，引用必须填 state（可选: {sorted(state_ids)}）",
                                        shot=sid, prop=ref, options=sorted(state_ids)))
                elif state_ids and state not in state_ids:
                    errors.append(_item("prop_state_unknown",
                                        f"[{sid}] 道具 {ref} 不存在 state '{state}'（可选: {sorted(state_ids)}）",
                                        shot=sid, prop=ref, state=state, options=sorted(state_ids)))
                elif not state_ids and state:
                    errors.append(_item("prop_state_unexpected", f"[{sid}] 道具 {ref} 无 states，引用不应填 state",
                                        shot=sid, prop=ref))

            for ch in shot.get("characters", []):
                ref = ch.get("ref")
                if ref in creatures:
                    if ch.get("outfit"):
                        errors.append(_item("creature_outfit", f"[{sid}] 生物 {ref} 引用不应填 outfit",
                                            shot=sid, creature=ref))
                    continue
                if ref not in chars:
                    errors.append(_item("character_ref", f"[{sid}] characters.ref 引用不存在的角色/生物: {ref}",
                                        shot=sid, character=ref))
                    continue
                outfit = ch.get("outfit", "default")
                outfit_ids = {o["id"] for o in chars[ref].get("outfits", [])}
                if outfit_ids and outfit not in outfit_ids:
                    errors.append(_item("outfit_unknown",
                                        f"[{sid}] 角色 {ref} 不存在 outfit '{outfit}'（可选: {sorted(outfit_ids)}）",
                                        shot=sid, character=ref, outfit=outfit, options=sorted(outfit_ids)))

            for d in shot.get("dialogue", []):
                cref = d.get("character_ref")
                if cref and cref not in chars:
                    errors.append(_item("dialogue_character", f"[{sid}] dialogue.character_ref 引用不存在的角色: {cref}",
                                        shot=sid, character=cref))

            narr = shot.get("narration", {})
            for ref in narr.get("unit_refs", []):
                if ref not in units:
                    errors.append(_item("narration_unit", f"[{sid}] narration.unit_refs 引用不存在的句子: {ref}",
                                        shot=sid, unit=ref))
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
        errors.append(_item("coverage_unmapped", f"[coverage] 以下句子未被任何镜头旁白覆盖且未标 skipped: {unmapped}",
                            n=len(unmapped), units=unmapped))

    declared = doc.get("coverage", {})
    if declared:
        if sorted(declared.get("unmapped_units", [])) != sorted(unmapped):
            warnings.append(_item("coverage_declared_units", f"[coverage] 声明的 unmapped_units 与实际不符，实际: {unmapped}",
                                  actual=unmapped))
        if total_shots:
            actual_ratio = round(inferred_shots / total_shots, 2)
            if abs(declared.get("inferred_shot_ratio", 0) - actual_ratio) > 0.011:
                warnings.append(_item(
                    "coverage_declared_ratio",
                    f"[coverage] inferred_shot_ratio 声明 {declared.get('inferred_shot_ratio')}，实际 {actual_ratio}",
                    declared=declared.get("inferred_shot_ratio"), actual=actual_ratio))

    # ---- 汇报 ----
    # 文本与改造前逐行 print 的结果逐字相同；--json 把同一段文本放进 text 字段，
    # 转换流水线用它回喂修复模型，两种模式回喂的内容不会分叉（spec 子计划 5b D）
    rows = [f"WARN  {w['text']}" for w in warnings] + [f"ERROR {e['text']}" for e in errors]
    ratio = round(inferred_shots / total_shots, 2) if total_shots else 0
    visual_only = (visual_covered - narrated_units - dialogue_covered) & set(units)
    rows.append(f"\n旁白模式 {narration_mode}；镜头 {total_shots} 个（inferred {inferred_shots} 个，占比 {ratio}）；"
                f"句子 {len(units)} 个，已覆盖 {len(covered & set(units))} 个"
                f"（旁白 {len(narrated_units & set(units))}，台词承载 {len(dialogue_covered)}，纯画面承载 {len(visual_only)}）。")
    rows.append("PASS" if not errors else f"FAIL（{len(errors)} 个错误）")
    text = "".join(r + "\n" for r in rows)
    if as_json:
        # 只用 ASCII：不受子进程控制台编码影响；default=str 兜住模型写进编号里的怪值
        print(json.dumps({"version": 1, "ok": not errors, "errors": errors, "warnings": warnings, "text": text},
                         ensure_ascii=True, default=str))
    else:
        sys.stdout.write(text)
    return 0 if not errors else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    as_json = "--json" in args
    paths = [a for a in args if a != "--json"]
    if len(paths) != 1:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(paths[0], as_json=as_json))
