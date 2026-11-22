"""出片配音（设计文档 3.1）：分镜 → 语音条 → 音色 → TTS（带缓存）。

语音条按镜头顺序拆，镜头内旁白与台词的先后按 narration.order（缺省旁白在前），与前端 timeline.ts 的
speechOf 同一算法。送 TTS 的文字即分镜原文，不改写。缓存键 = (文字, 音色, 情绪, 厂商, 语速)：没变的
语音条不重合成、不重复计费；缓存在会话目录的 audio/cache/ 下（WAV）。
音色：用户在「出片」页选的（session.json 的 voices）优先，其次按分镜里的抽象提示（male_elder…）取该厂商
第一个同性别音色；都没有的说话人列进「缺音色」，合成前拦截。
"""
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from render.providers.base import ProviderError, TransientError
from server.messages import UserError, compact, msg, public_cause, render_zh
from render.providers.tts_base import BilledError, concat_wavs, default_voice, tts_cost, wav_seconds

log = logging.getLogger("render.voice")

NARRATION = "narration"
# 各声音模式下哪些语音条走 TTS（设计文档 3.4）；其余由视频模型自己出声或不出声，只进字幕
TTS_KINDS = {
    "tts_all": {"narration", "dialogue", "inner_monologue", "voiceover"},
    "dialogue_native": {"narration", "inner_monologue", "voiceover"},
    "all_native": set(),
    "silent": set(),
}
CACHE_DIR = "audio/cache"
_SPLIT = re.compile(r"(?<=[。！？!?；;…，,、])")


class VoiceError(UserError, Exception):
    """配音没法进行：message 给用户看。"""


def speech_lines(doc: dict) -> list:
    """全部语音条：{"id", "episode", "shot", "kind", "speaker", "text", "emotion"}。"""
    out = []
    for ep in doc.get("episodes") or []:
        for shot in ep.get("shots") or []:
            narr = shot.get("narration") or {}
            mine = []
            if narr.get("text"):
                mine.append({"kind": "narration", "speaker": NARRATION, "text": narr["text"], "emotion": None})
            talk = [{"kind": d.get("type") or "dialogue", "speaker": d.get("character_ref") or "",
                     "text": d["text"], "emotion": d.get("emotion")}
                    for d in shot.get("dialogue") or [] if d.get("text")]
            mine = talk + mine if narr.get("order") == "after_dialogue" else mine + talk
            for i, line in enumerate(mine, 1):
                out.append({"id": f"{shot['id']}-L{i}", "episode": ep["id"], "shot": shot["id"], **line})
    return out


def tts_lines(lines: list, audio_mode: str) -> list:
    kinds = TTS_KINDS.get(audio_mode, set())
    return [x for x in lines if x["kind"] in kinds]


def speakers(doc: dict) -> dict:
    """说话人 → {"name", "hint"}：旁白取 meta.narration.tts_voice，角色取资产卡 voice.tts_voice。"""
    hint = ((doc.get("meta") or {}).get("narration") or {}).get("tts_voice")
    out = {NARRATION: {"name": compact(msg("voice.narrator")), "hint": hint}}
    assets = doc.get("assets") or {}
    for c in (assets.get("characters") or []) + (assets.get("creatures") or []):
        out[c["id"]] = {"name": c.get("name") or c["id"], "hint": (c.get("voice") or {}).get("tts_voice")}
    return out


def resolve_voices(doc: dict, lines: list, assigned: dict, caps) -> tuple:
    """(说话人 → 音色 id, 缺音色的说话人)。只看 lines 里用到的说话人；选了不存在的音色当没选。"""
    ids = {v.id for v in caps.voices}
    info = speakers(doc)
    voices, missing = {}, []
    for key in dict.fromkeys(x["speaker"] for x in lines):
        chosen = (assigned or {}).get(key)
        v = chosen if chosen in ids else default_voice(caps, (info.get(key) or {}).get("hint"))
        if v:
            voices[key] = v
        else:
            missing.append(key)
    return voices, missing


