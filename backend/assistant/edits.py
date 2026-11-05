"""助手的改内容工具（spec §8）：改镜头的拍法、资产卡的文字、主线剧情与章节梗概。

模型给出要改成什么，服务端算出「原 → 新」的对比卡，interrupt 暂停，等用户点「应用」或「放弃」（与操作工具同一套
resume，见 actions.py）。每次调用只中断一次；恢复时重算对比，章节、版本或任何一处与用户看到的卡不同就不应用。
应用后工具结果里带撤销用的数据（只存改动的那几处：被改的镜头、整张资产卡、那段梗概的改前 / 改后），
撤销由接口 POST /assistant/undo 调 undo() 做（不调模型）：那几处现在还等于「改后」才写回，否则 UndoError。
"""
import copy
from typing import Annotated, Callable, Optional, Union

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, ToolException
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from assistant.actions import _op, _version, _where
from assistant.tools import _ctx, _tool
from server import novels
from server.library import KINDS

MAX_EDITS = 20
# 镜头可改的字段（与前端 edit.ts 的可编辑边界一致）；枚举取自 schema/storyboard.schema.json
SHOT_FIELDS = {"action": str, "atmosphere": str, "shot_size": str, "duration_sec": float,
               "camera.movement": str, "camera.angle": str, "transition_out": str, "sfx": list}
ENUMS = {
    "shot_size": ("extreme_wide", "wide", "full", "medium", "medium_close", "close_up", "extreme_close_up", "insert"),
    "camera.movement": ("static", "push_in", "pull_out", "pan", "tilt", "track", "follow", "orbit", "crane",
                        "handheld", "zoom"),
    "camera.angle": ("eye_level", "high", "low", "overhead", "dutch", "pov", "over_shoulder"),
    "transition_out": ("cut", "dissolve", "fade_to_black", "match_cut", "whip_pan"),
}
LOCKED_SHOT = ("narration", "dialogue", "source")
ASSET_ENUMS = {"interior_exterior": ("interior", "exterior", "both")}  # 取自 schema/storyboard.schema.json
LOCKED_ASSET = ("id", "outfits", "states", "angles", "reference_images")
_MISSING = object()


class UndoError(Exception):
    """撤销不了（之后被别处改过、对象不在了）：说明给用户看。"""


class ShotEdit(BaseModel):
    shot_id: str = Field(description="镜头编号，如 E01-SH003，或唯一的后半段 SH003")
    field: str = Field(description="action 画面 / atmosphere 氛围 / shot_size 景别 / duration_sec 时长（秒，0.5–15）"
                                   " / camera.movement 运镜 / camera.angle 机位 / transition_out 转场 / sfx 音效（列表）")
    value: Union[str, float, list[str]] = Field(description="改成的值；文字给完整的新文字")


def _get(obj: dict, path: str):
    cur = obj
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return _MISSING
        cur = cur[k]
    return cur


def _set(obj: dict, path: str, value) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    obj[keys[-1]] = value


def _show(v) -> str:
    """对比卡上显示的文字。"""
    if v is _MISSING or v is None:
        return ""
    if isinstance(v, list):
        return "、".join(str(x) for x in v)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:g}"
    return str(v)


def _as_list(value) -> list:
    if isinstance(value, str):
        return [s.strip() for s in value.replace("，", "、").replace(",", "、").replace("/", "、").split("、") if s.strip()]
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return [x.strip() for x in value if x.strip()]
    raise ToolException("列表字段要给文字列表")


def _coerce(field: str, value):
    """镜头字段的值：白名单、类型、枚举与范围。"""
    if field.split(".")[0] in LOCKED_SHOT:
        raise ToolException(f"不能改 {field}：旁白、台词与溯源是原文，必须逐字保留")
    kind = SHOT_FIELDS.get(field)
    if kind is None:
        raise ToolException(f"不能改 {field}：镜头只能改 {', '.join(SHOT_FIELDS)}")
    if kind is float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ToolException("duration_sec 要给数字（秒）")
        if not 0.5 <= v <= 15:
            raise ToolException("duration_sec 要在 0.5 到 15 秒之间")
        return int(v) if v.is_integer() else v
    if kind is list:
        return _as_list(value)
    if not isinstance(value, str) or not value.strip():
        raise ToolException(f"{field} 要给非空的文字")
    if field in ENUMS and value not in ENUMS[field]:
        raise ToolException(f"{field} 只能是 {', '.join(ENUMS[field])}")
    return value.strip()


