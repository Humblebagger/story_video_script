"""自由节点：剧本之外补拍或重做一段（设计文档 docs/specs/2026-11-11-film-node-graph-design.md 第 1、2 节）。

节点存在出片会话的 free 列表里，与剧本段共用状态机、上限与出片线程（迁移函数见 session.py）。这里是接口侧的
新建、派生、修改、删除、排队与采用；校验要用分镜、关键帧与风格图，由调用方装进 Ctx 传入。
"""
import re
from pathlib import Path
from typing import NamedTuple, Optional

from render import compose, session as sess
from render.plan import assets_index
from render.providers import base
from server.messages import money

PROMPT_MAX = 2000
FIELDS = ("prompt", "refs", "first_frame", "duration", "target")
# 派生时从段的提示词里去掉的参考行；残余占位交给 compose.strip_placeholders
_REF_LINE = re.compile(r"^【(首帧|参考)】")


class Ctx(NamedTuple):
    doc: dict
    keyframes: dict         # 镜头 id → 关键帧图路径
    has_style: bool         # 本小说当前有风格图


def _free(s: dict, fid: str) -> dict:
    for n in s.get("free") or []:
        if n["id"] == fid:
            return n
    raise sess.NotFound.of("film.free.not_found", id=fid)


def _caps(s: dict):
    return sess._provider(s["provider"]).caps(s["model"])


def derive_prompt(text: str) -> str:
    """段的提示词 → 自由节点的正文：去掉【首帧】/【参考】行与残余占位（参考行在生成时按 refs 重新拼）。"""
    lines = [ln for ln in (text or "").splitlines() if not _REF_LINE.match(ln.strip())]
    return compose.strip_placeholders("\n".join(lines)).strip()[:PROMPT_MAX]


def tail_source(root, s: dict, source_id: str) -> Optional[Path]:
    """首帧 tail:<id> 的来源：那一段或那个自由节点采用的那次的尾帧文件；没有返回 None。"""
    it = next((x for x in sess.items(s) if x["id"] == source_id), None)
    if it is None or it.get("chosen") is None:
        return None
    rel = it["attempts"][it["chosen"]].get("last_frame")
    p = Path(root) / rel if rel else None
    return p if p is not None and p.is_file() else None


def tail_frame(root, s: dict, node: dict) -> Optional[Path]:
    """节点首帧为 tail:<id> 时的尾帧文件（出片线程组装请求用）。"""
    ff = node.get("first_frame") or ""
    return tail_source(root, s, ff[len("tail:"):]) if ff.startswith("tail:") else None


def validate(root, s: dict, node: dict, ctx: Ctx, caps, fields=FIELDS, *, run: bool = False) -> None:
    """只查 fields 涉及的项（改正文不必因为关键帧被删而失败）；生成前 run=True 全量查。"""
    fields = set(fields)
    refs = node["refs"]
    if "refs" in fields:
        if len(set(refs)) != len(refs):
            raise sess.SessionError.of("film.free.dup_ref")
        idx = assets_index(ctx.doc)
        for aid in refs:
            if aid == compose.STYLE_ID:
                if not ctx.has_style:
                    raise sess.SessionError.of("film.free.no_style")
                continue
            slot = compose.asset_slot(idx, aid)
            if slot is None:
                raise sess.SessionError.of("film.free.unknown_asset", id=aid)
            if not compose.image_for(slot, idx):
                raise sess.SessionError.of("film.free.no_ref_image", name=slot["name"], id=aid)
    if fields & {"refs", "first_frame"}:
        need = compose.free_slots_needed(refs, node.get("first_frame"), caps)
        if need > caps.max_refs:
            raise sess.SessionError.of("film.free.over_refs", need=need, max=caps.max_refs)
    ff = node.get("first_frame")
    if "first_frame" in fields and ff:
        if not caps.first_frame:
            raise sess.SessionError.of("film.free.no_first_frame")
        if ff.startswith("keyframe:"):
            if ff[len("keyframe:"):] not in ctx.keyframes:
                raise sess.SessionError.of("film.free.no_keyframe", shot=ff[len("keyframe:"):])
        elif ff.startswith("tail:"):
            src = ff[len("tail:"):]
            if src == node["id"]:
                raise sess.SessionError.of("film.free.self_tail")
            if tail_source(root, s, src) is None:
                raise sess.SessionError.of("film.free.no_tail", id=src)
        else:
            raise sess.SessionError.of("film.free.bad_first_frame", src=ff)
    if "duration" in fields and not node.get("target"):
        if not (1 <= node["duration"] <= caps.max_clip_sec):
            raise sess.SessionError.of("film.free.bad_duration", max=f"{caps.max_clip_sec:g}")
    if "prompt" in fields:
        if len(node["prompt"]) > PROMPT_MAX:
            raise sess.SessionError.of("film.free.prompt_too_long", max=PROMPT_MAX)
        if run and not node["prompt"].strip():
            raise sess.SessionError.of("film.free.empty_prompt")


