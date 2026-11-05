# Agent 助手 子计划 3：改内容、对比与撤销 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 助手能按用户的要求改三类内容：镜头的拍法、资产卡的文字、主线剧情与章节梗概。
- 改之前先在对话里出一张「原 → 新」的对比卡，用户点「应用」才保存。
- 应用后可以「撤销」。

**Architecture:**
- **后端**：
  - `server/app.py` 把「人工编辑后整份复验并保存」抽成 `_check_version_doc` / `_save_version_doc`，接口 `PUT …/versions/{vid}` 和助手共用。
  - 新文件 `backend/assistant/edits.py`：三个改内容工具与 `undo()`。复用子计划 2 的中断、恢复、核对做法：每次调用只中断一次，恢复时重算对比，对不上就不应用。
  - `store.py` 记录哪些修改已撤销（`<小说目录>/assistant.sqlite.undone.json`）。
  - 新接口 `POST /assistant/undo`；历史里撤销过的卡标 `undone`。
- **前端**：
  - 确认卡支持对比行、复验警告、「应用 / 放弃」「撤销」；
  - 会话存储加 `undoAssistantCard`；
  - App 收到 `edit` 通知后重读小说，并在没有未保存修改时重读正在看的版本。

**Tech Stack:** FastAPI（Python 3.12）、LangGraph 1.2.14、langchain-core 1.6；React 19、TS、Tailwind v4、shadcn。

**Spec:** `docs/specs/2026-11-01-assistant-panel-design.md` 第 8 节（8.1–8.3 是本计划要实现的细节）；中断与恢复的做法见第 7 节。

---

## 全局约束

- **提交**：
  - 只 `git add` 具体文件，不用 `git add -A` / `git commit -a`。
  - 提交信息用中文、写成描述式，**不带任何 Claude 署名**（不要 `Co-Authored-By`、不要 `Claude-Session`）。
- **后端检查**：在 `backend/` 下执行。venv 里没有 pytest，测试脚本直接用 `.venv/bin/python` 跑。每个任务结束时，下面的脚本都要打印 `ALL PASS`：
  - `tests/server/test_novels.py`、`tests/server/test_summary.py`、`tests/server/test_usage.py`、`tests/server/test_render.py`、`tests/server/test_compose.py`、`tests/server/test_assistant_ops.py`、`tests/server/test_assistant.py`
  - `tests/assistant/test_store.py`、`tests/assistant/test_tools.py`、`tests/assistant/test_graph.py`、`tests/assistant/test_actions.py`
  - 本计划新建的、到当前任务为止已存在的：`tests/assistant/test_edits.py`
- **前端检查**（在 `frontend/` 下执行）：
  - `npm test`：17 套全部通过（测试写进已有的 `tests/assistant.test.tsx`）。
  - `npm run lint`：0 error，warning 不超过 5 个。
  - `npx vite build`：成功。
- **不花钱**：
  - 测试一律用假模型（`tests/assistant/fake_model.py` 的 `ScriptedChat`），不调真实模型。
  - `assistant/smoke.py`、`render/smoke.py` 只由用户手动运行，开发和测试中不运行。
  - 不往正在运行的服务发助手消息。
- **密钥和路径**：
  - 不读、不打印 `backend/.env`。
  - 工具返回、SSE 事件、报错里都不能出现服务器上的目录或密钥。
- **后端报错文字**：沿用中文。
- **前端文字**：新文字进 `zh.ts` / `en.ts`，两边键一致；源码里注释以外不许有中文（有静态检查）。
- **不碰**：`backend/.env`、`docs/specs/2026-10-27-commercialization-design-contract.md`。

## 实施裁定

1. **改镜头在原版本上保存**：与界面「保存修改」同一函数（`PUT …/versions/{vid}`：整份复验，复验不过照样保存、标草稿）。spec §8 已改。
2. **撤销数据只存改动的几处**：
   - 改镜头时，存被改镜头的「改前 / 改后」整条镜头对象，不存整份分镜。原因：工具结果每一步都随消息列表写进存档，整份分镜几百 KB，会让存档膨胀。
   - 资产卡存整张卡的改前 / 改后；剧情存那段文字的改前 / 改后。
3. **撤销的判定只看「那几处现在是否还等于改后」**：spec 原则里的「只能撤销最近一次应用」不另做限制。不同对象的修改各自可撤；同一对象被后来的修改改过，自然等不上、撤不了。
4. **撤销记录放旁边的小文件**：不改存档里的消息。改消息要 `update_state`，会影响图的下一步，还可能碰到待确认的卡。清空对话时一起删。
5. **沿用 `confirm` / `action` 事件**，卡片多 `diff`、`warnings` 两个字段（spec §8.2），不另设 `diff` 事件。前端卡片组件统一处理。
6. **执行函数沿用 `actions.ops`**：在同一个字典里加 `version_check`、`version_save`，由 app 在导入时注入。`edits.py` 复用 `actions._op`、`_where`、`_version`、`_resuming`。
7. **镜头字段白名单**与前端 `edit.ts` 的可编辑边界一致：
   - 可改：`action`、`atmosphere`、`shot_size`、`duration_sec`、`camera.movement`、`camera.angle`、`transition_out`、`sfx`。
   - 旁白、台词、溯源锁死。
   - 枚举取自 `schema/storyboard.schema.json`。
8. **恢复时的核对**：`_ask_edit(build)` 中断一次。确认后重新 `build()`，章节、版本、`diff` 与用户看到的卡完全一致才应用，否则报错不应用。应用用的是这次重算出的计划，它与卡一致。
9. **页面联动**：
   - App 订阅 `onTask`。`kind === "edit"` 时重读小说。
   - 如果正在看的就是这一章这一版：没有未保存的修改就重读这一版；有就用 `notice.err` 提示，不重读，免得冲掉用户的修改。
   - 画布的出片会话不受影响（`TimelineCanvas` 只订阅 film / compose）。

## 文件结构

**后端**
- 改 `backend/server/app.py`：抽出 `_check_version_doc`、`_save_version_doc`；注入 `version_check` / `version_save`；新接口 `/assistant/undo`；历史传入已撤销集合。
- 改 `backend/assistant/store.py`：`undone`、`mark_undone`；`clear` 一并删撤销记录。
- 新建 `backend/assistant/edits.py`：`shots_edit`、`asset_edit`、`plot_edit`、`undo`、`UndoError`、`TOOLS`、`EDITS`。
- 改 `backend/assistant/graph.py`：`ALL_TOOLS` 加上改内容工具。
- 改 `backend/assistant/events.py`：出卡的工具集合加上改内容工具；`history(..., undone=)`。
- 改 `backend/prompts/assistant.md`：改内容的规则。
- 新测试 `backend/tests/assistant/test_edits.py`；改 `backend/tests/assistant/test_store.py`、`backend/tests/assistant/test_graph.py`、`backend/tests/server/test_assistant.py`、`backend/tests/server/test_assistant_ops.py`。

**前端**
- 改 `frontend/src/types.ts`、`frontend/src/api.ts`、`frontend/src/lib/assistantSession.ts`、`frontend/src/components/assistant/ActionCard.tsx`、`frontend/src/components/assistant/AssistantPanel.tsx`、`frontend/src/styles/workspace.css`、`frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`、`frontend/src/App.tsx`。
- 改测试 `frontend/tests/assistant.test.tsx`。

---

### Task 1: 保存版本的共用函数与撤销记录

**Files:**
- Modify: `backend/server/app.py`（`versions_update`，约 610–625 行）
- Modify: `backend/assistant/store.py`
- Test: `backend/tests/server/test_assistant_ops.py`、`backend/tests/assistant/test_store.py`

