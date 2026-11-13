"""build_clips / request_for 在「没有风格图」时的输出矩阵，供黄金文件生成与比对。

黄金文件由风格图功能之前的代码（fb90f81 的 render/compose.py）生成；
当前代码在不带风格图时必须与它逐字一致，只允许多出 style / style_hash / style_ref 三个空值字段。
本模块不导入 render，由调用方把 compose 等传进来，这样能对着旧代码跑。
"""
import copy
import dataclasses
import hashlib
import json
from pathlib import Path

NEW_KEYS = ("style", "style_hash")
SAMPLE_EVERY = 37


def _canon(x) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)


def dump(compose, FakeVideo, rewrite_refs, doc: dict, workdir: Path, *, strip_new: bool = True) -> dict:
    """返回 {配置名: {"digest": 全量摘要, "count": 段数, "sample": 抽样的段与请求}}。"""
    rich = copy.deepcopy(doc)
    for kind in ("characters", "props"):
        for card in rich["assets"][kind]:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
    for card in rich["assets"]["locations"]:
        for a in card.get("angles") or []:
            a["uri"] = f"https://img/{card['id']}-{a['angle']}.png"
    shots = [s for ep in doc["episodes"] for s in ep["shots"]]
    kf = {}
    for s in shots[::3]:
        p = Path(workdir) / f"{s['id']}.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + s["id"].encode())
        kf[s["id"]] = str(p)
    fake = FakeVideo()
    capsets = {"fake": fake.caps("fake-1"), "fw": FakeVideo(frame_with_refs=True).caps("fake-1"),
               "m2": FakeVideo(max_refs=2).caps("fake-1"), "m4": FakeVideo(max_refs=4).caps("fake-1")}
    rewrites = {"fake": fake.rewrite_prompt, "sd": rewrite_refs}
    sess = {"provider": "fake", "model": "fake-1", "resolution": "720p", "audio_mode": "tts_all"}
    out = {}
    for cn, caps in capsets.items():
        for dn, dd in (("doc", doc), ("rich", rich)):
            for kn, k in (("nokf", {}), ("kf", kf)):
                for rn, rw in rewrites.items():
                    cl = compose.build_clips(dd, caps, provider="fake", model="fake-1", resolution="720p",
                                             audio_mode="tts_all", keyframes=k, rewrite=rw)
                    rows = [{kk: v for kk, v in c.items()
                             if not kk.startswith("_") and not (strip_new and kk in NEW_KEYS)} for c in cl]
                    items = []
                    for r in rows:
                        rq, used = compose.request_for(dd, sess, r, keyframes=k, relay_frame=None,
                                                       caps=caps, rewrite=rw)
                        dct = dataclasses.asdict(rq)
                        if strip_new:
                            dct.pop("style_ref", None)
                            dct.pop("images", None)   # 只用于计费的新字段，不属于旧请求
                        items.append({"clip": r, "req": dct, "used": used})
                    text = _canon(items).replace(str(workdir), "KF")
                    items = json.loads(text)
                    out[f"{cn}/{dn}/{kn}/{rn}"] = {
                        "digest": hashlib.sha256(text.encode()).hexdigest(),
                        "count": len(items), "sample": items[::SAMPLE_EVERY]}
    return out