def create(root, ctx: Ctx, from_clip: Optional[str] = None) -> dict:
    """新建自由节点；from_clip 时从这一段派生：预填正文、参考、时长，挂靠这一段，接力首帧换成那一段的尾帧。"""
    with sess.mutate(root) as s:
        caps = _caps(s)
        seq = int(s.get("free_seq") or 0) + 1
        node = {"id": f"{sess.FREE_PREFIX}{seq:02d}", "target": None, "target_shots": None,
                "target_lost": False, "prompt": "", "refs": [], "first_frame": None,
                "duration": float(min(5, caps.max_clip_sec)), "state": "planned", "error": None, "error_msg": None,
                "uncertain": False, "attempts": [], "chosen": None, "created_at": sess._now()}
        if from_clip is not None:
            c = sess._clip(s, from_clip)
            ff = c.get("first_frame")
            if ff and ff.startswith("relay:"):
                ff = "tail:" + ff[len("relay:"):]
            node.update(target=c["id"], target_shots=list(c["shots"]), prompt=derive_prompt(c["prompt"]),
                        refs=list(c["refs"]), duration=c["duration"], first_frame=ff)
            try:
                validate(root, s, node, ctx, caps, ("first_frame",))
            except sess.SessionError:
                node["first_frame"] = None      # 首帧来源此刻不可用（上一段还没出、关键帧删了）：先不带
        node["estimate_cny"] = base.estimate_cny(node["duration"], caps, s["resolution"], compose.image_count(node))
        s["free_seq"] = seq
        s["free"] = list(s.get("free") or []) + [node]
        return s


def update(root, ctx: Ctx, fid: str, patch: dict) -> dict:
    """改正文、参考、首帧、时长、挂靠（传了哪些改哪些，只校验这些）。挂靠某段时时长跟随那一段。"""
    unknown = set(patch) - set(FIELDS)
    if unknown:
        raise sess.SessionError.of("film.free.bad_fields", keys=sorted(unknown))
    with sess.mutate(root) as s:
        n = _free(s, fid)
        if n["state"] in sess.IN_FLIGHT:
            raise sess.Conflict.of("film.free.busy_edit")
        caps = _caps(s)
        if "target" in patch:
            if patch["target"] is None:
                n.update(target=None, target_shots=None)
            else:
                c = sess._clip(s, patch["target"])
                n.update(target=c["id"], target_shots=list(c["shots"]), duration=c["duration"], target_lost=False)
        if "duration" in patch:
            if n.get("target"):
                raise sess.SessionError.of("film.free.target_duration")
            try:
                dur = round(float(patch["duration"]), 1)
            except (TypeError, ValueError):
                raise sess.SessionError.of("film.free.bad_duration", max=f"{caps.max_clip_sec:g}")
            n["duration"] = dur
        if "prompt" in patch:
            n["prompt"] = str(patch["prompt"] or "")
        if "refs" in patch:
            n["refs"] = [str(x) for x in (patch["refs"] or [])]
        if "first_frame" in patch:
            n["first_frame"] = patch["first_frame"] or None
        validate(root, s, n, ctx, caps, set(patch) | ({"duration"} if "target" in patch else set()))
        n["estimate_cny"] = base.estimate_cny(n["duration"], caps, s["resolution"], compose.image_count(n))
        return s


