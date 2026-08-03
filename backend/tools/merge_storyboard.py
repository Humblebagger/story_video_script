#!/usr/bin/env python3
"""分批转换结果合并器：把长章节按批产出的多份 storyboard JSON 合并成一份。

用法: python3 tools/merge_storyboard.py <批1.json> <批2.json> [...] -o <合并输出.json>

合并规则:
  - meta        取第一批；后批与首批不一致的字段报 WARN（续批要求 meta 一致）
  - source      units 按批次顺序拼接；unit ID 重复报 ERROR；编号断档报 WARN
  - assets      按 ID 合并。同 ID 卡片在多批出现时，除 outfits/angles/reference_images
                之外的字段必须逐字一致（续批规则：原卡原描述沿用），否则报 ERROR；
                outfits/angles/reference_images 按子项 ID 取并集（续批允许追加新状态）；
                例外——匿名卡身份揭示：characters 的 name/persona_notes 允许后批回改
                （取后批值 + WARN），aliases 取保序并集；视觉字段仍冻结
  - episodes    拼接；episode ID 重复报 ERROR
  - coverage    丢弃各批声明值，按合并结果重新计算（口径与 lint 一致）
合并后请再跑 tools/lint_storyboard.py 与 tools/check_fidelity.py（对整章原文）做终检。
"""
import argparse
import json
import sys
from pathlib import Path

MERGEABLE_LISTS = {"outfits": "id", "states": "id", "angles": "angle", "reference_images": "uri"}
# 匿名卡身份揭示预案：身份元信息允许后批回改（视觉字段仍冻结）
IDENTITY_OVERRIDABLE = {"name", "persona_notes"}


def merge_asset_card(base: dict, new: dict, kind: str, errors: list, warnings: list) -> None:
    """同 ID 资产卡合并：可增列表取并集，身份元信息后批可回改，其余字段必须一致。"""
    for key in set(base) | set(new):
        if kind == "characters" and key in IDENTITY_OVERRIDABLE:
            if key in new and base.get(key) != new[key]:
                warnings.append(f"[assets] {kind} {base.get('id')} 的 {key} 被后批回改"
                                f"（匿名卡身份揭示预案）: {base.get(key)!r} → {new[key]!r}")
                base[key] = new[key]
        elif kind == "characters" and key == "aliases":
            merged = list(base.get(key, []))
            added = [a for a in new.get(key, []) if a not in merged]
            if added:
                warnings.append(f"[assets] {kind} {base.get('id')} 的 aliases 追加: {added}")
                merged.extend(added)
            if merged:
                base[key] = merged
        elif key in MERGEABLE_LISTS:
            subkey = MERGEABLE_LISTS[key]
            existing = {item.get(subkey) for item in base.get(key, [])}
            merged = list(base.get(key, []))
            for item in new.get(key, []):
                if item.get(subkey) not in existing:
                    merged.append(item)
                elif next(i for i in base.get(key, []) if i.get(subkey) == item.get(subkey)) != item:
                    errors.append(f"[assets] {kind} {base.get('id')} 的 {key}.{item.get(subkey)} 在两批中描述不一致")
            if merged:
                base[key] = merged
        elif key not in base:
            base[key] = new[key]
        elif key in new and base[key] != new[key]:
            errors.append(f"[assets] {kind} {base.get('id')} 的字段 {key} 在两批中不一致（续批应原样沿用）")


def recompute_coverage(doc: dict) -> dict:
    units = {u["id"]: u for u in doc["source"]["units"]}
    mode = doc.get("meta", {}).get("narration", {}).get("mode", "original_text")
    narrated, dial, visual = set(), set(), set()
    total = inferred = 0
    for ep in doc.get("episodes", []):
        for shot in ep.get("shots", []):
            total += 1
            src = shot.get("source", {})
            if src.get("derivation") == "inferred":
                inferred += 1
            visual.update(src.get("unit_refs", []))
            narrated.update(shot.get("narration", {}).get("unit_refs", []))
            if any(d.get("verbatim", True) for d in shot.get("dialogue", [])):
                dial.update(r for r in src.get("unit_refs", [])
                            if units.get(r, {}).get("kind") == "dialogue")
    covered = narrated | dial
    if mode != "original_text":
        covered |= visual
    unmapped = [uid for uid, u in units.items() if not u.get("skipped") and uid not in covered]
    return {"unmapped_units": unmapped,
            "inferred_shot_ratio": round(inferred / total, 2) if total else 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batches", nargs="+")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()

    docs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.batches]
    merged = docs[0]
    errors, warnings = [], []

    for n, doc in enumerate(docs[1:], start=2):
        # meta 一致性
        for key, val in doc.get("meta", {}).items():
            if key in merged["meta"] and merged["meta"][key] != val:
                warnings.append(f"[meta] 批{n} 的 {key} 与首批不一致，沿用首批值")

        # units 拼接
        seen = {u["id"] for u in merged["source"]["units"]}
        for u in doc["source"]["units"]:
            if u["id"] in seen:
                errors.append(f"[source] 批{n} 的句子 ID 重复: {u['id']}")
            merged["source"]["units"].append(u)
        nums = sorted(int(u["id"][1:]) for u in merged["source"]["units"])
        gaps = [f"u{i:04d}" for a, b in zip(nums, nums[1:]) for i in range(a + 1, b)]
        if gaps:
            warnings.append(f"[source] 句子编号断档: {gaps}")

        # assets 按 ID 合并
        for kind in ("characters", "locations", "props", "creatures"):
            index = {c["id"]: c for c in merged["assets"].get(kind, [])}
            for card in doc.get("assets", {}).get(kind, []):
                if card["id"] in index:
                    merge_asset_card(index[card["id"]], card, kind, errors, warnings)
                else:
                    merged["assets"].setdefault(kind, []).append(card)

        # episodes 拼接
        ep_seen = {e["id"] for e in merged.get("episodes", [])}
        for ep in doc.get("episodes", []):
            if ep["id"] in ep_seen:
                errors.append(f"[episodes] 批{n} 的分集 ID 重复: {ep['id']}")
            merged["episodes"].append(ep)

    merged["coverage"] = recompute_coverage(merged)

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    if errors:
        print(f"FAIL（{len(errors)} 个错误，未写出文件）")
        return 1
    Path(args.output).write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    ups = len(merged["source"]["units"])
    shots = sum(len(e.get("shots", [])) for e in merged["episodes"])
    print(f"合并完成: {len(docs)} 批 → {ups} 句 / {len(merged['episodes'])} 集 / {shots} 镜 "
          f"→ {args.output}")
    print("请继续运行 lint_storyboard.py 与 check_fidelity.py（对整章原文）终检。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