- [ ] **Step 1: 写失败的测试**

`tests/server/test_assistant_ops.py` 在第 5 步之后、`print("\nALL PASS")` 之前追加：

```python
    # 6. 复验与保存（接口与助手共用）：只复验不改版本；保存后状态与复验一致；改坏了照样保存、标草稿
    doc = copy.deepcopy(novels.get_version(uid, nid, cid, "v1")["result"])
    shot = doc["episodes"][0]["shots"][0]
    shot["action"] = "改过的画面"
    chk = app_mod._check_version_doc(user, nid, cid, "v1", doc)
    assert chk == {"ok": True, "warnings": []}, chk
    assert novels.get_version(uid, nid, cid, "v1")["result"]["episodes"][0]["shots"][0]["action"] != "改过的画面"
    r = app_mod._save_version_doc(user, nid, cid, "v1", doc)
    assert r["status"] in ("succeeded", "completed_with_warnings") and r["id"] == "v1"
    assert novels.get_version(uid, nid, cid, "v1")["result"]["episodes"][0]["shots"][0]["action"] == "改过的画面"
    bad = copy.deepcopy(doc)
    bad["episodes"][0]["shots"][0]["narration"]["text"] = "完全不是原文"
    chk = app_mod._check_version_doc(user, nid, cid, "v1", bad)
    assert chk["ok"] is False and chk["warnings"] and len(chk["warnings"]) <= 5, chk
    assert all(isinstance(w, str) and _TMP.name not in w for w in chk["warnings"])
    assert app_mod._save_version_doc(user, nid, cid, "v1", bad)["status"] == "draft_invalid"
    app_mod._save_version_doc(user, nid, cid, "v1", doc)      # 改回去，免得影响后面
    print("6. 复验与保存 ✓")
```

`tests/assistant/test_store.py` 末尾（`ALL PASS` 之前）追加。沿用文件里已有的 `uid`、`nid`；如果名字不同，按文件实际改：

```python
    # 撤销记录：没有时为空；记两次只算一次；清空对话一并删掉
    assert store.undone(uid, nid) == set()
    store.mark_undone(uid, nid, "t1")
    store.mark_undone(uid, nid, "t1")
    store.mark_undone(uid, nid, "t2")
    assert store.undone(uid, nid) == {"t1", "t2"}
    store.clear(uid, nid)
    assert store.undone(uid, nid) == set()
    print("撤销记录 ✓")
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_assistant_ops.py; .venv/bin/python tests/assistant/test_store.py`
Expected: 前者 `AttributeError: … '_check_version_doc'`；后者 `AttributeError: … 'undone'`。

- [ ] **Step 3: `app.py` 抽出复验与保存**

把 `versions_update` 改成调用下面两个函数（放在 `versions_update` 之前）：

```python
def _check_version_doc(user: dict, nid: str, cid: str, vid: str, doc: dict) -> dict:
    """人工编辑后的整份复验，不保存（助手出对比卡时预先告诉用户）：{ok, warnings（最多 5 条，隐去服务器目录）}。"""
    existing = _novel_call(novels.get_version, user["id"], nid, cid, vid)
    context = _novel_call(novels.novel_context, user["id"], nid, cid)
    _doc, report, _status, _frozen = _reverify(existing, doc, context)
    return {"ok": report.ok,
            "warnings": [_hide_root(f"{f.object_path}: {f.message}", auth.DATA_DIR) for f in report.errors][:5]}


def _save_version_doc(user: dict, nid: str, cid: str, vid: str, doc: dict) -> dict:
    """人工编辑 + 整份复验后保存（接口与助手共用）。不合格标 draft_invalid 但照样保存；采用版被改了，长期记忆随之更新。"""
    existing = _novel_call(novels.get_version, user["id"], nid, cid, vid)
    context = _novel_call(novels.novel_context, user["id"], nid, cid)
    doc, report, status, frozen = _reverify(existing, doc, context)
    v = _novel_call(novels.update_version_result, user["id"], nid, cid, vid, doc,
                    verification=report.to_dict(), status=status, frozen_units=frozen)
    return {"id": vid, "edited_at": v["edited_at"], "status": status,
            "verification": report.to_dict()}


@app.put("/novels/{nid}/chapters/{cid}/versions/{vid}")
def versions_update(nid: str, cid: str, vid: str,
                    result: dict = Body(..., embed=False),
                    user: dict = Depends(novel_user)):
    """人工编辑 + 整份复验。采用版被改了，长期记忆随之按改后的产物更新。"""
    return _save_version_doc(user, nid, cid, vid, result)
```

`_hide_root` 定义在文件后面（导出那一节），运行时才调用，没有问题。

- [ ] **Step 4: `store.py` 加撤销记录**

```python
def _undone_path(user_id: str, nid: str):
    db = novels.assistant_db(user_id, nid)
    return db.with_name(db.name + ".undone.json")


def undone(user_id: str, nid: str) -> set:
    """撤销过的修改（工具调用编号）。存在存档旁边的小文件里：不改存档消息，免得影响图的下一步。"""
    try:
        return set(json.loads(_undone_path(user_id, nid).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def mark_undone(user_id: str, nid: str, tool_call_id: str) -> None:
    ids = undone(user_id, nid) | {tool_call_id}
    path = _undone_path(user_id, nid)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(sorted(ids)), encoding="utf-8")
    tmp.replace(path)
```

- 文件顶部加 `import json`。
- `clear` 的后缀元组加上 `".undone.json"`：`for suffix in ("", "-wal", "-shm", "-journal", ".undone.json"):`。
- 文件头注释补一行：「撤销记录：撤销过的修改的工具调用编号，存在 assistant.sqlite.undone.json，清空对话时一起删」。

- [ ] **Step 5: 跑测试，确认通过**

Run（在 `backend/` 下）：全局约束里的全部后端脚本。
Expected: 每个都 `ALL PASS`。

- [ ] **Step 6: 提交**

```bash
git add backend/server/app.py backend/assistant/store.py backend/tests/server/test_assistant_ops.py backend/tests/assistant/test_store.py
git commit -m "人工编辑的整份复验与保存抽成内部函数，接口与助手共用（只复验不保存的那份给出最多 5 条原因）；助手存档旁记下撤销过的修改，清空对话时一起删"
```

---

### Task 2: 改内容工具与撤销