def delete(root, fid: str) -> dict:
    """删节点与只属于它的文件；已复制进剧本段（含 orphaned）的尝试共用的文件保留。"""
    with sess.mutate(root) as s:
        n = _free(s, fid)
        if n["state"] in sess.IN_FLIGHT:
            raise sess.Conflict.of("film.free.busy_delete")
        if any(a.get("state") == sess.ABANDONED for a in n["attempts"]):
            raise sess.Conflict.of("film.free.pending_delete")      # 那次可能还会计费：删了节点就没处记
        users = [x["id"] for x in s.get("free") or [] if x.get("first_frame") == f"tail:{fid}"]
        if users:
            raise sess.Conflict.of("film.free.tail_in_use", id=users[0])
        shared = {a.get(k) for c in list(s["clips"]) + list(s.get("orphaned") or [])
                  for a in c.get("attempts") or [] if a.get("free_id") == fid for k in ("file", "last_frame")}
        doomed = [a[k] for a in n["attempts"] for k in ("file", "last_frame") if a.get(k) and a[k] not in shared]
        s["free"] = [x for x in s["free"] if x["id"] != fid]
    for rel in doomed:                      # 记录先改，文件后删：写回失败时不会留下指向已删文件的记录
        (Path(root) / rel).unlink(missing_ok=True)
    return s


def queue(root, ctx: Ctx, fid: str, expected_cny: Optional[float] = None) -> dict:
    """排队生成一次：全量校验；超过确认线要带金额，与服务端不一致 → Conflict（附金额）；过单章上限。"""
    with sess.mutate(root) as s:
        if (s.get("final") or {}).get("state") in sess.COMPOSE_BUSY:
            raise sess.Conflict.of("film.free.composing")
        n = _free(s, fid)
        if n["state"] in sess.IN_FLIGHT:
            raise sess.Conflict.of("film.run.busy", id=fid)
        validate(root, s, n, ctx, _caps(s), run=True)
        total = n["estimate_cny"]
        if total > s["confirm_over_cny"] and expected_cny is None:
            raise sess.Conflict.of("film.free.confirm", total, amount=money(total))
        if expected_cny is not None and abs(expected_cny - total) > 0.005:
            raise sess.Conflict.of("film.run.changed", total, amount=money(total))
        reserved = sum(c["estimate_cny"] for c in sess.items(s) if c["state"] in sess.IN_FLIGHT) + sess.abandoned_cny(s)
        if s["spent_cny"] + reserved + total > s["budget_cny"] + 1e-9:
            raise sess.BudgetExceeded.of("film.budget.exceeded", budget=f"{s['budget_cny']:g}",
                                         spent=money(s["spent_cny"]), reserved=money(reserved),
                                         total=money(total))
        n.update(state="queued", queued_at=sess._now(), uncertain=False)
        sess.set_error(n, None)
        return s


def set_chosen(root, fid: str, index: int) -> dict:
    with sess.mutate(root) as s:
        n = _free(s, fid)
        if n["state"] in sess.IN_FLIGHT:
            raise sess.Conflict.of("film.free.busy_choose")
        if not (0 <= index < len(n["attempts"])) or n["attempts"][index].get("state") != "succeeded":
            raise sess.SessionError.of("film.choose.not_success")
        n["chosen"] = index
        n["state"] = "done"
        sess.set_error(n, None)      # 重试失败后采用先前成功的那次：回到完成（uncertain 不动）
        return s