def _shots(doc: dict) -> list:
    return [(i, j, s) for i, ep in enumerate(doc.get("episodes") or []) for j, s in enumerate(ep.get("shots") or [])]


def _find_shot(doc: dict, ref: str) -> tuple:
    rows = _shots(doc)
    hit = [r for r in rows if r[2].get("id") == ref] or [r for r in rows if (r[2].get("id") or "").endswith("-" + ref)]
    if len(hit) != 1:
        raise ToolException(f"找不到唯一的镜头「{ref}」")
    return hit[0]


def _edit_card(tool_call_id: str, action: str, chapter_id: Optional[str], chapter: str,
               version_id: Optional[str], diff: list, warnings: list) -> dict:
    return {"tool_call_id": tool_call_id, "action": action, "chapter_id": chapter_id, "chapter": chapter,
            "version_id": version_id, "amount": None, "currency": None, "detail": {"edits": len(diff)},
            "diff": diff, "warnings": warnings}


def _ask_edit(build: Callable[[], tuple]) -> tuple:
    """出对比卡等用户点「应用」→ (是否应用, 用户看到的卡, 这次重算的应用计划)。确认后重算一遍，
    章节、版本与每一处「原 / 新」都与卡相同才应用（实施裁定 8）。"""
    card, plan = build()
    answer = interrupt(card) or {}
    seen = answer.get("card") or card
    if answer.get("decision") != "approve":
        return False, seen, None
    fresh, plan = build()
    if (fresh["chapter_id"], fresh["version_id"], fresh["diff"]) != (seen["chapter_id"], seen["version_id"], seen["diff"]):
        raise ToolException("要改的内容或位置在这之后变了，没有应用；要的话我再出一张新的对比卡")
    return True, seen, plan


def _done(text: str, card: dict, outcome: str, task: Optional[dict] = None, undo: Optional[dict] = None) -> tuple:
    return text, {"card": card, "outcome": outcome, "task": task, "undo": undo}


@_tool(response_format="content_and_artifact")
def shots_edit(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
               edits: list[ShotEdit], chapter: Optional[str] = None):
    """改一章（采用版，没有就取最新可用版）里镜头的拍法：画面、氛围、景别、时长、运镜、机位、转场、音效，一次最多 20 处。旁白与台词是原文，不能改。先给用户一张「原 → 新」的对比卡，用户点「应用」才保存（与界面上保存修改相同，会整份复验）；应用后用户可以撤销。chapter 缺省为当前章。"""
    uid, nid, _ = _ctx(config)
    user = {"id": uid}
    rows = [e if isinstance(e, dict) else e.model_dump() for e in edits or []]
    if not rows:
        raise ToolException("没有要改的地方")
    if len(rows) > MAX_EDITS:
        raise ToolException(f"一次最多改 {MAX_EDITS} 处")

    def build() -> tuple:
        ch = _where(config, chapter)[2]
        vid = _version(ch)
        doc = novels.get_version(uid, nid, ch["id"], vid).get("result") or {}
        new = copy.deepcopy(doc)
        diff, touched = [], []
        for e in rows:
            i, j, s = _find_shot(new, str(e.get("shot_id") or ""))
            value = _coerce(str(e.get("field") or ""), e.get("value"))
            old = _get(s, e["field"])
            if old == value:
                continue
            _set(s, e["field"], value)
            diff.append({"target": s["id"], "field": e["field"], "before": _show(old), "after": _show(value)})
            if (i, j) not in touched:
                touched.append((i, j))
        if not diff:
            raise ToolException("这些地方已经是要改成的样子，不用改")
        chk = _op("version_check", user, nid, ch["id"], vid, new)
        shots = {new["episodes"][i]["shots"][j]["id"]: {"before": doc["episodes"][i]["shots"][j],
                                                         "after": new["episodes"][i]["shots"][j]} for i, j in touched}
        card = _edit_card(tool_call_id, "shots_edit", ch["id"], ch["title"], vid, diff, chk["warnings"])
        return card, {"doc": new, "undo": {"kind": "shots", "chapter_id": ch["id"], "version_id": vid, "shots": shots}}

    ok, card, plan = _ask_edit(build)
    if not ok:
        return _done("用户放弃了，没有改", card, "rejected")
    r = _op("version_save", user, nid, card["chapter_id"], card["version_id"], plan["doc"])
    tail = "，复验没通过，这一版标成了草稿" if r.get("status") == "draft_invalid" else ""
    return _done(f"已应用 {len(card['diff'])} 处修改{tail}；用户可以在卡上撤销", card, "approved",
                 {"kind": "edit", "chapter_id": card["chapter_id"], "version_id": card["version_id"]}, plan["undo"])


