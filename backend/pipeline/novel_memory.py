"""小说长期记忆进入转换：人物状态 / 主线剧情 / 创作限制。

只放纯函数（不碰存储）：把长期记忆拼成用户消息里的三个块、把限制的负面提示词
确定性并进产物、对产物做两项软核查（关键词、已故角色再出场），以及「章后整理」
小调用（本章人物生命周期提议 + 剧情摘要，证据由程序核验）。

设计见 docs/specs/2026-10-12-novel-sessions-and-timeline-canvas-design.md §3–§5。
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from .chat import extract_json
from server.messages import ref
from render.providers.base import scrub_secrets
from .verification import Finding

LIFECYCLE_TYPES = ("deceased", "permanent_condition", "departed")
PLOT_CAP = 2000          # 【主线剧情】注入总长上限
PLOT_FULL_RECENT = 3     # 超长时最近几章保留完整摘要
SYNOPSIS_MAX = 200
# 已故/已下线角色出场时，镜头里带这些字样就当作闪回，不报
_FLASHBACK_MARKS = ("回忆", "梦", "幻觉", "想象", "闪回", "遗像", "画像", "照片", "讲述")


@dataclass
class NovelContext:
    """转换某章时从小说长期记忆取出的、此前章节已确定的事。

    lifecycle: 已确认的生命周期记录（只含排在本章之前的章节，或人工添加的）
    names: 角色 ID → 名称，拼块时用
    outline: 全书梗概（用户写）
    synopses: [(章节标题, 摘要)]，按章节顺序
    constraints: 启用中的创作限制
    """
    lifecycle: List[dict] = field(default_factory=list)
    names: dict = field(default_factory=dict)
    outline: str = ""
    synopses: List[Tuple[str, str]] = field(default_factory=list)
    constraints: List[dict] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.lifecycle or self.outline.strip() or self.synopses
                    or self.constraints)


# ---------- 注入块 ----------

def _lifecycle_line(entry: dict, names: dict) -> str:
    cid = entry.get("character_id", "")
    who = f"{cid} {names.get(cid, '')}".strip()
    where = entry.get("since") or {}
    at = "".join(x for x in (where.get("chapter_title", ""),
                             f"（{where['unit_ref']}）" if where.get("unit_ref") else ""))
    at = f"自{at}起" if at else "此前"
    detail = (entry.get("detail") or "").strip()
    kind = entry.get("type")
    if kind == "deceased":
        return (f"- {who}：{at}已死亡{('（' + detail + '）') if detail else ''}。"
                "现实时间线的镜头不得让该角色出场；回忆、梦境、他人讲述的画面可以，"
                "须在 action 里写明是回忆或梦境。")
    if kind == "departed":
        return (f"- {who}：{at}已永久离开故事{('（' + detail + '）') if detail else ''}。"
                "现实时间线的镜头不得让该角色出场；回忆、他人讲述的画面可以，须在 action 里写明。")
    return (f"- {who}：{at}永久状态变化——{detail or '见原文'}。"
            "此后外貌与动作须体现这一点（资产卡外貌描述同步保持）。")


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?[。！？!?])", text.strip(), re.S)
    return m.group(1) if m else text.strip()


def plot_text(outline: str, synopses: List[Tuple[str, str]],
              cap: int = PLOT_CAP) -> str:
    """全书梗概 + 此前各章摘要。超过 cap 时更早的章节只留首句，梗概始终完整。"""
    def render(items):
        parts = []
        if outline.strip():
            parts.append(f"全书梗概：{outline.strip()}")
        parts += [f"{title}：{text}" for title, text in items if text.strip()]
        return "\n".join(parts)

    full = render(synopses)
    if len(full) <= cap:
        return full
    keep = len(synopses) - PLOT_FULL_RECENT
    return render([(t, _first_sentence(s) if i < keep else s)
                   for i, (t, s) in enumerate(synopses)])


def memory_blocks(ctx: Optional[NovelContext]) -> str:
    """用户消息里追加的长期记忆块；什么都没有时返回空串（消息与以前逐字一致）。"""
    if ctx is None or ctx.empty():
        return ""
    blocks = []
    if ctx.lifecycle:
        lines = [_lifecycle_line(e, ctx.names) for e in ctx.lifecycle]
        blocks.append("【人物状态】\n以下是本书此前章节已确定、不可逆的人物状态，"
                      "本章转换须与之一致：\n" + "\n".join(lines))
    plot = plot_text(ctx.outline, ctx.synopses)
    if plot:
        blocks.append(
            "【主线剧情】\n以下主线剧情只用于理解人物关系、称谓与来龙去脉。"
            "本章的每个镜头仍必须依据本章原文句子，不得把主线剧情里有、本章原文里没有的"
            "情节画进镜头，也不得据此补写台词与旁白。\n" + plot)
    if ctx.constraints:
        lines = [f"- {c['text'].strip()}" for c in ctx.constraints if c.get("text", "").strip()]
        if lines:
            blocks.append(
                "【创作限制】\n以下是本书的创作限制，约束的是画面怎么呈现。"
                "原文溯源优先于限制：原文写到的句子仍须由镜头或旁白承载（覆盖率不变），"
                "只是画面改用侧面、遮挡、空镜，或交给旁白，不得为守限制而跳过句子。\n"
                + "\n".join(lines))
    return "\n\n".join(blocks)


# ---------- 确定性落地：负面提示词 ----------

_NEG_SPLIT = re.compile(r"[,，、;；\n]+")


def negative_terms(ctx: Optional[NovelContext]) -> List[str]:
    terms: List[str] = []
    for c in (ctx.constraints if ctx else []):
        for t in _NEG_SPLIT.split(c.get("negative_prompt") or ""):
            if t.strip() and t.strip() not in terms:
                terms.append(t.strip())
    return terms


def merge_negative_prompt(doc: dict, terms: List[str]) -> int:
    """把限制的负面提示词并进 meta.style.negative_prompt（去重，保留模型自己写的）。
    返回新增的词数。"""
    if not terms:
        return 0
    style = doc.setdefault("meta", {}).setdefault("style", {})
    existing = [t.strip() for t in _NEG_SPLIT.split(style.get("negative_prompt") or "")
                if t.strip()]
    added = [t for t in terms if t not in existing]
    if added:
        style["negative_prompt"] = "，".join(existing + added)
    return len(added)


# ---------- 软核查（MEDIUM，不打回） ----------

def _presentation_fields(shot: dict):
    """呈现层字段：转换器写的画面描述。台词/旁白/原文句子是原文逐字，不扫。"""
    for key in ("action", "atmosphere"):
        if isinstance(shot.get(key), str):
            yield key, shot[key]
    for i, c in enumerate(shot.get("characters") or []):
        if isinstance(c.get("action"), str):
            yield f"characters/{i}/action", c["action"]
    prompts = shot.get("prompts")
    if isinstance(prompts, dict):
        for k, v in prompts.items():
            if isinstance(v, str):
                yield f"prompts/{k}", v
    elif isinstance(prompts, str):
        yield "prompts", prompts


def _shots(doc: dict):
    for ei, ep in enumerate(doc.get("episodes") or []):
        for si, shot in enumerate(ep.get("shots") or []):
            yield f"/episodes/{ei}/shots/{si}", shot


def soft_findings(doc: dict, ctx: Optional[NovelContext]) -> List[Finding]:
    if ctx is None:
        return []
    found: List[Finding] = []
    rules = [(c, [k for k in c.get("keywords") or [] if k.strip()])
             for c in ctx.constraints]
    gone = {e["character_id"]: e for e in ctx.lifecycle
            if e.get("type") in ("deceased", "departed")}
    for path, shot in _shots(doc):
        sid = shot.get("id", path)
        refs = (shot.get("source") or {}).get("unit_refs") or []
        fields = list(_presentation_fields(shot))
        for c, keywords in rules:
            for key, text in fields:
                hit = [k for k in keywords if k in text]
                if hit:
                    found.append(Finding(
                        "NOVEL-CONSTRAINT-001", "medium", f"{path}/{key}",
                        params={"shot": sid, "keywords": hit, "constraint": c.get("text", "")},
                        unit_refs=list(refs)))
        if not gone:
            continue
        marked = any(m in text for _, text in fields for m in _FLASHBACK_MARKS)
        for c in shot.get("characters") or []:
            entry = gone.get(c.get("ref"))
            if entry and not marked:
                state = ref("verify.lifecycle.deceased" if entry["type"] == "deceased"
                            else "verify.lifecycle.departed")
                found.append(Finding(
                    "NOVEL-LIFECYCLE-001", "medium", f"{path}/characters",
                    params={"shot": sid, "state": state,
                            "character": f"{c.get('ref')}{ctx.names.get(c.get('ref'), '')}"},
                    unit_refs=list(refs)))
    return found


# ---------- 章后整理：生命周期提议 + 本章摘要 ----------

DIGEST_SYSTEM = """你是小说编辑。用户给你一章小说的句子单元（每句有 ID）和本书角色名单。请完成两件事：