def cache_key(text: str, voice: str, emotion: Optional[str], provider: str, speed: float = 1.0) -> str:
    blob = json.dumps([text, voice, emotion, provider, round(speed, 3)], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def split_text(text: str, max_chars: int) -> list:
    """超长的句子按标点切开（一句里没标点就硬切），每段 ≤ max_chars，拼起来等于原文。"""
    if len(text) <= max_chars:
        return [text]
    parts, cur = [], ""
    for piece in _SPLIT.split(text):
        while len(piece) > max_chars:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(piece[:max_chars])
            piece = piece[max_chars:]
        if len(cur) + len(piece) > max_chars:
            parts.append(cur)
            cur = piece
        else:
            cur += piece
    if cur:
        parts.append(cur)
    return [p for p in parts if p]


def _cache(root) -> Path:
    root = Path(root)
    if not root.is_dir():
        raise VoiceError.of("film.session.dir_gone")
    cache = root / CACHE_DIR
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _emotion(line: dict, caps) -> Optional[str]:
    return line.get("emotion") if caps.emotions else None


def _key(line: dict, voices: dict, provider) -> str:
    return cache_key(line["text"], voices[line["speaker"]], _emotion(line, provider.caps), provider.name)


def estimate(lines: list, voices: dict, provider, root) -> dict:
    """还没缓存的语音条字数与费用（合成前给用户确认）。"""
    cache = Path(root) / CACHE_DIR
    todo = [x for x in lines if not (cache / f"{_key(x, voices, provider)}.wav").exists()]
    chars = sum(len(x["text"]) for x in todo)
    return {"lines": len(lines), "chars": chars, "cny": tts_cost(chars, provider.caps)}


def _retry(fn, retries: int, sleep):
    for i in range(retries + 1):
        try:
            return fn()
        except TransientError:
            if i == retries:
                raise
            sleep(min(2 ** i, 8))


def synthesize(lines: list, voices: dict, provider, root, *, retries: int = 3, sleep=time.sleep,
               on_cost=None) -> tuple:
    """逐条合成（缓存命中直接用），返回 (结果, 失败)。

    结果每条 = 语音条 + file、duration、cost_cny、cached；失败每条 = 语音条 + error（中文兜底）+ error_msg（原因，可嵌进别的消息）。
    瞬时错误重试 retries 次；厂商明确失败与重试用尽都记进失败，不中断其余各条。
    on_cost(cny) 在每次真实合成后调用（计入出片会话的已花金额）；厂商收下后才失败（BilledError）也按其金额调用。
    """
    cache = _cache(root)
    done, failed = [], []
    for line in lines:
        voice = voices[line["speaker"]]
        emotion = _emotion(line, provider.caps)
        key = _key(line, voices, provider)
        final = cache / f"{key}.wav"
        if final.exists():
            done.append({**line, "file": final, "duration": wav_seconds(final), "cost_cny": 0.0, "cached": True})
            continue
        try:
            parts = split_text(line["text"], provider.caps.max_chars)
            files, cost = [], 0.0
            for i, part in enumerate(parts):
                dest = final if len(parts) == 1 else cache / f"{key}.part{i}.wav"
                r = _retry(lambda: provider.synthesize(part, voice, emotion, 1.0, dest), retries, sleep)
                files.append(r.file)
                cost += r.cost_cny
                if on_cost:
                    on_cost(r.cost_cny)
            if len(parts) > 1:
                concat_wavs(files, final)
                for f in files:
                    Path(f).unlink(missing_ok=True)
            done.append({**line, "file": final, "duration": wav_seconds(final),
                         "cost_cny": round(cost, 4), "cached": False})
        except BilledError as e:         # 厂商收下后才失败：可能已计费，照记花费，不重试
            if on_cost:
                on_cost(e.billed_cny)
            log.warning("%s", f"配音失败（已计费） {type(e).__name__}: {e}")  # i18n: internal
            m = public_cause(e)
            failed.append({**line, "error": render_zh(m["code"], m["params"]), "error_msg": m})
        except (ProviderError, TransientError) as e:
            log.warning("%s", f"配音失败 {type(e).__name__}: {e}")  # i18n: internal
            m = public_cause(e)
            failed.append({**line, "error": render_zh(m["code"], m["params"]), "error_msg": m})
    return done, failed