def _find_asset(uid: str, nid: str, card_id: str) -> tuple:
    assets = novels.get_memory(uid, nid)["assets"]
    for kind in KINDS:
        for c in assets.get(kind) or []:
            if c.get("id") == card_id:
                return kind, c
    raise ToolException(f"没有编号为 {card_id} 的资产卡")


@_tool(response_format="content_and_artifact")
def asset_edit(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
               card_id: str, fields: dict[str, Union[str, list[str]]]):
    """改一张资产卡（角色、场景、道具、生物）上已有的文字字段。fields 的键是字段名，嵌套字段用点号（如 appearance.face），值是改成的完整内容（别名等列表字段给列表）。编号、服装、状态、角度、参考图不能改。先给用户一张「原 → 新」的对比卡，用户点「应用」才保存；应用后可以撤销。"""
    uid, nid, _ = _ctx(config)
    if not fields:
        raise ToolException("没有要改的字段")

    def build() -> tuple:
        kind, cur = _find_asset(uid, nid, card_id)
        new = copy.deepcopy(cur)
        diff = []
        for path, value in fields.items():
            if path.split(".")[0] in LOCKED_ASSET:
                raise ToolException(f"不能改 {path}：编号、服装、状态、角度、参考图被镜头引用，改了会对不上")
            old = _get(cur, path)
            if old is _MISSING:
                raise ToolException(f"{card_id} 没有 {path} 这个字段")
            if isinstance(old, str):
                if not isinstance(value, str):
                    raise ToolException(f"{path} 要给文字")
                value = value.strip()
                if path in ASSET_ENUMS and value not in ASSET_ENUMS[path]:
                    raise ToolException(f"{path} 只能是 {', '.join(ASSET_ENUMS[path])}")
                if path == "name" and not value:
                    raise ToolException("名称不能为空")
            elif isinstance(old, list) and all(isinstance(x, str) for x in old):
                value = _as_list(value)
            else:
                raise ToolException(f"{path} 不是文字字段，不能改")
            if old == value:
                continue
            _set(new, path, value)
            diff.append({"target": f"{card_id} {cur.get('name', '')}", "field": path,
                         "before": _show(old), "after": _show(value)})
        if not diff:
            raise ToolException("这些字段已经是要改成的样子，不用改")
        card = _edit_card(tool_call_id, "asset_edit", None, "", None, diff, [])
        return card, {"kind": kind, "undo": {"kind": "asset", "asset_kind": kind, "card_id": card_id,
                                             "before": cur, "after": new}}

    ok, card, plan = _ask_edit(build)
    if not ok:
        return _done("用户放弃了，没有改", card, "rejected")
    try:
        novels.upsert_asset(uid, nid, plan["kind"], plan["undo"]["after"])
    except novels.NovelError as e:
        raise ToolException(str(e))
    return _done(f"已改好 {card_id}；用户可以在卡上撤销", card, "approved",
                 {"kind": "edit", "chapter_id": None, "version_id": None}, plan["undo"])