**Files:**
- Create: `backend/assistant/edits.py`
- Create: `backend/tests/assistant/test_edits.py`

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/assistant/test_edits.py`：

```python
#!/usr/bin/env python3
"""助手的改内容工具：改镜头（对比字段、编号后半段、白名单与枚举、旁白锁死、没变化报错、复验警告、应用、取消、
恢复时内容变了不应用、撤销与撤销被拒）、改资产卡（文字与列表字段、嵌套字段、锁死字段、应用与撤销）、
改剧情（全书梗概与章节梗概、应用与撤销）、撤销数据只含改动的镜头。复验与保存用替身（ops）。
用法: python3 tests/assistant/test_edits.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402
from langgraph.types import Command  # noqa: E402
from fake_model import ScriptedChat, call  # noqa: E402
from assistant import actions as A, edits as E  # noqa: E402
from server import auth, novels  # noqa: E402

DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))
saves: list = []
check = {"ok": True, "warnings": []}


def fake_ops(uid):
    def version_save(user, nid, cid, vid, doc):
        saves.append((cid, vid))
        novels.update_version_result(uid, nid, cid, vid, doc, verification={}, status="succeeded")
        return {"id": vid, "status": "succeeded"}
    A.ops.update(version_check=lambda user, nid, cid, vid, doc: dict(check), version_save=version_save)


def agent_for(script):
    return create_react_agent(ScriptedChat(script=script), E.TOOLS, checkpointer=InMemorySaver())


def run(agent, cfg, payload) -> list:
    out = []
    for chunk in agent.stream(payload, cfg, stream_mode="updates"):
        out += list(chunk.get("__interrupt__") or [])
    return out


def answer(it, decision="approve"):
    return Command(resume={it.id: {"decision": decision, "card": it.value}})


def result(agent, cfg) -> ToolMessage:
    return [m for m in agent.get_state(cfg).values["messages"] if isinstance(m, ToolMessage)][-1]


def shot(uid, nid, cid, sid):
    doc = novels.get_version(uid, nid, cid, "v1")["result"]
    return next(s for ep in doc["episodes"] for s in ep["shots"] if s["id"] == sid)


def main() -> int:
    uid = auth.register("alice", "secret1")["id"]
    nid = novels.create_novel(uid, "药")["id"]
    c1 = novels.create_chapter(uid, nid, "第一章 茶馆", text="原文")["id"]
    novels.create_version(uid, nid, c1, "v1", {}, "原文")
    novels.update_version_state(uid, nid, c1, "v1", "succeeded", result=copy.deepcopy(DOC))
    novels.adopt_version(uid, nid, c1, "v1")
    fake_ops(uid)
    first = DOC["episodes"][0]["shots"][0]
    sid, short = first["id"], first["id"].split("-")[-1]
    n = [0]

    def cfg(**extra):
        n[0] += 1
        return {"configurable": {"thread_id": f"t{n[0]}", "user_id": uid, "novel_id": nid,
                                 "where": {"chapter_id": c1}, **extra}}

    # 1. 改镜头：出卡（对比、编号后半段、没变化的不列），确认前不保存；应用后保存；撤销数据只含改动的镜头
    C = cfg()
    edits = [{"shot_id": short, "field": "action", "value": "新的画面"},
             {"shot_id": sid, "field": "duration_sec", "value": 7},
             {"shot_id": sid, "field": "shot_size", "value": first["shot_size"]}]
    ag = agent_for([call("shots_edit", {"edits": edits}, "s1"), AIMessage("改好了")])
    its = run(ag, C, {"messages": [HumanMessage("改第一个镜头")]})
    card = its[0].value
    assert card["action"] == "shots_edit" and card["chapter_id"] == c1 and card["version_id"] == "v1"
    assert card["amount"] is None and card["currency"] is None and card["warnings"] == []
    assert card["detail"] == {"edits": 2}, card
    assert card["diff"] == [
        {"target": sid, "field": "action", "before": first["action"], "after": "新的画面"},
        {"target": sid, "field": "duration_sec", "before": f"{first['duration_sec']:g}", "after": "7"}], card["diff"]
    assert saves == []
    run(ag, C, answer(its[0]))
    m = result(ag, C)
    assert saves == [(c1, "v1")] and shot(uid, nid, c1, sid)["action"] == "新的画面"
    assert shot(uid, nid, c1, sid)["duration_sec"] == 7
    assert m.artifact["outcome"] == "approved"
    assert m.artifact["task"] == {"kind": "edit", "chapter_id": c1, "version_id": "v1"}
    u = m.artifact["undo"]
    assert u["kind"] == "shots" and list(u["shots"]) == [sid] and u["shots"][sid]["before"] == first
    print("1. 改镜头并应用 ✓")

    # 2. 撤销：写回；再撤销（已经是改前的样子）被拒
    E.undo(uid, nid, u)
    assert shot(uid, nid, c1, sid) == first
    try:
        E.undo(uid, nid, u)
        raise AssertionError("改过之后不能再撤")
    except E.UndoError as e:
        assert sid in str(e)
    print("2. 改镜头撤销 ✓")

    # 3. 拒绝的情况：旁白锁死、不在白名单、枚举不对、时长越界、找不到镜头、没有变化 → 工具报错，不出卡
    for bad, word in [({"shot_id": sid, "field": "narration", "value": "x"}, "原文"),
                      ({"shot_id": sid, "field": "location_ref", "value": "S01"}, "不能改"),
                      ({"shot_id": sid, "field": "shot_size", "value": "huge"}, "shot_size"),
                      ({"shot_id": sid, "field": "duration_sec", "value": 30}, "0.5"),
                      ({"shot_id": "SH999", "field": "action", "value": "x"}, "SH999"),
                      ({"shot_id": sid, "field": "action", "value": first["action"]}, "不用改")]:
        C = cfg()
        ag = agent_for([call("shots_edit", {"edits": [bad]}, "sx"), AIMessage("好")])
        assert run(ag, C, {"messages": [HumanMessage("改")]}) == []
        m = result(ag, C)
        assert m.status == "error" and word in m.content, (bad, m.content)
    print("3. 改镜头被拒 ✓")

    # 4. 复验警告写在卡上；取消不保存
    saves.clear()
    check.update(ok=False, warnings=["episodes[0]: 时长对不上"])
    C = cfg()
    ag = agent_for([call("shots_edit", {"edits": [edits[0]]}, "s2"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("改")]})
    assert its[0].value["warnings"] == ["episodes[0]: 时长对不上"]
    run(ag, C, answer(its[0], "reject"))
    assert saves == [] and result(ag, C).artifact["outcome"] == "rejected"
    check.update(ok=True, warnings=[])
    print("4. 复验警告与取消 ✓")

    # 5. 恢复时内容变了（别处改过这个镜头）：不应用
    C = cfg()
    ag = agent_for([call("shots_edit", {"edits": [edits[0]]}, "s3"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("改")]})
    doc = copy.deepcopy(novels.get_version(uid, nid, c1, "v1")["result"])
    doc["episodes"][0]["shots"][0]["action"] = "别处改的"
    novels.update_version_result(uid, nid, c1, "v1", doc, verification={}, status="succeeded")
    run(ag, C, answer(its[0]))
    m = result(ag, C)
    assert saves == [] and m.status == "error" and "变了" in m.content, m.content
    novels.update_version_result(uid, nid, c1, "v1", copy.deepcopy(DOC), verification={}, status="succeeded")
    print("5. 恢复时内容变了 ✓")

    # 6. 改资产卡：文字、列表、嵌套字段；锁死字段与不存在的字段被拒；应用与撤销
    novels.upsert_asset(uid, nid, "characters", copy.deepcopy(DOC["assets"]["characters"][0]))
    c0 = DOC["assets"]["characters"][0]
    C = cfg()
    fields = {"name": "华老栓（改）", "aliases": ["老栓", "栓叔"], "appearance.face": "圆脸"}
    ag = agent_for([call("asset_edit", {"card_id": c0["id"], "fields": fields}, "a1"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("改角色")]})
    v = its[0].value
    assert v["action"] == "asset_edit" and v["chapter_id"] is None and v["detail"] == {"edits": 3}
    assert {"target": f"{c0['id']} {c0['name']}", "field": "aliases", "before": "、".join(c0["aliases"]),
            "after": "老栓、栓叔"} in v["diff"], v["diff"]
    run(ag, C, answer(its[0]))
    m = result(ag, C)
    mem = novels.get_memory(uid, nid)["assets"]["characters"][0]
    assert mem["name"] == "华老栓（改）" and mem["aliases"] == ["老栓", "栓叔"] and mem["appearance"]["face"] == "圆脸"
    assert m.artifact["task"] == {"kind": "edit", "chapter_id": None, "version_id": None}
    E.undo(uid, nid, m.artifact["undo"])
    assert novels.get_memory(uid, nid)["assets"]["characters"][0] == c0
    for bad, word in [({"id": "C99"}, "不能改"), ({"outfits": "x"}, "不能改"), ({"nickname": "x"}, "没有"),
                      ({"appearance": "x"}, "文字"), ({"name": " "}, "名称")]:
        C = cfg()
        ag = agent_for([call("asset_edit", {"card_id": c0["id"], "fields": bad}, "ax"), AIMessage("好")])
        assert run(ag, C, {"messages": [HumanMessage("改")]}) == []
        m = result(ag, C)
        assert m.status == "error" and word in m.content, (bad, m.content)
    C = cfg()
    ag = agent_for([call("asset_edit", {"card_id": "C99", "fields": {"name": "x"}}, "ay"), AIMessage("好")])
    run(ag, C, {"messages": [HumanMessage("改")]})
    assert "C99" in result(ag, C).content
    print("6. 改资产卡 ✓")

    # 7. 改剧情：全书梗概与本章梗概一起改；应用；撤销；别处改过之后撤销被拒
    novels.set_outline(uid, nid, "旧梗概")
    C = cfg()
    ag = agent_for([call("plot_edit", {"outline": "新梗概", "synopsis": "第一章新梗概"}, "p1"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("改剧情")]})
    v = its[0].value
    assert v["action"] == "plot_edit" and v["chapter_id"] == c1 and v["detail"] == {"edits": 2}
    assert [d["field"] for d in v["diff"]] == ["outline", "synopsis"] and v["diff"][1]["before"] == ""
    run(ag, C, answer(its[0]))
    m = result(ag, C)
    plot = novels.get_memory(uid, nid)["plot"]
    assert plot["outline"] == "新梗概" and plot["chapters"][0]["synopsis"] == "第一章新梗概"
    E.undo(uid, nid, m.artifact["undo"])
    plot = novels.get_memory(uid, nid)["plot"]
    assert plot["outline"] == "旧梗概" and plot["chapters"] == []
    novels.set_outline(uid, nid, "又改了")
    try:
        E.undo(uid, nid, {**m.artifact["undo"], "synopsis": None})
        raise AssertionError("梗概被别处改过，不能撤")
    except E.UndoError as e:
        assert "梗概" in str(e)
    C = cfg()
    ag = agent_for([call("plot_edit", {}, "p2"), AIMessage("好")])
    run(ag, C, {"messages": [HumanMessage("改")]})
    assert result(ag, C).status == "error"
    print("7. 改剧情 ✓")

    # 8. 参数说明里没有 config、tool_call_id；EDITS 名单
    for t in E.TOOLS:
        props = t.tool_call_schema.model_json_schema().get("properties", {})
        assert "config" not in props and "tool_call_id" not in props, (t.name, props)
    assert E.EDITS == ("shots_edit", "asset_edit", "plot_edit")
    print("8. 参数说明 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd backend && .venv/bin/python tests/assistant/test_edits.py`
Expected: FAIL，`ImportError: cannot import name 'edits' from 'assistant'`

- [ ] **Step 3: 实现 `assistant/edits.py`**

```python
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
        if u["outline"]:
            novels.set_outline(uid, nid, u["outline"]["after"])
        if u["synopsis"]:
            novels.set_synopsis(uid, nid, u["synopsis"]["chapter_id"], u["synopsis"]["after"])
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
```

注意：
- `actions._op` 会把执行函数的 `HTTPException` 转成 `ToolException`；`undo` 里再把它转成 `UndoError`。
- 镜头相等比较用的是整条镜头字典。`_save_version_doc` 的复验只改分镜顶层的 `coverage`，不动镜头，所以应用后读回的镜头与 `after` 相等。如果测试第 2 步发现不相等，先查是哪个字段被改了。不要放宽比较；要么在 `after` 里存保存后读回的镜头，要么只比较白名单字段。在报告里说明你怎么处理的。

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd backend && .venv/bin/python tests/assistant/test_edits.py`
Expected: 1–8 都 ✓，`ALL PASS`。然后跑全局约束里的全部后端脚本。

- [ ] **Step 5: 提交**

```bash
git add backend/assistant/edits.py backend/tests/assistant/test_edits.py
git commit -m "助手改内容工具：改镜头拍法（白名单字段与枚举、旁白台词锁死）、资产卡文字字段、主线剧情与章节梗概；先出「原 → 新」对比卡（改镜头带复验警告），应用后结果里带只含改动几处的撤销数据；恢复时内容或位置变了不应用；撤销要求那几处之后没被改过"
```

---

### Task 3: 智能体、事件与撤销接口

**Files:**
- Modify: `backend/assistant/graph.py`
- Modify: `backend/assistant/events.py`
- Modify: `backend/prompts/assistant.md`
- Modify: `backend/server/app.py`（助手一节）
- Test: `backend/tests/assistant/test_graph.py`、`backend/tests/server/test_assistant.py`

- [ ] **Step 1: 写失败的测试**

`tests/assistant/test_graph.py` 导入改成 `from assistant import actions, edits, events, graph, store`，在末尾 `ALL PASS` 之前追加：

```python
    # 16. 改内容工具在智能体里：出卡发 confirm（不出工具行），应用后发 action（不带撤销数据）；历史里撤销过的卡标 undone
    assert [t.name for t in graph.ALL_TOOLS][-3:] == list(edits.EDITS)
    novels.set_outline(uid, nid, "旧梗概")
    store.clear(uid, nid)
    model = ScriptedChat(script=[call("plot_edit", {"outline": "新梗概"}, "p1"), AIMessage("改好了。")])
    cfg = graph.run_config(uid, nid, {"chapter_id": cid}, "zh")
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(model, cp)
        evs = list(events.stream(agent, cfg, "改梗概"))
        assert [e["event"] for e in evs] == ["confirm", "done"], evs
        conf = evs[0]["data"]
        assert conf["action"] == "plot_edit" and conf["diff"][0]["after"] == "新梗概"
        card = graph.pending(agent, cfg)[0].value
        evs = list(events.stream(agent, graph.run_config(uid, nid, {}, "zh", resume_tool_call="p1"),
                                 Command(resume={conf["id"]: {"decision": "approve", "card": card}})))
        assert [e["event"] for e in evs] == ["action", "token", "done"], evs
        assert evs[0]["data"]["outcome"] == "approved" and "undo" not in evs[0]["data"]
        assert evs[0]["data"]["task"] == {"kind": "edit", "chapter_id": None, "version_id": None}
        h = events.history(agent, cfg)
        assert h[-1]["cards"][0]["outcome"] == "approved" and "undo" not in h[-1]["cards"][0]
        h = events.history(agent, cfg, undone={"p1"})
        assert h[-1]["cards"][0]["outcome"] == "undone"
    print("16. 改内容工具 ✓")
```

`tests/server/test_assistant.py` 在末尾 `ALL PASS` 之前追加（`c`、`H`、`HB`、`A`、`uid`、`nid`、`cid`、`script`、`events_of` 都是已有的）：

```python
    # 23. 撤销接口：应用一次改剧情后撤销；撤销两次 409；别人的小说 404；找不到 404；参数非法 422；正在回答 409
    store.clear(uid, nid)
    app_mod._assistant_model = lambda: ScriptedChat(script=script)
    novels.set_outline(uid, nid, "旧梗概")
    script[:] = [call("plot_edit", {"outline": "新梗概"}, "pe1")]
    conf = events_of(c.post(A + "/messages", headers=H, json={"text": "改梗概", "lang": "zh"}))[0][1]
    script[:] = [AIMessage("改好了。")]
    evs = events_of(c.post(A + "/resume", headers=H,
                           json={"id": conf["id"], "decision": "approve", "lang": "zh", "where": {}}))
    assert evs[0][1]["outcome"] == "approved", evs
    assert novels.get_memory(uid, nid)["plot"]["outline"] == "新梗概"
    U = A + "/undo"
    n_usage = len(usage.read(user_id=uid))
    assert c.post(U, json={"tool_call_id": "pe1"}).status_code == 401
    assert c.post(U, headers=HB, json={"tool_call_id": "pe1"}).status_code == 404
    assert c.post(U, headers=H, json={}).status_code == 422
    assert c.post(U, headers=H, json={"tool_call_id": "nope"}).status_code == 404
    token = store.try_begin(uid, nid)
    assert c.post(U, headers=H, json={"tool_call_id": "pe1"}).status_code == 409
    store.end(uid, nid, token)
    r = c.post(U, headers=H, json={"tool_call_id": "pe1"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["task"] == {"kind": "edit", "chapter_id": None, "version_id": None}
    assert novels.get_memory(uid, nid)["plot"]["outline"] == "旧梗概"
    assert len(usage.read(user_id=uid)) == n_usage, "撤销不调模型、不记用量"
    r = c.post(U, headers=H, json={"tool_call_id": "pe1"})
    assert r.status_code == 409 and "撤销过" in r.json()["detail"]
    h = c.get(A, headers=H).json()["messages"]
    assert h[-1]["cards"][0]["outcome"] == "undone"
    assert store.try_begin(uid, nid) and store.end(uid, nid) is None
    print("23. 撤销接口 ✓")

    # 24. 之后被别处改过：撤销 409 并说明原因
    script[:] = [call("plot_edit", {"outline": "第二版梗概"}, "pe2")]
    conf = events_of(c.post(A + "/messages", headers=H, json={"text": "再改", "lang": "zh"}))[0][1]
    script[:] = [AIMessage("好。")]
    events_of(c.post(A + "/resume", headers=H, json={"id": conf["id"], "decision": "approve", "lang": "zh", "where": {}}))
    novels.set_outline(uid, nid, "别处改的")
    r = c.post(U, headers=H, json={"tool_call_id": "pe2"})
    assert r.status_code == 409 and "改过" in r.json()["detail"], r.text
    assert novels.get_memory(uid, nid)["plot"]["outline"] == "别处改的"
    print("24. 撤销被拒 ✓")
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd backend && .venv/bin/python tests/assistant/test_graph.py; .venv/bin/python tests/server/test_assistant.py`
Expected: 前者第 16 步失败（`ALL_TOOLS` 里没有改内容工具）；后者第 23 步失败。

- [ ] **Step 3: `graph.py`**

```python
from assistant import actions, edits, store
...
ALL_TOOLS = TOOLS + actions.TOOLS + edits.TOOLS
```

- [ ] **Step 4: `events.py`**

- 导入改成 `from assistant.actions import ACTIONS` 加 `from assistant.edits import EDITS`，再定义：

```python
CARD_TOOLS = ACTIONS + EDITS    # 出卡片的工具：不发 tool_start / tool_end，历史里进 cards
```

- `stream` 和 `history` 里所有 `in ACTIONS` / `not in ACTIONS` 改成 `CARD_TOOLS`。
- `action_view` 不动。它只取 `card`、`outcome`、`task`，撤销数据 `undo` 不会出去。
- `history` 加参数 `undone: Optional[set] = None`，docstring 补「undone：撤销过的修改，卡标 undone」。在处理 `ToolMessage` 的分支里，算出 `view` 之后：

```python
                view = action_view(m, hide)
                if undone and view["outcome"] == "approved" and m.tool_call_id in undone:
                    view["outcome"] = "undone"
```

- 文件头注释的事件说明里，`action` 的 `outcome` 加一个取值说明：「历史里撤销过的修改为 undone」。

- [ ] **Step 5: 系统提示 `prompts/assistant.md`**

把这一行：

```
- 你不能出关键帧图，不能改镜头、资产卡、剧情和设置，也不能删除任何东西；用户要做这些时说明怎么做，并用 goto 放跳转按钮。
```

换成：

```
- 你能按用户的要求改内容：shots_edit 改镜头的拍法、asset_edit 改资产卡上的文字、plot_edit 改全书梗概与章节梗概。
  - 先用 shots_get / assets_find / plot_get 查到现在的内容，再给出改后的完整文字，不要只给片段。
  - 会自动给用户一张「原 → 新」的对比卡，由用户点「应用」，你不用再问「确定吗」。
  - 用户可能在卡上撤销你的修改；之后还要改，先重新查一遍。
  - 旁白与台词是原文，不能改；资产卡的编号、服装、状态、参考图不能改。
- 你不能出关键帧图、不能改设置，也不能删除任何东西；用户要做这些时说明怎么做，并用 goto 放跳转按钮。
```

- [ ] **Step 6: `app.py`**

导入加 `from assistant import edits as assistant_edits`。

注入执行函数，在已有的 `assistant_actions.ops.update(...)` 里加两项：

```python
assistant_actions.ops.update(start_version=_start_version, film_quote=_film_quote, film_run=_film_run,
                             compose_quote=_compose_quote, compose_start=_compose_start,
                             export_check=_export_check, version_check=_check_version_doc,
                             version_save=_save_version_doc)
```

`assistant_history` 把已撤销的集合传进历史：

```python
        return {"messages": assistant_events.history(agent, cfg, hide=str(auth.DATA_DIR),
                                                     undone=assistant_store.undone(user["id"], nid))}
```

新增撤销接口（放在 `assistant_resume` 之后）：

```python
def _assistant_undo_data(user_id: str, nid: str, tool_call_id: str) -> Optional[dict]:
    """存档里这次修改的撤销数据：应用成功的改内容工具结果才有。"""
    if not assistant_store.exists(user_id, nid):
        return None
    with assistant_store.saver(user_id, nid) as cp:
        agent = assistant_graph.build_agent(assistant_graph.NullModel(), cp)
        msgs = agent.get_state(assistant_graph.run_config(user_id, nid, {}, "zh")).values.get("messages") or []
    for m in msgs:
        if getattr(m, "tool_call_id", None) == tool_call_id and m.name in assistant_edits.EDITS:
            a = m.artifact if m.status != "error" else None
            return a["undo"] if a and a.get("outcome") == "approved" and a.get("undo") else None
    return None


@app.post("/novels/{nid}/assistant/undo")
def assistant_undo(nid: str, body: dict = Body(...), user: dict = Depends(novel_user)):
    """对比卡上点了「撤销」：把那次应用的改动写回去（spec §8.2）。不调模型、不记用量；之后被别处改过 409。"""
    _assistant_db(user, nid)
    tcid = body.get("tool_call_id")
    if not isinstance(tcid, str) or not tcid:
        raise HTTPException(422, "tool_call_id 不合法")
    token = assistant_store.try_begin(user["id"], nid)
    if not token:
        raise HTTPException(409, "助手正在回答，等它说完再撤销")
    try:
        if tcid in assistant_store.undone(user["id"], nid):
            raise HTTPException(409, "这次修改已经撤销过了")
        data = _assistant_undo_data(user["id"], nid, tcid)
        if data is None:
            raise HTTPException(404, "找不到这次修改")
        try:
            message = assistant_edits.undo(user["id"], nid, data)
        except assistant_edits.UndoError as e:
            raise HTTPException(409, _hide_root(str(e), auth.DATA_DIR))
        assistant_store.mark_undone(user["id"], nid, tcid)
        return {"ok": True, "message": message,
                "task": {"kind": "edit", "chapter_id": data.get("chapter_id"), "version_id": data.get("version_id")}}
    finally:
        assistant_store.end(user["id"], nid, token)
```

- 剧情撤销数据里没有 `chapter_id`；改本章梗概时在 `synopsis` 里。`task` 的 `chapter_id` 取 `data.get("chapter_id")`，剧情时为 `None`。测试第 23 步按此断言。
- 文件头的接口说明加一行：`POST        /novels/{nid}/assistant/undo       撤销助手的一次修改（不调模型）`。

- [ ] **Step 7: 跑测试，确认通过**

Run: 全局约束里的全部后端脚本（含 `test_edits.py`）。
Expected: 每个都 `ALL PASS`。

- [ ] **Step 8: 提交**

```bash
git add backend/assistant/graph.py backend/assistant/events.py backend/prompts/assistant.md backend/server/app.py backend/tests/assistant/test_graph.py backend/tests/server/test_assistant.py
git commit -m "助手接上改内容工具：出对比卡与应用结果走 confirm / action 事件，撤销数据不出存档；新增 undo 接口（不调模型、要并发锁、撤销过或之后被改过 409）；历史里撤销过的卡标 undone；系统提示写明能改什么、不能改什么"
```

---

### Task 4: 前端对比卡与撤销

**Files:**
- Modify: `frontend/src/types.ts`、`frontend/src/api.ts`、`frontend/src/lib/assistantSession.ts`
- Modify: `frontend/src/components/assistant/ActionCard.tsx`、`frontend/src/components/assistant/AssistantPanel.tsx`
- Modify: `frontend/src/styles/workspace.css`、`frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`
- Test: `frontend/tests/assistant.test.tsx`

- [ ] **Step 1: 写失败的测试**

`tests/assistant.test.tsx` 的桩后端里，POST 分支要认出撤销接口。在 `globalThis.fetch = …` 里、处理流式 POST 之前加：

```ts
  if (method === 'POST' && String(url).endsWith('/assistant/undo')) {
    return new Response(JSON.stringify(undoReply.body), { status: undoReply.status })
  }
```

并在 `let history` 旁声明：

```ts
let undoReply: { status: number; body: unknown } = { status: 200, body: { ok: true, message: 'ok', task: { kind: 'edit', chapter_id: 'c1', version_id: 'v1' } } }
```

在确认卡测试块之后、`globalThis.fetch = realFetch` 之前追加：

```ts
{
  // 对比卡：原 → 新、复验警告、应用 / 放弃；应用后撤销；撤销失败给提示；撤销成功通知工作台
  const tasks: unknown[] = []
  const offTask = onTask((t) => tasks.push(t))
  const diffCard = { id: 'i9', tool_call_id: 'e1', action: 'shots_edit', chapter_id: 'c1', chapter: '第一章', version_id: 'v1',
                     amount: null, currency: null, detail: { edits: 1 },
                     diff: [{ target: 'E01-SH001', field: 'action', before: '旧画面', after: '新画面' }],
                     warnings: ['episodes[0]: 时长对不上'] }
  history = []
  let root = await mount('n-edit')
  script = [{ event: 'confirm', data: diffCard }]
  await type('改第一个镜头')
  await enter()
  const box = () => $$('assistant-card').at(-1)!
  const rows = $$('assistant-diff-row')
  must(rows.length === 1 && rows[0].textContent!.includes('旧画面') && rows[0].textContent!.includes('新画面'), '原 → 新')
  must(!!$('assistant-card-warnings') && $('assistant-card-warnings')!.textContent!.includes('时长'), '复验警告')
  must(!$('assistant-card-cost'), '改内容没有金额行')
  must(($('assistant-card-approve')!.textContent ?? '').length > 0 && !$('assistant-card-undo'), '待确认时没有撤销')
  script = [{ event: 'action', data: { tool_call_id: 'e1', action: 'shots_edit', outcome: 'approved', card: diffCard,
                                       task: { kind: 'edit', chapter_id: 'c1', version_id: 'v1' } } }]
  await act(async () => { $('assistant-card-approve')!.click() })
  await flush()
  must(box().getAttribute('data-outcome') === 'approved' && !!$('assistant-card-undo'), '应用后有撤销')
  must(!$('assistant-task'), '改内容不挂任务卡')
  must(tasks.length === 1 && (tasks[0] as { kind: string }).kind === 'edit', '应用后通知工作台')

  undoReply = { status: 409, body: { detail: '镜头 E01-SH001 在这之后又被改过，不能撤销' } }
  await act(async () => { $('assistant-card-undo')!.click() })
  await flush()
  must(box().getAttribute('data-outcome') === 'approved' && !($('assistant-card-undo') as HTMLButtonElement).disabled,
       '撤销失败：卡不变，还能再点')
  must(calls.at(-1)!.url.endsWith('/assistant/undo') && JSON.parse(calls.at(-1)!.body!).tool_call_id === 'e1', '撤销请求带工具调用编号')
  undoReply = { status: 200, body: { ok: true, message: 'ok', task: { kind: 'edit', chapter_id: 'c1', version_id: 'v1' } } }
  await act(async () => { $('assistant-card-undo')!.click() })
  await flush()
  must(box().getAttribute('data-outcome') === 'undone' && !!$('assistant-card-undone') && !$('assistant-card-undo'), '撤销后变已撤销')
  must(tasks.length === 2, '撤销后通知工作台')
  await act(async () => { root.unmount() })

  // 历史里撤销过的卡；放弃的卡
  history = [
    { role: 'user', text: '改' },
    { role: 'assistant', text: '', tools: [], goto: [], cards: [
      { tool_call_id: 'e2', action: 'plot_edit', outcome: 'undone',
        card: { ...diffCard, tool_call_id: 'e2', action: 'plot_edit', warnings: [],
                diff: [{ target: 'all', field: 'outline', before: 'a', after: 'b' }] } },
      { tool_call_id: 'e3', action: 'asset_edit', outcome: 'rejected', card: { ...diffCard, tool_call_id: 'e3', action: 'asset_edit', warnings: [] } },
    ] },
  ]
  root = await mount('n-edit2')
  must($$('assistant-card').map((x) => x.getAttribute('data-outcome')).join() === 'undone,rejected', '历史卡片状态')
  must(!$('assistant-card-undo'), '撤销过、放弃的都没有撤销按钮')
  await act(async () => { root.unmount() })
  offTask()
  console.log('✓ 对比卡与撤销')
}
```

`calls` 的元素形状按文件里实际的写（`{ method, url, body }`）。按钮顺序、`$`/`$$` 的用法沿用已有测试。

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd frontend && npm test`
Expected: `assistant.test.tsx` 失败于「✗ 原 → 新」，或者在那之前就类型报错。

- [ ] **Step 3: 类型**

`src/types.ts` 助手一节：

```ts
export type AssistantAction = 'generate_storyboard' | 'film_run' | 'compose' | 'export_fcpxml'
  | 'shots_edit' | 'asset_edit' | 'plot_edit'
```

`AssistantTask.kind` 加 `'edit'`：`kind: 'job' | 'film' | 'compose' | 'export' | 'edit'`。

`AssistantCardInfo`：
- `chapter_id: string | null`
- `detail` 加 `edits?: number`
- 加：

```ts
  /** 改内容：逐条「原 → 新」（值都是显示用的文字） */
  diff?: { target: string; field: string; before: string; after: string }[]
  /** 改镜头：复验不过的原因（应用后版本会标草稿） */
  warnings?: string[]
```

`AssistantCard.outcome` 加 `'undone'`。

`assistantTask.ts` 的 `TASK_POLL_MS` 是 `Record<AssistantTask['kind'], number>`，要补上 `edit: 0`。`useTaskView` 不会用到 `edit`（改内容不挂任务卡）。

- [ ] **Step 4: 接口**

`src/api.ts` 助手一节加：

```ts
/** 撤销助手的一次修改（不调模型）。之后被别处改过等情况以 ApiError（409，带原因）抛出 */
export const undoAssistant = (nid: string, toolCallId: string) =>
  req<{ ok: true; message: string; task: AssistantTask }>(`/novels/${encodeURIComponent(nid)}/assistant/undo`,
                                                          jsonPost({ tool_call_id: toolCallId }))
```

（`jsonPost` 与 `req` 是文件里已有的；`AssistantTask` 加进类型导入。）

- [ ] **Step 5: 会话存储**

`src/lib/assistantSession.ts` 加（导入 `undoAssistant`）：

```ts
/** 改卡上的一张卡（按 tool_call_id，在哪条消息里都行） */
const patchCard = (nid: string, toolCallId: string, fn: (c: AssistantCard) => AssistantCard) =>
  put(nid, (s) => ({ ...s, msgs: s.msgs.map((m) => (m.cards?.some((c) => c.tool_call_id === toolCallId)
    ? { ...m, cards: m.cards.map((c) => (c.tool_call_id === toolCallId ? fn(c) : c)) } : m)) }))

/** 对比卡上点了「撤销」：成功后卡变已撤销并通知工作台；失败时卡不变，原因抛给界面提示 */
export async function undoAssistantCard(nid: string, toolCallId: string): Promise<void> {
  const s0 = getSession(nid)
  if (s0.busy) return
  patchCard(nid, toolCallId, (c) => ({ ...c, sending: true }))
  try {
    const r = await undoAssistant(nid, toolCallId)
    patchCard(nid, toolCallId, (c) => ({ ...c, sending: false, outcome: 'undone' }))
    notifyTask(r.task)
  } catch (e) {
    patchCard(nid, toolCallId, (c) => ({ ...c, sending: false }))
    throw e
  }
}
```

- [ ] **Step 6: 文案**

`zh.ts` 的 `assistant` 一节：
- `action` 里加 `shots_edit: '改镜头', asset_edit: '改资产卡', plot_edit: '改剧情'`；
- `card` 里加 `apply: '应用', discard: '放弃', applied: '已应用', undo: '撤销', undone: '已撤销', undoFailed: '撤销失败：{msg}', warnings: '复验不通过，应用后这一版会标成草稿：', edits: '{n} 处修改'`；
- 再加 `field`：

```ts
    field: {
      action: '画面', atmosphere: '氛围', shot_size: '景别', duration_sec: '时长', camera_movement: '运镜',
      camera_angle: '机位', transition_out: '转场', sfx: '音效', outline: '全书梗概', synopsis: '本章梗概',
      name: '名称', aliases: '别名', visual_prompt: '画面提示词',
    },
```

`en.ts` 对应：
- `action` 加 `shots_edit: 'Edit shots', asset_edit: 'Edit asset card', plot_edit: 'Edit plot'`；
- `card` 加 `apply: 'Apply', discard: 'Discard', applied: 'Applied', undo: 'Undo', undone: 'Undone', undoFailed: 'Could not undo: {msg}', warnings: 'Fails verification; this version will be marked as a draft after applying:', edits: '{n} changes'`；
- `field`：

```ts
    field: {
      action: 'Action', atmosphere: 'Atmosphere', shot_size: 'Shot size', duration_sec: 'Duration', camera_movement: 'Camera movement',
      camera_angle: 'Camera angle', transition_out: 'Transition', sfx: 'Sound effects', outline: 'Book outline', synopsis: 'Chapter synopsis',
      name: 'Name', aliases: 'Aliases', visual_prompt: 'Visual prompt',
    },
```

- [ ] **Step 7: 卡片组件**

`src/components/assistant/ActionCard.tsx` 整体改成下面这样（在原有基础上加对比、警告、应用 / 放弃、撤销）：

```tsx
/** 助手对话里的操作卡：标题、金额与要点；改内容的卡逐条显示「原 → 新」与复验警告。
 *  待确认时给「确认 / 取消」（改内容为「应用 / 放弃」），请求回来之前禁用；
 *  确认后的操作挂任务卡；应用后的修改给「撤销」；没做成的写原因。 */
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import type { AssistantCard, AssistantGoto } from '@/types'
import { TaskCard } from './TaskCard'

const EDITS = ['shots_edit', 'asset_edit', 'plot_edit']

export function ActionCard({ novelId, c, busy, onDecide, onUndo, onGoto }: {
  novelId: string
  c: AssistantCard
  /** 正在回答（或别的卡在发送）：按钮禁用 */
  busy: boolean
  onDecide: (decision: 'approve' | 'reject') => void
  onUndo: () => void
  onGoto: (g: AssistantGoto) => void
}) {
  const { t } = useI18n()
  const info = c.card
  const edit = EDITS.includes(c.action)
  const title = t(`assistant.action.${c.action}` as MsgKey) + (info?.chapter ? ` · ${info.chapter}` : '')
  const cost = !info || info.currency === null ? null
    : info.amount === null ? t('assistant.card.modelCost') : t('assistant.card.cny', { n: info.amount.toFixed(2) })
  const d = info?.detail ?? {}
  const notes = [
    d.clips !== undefined ? t('assistant.card.clips', { n: d.clips }) : null,
    d.chars !== undefined ? t(c.action === 'compose' ? 'assistant.card.ttsChars' : 'assistant.card.chars', { n: d.chars }) : null,
    d.edits !== undefined ? t('assistant.card.edits', { n: d.edits }) : null,
    d.archived ? t('assistant.card.archived') : null,
    c.action === 'compose' && d.draft ? t('assistant.card.draft') : null,
  ].filter((x): x is string => !!x)
  const fieldName = (f: string) => {
    const key = `assistant.field.${f.replace('.', '_')}` as MsgKey
    const s = t(key)
    return s === key ? f : s
  }
  const locked = busy || !!c.sending
  return (
    <div className="assistant__card" data-testid="assistant-card" data-outcome={c.outcome}>
      <p className="font-medium">{title}</p>
      {cost && <p data-testid="assistant-card-cost">{cost}</p>}
      {!!notes.length && <p className="text-xs text-muted-foreground">{notes.join(t('common.listSep'))}</p>}
      {!!info?.diff?.length && (
        <ul className="assistant__diff">
          {info.diff.map((r, i) => (
            <li key={i} data-testid="assistant-diff-row">
              <p className="text-xs text-muted-foreground">{r.target} · {fieldName(r.field)}</p>
              <p className="assistant__diff-before">{r.before}</p>
              <p className="assistant__diff-after">{r.after}</p>
            </li>
          ))}
        </ul>
      )}
      {!!info?.warnings?.length && (
        <div className="text-xs text-warning" data-testid="assistant-card-warnings">
          <p>{t('assistant.card.warnings')}</p>
          <ul className="list-disc pl-4">{info.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}
      {c.outcome === 'pending' && (
        <div className="flex gap-2">
          <Button size="sm" disabled={locked} data-testid="assistant-card-approve" onClick={() => onDecide('approve')}>
            {c.sending && <Loader2 className="size-3 animate-spin" />}
            {t(edit ? 'assistant.card.apply' : 'assistant.card.confirm')}
          </Button>
          <Button size="sm" variant="outline" disabled={locked} data-testid="assistant-card-reject" onClick={() => onDecide('reject')}>
            {t(edit ? 'assistant.card.discard' : 'assistant.card.reject')}
          </Button>
        </div>
      )}
      {c.outcome === 'approved' && !edit && <p className="text-xs text-muted-foreground">{t('assistant.card.approved')}</p>}
      {c.outcome === 'approved' && edit && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>{t('assistant.card.applied')}</span>
          <Button size="sm" variant="ghost" disabled={locked} data-testid="assistant-card-undo" onClick={onUndo}>
            {c.sending && <Loader2 className="size-3 animate-spin" />}
            {t('assistant.card.undo')}
          </Button>
        </div>
      )}
      {c.outcome === 'undone' && (
        <p className="text-xs text-muted-foreground" data-testid="assistant-card-undone">{t('assistant.card.undone')}</p>
      )}
      {c.outcome === 'rejected' && (
        <p className="text-xs text-muted-foreground" data-testid="assistant-card-rejected">{t('assistant.card.rejected')}</p>
      )}
      {c.outcome === 'failed' && (
        <p className="text-xs text-destructive" data-testid="assistant-card-failed">{t('assistant.card.failed', { msg: c.error ?? '' })}</p>
      )}
      {c.task && c.task.kind !== 'edit' && (c.outcome === 'approved' || c.outcome === 'done') && (
        <TaskCard novelId={novelId} task={c.task} chapter={info?.chapter ?? ''} onGoto={onGoto} />
      )}
    </div>
  )
}
```

先读一遍现有的 `ActionCard.tsx`。如果它与子计划 2 的计划写法有出入（例如类名、`data-testid`），以现有文件为准合并，上面新增的部分保持不变。

- [ ] **Step 8: 面板**

`AssistantPanel.tsx`：
- 导入 `undoAssistantCard`；
- `ActionCard` 加 `onUndo`：

```tsx
              <ActionCard key={c.tool_call_id} novelId={novelId} c={c} busy={busy} onGoto={onGoto}
                          onDecide={(d) => void decideAssistant(novelId, c.tool_call_id, d, opts())}
                          onUndo={() => {
                            undoAssistantCard(novelId, c.tool_call_id).catch((e) =>
                              toast.error(t('assistant.card.undoFailed', { msg: e instanceof Error ? e.message : String(e) })))
                          }} />
```

`toast` 已从 `sonner` 导入。

- [ ] **Step 9: 样式**

`src/styles/workspace.css`，在 `.assistant__task` 之后加：

```css
.assistant__diff { display: flex; flex-direction: column; gap: 6px; }
.assistant__diff-before { font-size: 12px; color: var(--ui-muted-foreground); text-decoration: line-through; white-space: pre-wrap; max-height: 8em; overflow-y: auto; }
.assistant__diff-after { font-size: 13px; white-space: pre-wrap; max-height: 8em; overflow-y: auto; }
```

- [ ] **Step 10: 跑测试，确认通过**

Run: `cd frontend && npm test && npm run lint && npx vite build`
Expected: 17 套全过，`assistant.test.tsx` 多出「✓ 对比卡与撤销」；lint 0 error、warning ≤ 5；build 成功。

- [ ] **Step 11: 提交**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/lib/assistantSession.ts frontend/src/lib/assistantTask.ts frontend/src/components/assistant/ActionCard.tsx frontend/src/components/assistant/AssistantPanel.tsx frontend/src/styles/workspace.css frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/assistant.test.tsx
git commit -m "助手对比卡：改内容的卡逐条显示「原 → 新」与复验警告，按钮为应用 / 放弃；应用后给撤销，撤销失败提示原因、成功变已撤销；应用与撤销都通知工作台"
```

（`assistantTask.ts` 如果没改，就从 `git add` 里去掉。）

---

### Task 5: 页面联动（改内容后重读）

**Files:**
- Modify: `frontend/src/App.tsx`（子计划 2 加的 `onTask` 订阅）
- Modify: `frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`

没有新增自动测试：App 整体挂载太重，现有测试都不挂 App。这一步的行为请用户在浏览器验收时确认。审查重点看依赖数组与「有未保存修改不重读」。

- [ ] **Step 1: 文案**

`zh.ts` 的 `assistant` 一节加 `editedDirty: '助手改了这一版，你有未保存的修改；保存时会覆盖助手的改动'`；`en.ts` 加 `editedDirty: 'The assistant changed this version while you have unsaved edits; saving will overwrite its changes'`。

- [ ] **Step 2: App 订阅**

把子计划 2 里的这段：

```tsx
  useEffect(() => onTask((t) => {
    if (t.kind === 'job') void watchJobs()
    bumpSummary()
  }), [watchJobs, bumpSummary])
```

改成：

```tsx
  // 助手发起了操作或改了内容：转换让任务巡检立刻刷新；改内容重读小说，正在看的这一版没有未保存修改就重读
  // （有就只提示，免得冲掉用户的修改）；各种操作都让小说概览重算
  useEffect(() => onTask((t) => {
    if (t.kind === 'job') void watchJobs()
    if (t.kind === 'edit' && novel) {
      void reloadOpen(novel.id, chapter?.id ?? null)
      if (t.version_id && chapter?.id === t.chapter_id && docVid === t.version_id) {
        if (dirty) notice.err(tr('assistant.editedDirty'))
        else void openVersion(novel.id, t.chapter_id, t.version_id)
      }
    }
    bumpSummary()
  }), [watchJobs, bumpSummary, novel, chapter?.id, docVid, dirty, reloadOpen, openVersion])
```

- `tr` / `t`：App 里已有的翻译函数用哪个就用哪个（文件里提示文字用的是 `t(...)`，就写 `t('assistant.editedDirty')`，并把 `t` 加进依赖）。
- `openVersion`、`reloadOpen`、`docVid`、`dirty`、`notice` 都是 App 里已有的。

- [ ] **Step 3: 跑检查**

Run: `cd frontend && npm test && npm run lint && npx vite build`
Expected: 17 套全过；lint 0 error、warning ≤ 5（不能新增 exhaustive-deps 警告）；build 成功。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/App.tsx frontend/src/i18n/zh.ts frontend/src/i18n/en.ts
git commit -m "助手改内容后页面联动：重读小说；正在看的这一版没有未保存修改就重读，有就提示保存会覆盖助手的改动"
```

---

## 自查（写计划时已做）

- **spec 覆盖**：
  - §8.1 三个工具的白名单、锁死、枚举、编号后半段、没变化报错 → Task 2；
  - 改镜头与「保存修改」同一函数、复验警告 → Task 1、2；
  - 恢复时核对 → Task 2（`_ask_edit`）；
  - §8.2 卡片字段与事件 → Task 3；撤销接口与 `undone` 记录 → Task 1、3；历史标 `undone` → Task 3；
  - 页面联动 → Task 5；前端卡片 → Task 4；
  - §8.3 测试 → 各任务 Step 1。
- **类型一致**：
  - 后端卡片多 `diff`、`warnings`、`detail.edits`，`chapter_id` 可为空，与前端 `AssistantCardInfo` 一致。
  - `task.kind="edit"` 前后端一致；撤销接口返回 `{ok, message, task}` 与 `undoAssistant` 一致。
  - `ops` 新增的 `version_check` / `version_save` 在 Task 1（定义）、Task 2（替身）、Task 3（注入）一致。
- **有意留给实施者判断的两处**：Task 2 的镜头相等比较、Task 5 的翻译函数名。都写明了判断依据。