1. 列出本章发生的**不可逆**人物状态变化，只限三类：
   - deceased：死亡
   - permanent_condition：永久伤病或残疾（写明具体情况，如「左腿残疾，此后拄拐」）
   - departed：永久离开故事（远走他乡且不再回来、出家等）
   暂时性的（受伤后会好、短暂离开）不算。只记名单里的角色。每条必须给出发生处的句子 ID（unit_ref）
   和从该句逐字摘录的证据（evidence_quote，必须是该句原文的连续片段，不得改字）。
   没有就给空数组，不要猜。
2. 写本章剧情摘要：不超过 200 字，写人物、事件、因果，不写画面与镜头。

只输出一个 JSON 对象，不要解释文字：
{"lifecycle": [{"character_id": "C03", "type": "deceased", "detail": "病死", "unit_ref": "u0121", "evidence_quote": "……"}],
 "synopsis": "……"}"""


def digest_message(units: List[dict], characters: List[dict]) -> str:
    roster = "\n".join(f"{c.get('id')} {c.get('name', '')}" for c in characters) or "无"
    lines = "\n".join(f"{u['id']} {u.get('text', '')}" for u in units)
    return f"【角色名单】\n{roster}\n\n【本章句子单元】\n{lines}"


def check_digest(raw: dict, units: List[dict], characters: List[dict]
                 ) -> Tuple[List[dict], str, List[str]]:
    """核验章后整理的输出。返回 (通过核验的生命周期提议, 摘要, 丢弃原因)。

    evidence_quote 必须是所引句单元原文的子串、character_id 必须在名单里——
    模型编不出不存在的死亡。摘要是概括不是证据，不核验，只截长。
    """
    by_id = {u["id"]: u.get("text", "") for u in units}
    known = {c.get("id") for c in characters}
    kept, dropped = [], []
    for item in raw.get("lifecycle") or []:
        if not isinstance(item, dict):
            dropped.append(f"不是对象：{item!r}")
            continue
        cid, kind = item.get("character_id"), item.get("type")
        ref, quote = item.get("unit_ref"), (item.get("evidence_quote") or "").strip()
        if cid not in known:
            dropped.append(f"{cid}：不在角色名单里")
        elif kind not in LIFECYCLE_TYPES:
            dropped.append(f"{cid}：未知的状态类型 {kind}")
        elif ref not in by_id:
            dropped.append(f"{cid}：引用的句子 {ref} 不在本章")
        elif not quote or quote not in by_id[ref]:
            dropped.append(f"{cid}：证据「{scrub_secrets(quote)[:30]}」不是 {ref} 原文的逐字片段")
        else:
            kept.append({"character_id": cid, "type": kind,
                         "detail": str(item.get("detail") or "").strip(),
                         "unit_ref": ref, "evidence_quote": quote})
    synopsis = str(raw.get("synopsis") or "").strip()[:SYNOPSIS_MAX]
    return kept, synopsis, dropped


def run_digest(chat, units: List[dict], characters: List[dict]
               ) -> Tuple[List[dict], str, List[str]]:
    """一次小调用。chat 是 chat.ChatInvoker；输出不可解析时抛 ValueError。"""
    raw = chat.text(chat.invoke([SystemMessage(DIGEST_SYSTEM),
                                 HumanMessage(digest_message(units, characters))],
                                max_tokens=2000))
    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        raise ValueError("章后整理输出不是 JSON 对象")
    return check_digest(parsed, units, characters)