@_tool(response_format="content_and_artifact")
def plot_edit(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
              outline: Optional[str] = None, chapter: Optional[str] = None, synopsis: Optional[str] = None):
    """改主线剧情：outline 是全书梗概，synopsis 是某一章的梗概（chapter 指明哪一章，缺省为当前章），都给改后的全文。先给用户一张「原 → 新」的对比卡，用户点「应用」才保存；应用后可以撤销。"""
    uid, nid, _ = _ctx(config)
    if outline is None and synopsis is None:
        raise ToolException("要给 outline 或 synopsis")

    def build() -> tuple:
        plot = novels.get_memory(uid, nid)["plot"]
        diff, undo = [], {"kind": "plot", "outline": None, "synopsis": None}
        cid, title = None, ""
        if outline is not None:
            old, new = plot.get("outline") or "", outline.strip()
            if old != new:
                diff.append({"target": "全书梗概", "field": "outline", "before": old, "after": new})
                undo["outline"] = {"before": old, "after": new}
        if synopsis is not None:
            ch = _where(config, chapter)[2]
            cid, title = ch["id"], ch["title"]
            old = next((s.get("synopsis") or "" for s in plot.get("chapters") or [] if s.get("chapter_id") == cid), "")
            new = synopsis.strip()
            if len(new) > novels.SYNOPSIS_MAX:
                raise ToolException(f"章节梗概不超过 {novels.SYNOPSIS_MAX} 字（现在 {len(new)} 字）")
            if old != new:
                diff.append({"target": f"{title} 梗概", "field": "synopsis", "before": old, "after": new})
                undo["synopsis"] = {"chapter_id": cid, "before": old, "after": new}
        if not diff:
            raise ToolException("剧情已经是要改成的样子，不用改")
        return _edit_card(tool_call_id, "plot_edit", cid, title, None, diff, []), {"undo": undo}

    ok, card, plan = _ask_edit(build)
    if not ok:
        return _done("用户放弃了，没有改", card, "rejected")
    u = plan["undo"]
    try:
        if u["synopsis"]:  # 先写可能失败的这一段，失败时什么都没改
            novels.set_synopsis(uid, nid, u["synopsis"]["chapter_id"], u["synopsis"]["after"])
        if u["outline"]:
            novels.set_outline(uid, nid, u["outline"]["after"])
    except novels.NovelError as e:
        raise ToolException(str(e))
    return _done("已改好剧情；用户可以在卡上撤销", card, "approved",
                 {"kind": "edit", "chapter_id": card["chapter_id"], "version_id": None}, u)


def undo(user_id: str, nid: str, data: dict) -> str:
    """把一次应用的改动写回去；那几处在这之后被别处改过（不再等于「改后」）就拒绝。返回给用户看的一句话。"""
    kind = data.get("kind")
    if kind == "shots":
        cid, vid = data["chapter_id"], data["version_id"]
        try:
            doc = copy.deepcopy(novels.get_version(user_id, nid, cid, vid).get("result") or {})
        except novels.NotFound:
            raise UndoError("这个版本已经不在了，不能撤销")
        for sid, pair in data["shots"].items():
            hit = [r for r in _shots(doc) if r[2].get("id") == sid]
            if len(hit) != 1 or hit[0][2] != pair["after"]:
                raise UndoError(f"镜头 {sid} 在这之后又被改过，不能撤销")
            i, j, _s = hit[0]
            doc["episodes"][i]["shots"][j] = copy.deepcopy(pair["before"])
        try:
            _op("version_save", {"id": user_id}, nid, cid, vid, doc)
        except ToolException as e:
            raise UndoError(str(e))
        return f"已撤销 {len(data['shots'])} 个镜头的修改"
    if kind == "asset":
        cards = novels.get_memory(user_id, nid)["assets"].get(data["asset_kind"]) or []
        cur = next((c for c in cards if c.get("id") == data["card_id"]), None)
        if cur != data["after"]:
            raise UndoError(f"资产卡 {data['card_id']} 在这之后又被改过，不能撤销")
        novels.upsert_asset(user_id, nid, data["asset_kind"], copy.deepcopy(data["before"]))
        return f"已撤销 {data['card_id']} 的修改"
    if kind == "plot":
        plot = novels.get_memory(user_id, nid)["plot"]
        o, s = data.get("outline"), data.get("synopsis")
        if o and (plot.get("outline") or "") != o["after"]:
            raise UndoError("全书梗概在这之后又被改过，不能撤销")
        if s:
            cur = next((x.get("synopsis") or "" for x in plot.get("chapters") or []
                        if x.get("chapter_id") == s["chapter_id"]), "")
            if cur != s["after"]:
                raise UndoError("这一章的梗概在这之后又被改过，不能撤销")
        if o:
            novels.set_outline(user_id, nid, o["before"])
        if s:
            novels.set_synopsis(user_id, nid, s["chapter_id"], s["before"])
        return "已撤销剧情的修改"
    raise UndoError("这条修改不能撤销")


TOOLS = [shots_edit, asset_edit, plot_edit]
EDITS = tuple(t.name for t in TOOLS)
