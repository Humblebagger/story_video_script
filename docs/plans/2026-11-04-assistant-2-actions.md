# Agent 助手 子计划 2：发起操作与确认卡 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 助手能替用户发起四个操作：
- 生成分镜、出片、配音合成：花钱的先在对话里出一张确认卡，用户点「确认」才执行；
- 导出剪辑工程：不花钱，直接在对话里放下载按钮；
- 执行后对话里出现任务卡，显示进度，结束后给跳转。

**Architecture:**
- **后端**：
  - `server/app.py` 把「转换本章、出片、合成、导出检查」从接口函数里抽成内部函数，接口和助手共用，鉴权、验证门、上限、确认金额完全相同。
  - 新文件 `backend/assistant/actions.py`：四个操作工具。花钱的工具先算预估，再用 `langgraph.types.interrupt` 暂停这一轮；用户点按钮后，新接口 `POST /assistant/resume` 用 `Command(resume=…)` 接着跑。
  - `graph.py` 关掉并行工具调用，并提供「发新消息时取消待确认的卡」。
  - `events.py` 多发两种事件 `confirm` / `action`，历史里多一个 `cards` 字段。
- **前端**：
  - 会话存储处理新事件并提供 `decideAssistant`。
  - 新组件 `ActionCard`（确认卡）和 `TaskCard`（任务进度）。
  - 桥接里加 `notifyTask` / `onTask`：操作开始后通知 App 刷新任务巡检、通知画布重读出片会话。

**Tech Stack:** FastAPI（Python 3.12）、LangGraph 1.2.14（`create_react_agent`、`interrupt`、`Command`、`SqliteSaver`）、langchain-core 1.6；React 19、TS、Tailwind v4、shadcn。

**Spec:** `docs/specs/2026-11-01-assistant-panel-design.md` 第 7 节（7.1–7.4 是本计划要实现的细节）。

---

## 全局约束

- **提交**：
  - 只 `git add` 具体文件，不用 `git add -A` / `git commit -a`。
  - 提交信息用中文、写成描述式，**不带任何 Claude 署名**（不要 `Co-Authored-By`、不要 `Claude-Session`）。
- **后端检查**：在 `backend/` 下执行。venv 里没有 pytest，测试脚本直接用 `.venv/bin/python` 跑。每个任务结束时，下面的脚本都要打印 `ALL PASS`：
  - `tests/server/test_novels.py`、`tests/server/test_summary.py`、`tests/server/test_usage.py`、`tests/server/test_render.py`、`tests/server/test_compose.py`
  - `tests/assistant/test_store.py`、`tests/assistant/test_tools.py`、`tests/assistant/test_graph.py`、`tests/server/test_assistant.py`
  - 本计划新建的、到当前任务为止已存在的：`tests/server/test_assistant_ops.py`、`tests/assistant/test_actions.py`
- **前端检查**（在 `frontend/` 下执行）：
  - `npm test`：17 套全部通过（本计划不加新套，测试写进已有的 `tests/assistant.test.tsx` 与 `tests/film.test.tsx`）。
  - `npm run lint`：0 error，warning 不超过 5 个。
  - `npx vite build`：成功。
- **不花钱**：
  - 测试一律用假模型（`tests/assistant/fake_model.py` 的 `ScriptedChat`）和假出片、假配音厂商，不调真实模型。
  - 生成分镜的测试把 `app_mod._run_version_job` 换成空函数，不跑真实转换。
  - `assistant/smoke.py`、`render/smoke.py` 只由用户手动运行，开发和测试中不运行。
  - 不往正在运行的服务发助手消息。
- **密钥和路径**：
  - 不读、不打印 `backend/.env`。
  - 工具返回、SSE 事件、报错里都不能出现服务器上的目录或密钥。
- **后端报错文字**：沿用中文。
- **前端文字**：新文字进 `zh.ts` / `en.ts`；源码里注释以外不许有中文（有静态检查）。
- **不碰**：`backend/.env`、`docs/specs/2026-10-27-commercialization-design-contract.md`。

## 实施裁定

以下几条都已在本机用 LangGraph 1.2.14 写原型验证过。

1. **中断与恢复**：
   - 工具里调用 `interrupt(card)` 时，`agent.stream(..., stream_mode=["messages", "updates"])` 的 updates 流会出一项 `{"__interrupt__": (Interrupt(value=card, id=...),)}`，然后这一轮结束。
   - 之后 `agent.get_state(cfg).interrupts` 是这些 `Interrupt`，`.next == ("tools",)`。
   - 恢复用 `agent.stream(Command(resume={interrupt_id: value}), cfg, ...)`。
   - 恢复时**工具从头重跑**：`interrupt()` 之前的代码会再执行一遍，第一次 `interrupt()` 直接返回 `value`。一个工具里可以按顺序调多次 `interrupt()`，各自对应一次恢复。
   - 同一次工具调用里先后几次中断，**中断编号相同**；每次用 `Command(resume={编号: 值})` 恢复，前面的回答会按顺序重放，已验证。所以重新出的卡和原来的卡 `id` 一样，前端按 `tool_call_id` 替换即可。
   - 项目的 `_tool` 装饰器设了 `handle_tool_error=True`，只吞 `ToolException`；中断照常冒泡。
2. **工具调用编号**：工具参数声明 `tool_call_id: Annotated[str, InjectedToolCallId]` 可以拿到本次调用的编号。它和 `config` 一样，不出现在给模型的参数说明里。
3. **卡以服务端存档为准**：恢复时，`resume` 接口从存档里取这张中断卡的原值，作为 `{"decision", "card"}` 传给工具，不收前端传来的卡。工具重跑时，用这张「用户看到的卡」和重算的预估比较，对不上就重新出卡（spec §7.1）。
4. **关掉并行工具调用**：`build_agent` 先调用 `model.bind_tools(ALL_TOOLS, parallel_tool_calls=False)` 再交给 `create_react_agent`。
   - 原因：同一步里两个工具各自中断时，恢复其中一个会让整个工具节点重跑，已执行的那个会再执行一次。
   - 已验证：`ChatAnthropic` 这样绑定后，`tool_choice` 带 `disable_parallel_tool_use: True`，`create_react_agent` 接受已绑定的模型。
   - `ScriptedChat` 和 `NullModel` 的 `bind_tools` 都返回自身，不受影响。
5. **发新消息时取消待确认的卡**：
   - 对每个中断，`agent.update_state(cfg, {"messages": [ToolMessage(已取消, tool_call_id=…, name=…, artifact=…)]}, as_node="tools")`。
   - 之后用新的 `HumanMessage` 正常开一轮，模型只被调一次，看到的是「取消结果 + 新问题」。已验证。
   - 取消不调模型、不记用量。
6. **操作工具不出折叠的工具行**：四个操作工具不发 `tool_start` / `tool_end`，历史里也不进 `tools`，只用卡片表示（spec §7.2）。
7. **生成分镜没有金额**：服务端没有转换费用的预估，卡上 `amount=null`、`currency="usd"`，前端写「按模型用量计费，无法预估」。仍然总要确认（用户定的「花钱要确认」）。
8. **出片要求已有会话**：助手不替用户选厂商和档位。没有会话时报错「还没有出片会话：先到出片那一步选好厂商与档位」，模型用 `goto` 带用户过去。
9. **合成金额为 0 不出卡**：配音都已缓存，或这个声音模式不配音时，直接执行，`outcome="done"`。
10. **任务卡不复用 `useFilm` / `useCompose`**：spec 原则里写了「复用 `useJob`、`useFilm`、`useCompose`」，但这两个钩子会取片段文件、建 blob URL，太重。任务卡改用轻量轮询（`getJob`、`getFilm`），状态判断写成纯函数，可单测。spec §7.3 已按此写。
11. **`render_keyframes` 不做**：服务端没有出图，spec §7 已删。

## 文件结构

**后端**
- 改 `backend/render/session.py`：新增 `run_quote(s, clip_ids)`（纯函数：挑段、计价、前提检查），`queue_run` 改用它。
- 改 `backend/server/app.py`：
  - 抽出 `_start_version`、`_film_quote`、`_film_run`、`_compose_quote`、`_compose_start`、`_export_check`，接口改调它们。
  - 导入时把它们填进 `assistant_actions.ops`。
  - 助手接口：抽出共用的流式响应 `_assistant_stream`；新增 `POST /novels/{nid}/assistant/resume`；发消息前取消待确认的卡。
- 新建 `backend/assistant/actions.py`：四个操作工具、`ops`、`ACTIONS`。
- 改 `backend/assistant/graph.py`：`ALL_TOOLS`、关并行、`pending`、`cancel_pending`。
- 改 `backend/assistant/events.py`：`stream` 接受文字或 `Command`；`confirm` / `action` 事件；历史里的 `cards`。
- 改 `backend/prompts/assistant.md`：能发起四个操作的规则。
- 新测试：`backend/tests/server/test_assistant_ops.py`、`backend/tests/assistant/test_actions.py`。
- 改测试：`backend/tests/assistant/test_graph.py`、`backend/tests/server/test_assistant.py`。

**前端**
- 改 `frontend/src/types.ts`：`AssistantAction`、`AssistantTask`、`AssistantCardInfo`、`AssistantCard`，`AssistantMsg.cards`，两种新事件。
- 改 `frontend/src/api.ts`：抽出 `streamSse`，新增 `resumeAssistant`。
- 改 `frontend/src/lib/assistantBridge.ts`：`notifyTask`、`onTask`。
- 新建 `frontend/src/lib/assistantTask.ts`：任务进度的纯函数与轮询钩子 `useTaskView`。
- 改 `frontend/src/lib/assistantSession.ts`：共用的 `run`、卡片事件、`decideAssistant`、发新消息时把待确认的卡标成已取消。
- 新建 `frontend/src/components/assistant/ActionCard.tsx`、`frontend/src/components/assistant/TaskCard.tsx`。
- 改 `frontend/src/components/assistant/AssistantPanel.tsx`：渲染卡片。
- 改 `frontend/src/styles/workspace.css`：卡片样式。
- 改 `frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`。
- 改 `frontend/src/App.tsx`、`frontend/src/components/TimelineCanvas.tsx`：订阅 `onTask`。
- 改测试：`frontend/tests/assistant.test.tsx`、`frontend/tests/film.test.tsx`。

---

### Task 1: 后端执行函数（接口与助手共用）

**Files:**
- Modify: `backend/render/session.py`（`queue_run` 附近，约 294–328 行）
- Modify: `backend/server/app.py`（`versions_create` 约 577–605 行；出片 `render_clip_run` / `render_run_all` 约 953–975 行；合成 `render_export` / `render_compose_post` 约 1120–1198 行）
- Create: `backend/tests/server/test_assistant_ops.py`

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/server/test_assistant_ops.py`：

```python
#!/usr/bin/env python3
"""接口与助手共用的执行函数：出片预估（要会话、不改段状态、点名的段、在跑的段 409）、排队出片（金额不对 409）、
合成预估（缺音色 422、金额与预览一致、合成中 409）、导出检查（没成片 409）、转换本章（没原文 422、任务进表）。
假视频厂商 + 假 TTS，不联网、不花钱。用法: python3 tests/server/test_assistant_ops.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_TTS_PROVIDER"] = "fake"
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"

from fastapi import HTTPException  # noqa: E402
from render import providers, session as render_session  # noqa: E402
from render.providers.fake import FakeTts, FakeVideo  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402

providers.register("fake", lambda: FakeVideo())
providers.register_tts("fake", lambda: FakeTts())
DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))


def status_of(fn, *args) -> tuple:
    try:
        fn(*args)
    except HTTPException as e:
        d = e.detail
        return e.status_code, d.get("message") if isinstance(d, dict) else str(d)
    raise AssertionError("应抛 HTTPException")


def main() -> int:
    user = auth.register("alice", "secret1")
    uid = user["id"]
    nid = novels.create_novel(uid, "药")["id"]
    cid = novels.create_chapter(uid, nid, "第一章", text="原文")["id"]
    empty = novels.create_chapter(uid, nid, "第二章", text="")["id"]
    novels.create_version(uid, nid, cid, "v1", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v1", "succeeded", result=copy.deepcopy(DOC))
    root = novels.render_dir(uid, nid, cid, "v1")

    # 1. 出片预估：没会话 404；建会话后金额 = 剩余各段合计；不改段状态；点名的段只算这几段
    code, msg = status_of(app_mod._film_quote, user, nid, cid, "v1", None)
    assert code == 404 and "出片会话" in msg, msg
    s = app_mod.render_session_post(nid, cid, "v1", None, user)
    q = app_mod._film_quote(user, nid, cid, "v1", None)
    planned = [c for c in s["clips"] if c["state"] == "planned"]
    assert q["clips"] == [c["id"] for c in planned]
    assert q["amount"] == round(sum(c["estimate_cny"] for c in planned), 2)
    assert all(c["state"] == "planned" for c in render_session.load(root)["clips"]), "预估不改段状态"
    first = planned[0]["id"]
    one = app_mod._film_quote(user, nid, cid, "v1", [first])
    assert one["clips"] == [first] and one["amount"] == planned[0]["estimate_cny"]
    print("1. 出片预估 ✓")

    # 2. 排队出片：金额对不上 409；对上了排队；在跑的段再预估 409；剩余预估不含已排队的
    code, _ = status_of(app_mod._film_run, user, nid, cid, "v1", [first], one["amount"] + 1)
    assert code == 409
    v = app_mod._film_run(user, nid, cid, "v1", [first], one["amount"])
    assert next(c for c in v["clips"] if c["id"] == first)["state"] == "queued"
    code, msg = status_of(app_mod._film_quote, user, nid, cid, "v1", [first])
    assert code == 409 and "排队" in msg, msg
    assert first not in app_mod._film_quote(user, nid, cid, "v1", None)["clips"]
    print("2. 排队出片 ✓")

    # 3. 合成预估：缺音色 422；选好音色后金额与合成预览一致；合成中 409
    code, msg = status_of(app_mod._compose_quote, user, nid, cid, "v1", True)
    assert code == 422 and "音色" in msg, msg
    voices = app_mod.render_voices(nid, cid, "v1", user)
    app_mod.render_voices_put(nid, cid, "v1", app_mod.RenderVoicesBody(
        voices={k: "fake-male" for k in voices["missing"]}), user)
    p = app_mod.render_compose_get(nid, cid, "v1", True, user)
    q = app_mod._compose_quote(user, nid, cid, "v1", True)
    assert q == {"amount": p["tts_cny"], "chars": p["tts_chars"]}, q
    with render_session.mutate(root) as sess:
        sess["final"] = {"state": "running", "files": [], "report": None, "error": None, "detail": None}
    code, msg = status_of(app_mod._compose_quote, user, nid, cid, "v1", True)
    assert code == 409 and "合成" in msg, msg
    with render_session.mutate(root) as sess:
        sess["final"] = None
    print("3. 合成预估 ✓")

    # 4. 导出检查：还没有成片 409
    code, msg = status_of(app_mod._export_check, user, nid, cid, "v1")
    assert code == 409 and "成片" in msg, msg
    print("4. 导出检查 ✓")

    # 5. 转换本章：没原文 422；有原文时建版本、任务进表（后台转换换成空函数，不调模型）
    real = app_mod._run_version_job
    app_mod._run_version_job = lambda *a, **k: None
    try:
        code, _ = status_of(app_mod._start_version, user, nid, empty, {}, False)
        assert code == 422
        r = app_mod._start_version(user, nid, cid, {}, False)
        job = app_mod._jobs[r["job_id"]]
        assert job["novel_id"] == nid and job["chapter_id"] == cid and r["version_id"] == r["job_id"]
        assert novels.get_version(uid, nid, cid, r["version_id"])["status"] == "queued"
    finally:
        app_mod._run_version_job = real
    print("5. 转换本章 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_assistant_ops.py`
Expected: FAIL，`AttributeError: module 'server.app' has no attribute '_film_quote'`

- [ ] **Step 3: `render/session.py` 抽出 `run_quote`**

把 `queue_run` 里「挑段 + 计价 + 前提检查」抽成纯函数。`queue_run` 改成调用它，行为不变：

```python
def run_quote(s: dict, clip_ids: Optional[list] = None) -> tuple:
    """要出的段与合计预估（元），不改会话。queue_run 与助手的确认卡共用这一套挑选、计价与前提检查。"""
    if (s.get("final") or {}).get("state") in COMPOSE_BUSY:
        raise Conflict("正在合成，等它结束再出片")
    if clip_ids is None:
        targets = _remaining(s)
    else:
        targets = [_clip(s, cid) for cid in dict.fromkeys(clip_ids)]
        for c in targets:
            if c["state"] in IN_FLIGHT:
                raise Conflict(f"{c['id']} 已在排队或生成中")
    if not targets:
        raise SessionError("没有要出的段")
    return targets, round(sum(c["estimate_cny"] for c in targets), 2)


def queue_run(root, clip_ids: Optional[list] = None, expected_cny: Optional[float] = None) -> dict:
    """排队出片。clip_ids=None 为批量出剩余各段（planned / failed，不含待核对的段），必须带
    确认金额；单段超过确认线也要带。金额与服务端重算不一致 → Conflict（附重算金额）。
    单段点名重做视为用户已看过「请到控制台核对」，清掉待核对标记。"""
    with mutate(root) as s:
        targets, total = run_quote(s, clip_ids)
        if (clip_ids is None or total > s["confirm_over_cny"]) and expected_cny is None:
            raise Conflict(f"本次约 ¥{total:.2f}，请确认金额后再出片", total)
        if expected_cny is not None and abs(expected_cny - total) > 0.005:
            raise Conflict(f"预估金额已变为 ¥{total:.2f}，请重新确认", total)
        reserved = sum(c["estimate_cny"] for c in s["clips"] if c["state"] in IN_FLIGHT)
        if s["spent_cny"] + reserved + total > s["budget_cny"] + 1e-9:
            raise BudgetExceeded(f"超出单章上限 ¥{s['budget_cny']:g}：已花 ¥{s['spent_cny']:.2f}，"
                                 f"在跑预留 ¥{reserved:.2f}，本次约 ¥{total:.2f}")
        for c in targets:
            c["state"], c["error"], c["queued_at"] = "queued", None, _now()
            c["uncertain"] = False
        return s
```

- [ ] **Step 4: `app.py` 抽出转换本章**

把 `versions_create` 的函数体原样移进 `_start_version`，接口只调用它：

```python
def _start_version(user: dict, nid: str, cid: str, overrides: dict, strict: bool) -> dict:
    """转换本章 → 新版本（接口与助手共用）。返回 job_id（即版本 id），进度/分批预览照旧走 /jobs。"""
    novel = _novel_call(novels.get_novel, user["id"], nid)
    chapter = _novel_call(novels.get_chapter, user["id"], nid, cid)
    text = chapter.get("text") or ""
    if not text.strip():
        raise HTTPException(422, "本章还没有原文")
    raw = auth.get_user_raw(user["id"])
    cap = raw.get("monthly_cap_usd") if raw else None
    if cap is not None and usage.month_spent(user["id"], pricing.load()) >= cap:
        raise HTTPException(429, "本月用量已达上限，请联系管理员")
    merged = {**_clean_params(novel.get("params")), **_clean_params(overrides)}
    params = ConvertParams(**{**merged, "work_title": novel["title"],
                              "chapter": chapter["title"]})
    job_id = uuid.uuid4().hex[:12]
    _novel_call(novels.create_version, user["id"], nid, cid, job_id,
                {**merged, "strict": strict}, text)
    job = {"id": job_id, "user_id": user["id"], "status": "queued", "log": [],
           "result": None, "quality_report": None, "error": None, "persisted": True,
           "created_at": store.now_iso(), "work_title": novel["title"],
           "chapter": chapter["title"], "chars": len(text), "progress": {},
           "partial": None, "novel_id": nid, "chapter_id": cid, "version_id": job_id}
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_run_version_job, job, user["id"], nid, cid, text, params, strict)
    return {"job_id": job_id, "version_id": job_id, "status_url": f"/jobs/{job_id}"}


@app.post("/novels/{nid}/chapters/{cid}/versions")
def versions_create(nid: str, cid: str, req: VersionRequest,
                    user: dict = Depends(novel_user)):
    """转换本章 → 新版本。返回 job_id（即版本 id），进度/分批预览照旧走 /jobs。"""
    return _start_version(user, nid, cid, req.overrides, req.strict)
```

`_executor.submit(_run_version_job, …)` 在调用时才查全局名，所以测试把 `app_mod._run_version_job` 换掉就能生效。

- [ ] **Step 5: `app.py` 抽出出片**

在 `render_clip_run` 之前加两个函数，两个出片接口改调 `_film_run`：

```python
def _film_quote(user: dict, nid: str, cid: str, vid: str, clip_ids: Optional[list]) -> dict:
    """出片确认卡的预估：要出哪几段、合计多少元（不改段状态）。厂商与档位由用户在出片那一步选，所以要求已有会话。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    if render_session.load(root) is None:
        raise HTTPException(404, "还没有出片会话：先到出片那一步选好厂商与档位")
    s = _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                     allow_in_flight=True, style=_style_for(owner["user_id"], owner["nid"]))
    targets, total = _render_call(render_session.run_quote, s, clip_ids)
    return {"amount": total, "clips": [c["id"] for c in targets]}


def _film_run(user: dict, nid: str, cid: str, vid: str, clip_ids: Optional[list],
              expected_cny: Optional[float]) -> dict:
    """排队出片（接口与助手共用）：按已保存的分镜刷新会话再排队；确认金额由 queue_run 校验。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid)
    _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                 allow_in_flight=True, style=_style_for(owner["user_id"], owner["nid"]))
    s = _render_call(render_session.queue_run, root, clip_ids, expected_cny)
    _render_runner.watch(root)
    return _render_call(render_session.view, s)


@app.post(_R + "/clips/{clip_id}/run")
def render_clip_run(nid: str, cid: str, vid: str, clip_id: str,
                    body: Optional[RenderRunBody] = None, user: dict = Depends(novel_user)):
    """出这一段（试段或重做）。超过确认线时要带 expected_cny。"""
    return _film_run(user, nid, cid, vid, [clip_id], body.expected_cny if body else None)


@app.post(_R + "/run")
def render_run_all(nid: str, cid: str, vid: str, body: RenderRunBody,
                   user: dict = Depends(novel_user)):
    """批量出剩余各段：必须带用户确认的预估金额，服务端重算不一致 409。"""
    return _film_run(user, nid, cid, vid, None, body.expected_cny)
```

- [ ] **Step 6: `app.py` 抽出合成与导出检查**

在 `_compose_preview` 之后、`render_compose_get` 之前加：

```python
_NO_FFMPEG = ("服务器没有装 ffmpeg：macOS 执行 brew install ffmpeg，"
              "Ubuntu / Debian 执行 apt install ffmpeg，装好后重启后端")
_EXPORT_REASONS = {"none": "还没有合成好的成片", "stale": "成片已过期，请先重新合成",
                   "no_timeline": "这份成片是旧版合成的，重新合成一次即可导出（会复用已有配音与规整结果，不花钱）",
                   "busy": "正在合成，完成后再导出"}


def _compose_blockers(p: dict, draft: bool) -> None:
    """合成前提：有 ffmpeg、说话人都有音色、非草稿时每段都有视频。"""
    if render_mix.tools() is None:
        raise HTTPException(422, _NO_FFMPEG)
    if p["missing_voices"]:
        raise HTTPException(422, "还有说话人没选音色：" + "、".join(k or "（未标说话人）" for k in p["missing_voices"]))
    if p["no_video"] and not draft:
        raise HTTPException(422, f"{len(p['no_video'])} 段还没有可用的视频；打开「草稿合成」可用关键帧补位")


def _compose_quote(user: dict, nid: str, cid: str, vid: str, draft: bool) -> dict:
    """合成确认卡的预估：未缓存配音的字数与金额（元）。过验证门与合成前提；合成中 409。"""
    _render_ctx(user, nid, cid, vid)          # 过验证门
    _root, _doc, _kfs, _s, p = _compose_preview(user, nid, cid, vid, draft)
    if (p.get("final") or {}).get("state") in render_session.COMPOSE_BUSY:
        raise HTTPException(409, "正在合成，等它结束再合成")
    _compose_blockers(p, draft)
    return {"amount": p["tts_cny"], "chars": p["tts_chars"]}


def _compose_start(user: dict, nid: str, cid: str, vid: str, draft: bool,
                   expected_cny: Optional[float]) -> dict:
    """合成整章（后台线程，接口与助手共用）。配音金额大于 0 时必须带确认金额。"""
    _render_ctx(user, nid, cid, vid)          # 过验证门
    root, doc, kfs, s, p = _compose_preview(user, nid, cid, vid, draft)
    _compose_blockers(p, draft)
    if p["tts_cny"] > 0 and (expected_cny is None or abs(expected_cny - p["tts_cny"]) > 1e-6):
        raise HTTPException(409, detail={"message": f"本次配音约 ¥{p['tts_cny']:.2f}，请确认金额后再合成",
                                         "expected_cny": p["tts_cny"]})
    s = _render_call(render_session.begin_compose, root, fingerprint=p["fingerprint"],
                     tts_cny=p["tts_cny"], draft=draft, voices=s.get("voices") or {})
    t = threading.Thread(target=_compose_worker, args=(root, doc, s, kfs, draft, render_mix.tools()),
                         name=f"compose-{vid}", daemon=True)
    _compose_threads[str(root)] = t
    t.start()
    return _render_call(render_session.view, s)


def _export_check(user: dict, nid: str, cid: str, vid: str) -> tuple:
    """能否导出剪辑工程：成片已合成、没过期、有 ffmpeg。返回 (会话目录, ffmpeg 工具)。"""
    root, _doc, _kfs, _s, p = _compose_preview(user, nid, cid, vid, True)
    reason = p.get("export_reason")
    if reason:
        raise HTTPException(409, _EXPORT_REASONS[reason])
    tools = render_mix.tools()
    if not tools:
        raise HTTPException(503, "服务器没有安装 ffmpeg，无法导出")
    return root, tools
```

`render_export` 的开头改成用 `_export_check`，后面不变：

```python
@app.get(_R + "/export.zip")
def render_export(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    """导出剪辑工程（FCPXML + 素材 + 字幕 + 说明）。只读本地文件、跑本地 ffmpeg，不花钱。"""
    root, tools = _export_check(user, nid, cid, vid)
    novel = _novel_call(novels.get_novel, user["id"], nid)
    # ……以下保持原样（chapter / title / export / Content-Disposition）
```

`render_compose_post` 改成：

```python
@app.post(_R + "/compose")
def render_compose_post(nid: str, cid: str, vid: str, body: RenderComposeBody,
                        user: dict = Depends(novel_user)):
    """合成整章（后台线程）。过验证门；配音金额（未缓存的字数 × 单价）大于 0 时必须带确认金额。"""
    return _compose_start(user, nid, cid, vid, body.draft, body.expected_cny)
```

注意：
- 原来 `render_compose_post` 里没装 ffmpeg 时的 422 文字，现在来自 `_NO_FFMPEG`，内容不变。
- `test_compose.py` 断言了这些文字，跑一遍确认。

- [ ] **Step 7: 跑测试，确认通过**

Run（在 `backend/` 下）：
```bash
for t in tests/server/test_assistant_ops.py tests/server/test_render.py tests/server/test_compose.py tests/server/test_novels.py tests/server/test_summary.py tests/server/test_usage.py tests/assistant/test_store.py tests/assistant/test_tools.py tests/assistant/test_graph.py tests/server/test_assistant.py; do .venv/bin/python $t 2>&1 | tail -1; done
```
Expected: 每行都是 `ALL PASS`。

- [ ] **Step 8: 提交**

```bash
git add backend/render/session.py backend/server/app.py backend/tests/server/test_assistant_ops.py
git commit -m "出片、合成、导出检查与转换本章抽成内部函数，接口与助手共用：出片预估与排队同一套挑段计价（run_quote），合成预估带前提检查与合成中 409，导出检查返回会话目录与 ffmpeg"
```

---

### Task 2: 操作工具（确认卡与重新出卡）

**Files:**
- Create: `backend/assistant/actions.py`
- Create: `backend/tests/assistant/test_actions.py`

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/assistant/test_actions.py`：

```python
#!/usr/bin/env python3
"""助手的操作工具：出卡字段、确认后执行、取消不执行、金额变了重新出卡（以服务端给的卡为准）、连变 3 次不执行、
合成金额为 0 不出卡、生成分镜（没原文报错、无金额、本章已有采用版）、导出直接放下载按钮、执行函数的 HTTP 报错转述、
工具参数说明里没有 config 与 tool_call_id。执行函数用替身（ops），不碰出片与模型。
用法: python3 tests/assistant/test_actions.py
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

from fastapi import HTTPException  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402
from langgraph.types import Command  # noqa: E402
from fake_model import ScriptedChat, call  # noqa: E402
from assistant import actions as A  # noqa: E402
from server import auth, novels  # noqa: E402

DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))
calls: list = []
film = {"amount": 1.5, "clips": ["C1", "C2"]}
comp = {"amount": 0.0, "chars": 0}


def fake_ops():
    def film_quote(user, nid, cid, vid, ids):
        if callable(film.get("next")):
            film["amount"] = film["next"]()
        return {"amount": film["amount"], "clips": list(film["clips"])}

    A.ops.update(
        start_version=lambda user, nid, cid, ov, strict: calls.append(("start", cid)) or {"job_id": "j1", "version_id": "j1"},
        film_quote=film_quote,
        film_run=lambda user, nid, cid, vid, ids, exp: calls.append(("film", vid, ids, exp)) or {},
        compose_quote=lambda user, nid, cid, vid, draft: dict(comp),
        compose_start=lambda user, nid, cid, vid, draft, exp: calls.append(("compose", draft, exp)) or {},
        export_check=lambda user, nid, cid, vid: calls.append(("export", vid)) or (None, None),
    )


def agent_for(script: list):
    return create_react_agent(ScriptedChat(script=script), A.TOOLS, checkpointer=InMemorySaver())


def run(agent, cfg, payload) -> list:
    """跑到停（结束或中断），返回这次出的中断。"""
    out = []
    for chunk in agent.stream(payload, cfg, stream_mode="updates"):
        out += list(chunk.get("__interrupt__") or [])
    return out


def answer(it, decision="approve"):
    """模拟 resume 接口：卡取自存档（中断的原值），不是前端传的。"""
    return Command(resume={it.id: {"decision": decision, "card": it.value}})


def result(agent, cfg) -> ToolMessage:
    return [m for m in agent.get_state(cfg).values["messages"] if isinstance(m, ToolMessage)][-1]


def main() -> int:
    uid = auth.register("alice", "secret1")["id"]
    nid = novels.create_novel(uid, "药")["id"]
    c1 = novels.create_chapter(uid, nid, "第一章 茶馆", text="原文")["id"]
    c2 = novels.create_chapter(uid, nid, "第二章 刑场", text="")["id"]
    novels.create_version(uid, nid, c1, "v1", {}, "原文")
    novels.update_version_state(uid, nid, c1, "v1", "succeeded", result=copy.deepcopy(DOC))
    novels.adopt_version(uid, nid, c1, "v1")
    fake_ops()
    n = [0]

    def cfg():
        n[0] += 1
        return {"configurable": {"thread_id": f"t{n[0]}", "user_id": uid, "novel_id": nid,
                                 "where": {"chapter_id": c1}}}

    # 1. 出片：出卡字段；确认前不执行；确认后带卡上金额执行，结果带任务
    C = cfg()
    ag = agent_for([call("film_run", {}, "f1"), AIMessage("开始了")])
    its = run(ag, C, {"messages": [HumanMessage("出片")]})
    assert len(its) == 1 and calls == []
    card = its[0].value
    assert card == {"tool_call_id": "f1", "action": "film_run", "chapter_id": c1, "chapter": "第一章 茶馆",
                    "version_id": "v1", "amount": 1.5, "currency": "cny", "detail": {"clips": 2}}, card
    assert run(ag, C, answer(its[0])) == []
    assert calls == [("film", "v1", None, 1.5)], calls
    m = result(ag, C)
    assert m.status != "error" and m.artifact == {"card": card, "outcome": "approved",
                                                  "task": {"kind": "film", "chapter_id": c1, "version_id": "v1"}}
    print("1. 出片确认后执行 ✓")

    # 2. 取消：不执行，结果说明取消
    calls.clear()
    C = cfg()
    ag = agent_for([call("film_run", {"clip_ids": ["C1"]}, "f2"), AIMessage("好的")])
    its = run(ag, C, {"messages": [HumanMessage("出 C1")]})
    run(ag, C, answer(its[0], "reject"))
    m = result(ag, C)
    assert calls == [] and m.artifact["outcome"] == "rejected" and "取消" in m.content
    print("2. 取消不执行 ✓")

    # 3. 金额变了：重新出卡（带原金额），再确认才按新金额执行
    C = cfg()
    ag = agent_for([call("film_run", {}, "f3"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("出片")]})
    film["amount"] = 2.0
    its2 = run(ag, C, answer(its[0]))
    assert calls == [] and len(its2) == 1
    assert its2[0].value["amount"] == 2.0 and its2[0].value["changed"] is True and its2[0].value["previous_amount"] == 1.5
    run(ag, C, answer(its2[0]))
    assert calls == [("film", "v1", None, 2.0)], calls
    print("3. 金额变了重新出卡 ✓")

    # 4. 连变 3 次：不执行，工具报错
    calls.clear()
    seq = iter(range(10, 100))
    film["next"] = lambda: float(next(seq))
    C = cfg()
    ag = agent_for([call("film_run", {}, "f4"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("出片")]})
    shown = 1
    while its:
        its = run(ag, C, answer(its[0]))
        shown += bool(its)
    film.pop("next")
    film["amount"] = 1.5
    m = result(ag, C)
    assert shown == 3 and calls == [] and m.status == "error" and "一直在变" in m.content, (shown, m.content)
    print("4. 连变 3 次不执行 ✓")

    # 5. 合成：金额为 0 不出卡直接执行；大于 0 出卡，确认后带金额
    C = cfg()
    ag = agent_for([call("compose", {}, "m1"), AIMessage("好")])
    assert run(ag, C, {"messages": [HumanMessage("合成")]}) == []
    m = result(ag, C)
    assert calls == [("compose", True, None)] and m.artifact["outcome"] == "done"
    assert m.artifact["task"] == {"kind": "compose", "chapter_id": c1, "version_id": "v1"}
    calls.clear()
    comp.update(amount=0.3, chars=120)
    C = cfg()
    ag = agent_for([call("compose", {"draft": False}, "m2"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("合成")]})
    assert its[0].value["detail"] == {"chars": 120, "draft": False} and its[0].value["amount"] == 0.3
    run(ag, C, answer(its[0]))
    assert calls == [("compose", False, 0.3)], calls
    print("5. 合成 ✓")

    # 6. 生成分镜：没原文报错不出卡；有原文出卡（无金额、已有采用版），确认后开任务
    calls.clear()
    C = cfg()
    ag = agent_for([call("generate_storyboard", {"chapter": c2}, "g1"), AIMessage("好")])
    assert run(ag, C, {"messages": [HumanMessage("生成第二章")]}) == []
    m = result(ag, C)
    assert m.status == "error" and "原文" in m.content and calls == []
    C = cfg()
    ag = agent_for([call("generate_storyboard", {}, "g2"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("生成")]})
    v = its[0].value
    assert v["amount"] is None and v["currency"] == "usd" and v["version_id"] is None
    assert v["detail"] == {"chars": 2, "archived": True}, v
    run(ag, C, answer(its[0]))
    m = result(ag, C)
    assert calls == [("start", c1)]
    assert m.artifact["task"] == {"kind": "job", "chapter_id": c1, "version_id": "j1", "job_id": "j1"}
    print("6. 生成分镜 ✓")

    # 7. 导出：不出卡，检查后放下载按钮
    calls.clear()
    C = cfg()
    ag = agent_for([call("export_fcpxml", {}, "e1"), AIMessage("好")])
    assert run(ag, C, {"messages": [HumanMessage("导出")]}) == []
    m = result(ag, C)
    assert calls == [("export", "v1")] and m.artifact["outcome"] == "done"
    assert m.artifact["task"] == {"kind": "export", "chapter_id": c1, "version_id": "v1"}
    assert m.artifact["card"]["amount"] is None and m.artifact["card"]["currency"] is None
    print("7. 导出 ✓")

    # 8. 执行函数的 HTTP 报错转成工具报错（带说明，不中断对话）
    def boom(*a):
        raise HTTPException(409, detail={"message": "预估金额已变为 ¥9.00，请重新确认", "expected_cny": 9.0})
    A.ops["film_run"] = boom
    C = cfg()
    ag = agent_for([call("film_run", {}, "f5"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("出片")]})
    run(ag, C, answer(its[0]))
    m = result(ag, C)
    assert m.status == "error" and "¥9.00" in m.content, m.content
    fake_ops()
    print("8. 报错转述 ✓")

    # 9. 参数说明里没有 config、tool_call_id
    for t in A.TOOLS:
        props = t.tool_call_schema.model_json_schema().get("properties", {})
        assert "config" not in props and "tool_call_id" not in props, (t.name, props)
    assert A.ACTIONS == ("generate_storyboard", "film_run", "compose", "export_fcpxml")
    print("9. 参数说明 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd backend && .venv/bin/python tests/assistant/test_actions.py`
Expected: FAIL，`ImportError: cannot import name 'actions' from 'assistant'`

- [ ] **Step 3: 实现 `assistant/actions.py`**

```python
"""助手的操作工具（spec §7）：生成分镜、出片、配音合成先出确认卡，用户点确认才执行；导出不花钱，直接放下载按钮。

确认：服务端先算预估，interrupt(卡) 暂停这一轮；用户点按钮后接口用 Command(resume={中断编号: {decision, card}})
接着跑，card 是接口从存档里取的那张（不信前端）。恢复时工具从头重跑：重算预估，与用户确认的卡对不上就带原金额
重新出卡，连变 MAX_RECARD 次不执行。
执行函数在 server/app.py（与接口同一份：鉴权、验证门、上限、确认金额都一样），由 app 在导入时填进 ops——
本包不能反过来导入 app（循环导入）。
"""
from typing import Annotated, Callable, Optional

from fastapi import HTTPException
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, ToolException
from langgraph.types import interrupt

from assistant.tools import LIVE, _chapters, _ctx, _tool, resolve_chapter
from server import summary

# 名字 → app 里的执行函数：start_version / film_quote / film_run / compose_quote / compose_start / export_check
ops: dict = {}
MAX_RECARD = 3


def _op(name: str, *args):
    """调 app 里的执行函数；HTTPException 的说明变成给模型看的工具报错。"""
    try:
        return ops[name](*args)
    except HTTPException as e:
        d = e.detail
        raise ToolException(d.get("message", str(d)) if isinstance(d, dict) else str(d))


def _where(config: RunnableConfig, chapter: Optional[str]) -> tuple:
    uid, nid, where = _ctx(config)
    return uid, nid, resolve_chapter(_chapters(uid, nid), chapter, where.get("chapter_id"))


def _version(ch: dict) -> str:
    vid = summary._pick_version(ch)
    if not vid:
        raise ToolException(f"{ch['title']} 还没有可用的分镜版本")
    return vid


def _card(tool_call_id: str, action: str, ch: dict, vid: Optional[str], quote: dict) -> dict:
    return {"tool_call_id": tool_call_id, "action": action, "chapter_id": ch["id"], "chapter": ch["title"],
            "version_id": vid, **quote}


def _same(a: dict, b: dict) -> bool:
    """预估与卡一致：金额（都没有，或相差不到 1e-6 元）与要点都相同。"""
    if (a["amount"] is None) != (b["amount"] is None):
        return False
    if a["amount"] is not None and abs(a["amount"] - b["amount"]) > 1e-6:
        return False
    return a["detail"] == b["detail"]


def _ask(card: dict, quote: Callable[[], dict]) -> tuple:
    """出卡等用户确认 → (是否确认, 用户最后确认或取消的那张卡)。确认后重算预估，对不上就带原金额重新出卡。"""
    for _ in range(MAX_RECARD):
        answer = interrupt(card) or {}
        seen = answer.get("card") or card
        if answer.get("decision") != "approve":
            return False, seen
        fresh = quote()
        if _same(fresh, seen):
            return True, seen
        card = {**seen, **fresh, "changed": True, "previous_amount": seen["amount"]}
    raise ToolException("预估一直在变，先不执行；稍后再让我试一次")


def _result(text: str, card: dict, outcome: str, task: Optional[dict] = None) -> tuple:
    return text, {"card": card, "outcome": outcome, "task": task}


@_tool(response_format="content_and_artifact")
def generate_storyboard(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
                        chapter: Optional[str] = None):
    """把一章原文生成分镜（新版本，分钟级任务）。会花模型费用：先给用户一张确认卡，用户点确认才开始。chapter 可写编号、「第三章」或标题片段，缺省为当前章。"""
    uid, nid, ch = _where(config, chapter)

    def quote() -> dict:
        cur = resolve_chapter(_chapters(uid, nid), ch["id"], None)
        if not cur.get("chars"):
            raise ToolException(f"{cur['title']} 还没有原文")
        if cur.get("latest_status") in LIVE:
            raise ToolException(f"{cur['title']} 正在生成分镜，等它跑完再说")
        return {"amount": None, "currency": "usd",
                "detail": {"chars": cur["chars"], "archived": bool(cur.get("adopted_version"))}}

    ok, card = _ask(_card(tool_call_id, "generate_storyboard", ch, None, quote()), quote)
    if not ok:
        return _result("用户取消了，没有生成", card, "rejected")
    r = _op("start_version", {"id": uid}, nid, ch["id"], {}, False)
    task = {"kind": "job", "chapter_id": ch["id"], "version_id": r["version_id"], "job_id": r["job_id"]}
    return _result(f"已开始生成「{ch['title']}」的分镜，进度在任务卡上", card, "approved", task)


@_tool(response_format="content_and_artifact")
def film_run(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
             chapter: Optional[str] = None, clip_ids: Optional[list[str]] = None):
    """出片（视频生成）。clip_ids 缺省为这一章所有没出或失败的段，也可以点名几段重做。会花钱：先给用户一张带金额（元）的确认卡，用户点确认才开始。要求用户已在出片那一步选好厂商与档位。chapter 缺省为当前章。"""
    uid, nid, ch = _where(config, chapter)
    vid = _version(ch)
    user, ids = {"id": uid}, (clip_ids or None)

    def quote() -> dict:
        q = _op("film_quote", user, nid, ch["id"], vid, ids)
        return {"amount": q["amount"], "currency": "cny", "detail": {"clips": len(q["clips"])}}

    ok, card = _ask(_card(tool_call_id, "film_run", ch, vid, quote()), quote)
    if not ok:
        return _result("用户取消了，没有出片", card, "rejected")
    _op("film_run", user, nid, ch["id"], vid, ids, card["amount"])
    return _result(f"已开始出「{ch['title']}」的 {card['detail']['clips']} 段，进度在任务卡上", card, "approved",
                   {"kind": "film", "chapter_id": ch["id"], "version_id": vid})


@_tool(response_format="content_and_artifact")
def compose(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
            chapter: Optional[str] = None, draft: bool = True):
    """配音并合成整章成片。draft=true（默认）时还没出视频的段用关键帧补位。配音要花钱时先给用户一张带金额（元）的确认卡；不花钱（配音都已缓存或不需要配音）就直接开始。chapter 缺省为当前章。"""
    uid, nid, ch = _where(config, chapter)
    vid = _version(ch)
    user = {"id": uid}

    def quote() -> dict:
        q = _op("compose_quote", user, nid, ch["id"], vid, draft)
        return {"amount": q["amount"], "currency": "cny", "detail": {"chars": q["chars"], "draft": draft}}

    card = _card(tool_call_id, "compose", ch, vid, quote())
    outcome = "done"
    if card["amount"] > 0:
        ok, card = _ask(card, quote)
        if not ok:
            return _result("用户取消了，没有合成", card, "rejected")
        outcome = "approved"
    _op("compose_start", user, nid, ch["id"], vid, draft, card["amount"] if card["amount"] > 0 else None)
    return _result(f"已开始合成「{ch['title']}」，进度在任务卡上", card, outcome,
                   {"kind": "compose", "chapter_id": ch["id"], "version_id": vid})


@_tool(response_format="content_and_artifact")
def export_fcpxml(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
                  chapter: Optional[str] = None):
    """导出剪辑工程（FCPXML 工程包，给达芬奇 / Final Cut 用）。不花钱：检查能导出后在回答下方放一个下载按钮。要求成片已合成且没过期。chapter 缺省为当前章。"""
    uid, nid, ch = _where(config, chapter)
    vid = _version(ch)
    _op("export_check", {"id": uid}, nid, ch["id"], vid)
    card = _card(tool_call_id, "export_fcpxml", ch, vid, {"amount": None, "currency": None, "detail": {}})
    return _result("已在回答下方放了「下载剪辑工程」按钮", card, "done",
                   {"kind": "export", "chapter_id": ch["id"], "version_id": vid})


TOOLS = [generate_storyboard, film_run, compose, export_fcpxml]
ACTIONS = tuple(t.name for t in TOOLS)
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd backend && .venv/bin/python tests/assistant/test_actions.py`
Expected: 9 行 ✓，最后 `ALL PASS`。然后跑全局约束里的全部后端脚本。

- [ ] **Step 5: 提交**

```bash
git add backend/assistant/actions.py backend/tests/assistant/test_actions.py
git commit -m "助手操作工具：生成分镜、出片、配音合成先出确认卡（interrupt 暂停），确认后按卡上金额执行，金额或要点变了带原金额重新出卡、连变 3 次不执行；合成配音不花钱直接开始；导出检查后放下载按钮；执行函数由 app 注入"
```

---

### Task 3: 智能体与事件（关并行、取消待确认的卡、confirm / action 事件、历史里的卡）

**Files:**
- Modify: `backend/assistant/graph.py`
- Modify: `backend/assistant/events.py`
- Modify: `backend/prompts/assistant.md`
- Test: `backend/tests/assistant/test_graph.py`

- [ ] **Step 1: 写失败的测试**

`test_graph.py` 里已有断言整条历史等于某个字典的地方（例如第 6 步的 `hist[3] == {"role": "assistant", "text": "好的。", "tools": [], "goto": []}`），每条助手消息都多了 `"cards": []`。用 `grep -n '"goto": \[\]}' tests/assistant/test_graph.py tests/server/test_assistant.py` 找出来，补上 `"cards": []`。

文件开头的导入改成：

```python
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402
from fake_model import ScriptedChat, call  # noqa: E402
from assistant import actions, events, graph, store  # noqa: E402
from server import auth, novels  # noqa: E402
```

在 `main()` 末尾、`print("\nALL PASS")` 之前追加：

```python
    # 11. 关掉并行工具调用（操作工具会中断，并行时恢复一个会让另一个重跑）
    class Rec(ScriptedChat):
        bound: dict = {}

        def bind_tools(self, tools, **kwargs):
            self.bound.update(kwargs)
            return self
    r = Rec(script=[])
    graph.build_agent(r, InMemorySaver())
    assert r.bound.get("parallel_tool_calls") is False
    assert [t.name for t in graph.ALL_TOOLS][-4:] == list(actions.ACTIONS)
    print("11. 关并行 ✓")

    # 12. 操作工具出卡：只发 confirm（不发 tool_start），流以 done 结束；历史里是待确认的卡
    starts = []
    actions.ops["start_version"] = lambda user, nid_, cid_, ov, strict: starts.append(cid_) or {"job_id": "j1", "version_id": "j1"}
    cfg = graph.run_config(uid, nid, {"chapter_id": cid}, "zh")
    store.clear(uid, nid)
    model = ScriptedChat(script=[call("generate_storyboard", {}, "g1"), AIMessage("开始了。")])
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(model, cp)
        evs = list(events.stream(agent, cfg, "生成分镜"))
        assert [e["event"] for e in evs] == ["confirm", "done"], evs
        conf = evs[0]["data"]
        assert conf["tool_call_id"] == "g1" and conf["action"] == "generate_storyboard" and conf["id"]
        assert conf["amount"] is None and conf["detail"] == {"chars": 2, "archived": False}
        assert [it.id for it in graph.pending(agent, cfg)] == [conf["id"]]
        h = events.history(agent, cfg)
    assert h[-1]["tools"] == [] and h[-1]["cards"] == [
        {"tool_call_id": "g1", "action": "generate_storyboard", "outcome": "pending", "card": conf}], h[-1]
    print("12. 出卡 ✓")

    # 13. 恢复（确认）：action 事件带结果与任务，之后模型接着说；历史里卡变成已确认
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(model, cp)
        card = graph.pending(agent, cfg)[0].value
        evs = list(events.stream(agent, cfg, Command(resume={conf["id"]: {"decision": "approve", "card": card}})))
        assert [e["event"] for e in evs] == ["action", "token", "done"], evs
        act = evs[0]["data"]
        assert act["outcome"] == "approved" and act["tool_call_id"] == "g1" and act["action"] == "generate_storyboard"
        assert act["task"] == {"kind": "job", "chapter_id": cid, "version_id": "j1", "job_id": "j1"} and starts == [cid]
        assert graph.pending(agent, cfg) == []
        h = events.history(agent, cfg)
    assert h[-1]["cards"][0]["outcome"] == "approved" and h[-1]["cards"][0]["task"]["job_id"] == "j1"
    assert h[-1]["text"] == "开始了。"
    print("13. 恢复 ✓")

    # 14. 有待确认的卡时发新消息：卡补「已取消」（不调模型），新一轮模型看到取消结果与新问题
    model = ScriptedChat(script=[call("generate_storyboard", {}, "g2"), AIMessage("好的，不生成了。")])
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(model, cp)
        list(events.stream(agent, cfg, "再生成一次"))
        assert len(graph.pending(agent, cfg)) == 1
        calls_before = len(model.seen)
        assert graph.cancel_pending(agent, cfg) == 1
        assert len(model.seen) == calls_before, "取消不调模型"
        assert graph.pending(agent, cfg) == [] and graph.cancel_pending(agent, cfg) == 0
        evs = list(events.stream(agent, cfg, "算了，问个别的"))
        assert [e["event"] for e in evs] == ["token", "done"], evs
        last = model.seen[-1]
        assert any(isinstance(m, ToolMessage) and m.content == graph.CANCELLED for m in last)
        assert isinstance(last[-1], HumanMessage) and last[-1].content == "算了，问个别的"
        h = events.history(agent, cfg)
    assert h[-3]["cards"][0]["outcome"] == "rejected" and h[-1]["text"] == "好的，不生成了。"
    print("14. 发新消息取消待确认的卡 ✓")

    # 15. 操作工具报错：action 事件 outcome=failed 带原因；历史里同样；被停掉没结果的标「（已中断）」
    model = ScriptedChat(script=[call("film_run", {}, "f1"), AIMessage("没有可用版本。")])
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(model, cp)
        evs = list(events.stream(agent, cfg, "出片"))
        assert [e["event"] for e in evs] == ["action", "token", "done"], evs
        assert evs[0]["data"]["outcome"] == "failed" and "分镜版本" in evs[0]["data"]["error"]
        h = events.history(agent, cfg)
    assert h[-1]["cards"][0]["outcome"] == "failed"
    dangling = [HumanMessage("q"), call("film_run", {}, "f9")]
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(ScriptedChat(script=[]), cp)
        agent.update_state(cfg, {"messages": dangling}, as_node="agent")
        h = events.history(agent, cfg)
    assert h[-1]["cards"][-1] == {"tool_call_id": "f9", "action": "film_run", "outcome": "failed",
                                   "error": events.INTERRUPTED}, h[-1]
    print("15. 操作报错与被停掉 ✓")
```

说明：
- 第 15 步最后一段用 `update_state(..., as_node="agent")`，造出「工具调用后面没有结果、也没有中断」的存档，模拟回答被停掉的情形。
- 如果 LangGraph 拒绝这样写（例如报 `InvalidUpdateError`），改用 `as_node="tools"`，并只放入 `[HumanMessage("q"), call(...)]`。断言不变。

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd backend && .venv/bin/python tests/assistant/test_graph.py`
Expected: 第 6 步之前的旧步骤通过；第 6 步因为缺 `cards` 失败（或第 11 步 `AttributeError: ... ALL_TOOLS`）。

- [ ] **Step 3: 改 `graph.py`**

导入与常量：

```python
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
...
from assistant import actions, store
from assistant.tools import TOOLS
from server import novels

ALL_TOOLS = TOOLS + actions.TOOLS
CANCELLED = "用户没有确认，发了新消息；这个操作已取消"
```

`build_agent` 改成：

```python
def build_agent(model, checkpointer):
    """一次只调一个工具：操作工具会中断等确认，同一步里两个工具各自中断时，恢复其中一个会让整个工具节点重跑、
    已执行的那个再执行一次。create_react_agent 接受已绑定工具的模型。"""
    return create_react_agent(model.bind_tools(ALL_TOOLS, parallel_tool_calls=False), ALL_TOOLS,
                              pre_model_hook=_pre_model, checkpointer=checkpointer)
```

在 `build_agent` 后面加：

```python
def pending(agent, config: dict) -> list:
    """存档里待确认的卡（LangGraph 的中断）。"""
    return list(agent.get_state(config).interrupts)


def cancel_pending(agent, config: dict) -> int:
    """有待确认的卡时用户发了新消息：给每张卡补一条「已取消」的工具结果（不调模型），新消息照常开新的一轮。"""
    its = pending(agent, config)
    if not its:
        return 0
    msgs = [ToolMessage(CANCELLED, tool_call_id=it.value["tool_call_id"], name=it.value["action"],
                        artifact={"card": it.value, "outcome": "rejected", "task": None}) for it in its]
    agent.update_state(config, {"messages": msgs}, as_node="tools")
    return len(msgs)
```

`NullModel.bind_tools(self, tools, **kwargs)` 已经接受关键字参数，不用改。

- [ ] **Step 4: 改 `events.py`**

文件头注释的事件列表补上 `confirm {卡, id}` / `action {tool_call_id, action, outcome, card?, task?, error?}`，并注明「操作工具不发 tool_start / tool_end」。

导入：

```python
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from assistant.actions import ACTIONS
```

加两个视图函数（放在 `_hide` 之后）：

```python
def action_view(m: ToolMessage, hide: Optional[str] = None) -> dict:
    """操作工具的结果 → action 事件 / 历史里的卡。报错（或没有 artifact）算没做成。"""
    if m.status == "error" or not m.artifact:
        return {"tool_call_id": m.tool_call_id, "action": m.name, "outcome": "failed",
                "error": _hide(text_of(m), hide)[:300]}
    a = m.artifact
    return {"tool_call_id": m.tool_call_id, "action": m.name, "outcome": a["outcome"],
            "card": a.get("card"), "task": a.get("task")}


def confirm_view(it) -> dict:
    """待确认的卡：中断的原值加上中断编号（恢复时用它）。"""
    return {**it.value, "id": it.id}
```

`stream` 改成接受文字或 `Command`，并处理中断与操作工具：

```python
def stream(agent, config: dict, payload, hide: Optional[str] = None) -> Iterator[dict]:
    """跑一轮，逐个产出事件。payload 是用户的文字，或恢复用的 Command。客户端断开时调用方停止迭代即可。"""
    inp = {"messages": [HumanMessage(payload)]} if isinstance(payload, str) else payload
    try:
        for mode, chunk in agent.stream(inp, config, stream_mode=["messages", "updates"]):
            if mode == "messages":
                msg, meta = chunk
                if meta.get("langgraph_node") == "agent" and isinstance(msg, (AIMessage, AIMessageChunk)):
                    t = text_of(msg)
                    if t:
                        yield {"event": "token", "data": {"text": t}}
                continue
            for node, update in chunk.items():
                if node == "__interrupt__":
                    for it in update:
                        yield {"event": "confirm", "data": confirm_view(it)}
                    continue
                for m in (update or {}).get("messages") or []:
                    if node == "agent" and isinstance(m, AIMessage):
                        for tc in m.tool_calls or []:
                            if tc["name"] not in ACTIONS:
                                yield {"event": "tool_start", "data": {"id": tc["id"], "name": tc["name"], "args": tc["args"]}}
                    elif node == "tools" and isinstance(m, ToolMessage):
                        if m.name in ACTIONS:
                            yield {"event": "action", "data": action_view(m, hide)}
                            continue
                        ok = m.status != "error"
                        yield {"event": "tool_end", "data": {"id": m.tool_call_id, "ok": ok,
                                                             "summary": _hide(text_of(m), hide)[:200]}}
                        if ok and m.name == "goto" and m.artifact:
                            yield {"event": "goto", "data": m.artifact}
    except GraphRecursionError:
        yield {"event": "token", "data": {"text": TOO_MANY}}
    except Exception as e:  # 模型、网关、存档出错：给用户一条报错，不抛到 SSE 外面
        yield {"event": "error", "data": {"message": _hide(f"助手出错：{e}", hide)[:300]}}
        return
    yield {"event": "done", "data": {}}
```

`history` 改成带卡片（docstring 补一句「操作工具不进 tools，进 cards：待确认的带中断编号，被停掉没结果的标失败「（已中断）」」）：

```python
def history(agent, config: dict, hide: Optional[str] = None) -> list:
    """……（原 docstring）"""
    snap = agent.get_state(config)
    msgs = snap.values.get("messages") or []
    waiting = {it.value.get("tool_call_id"): it for it in snap.interrupts}
    out: list = []
    cur = None
    for m in msgs:
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "text": text_of(m)})
            cur = None
            continue
        if cur is None:
            cur = {"role": "assistant", "text": "", "tools": [], "goto": [], "cards": []}
            out.append(cur)
        if isinstance(m, AIMessage):
            t = text_of(m)
            if t:
                cur["text"] += ("\n\n" if cur["text"] else "") + t
            for tc in m.tool_calls or []:
                if tc["name"] in ACTIONS:
                    it = waiting.get(tc["id"])
                    cur["cards"].append(
                        {"tool_call_id": tc["id"], "action": tc["name"], "outcome": "pending", "card": confirm_view(it)}
                        if it else {"tool_call_id": tc["id"], "action": tc["name"], "outcome": "failed",
                                    "error": INTERRUPTED})
                else:
                    cur["tools"].append({"id": tc["id"], "name": tc["name"], "args": tc["args"], "ok": None, "summary": ""})
        elif isinstance(m, ToolMessage):
            if m.name in ACTIONS:
                view = action_view(m, hide)
                cur["cards"] = [view if c["tool_call_id"] == m.tool_call_id else c for c in cur["cards"]]
                continue
            for t in cur["tools"]:
                if t["id"] == m.tool_call_id:
                    t["ok"] = m.status != "error"
                    t["summary"] = _hide(text_of(m), hide)[:200]
            if m.status != "error" and m.name == "goto" and m.artifact:
                cur["goto"].append(m.artifact)
    for entry in out:
        for t in entry.get("tools") or []:
            if t["ok"] is None:
                t["ok"], t["summary"] = False, INTERRUPTED
    return out
```

注意：被取消的卡（`cancel_pending` 补的 `ToolMessage`）会排在后来的 `HumanMessage` 之前，所以会落在它原来那条助手消息里，正确。

- [ ] **Step 5: 改系统提示 `prompts/assistant.md`**

把这一行：

```
- 你现在不能替用户执行任何操作（生成、出片、合成、修改都不行）。用户要做事时，说明怎么做，并用 goto 工具放一个跳转按钮。
```

换成：

```
- 你能替用户发起四个操作：generate_storyboard 生成分镜、film_run 出片、compose 配音合成、export_fcpxml 导出剪辑工程。
  - 只在用户明确要做时调用，一次只发起一个操作。
  - 花钱的操作会自动给用户一张确认卡，由用户在卡上点确认，你不用再问「确定吗」。
  - 工具返回「已开始」才算开始，不要提前说做完了；进度在任务卡上，不必反复去查。
  - 用户取消了就不要再发起同一个操作，除非用户再次提出。
  - 前提不满足（没有原文、还没有出片会话、缺音色、成片过期等）时，说明原因，并用 goto 放跳转按钮让用户去处理。
- 你不能出关键帧图，不能改镜头、资产卡、剧情和设置，也不能删除任何东西；用户要做这些时说明怎么做，并用 goto 放跳转按钮。
```

- [ ] **Step 6: 跑测试，确认通过**

Run: `cd backend && .venv/bin/python tests/assistant/test_graph.py`
Expected: 1–15 都 ✓，`ALL PASS`。然后跑全局约束里的全部后端脚本。`test_assistant.py` 里如果也有整条历史的字典断言，按 Step 1 补上 `"cards": []`。

- [ ] **Step 7: 提交**

```bash
git add backend/assistant/graph.py backend/assistant/events.py backend/prompts/assistant.md backend/tests/assistant/test_graph.py backend/tests/server/test_assistant.py
git commit -m "助手智能体接上操作工具：关掉并行工具调用；出卡发 confirm 事件、操作结果发 action 事件，操作工具不出折叠的工具行；历史里带卡片（待确认的带中断编号）；有待确认的卡时发新消息先补「已取消」再开新一轮；系统提示写明能发起的四个操作与规则"
```

（`test_assistant.py` 如果没有改动，就从 `git add` 里去掉。）

---

### Task 4: 接口（恢复、发新消息先取消、执行函数接进助手）

**Files:**
- Modify: `backend/server/app.py`（助手一节，约 1327–1470 行）
- Test: `backend/tests/server/test_assistant.py`

- [ ] **Step 1: 写失败的测试**

`test_assistant.py` 的导入加上：

```python
import copy  # noqa: E402（放到文件顶部的 import 区）
from render import providers  # noqa: E402
from render.providers.fake import FakeTts, FakeVideo  # noqa: E402
```

并在导入之后注册假厂商：

```python
providers.register("fake", lambda: FakeVideo())
providers.register_tts("fake", lambda: FakeTts())
DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))
```

在 `main()` 末尾、`print("\nALL PASS")` 之前追加（`script`、`c`、`H`、`HB`、`A`、`uid`、`nid`、`cid`、`events_of` 都是文件里已有的）：

```python
    # 15. 生成分镜出卡：只有 confirm 与 done；历史里是待确认的卡（带中断编号）
    app_mod._assistant_model = lambda: ScriptedChat(script=script)   # 前面的步骤可能换过模型
    os.environ.pop("STORYBOARD_ASSISTANT_DAILY", None)
    store.clear(uid, nid)
    real_job = app_mod._run_version_job
    app_mod._run_version_job = lambda *a, **k: None       # 不跑真实转换
    script[:] = [call("generate_storyboard", {}, "g1"), AIMessage("开始了。")]
    r = c.post(A + "/messages", headers=H, json={"text": "生成第一章", "lang": "zh", "where": {"chapter_id": cid}})
    evs = events_of(r)
    assert [e for e, _ in evs] == ["confirm", "done"], evs
    conf = evs[0][1]
    assert conf["action"] == "generate_storyboard" and conf["chapter_id"] == cid and conf["amount"] is None
    h = c.get(A, headers=H).json()["messages"]
    assert h[-1]["cards"][0]["outcome"] == "pending" and h[-1]["cards"][0]["card"]["id"] == conf["id"]
    print("15. 出卡 ✓")

    # 16. 恢复的校验：未登录 401、别人的小说 404、decision 非法 422、不是待确认的卡 409
    R2 = A + "/resume"
    ok_body = {"id": conf["id"], "decision": "approve", "lang": "zh", "where": {"chapter_id": cid}}
    assert c.post(R2, json=ok_body).status_code == 401
    assert c.post(R2, headers=HB, json=ok_body).status_code == 404
    assert c.post(R2, headers=H, json={**ok_body, "decision": "maybe"}).status_code == 422
    assert c.post(R2, headers=H, json={**ok_body, "id": "nope"}).status_code == 409
    print("16. 恢复校验 ✓")

    # 17. 恢复（确认）：action 事件带任务、模型接着说；任务进表；记一笔用量；锁已释放
    n_usage = len([x for x in usage.read(user_id=uid) if x["purpose"] == "assistant"])
    r = c.post(R2, headers=H, json=ok_body)
    evs = events_of(r)
    assert [e for e, _ in evs] == ["action", "token", "done"], evs
    act = evs[0][1]
    assert act["outcome"] == "approved" and act["task"]["kind"] == "job"
    assert app_mod._jobs[act["task"]["job_id"]]["novel_id"] == nid
    assert len([x for x in usage.read(user_id=uid) if x["purpose"] == "assistant"]) == n_usage + 1
    assert store.try_begin(uid, nid) and store.end(uid, nid) is None
    assert c.post(R2, headers=H, json=ok_body).status_code == 409, "处理过的卡不能再恢复"
    assert _TMP.name not in r.text
    print("17. 恢复确认 ✓")

    # 18. 出片：真的排上队（假厂商），卡上金额等于剩余各段合计
    c2 = novels.create_chapter(uid, nid, "第二章 刑场", text="原文二")["id"]
    novels.create_version(uid, nid, c2, "v2", {}, "原文二")
    novels.update_version_state(uid, nid, c2, "v2", "succeeded", result=copy.deepcopy(DOC))
    novels.adopt_version(uid, nid, c2, "v2")
    sess = c.post(f"/novels/{nid}/chapters/{c2}/versions/v2/render/session", headers=H, json={}).json()
    script[:] = [call("film_run", {"chapter": c2}, "f1"), AIMessage("出片开始了。")]
    evs = events_of(c.post(A + "/messages", headers=H, json={"text": "第二章出片", "lang": "zh"}))
    assert [e for e, _ in evs] == ["confirm", "done"], evs
    conf = evs[0][1]
    assert conf["amount"] == sess["remaining_cny"] and conf["currency"] == "cny" and conf["version_id"] == "v2"
    evs = events_of(c.post(R2, headers=H, json={"id": conf["id"], "decision": "approve", "lang": "zh", "where": {}}))
    assert evs[0][0] == "action" and evs[0][1]["outcome"] == "approved", evs
    s = c.get(f"/novels/{nid}/chapters/{c2}/versions/v2/render/session", headers=H).json()
    assert all(x["state"] == "queued" for x in s["clips"]), [x["state"] for x in s["clips"]]
    print("18. 出片排队 ✓")

    # 19. 有待确认的卡时发新消息：卡变已取消，模型看到取消结果与新问题
    script[:] = [call("generate_storyboard", {"chapter": c2}, "g2")]
    evs = events_of(c.post(A + "/messages", headers=H, json={"text": "生成第二章", "lang": "zh"}))
    stale = evs[0][1]["id"]
    model = ScriptedChat(script=[AIMessage("好的，不生成了。")])
    app_mod._assistant_model = lambda: model
    evs = events_of(c.post(A + "/messages", headers=H, json={"text": "算了", "lang": "zh"}))
    assert [e for e, _ in evs] == ["token", "done"], evs
    assert any(getattr(m, "content", None) == assistant_graph.CANCELLED for m in model.seen[-1])
    h = c.get(A, headers=H).json()["messages"]
    assert h[-3]["cards"][0]["outcome"] == "rejected" and h[-1]["text"] == "好的，不生成了。"
    assert c.post(R2, headers=H, json={"id": stale, "decision": "approve", "lang": "zh", "where": {}}).status_code == 409
    app_mod._assistant_model = lambda: ScriptedChat(script=script)
    app_mod._run_version_job = real_job
    print("19. 发新消息取消待确认的卡 ✓")

    # 20. 恢复也受每日上限约束（429）
    saved_daily = os.environ.get("STORYBOARD_ASSISTANT_DAILY")
    os.environ["STORYBOARD_ASSISTANT_DAILY"] = "0"
    try:
        assert c.post(R2, headers=H, json={"id": "x", "decision": "reject", "lang": "zh", "where": {}}).status_code == 429
    finally:
        if saved_daily is None:
            os.environ.pop("STORYBOARD_ASSISTANT_DAILY", None)
        else:
            os.environ["STORYBOARD_ASSISTANT_DAILY"] = saved_daily
    print("20. 恢复受每日上限 ✓")
```

还要做两处调整：
- 文件开头导入 `from assistant import graph as assistant_graph`（和已有的 `from assistant import store` 放一起）。
- 第 15 步开头已经把模型恢复成脚本假模型，并清掉每日上限的环境变量；如果前面的步骤还改过别的全局状态（例如锁没放），也在这里复原。

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_assistant.py`
Expected: 1–14 通过；第 15 步失败（`film_run` 等的执行函数还没注入 `ops`，生成分镜的确认后会 `KeyError`；或者 `/resume` 返回 404/405）。

- [ ] **Step 3: 改 `app.py` 的助手一节**

导入区加：

```python
from langgraph.types import Command
from assistant import actions as assistant_actions
```

在「---------- 助手 ----------」小节开头（`_ASSISTANT_STEPS` 前）把执行函数注入工具：

```python
# 操作工具调这些（与接口同一份）；assistant 包不能反过来导入 app
assistant_actions.ops.update(start_version=_start_version, film_quote=_film_quote, film_run=_film_run,
                             compose_quote=_compose_quote, compose_start=_compose_start,
                             export_check=_export_check)
```

把 `assistant_send` 拆成「校验 → 取锁 → 建模型 → 共用的流式响应」，并新增 `assistant_resume`。替换从 `@app.post("/novels/{nid}/assistant/messages")` 起到 `return _Resp(...)` 止的整段：

```python
def _assistant_ctx(user: dict, nid: str, body: dict) -> tuple:
    """(lang, where)：语言只收 zh / en；where 校验 step 后消毒（见 _assistant_where）。"""
    lang = body.get("lang") if body.get("lang") in ("zh", "en") else "zh"
    raw = body.get("where") or {}
    if not isinstance(raw, dict):
        raise HTTPException(422, "where 不合法")
    if raw.get("step") is not None and raw.get("step") not in _ASSISTANT_STEPS:
        raise HTTPException(422, "where.step 不合法")
    return lang, _assistant_where(user["id"], nid, raw)


def _assistant_begin(user: dict, nid: str) -> float:
    """每日上限（429）与并发锁（409）；返回锁凭据。"""
    if assistant_store.used_today(user["id"]) >= assistant_store.daily_limit():
        raise HTTPException(429, "今天的助手消息已用完，明天再来")
    token = assistant_store.try_begin(user["id"], nid)
    if not token:
        raise HTTPException(409, "上一条还在回答")
    return token


def _assistant_pending(user_id: str, nid: str) -> dict:
    """存档里待确认的卡：中断编号 → 卡（中断的原值）。"""
    if not assistant_store.exists(user_id, nid):
        return {}
    with assistant_store.saver(user_id, nid) as cp:
        agent = assistant_graph.build_agent(assistant_graph.NullModel(), cp)
        cfg = assistant_graph.run_config(user_id, nid, {}, "zh")
        return {it.id: it.value for it in assistant_graph.pending(agent, cfg)}


def _assistant_stream(user: dict, nid: str, where: dict, lang: str, payload, token: float, model,
                      before=None) -> StreamingResponse:
    """跑一轮（发消息或确认卡恢复）→ SSE 响应。payload：用户文字或 Command。
    before(agent, cfg)：开跑前在同一份存档上做的事（发新消息时取消待确认的卡）。"""
    root = str(auth.DATA_DIR)   # 整个数据根：用户目录、密钥文件等任何服务器路径都隐去

    def gen():
        cb = UsageCallback()
        ok = False
        try:
            with assistant_store.saver(user["id"], nid) as cp:
                agent = assistant_graph.build_agent(model, cp)
                cfg = assistant_graph.run_config(user["id"], nid, where, lang, [cb])
                try:
                    if before:
                        before(agent, cfg)
                except Exception as e:  # 存档读写出错：给一条报错，不开新一轮
                    yield assistant_events.sse({"event": "error", "data": {
                        "message": assistant_events._hide(f"助手出错：{e}", root)[:300]}})
                    return
                for ev in assistant_events.stream(agent, cfg, payload, hide=root):
                    if ev["event"] == "done":
                        ok = True
                    yield assistant_events.sse(ev)
        finally:
            assistant_store.end(user["id"], nid, token)
            try:
                usage.record(user_id=user["id"], purpose=assistant_store.PURPOSE, model=load_settings().model,
                             usage=cb.usage_totals(), ok=ok, novel_id=nid, chapter_id=where.get("chapter_id"))
            except Exception as e:  # 落账失败不影响对话
                print(f"[usage] 助手落账失败：{e!r}", flush=True)

    class _Body:
        # （原样保留现有 _Body 类的全部内容与注释）
        ...

    class _Resp(StreamingResponse):
        # （原样保留现有 _Resp 类的全部内容与注释）
        ...

    return _Resp(_Body(), media_type="text/event-stream",
                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _assistant_model_or_503(user: dict, nid: str, token: float):
    try:
        return _assistant_model()
    except Exception as e:
        assistant_store.end(user["id"], nid, token)
        raise HTTPException(503, assistant_events._hide(f"助手暂不可用：{e}", str(auth.DATA_DIR)))


@app.post("/novels/{nid}/assistant/messages")
def assistant_send(nid: str, body: dict = Body(...), user: dict = Depends(novel_user)):
    _assistant_db(user, nid)
    text = str(body.get("text") or "").strip()
    if not text or len(text) > _ASSISTANT_MAX:
        raise HTTPException(422, f"消息不能为空，且不超过 {_ASSISTANT_MAX} 字")
    lang, where = _assistant_ctx(user, nid, body)
    token = _assistant_begin(user, nid)
    model = _assistant_model_or_503(user, nid, token)
    # 有待确认的卡：先按「取消」处理（spec §7.2），再开新的一轮
    return _assistant_stream(user, nid, where, lang, text, token, model, before=assistant_graph.cancel_pending)


@app.post("/novels/{nid}/assistant/resume")
def assistant_resume(nid: str, body: dict = Body(...), user: dict = Depends(novel_user)):
    """点了确认卡上的按钮：接着跑被中断的那一轮（spec §7.2）。卡以存档为准，不收前端传来的卡。"""
    _assistant_db(user, nid)
    iid, decision = body.get("id"), body.get("decision")
    if not isinstance(iid, str) or decision not in ("approve", "reject"):
        raise HTTPException(422, "id 或 decision 不合法")
    lang, where = _assistant_ctx(user, nid, body)
    token = _assistant_begin(user, nid)
    try:
        card = _assistant_pending(user["id"], nid).get(iid)
    except Exception:
        assistant_store.end(user["id"], nid, token)
        raise
    if card is None:
        assistant_store.end(user["id"], nid, token)
        raise HTTPException(409, "这张确认卡已经处理过")
    model = _assistant_model_or_503(user, nid, token)
    cmd = Command(resume={iid: {"decision": decision, "card": card}})
    return _assistant_stream(user, nid, where, lang, cmd, token, model)
```

要点：
- `_Body` / `_Resp` 两个类**原样搬进** `_assistant_stream`，里面引用的 `gen`、`user`、`nid`、`token` 都是闭包变量，名字不变。
- `assistant_send` 原有的校验顺序不变：正文 422 → where 422 → 上限 429 → 锁 409 → 模型 503。
- 文件头的接口说明注释里，在「以上全部需要登录」之前加一行：

```
助手（spec docs/specs/2026-11-01-assistant-panel-design.md）：
  GET/DELETE  /novels/{nid}/assistant            历史 / 清空
  POST        /novels/{nid}/assistant/messages   发消息（SSE）；有待确认的卡时先按取消处理
  POST        /novels/{nid}/assistant/resume     确认卡上点了确认或取消，接着跑（SSE）
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd backend && .venv/bin/python tests/server/test_assistant.py`
Expected: 1–20 都 ✓，`ALL PASS`。然后跑全局约束里的全部后端脚本。

- [ ] **Step 5: 提交**

```bash
git add backend/server/app.py backend/tests/server/test_assistant.py
git commit -m "助手接口：新增 resume 接着跑被确认卡中断的一轮（卡以存档为准、处理过的 409、同样受每日上限与并发锁、记一笔用量）；发新消息时先把待确认的卡按取消处理；操作工具接上与接口同一份的执行函数；发消息与恢复共用同一个流式响应"
```

---

### Task 5: 前端基础（类型、接口、桥接、任务进度、会话存储）

**Files:**
- Modify: `frontend/src/types.ts`（助手一节，约 876–904 行）
- Modify: `frontend/src/api.ts`（助手一节，约 523–552 行）
- Modify: `frontend/src/lib/assistantBridge.ts`
- Create: `frontend/src/lib/assistantTask.ts`
- Modify: `frontend/src/lib/assistantSession.ts`
- Test: `frontend/tests/assistant.test.tsx`

- [ ] **Step 1: 写失败的测试**

在 `tests/assistant.test.tsx` 的「位置与跳转」块之后、`// ---------- 极简渲染 ----------` 之前插入（顶部 import 补上 `notifyTask, onTask`，以及 `import { composeView, filmView, jobView } from '../src/lib/assistantTask'` 和需要的类型）：

```ts
import { composeView, filmView, jobView } from '../src/lib/assistantTask'
import type { AssistantTask, FilmSession, Job } from '../src/types'

// ---------- 任务通知 ----------
{
  const got: AssistantTask[] = []
  const off = onTask((t) => got.push(t))
  notifyTask({ kind: 'film', chapter_id: 'c1', version_id: 'v1' })
  off()
  notifyTask({ kind: 'job', chapter_id: 'c1', version_id: 'j1', job_id: 'j1' })
  must(got.length === 1 && got[0].kind === 'film', '订阅者收到、退订后不再收到')
  console.log('✓ 任务通知')
}

// ---------- 任务进度 ----------
{
  const job = (o: Partial<Job>) => ({ id: 'j1', status: 'running', log: [], result: null, quality_report: null, error: null, ...o }) as Job
  const prog = { batches: 2, batch: 1, total_chars: 200, done_chars: 50, attempt: 1, max_attempts: 3, phase: 'generating' as const }
  must(jobView(job({ progress: prog })).state === 'running' && jobView(job({ progress: prog })).pct === 25, '生成中百分比')
  must(jobView(job({ status: 'queued' })).pct === null, '还没进度')
  must(jobView(job({ status: 'succeeded' })).state === 'ok', '完成')
  must(jobView(job({ status: 'completed_with_warnings' })).state === 'ok', '带警告也算完成')
  const f = jobView(job({ status: 'failed', error: '模型超时\n详细' }))
  must(f.state === 'failed' && f.error === '模型超时', '失败取第一行')

  const clip = (state: string) => ({ id: state, state }) as unknown as FilmSession['clips'][number]
  const film = (states: string[], final: FilmSession['final'] = null) => ({ clips: states.map(clip), final }) as FilmSession
  const r = filmView(film(['done', 'running', 'queued', 'planned']))
  must(r.state === 'running' && r.done === 1 && r.total === 4 && r.flying === 2, '出片在跑')
  must(filmView(film(['done', 'done'])).state === 'ok', '出完')
  const ff = filmView(film(['done', 'failed']))
  must(ff.state === 'failed' && ff.failed === 1, '有失败的段')
  const fin = (state: 'queued' | 'running' | 'done' | 'failed', o = {}) =>
    ({ state, files: [], report: null, error: null, detail: null, ...o })
  must(composeView(film([], fin('running', { step: '配音 3 条' }))).state === 'running', '合成中')
  must(composeView(film([], fin('running', { step: '配音 3 条' }))).step === '配音 3 条', '合成步骤')
  must(composeView(film([], fin('done'))).state === 'ok', '合成完')
  must(composeView(film([], fin('failed', { error: 'ffmpeg 出错' }))).error === 'ffmpeg 出错', '合成失败原因')
  must(composeView(film([])).state === 'gone', '没有合成记录')
  console.log('✓ 任务进度')
}
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd frontend && npm test`
Expected: typecheck 失败（`assistantTask` 不存在、`notifyTask` 未导出）。

- [ ] **Step 3: 类型**

`src/types.ts` 助手一节，在 `AssistantMsg` 之前加：

```ts
export type AssistantAction = 'generate_storyboard' | 'film_run' | 'compose' | 'export_fcpxml'
/** 操作开始后要跟进度的任务：job 跟 /jobs，film / compose 跟出片会话，export 只是一个下载按钮 */
export interface AssistantTask {
  kind: 'job' | 'film' | 'compose' | 'export'
  chapter_id: string
  version_id: string | null
  job_id?: string
}
/** 确认卡上的内容（服务端算好的预估）；待确认时带 id（中断编号，恢复时用） */
export interface AssistantCardInfo {
  id?: string
  tool_call_id: string
  action: AssistantAction
  chapter_id: string
  chapter: string
  version_id: string | null
  /** 生成分镜为 null（按模型用量计费，无法预估） */
  amount: number | null
  currency: 'cny' | 'usd' | null
  detail: { clips?: number; chars?: number; archived?: boolean; draft?: boolean }
  /** 恢复时预估变了，重新出的卡 */
  changed?: boolean
  previous_amount?: number | null
}
export interface AssistantCard {
  tool_call_id: string
  action: AssistantAction
  outcome: 'pending' | 'approved' | 'rejected' | 'done' | 'failed'
  card?: AssistantCardInfo | null
  task?: AssistantTask | null
  error?: string
  /** 本地标记：点了按钮，恢复请求还没回来 */
  sending?: boolean
}
```

`AssistantMsg` 加一个字段：

```ts
  cards?: AssistantCard[]
```

`AssistantEvent` 加两种：

```ts
  | { event: 'confirm'; data: AssistantCardInfo & { id: string } }
  | { event: 'action'; data: AssistantCard }
```

- [ ] **Step 4: 接口**

`src/api.ts` 助手一节：把 `streamAssistant` 的函数体抽成 `streamSse`，再加 `resumeAssistant`：

```ts
/** POST 一个 JSON，逐个回调返回的 SSE 事件；signal 中止即停止。429 / 409 / 422 等在开始流之前以 ApiError 抛出。 */
async function streamSse(path: string, body: unknown, onEvent: (e: AssistantEvent) => void,
                         signal?: AbortSignal): Promise<void> {
  const res = await send(path, { ...jsonPost(body), signal })
  const reader = res.body?.getReader()
  if (!reader) return
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const { events, rest } = parseSse(buf)
    buf = rest
    events.forEach(onEvent)
  }
  const { events } = parseSse(buf + '\n\n')
  events.forEach(onEvent)
}

/** 发一条消息并逐个回调事件；signal 中止即停止（服务端跑完当前这一步就停）。 */
export const streamAssistant = (
  nid: string, body: { text: string; lang: string; where: AssistantWhere },
  onEvent: (e: AssistantEvent) => void, signal?: AbortSignal,
) => streamSse(`/novels/${encodeURIComponent(nid)}/assistant/messages`, body, onEvent, signal)

/** 确认卡上点了确认或取消：接着跑被中断的那一轮，同样流式返回 */
export const resumeAssistant = (
  nid: string, body: { id: string; decision: 'approve' | 'reject'; lang: string; where: AssistantWhere },
  onEvent: (e: AssistantEvent) => void, signal?: AbortSignal,
) => streamSse(`/novels/${encodeURIComponent(nid)}/assistant/resume`, body, onEvent, signal)
```

- [ ] **Step 5: 桥接**

`src/lib/assistantBridge.ts` 末尾加（顶部 import 类型补上 `AssistantTask`；文件头注释补「助手发起的操作（助手发出、App 与画布接）」）：

```ts
const taskSubs = new Set<(t: AssistantTask) => void>()

/** 助手发起的操作开始了：App 刷新任务巡检，画布重读出片会话 */
export function notifyTask(t: AssistantTask): void {
  taskSubs.forEach((f) => f(t))
}

export function onTask(cb: (t: AssistantTask) => void): () => void {
  taskSubs.add(cb)
  return () => { taskSubs.delete(cb) }
}
```

- [ ] **Step 6: 任务进度**

新建 `src/lib/assistantTask.ts`：

```ts
/** 助手任务卡的进度：生成分镜查 /jobs，出片与合成查出片会话；状态判断是纯函数（可单测），钩子只管轮询。
 *  只在卡片挂载（面板显示）时查，卸载即停；网络抖动不改显示，下次再查。 */
import { useEffect, useState } from 'react'
import { ApiError, getFilm, getJob, TERMINAL } from '@/api'
import { IN_FLIGHT } from '@/film'
import type { AssistantTask, FilmSession, Job } from '@/types'

export interface TaskView {
  state: 'loading' | 'running' | 'ok' | 'failed' | 'gone'
  /** 生成分镜的百分比；还没进度为 null */
  pct?: number | null
  /** 出片：已出、共、在跑、失败的段数 */
  done?: number
  total?: number
  flying?: number
  failed?: number
  /** 合成进行到哪一步（服务端给的文字） */
  step?: string | null
  error?: string | null
}

export const TASK_POLL_MS: Record<AssistantTask['kind'], number> = { job: 1500, film: 5000, compose: 3000, export: 0 }

export function jobView(j: Job): TaskView {
  if (!TERMINAL.includes(j.status)) {
    const p = j.progress
    return { state: 'running', pct: p && p.total_chars ? Math.round((100 * p.done_chars) / p.total_chars) : null }
  }
  return j.status === 'failed' ? { state: 'failed', error: (j.error ?? '').split('\n')[0] || null } : { state: 'ok' }
}

export function filmView(s: FilmSession): TaskView {
  const count = (pred: (st: string) => boolean) => s.clips.filter((c) => pred(c.state)).length
  const v = { done: count((st) => st === 'done'), total: s.clips.length,
              flying: count((st) => (IN_FLIGHT as string[]).includes(st)), failed: count((st) => st === 'failed') }
  if (v.flying) return { state: 'running', ...v }
  return { state: v.failed ? 'failed' : 'ok', ...v }
}

export function composeView(s: FilmSession): TaskView {
  const f = s.final
  if (!f) return { state: 'gone' }
  if (f.state === 'queued' || f.state === 'running') return { state: 'running', step: f.step ?? null }
  return f.state === 'failed' ? { state: 'failed', error: f.error } : { state: 'ok' }
}

export function useTaskView(nid: string, task: AssistantTask): TaskView {
  const { kind, chapter_id: cid, version_id: vid, job_id: jobId } = task
  const [view, setView] = useState<TaskView>({ state: kind === 'export' ? 'ok' : 'loading' })
  useEffect(() => {
    if (kind === 'export') return
    let gone = false
    let timer: number | undefined
    const tick = async () => {
      let next: TaskView | null = null
      try {
        if (kind === 'job') next = jobView(await getJob(jobId ?? ''))
        else {
          const s = await getFilm(nid, cid, vid ?? '')
          next = kind === 'film' ? filmView(s) : composeView(s)
        }
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) next = { state: 'gone' }
      }
      if (gone) return
      if (next) setView(next)
      if (!next || next.state === 'running') timer = window.setTimeout(() => void tick(), TASK_POLL_MS[kind])
    }
    void tick()
    return () => { gone = true; window.clearTimeout(timer) }
  }, [nid, kind, cid, vid, jobId])
  return view
}
```

如果 `IN_FLIGHT` 的类型让 `includes` 报错，按上面那样转成 `string[]`。

- [ ] **Step 7: 会话存储**

`src/lib/assistantSession.ts`：
- 导入加 `resumeAssistant`、`notifyTask`（来自 `@/lib/assistantBridge`），以及类型 `AssistantCard`、`AssistantEvent`。
- 文件头注释补一句：「确认卡：decideAssistant 接着跑被中断的那一轮，输出接在同一条回答后面；发新消息时，本地把待确认的卡标成已取消（服务端同时取消）。」

具体改动如下。

(a) `settleTools` 改成同时清掉卡片的「发送中」：

```ts
/** 被停掉或断流时：没有结果的工具调用标成失败（不再转圈），卡片退出「发送中」 */
const settleTools = (m: AssistantMsg): AssistantMsg => ({
  ...m,
  tools: (m.tools ?? []).map((x) => (x.ok === null ? { ...x, ok: false } : x)),
  ...(m.cards ? { cards: m.cards.map((c) => (c.sending ? { ...c, sending: false } : c)) } : {}),
})

/** 按 tool_call_id 替换或追加一张卡 */
const upsertCard = (m: AssistantMsg, c: AssistantCard): AssistantMsg => {
  const cards = m.cards ?? []
  return { ...m, cards: cards.some((x) => x.tool_call_id === c.tool_call_id)
    ? cards.map((x) => (x.tool_call_id === c.tool_call_id ? c : x)) : [...cards, c] }
}

/** 发新消息时服务端会取消待确认的卡：本地同步标成已取消 */
const dropPending = (msgs: AssistantMsg[]): AssistantMsg[] => msgs.map((m) => (
  m.cards?.some((c) => c.outcome === 'pending')
    ? { ...m, cards: m.cards.map((c) => (c.outcome === 'pending' ? { ...c, outcome: 'rejected' as const, sending: false } : c)) }
    : m))
```

(b) 把 `sendAssistant` 里「建流、处理事件、收尾」那部分抽成共用的 `run`，`sendAssistant` 与新的 `decideAssistant` 都用它：

```ts
type Starter = (onEvent: (e: AssistantEvent) => void, signal: AbortSignal) => Promise<void>

/** 跑一条流，事件都落到最后一条助手消息上。resume：确认卡恢复（文字另起一段；409 显示服务端原因） */
async function run(nid: string, o: SendOpts, resume: boolean, start: Starter, onLimited: () => void): Promise<void> {
  const ctl = new AbortController()
  ctls.set(nid, ctl)
  // 换小说、退出登录会把这条流从表里撤掉：之后的事件一律丢弃
  const alive = () => ctls.get(nid) === ctl
  const patchLast = (fn: (m: AssistantMsg) => AssistantMsg) => {
    if (alive()) put(nid, (s) => ({ ...s, msgs: s.msgs.map((m, i) => (i === s.msgs.length - 1 ? fn(m) : m)) }))
  }
  let ended = false
  let gap = resume       // 工具调用、卡片之后的下一段文字另起一段
  try {
    await start((e) => {
      if (e.event === 'token') {
        const sep = gap
        gap = false
        patchLast((m) => ({ ...m, text: m.text + (sep && m.text ? '\n\n' : '') + e.data.text }))
      } else if (e.event === 'tool_start') {
        gap = true
        patchLast((m) => ({ ...m, tools: [...(m.tools ?? []), { ...e.data, ok: null, summary: '' }] }))
      } else if (e.event === 'tool_end') {
        patchLast((m) => ({ ...m, tools: (m.tools ?? []).map((x) => (x.id === e.data.id ? { ...x, ok: e.data.ok, summary: e.data.summary } : x)) }))
      } else if (e.event === 'goto') patchLast((m) => ({ ...m, goto: [...(m.goto ?? []), e.data] }))
      else if (e.event === 'confirm') {
        gap = true
        patchLast((m) => upsertCard(m, { tool_call_id: e.data.tool_call_id, action: e.data.action, outcome: 'pending', card: e.data }))
      } else if (e.event === 'action') {
        gap = true
        patchLast((m) => upsertCard(m, { ...e.data, sending: false }))
        if (e.data.task && e.data.outcome !== 'failed' && alive()) notifyTask(e.data.task)
      } else if (e.event === 'error') { ended = true; patchLast((m) => settleTools({ ...m, error: e.data.message })) }
      else if (e.event === 'done') ended = true
    }, ctl.signal)
    // 流断了却既没有 done 也没有 error（代理掐断、服务重启）：给报错与重试，不留空泡泡
    if (!ended) patchLast((m) => settleTools({ ...m, error: o.cutOffText }))
  } catch (err) {
    if (ctl.signal.aborted) patchLast((m) => settleTools({ ...m, interrupted: true }))
    else if (err instanceof ApiError && err.status === 429) { if (alive()) onLimited() }
    else if (err instanceof ApiError && err.status === 409) patchLast((m) => settleTools({ ...m, error: resume ? err.message : o.busyText }))
    else patchLast((m) => settleTools({ ...m, error: err instanceof Error ? err.message : String(err) }))
  } finally {
    if (alive()) {
      ctls.delete(nid)
      put(nid, (s) => ({ ...s, busy: false }))
    }
  }
}

export async function sendAssistant(nid: string, raw: string, o: SendOpts): Promise<void> {
  const q = raw.trim()
  const s0 = getSession(nid)
  if (!q || s0.busy || s0.limited || q.length > ASSISTANT_MAX) return
  const before = s0.msgs
  put(nid, (s) => ({ ...s, draft: '', busy: true,
                     msgs: [...dropPending(s.msgs), { role: 'user', text: q }, { role: 'assistant', text: '', tools: [], goto: [], cards: [] }] }))
  await run(nid, o, false,
            (onEvent, signal) => streamAssistant(nid, { text: q, lang: o.lang, where: o.where }, onEvent, signal),
            // 429 在服务端动任何东西之前：恢复成发送前的样子（待确认的卡也还在）
            () => put(nid, (s) => ({ ...s, limited: true, msgs: before, draft: q })))
}

/** 确认卡上点了确认或取消：接着跑被中断的那一轮，输出接在同一条回答后面 */
export async function decideAssistant(nid: string, toolCallId: string, decision: 'approve' | 'reject',
                                      o: SendOpts): Promise<void> {
  const s0 = getSession(nid)
  const last = s0.msgs[s0.msgs.length - 1]
  const card = last?.role === 'assistant' ? last.cards?.find((c) => c.tool_call_id === toolCallId) : undefined
  const id = card?.card?.id
  if (!card || card.outcome !== 'pending' || !id || s0.busy || s0.limited) return
  put(nid, (s) => ({ ...s, busy: true,
                     msgs: s.msgs.map((m, i) => (i === s.msgs.length - 1 ? upsertCard(m, { ...card, sending: true }) : m)) }))
  await run(nid, o, true,
            (onEvent, signal) => resumeAssistant(nid, { id, decision, lang: o.lang, where: o.where }, onEvent, signal),
            () => put(nid, (s) => ({ ...s, limited: true })))
}
```

注意：
- 原来 `sendAssistant` 在 429 时把最后两条消息切掉、草稿放回去。现在改为恢复成发送前的整份消息（`before`），效果相同，同时把被本地标成已取消的卡也恢复回来。
- `retryAssistant` 不变。

- [ ] **Step 8: 跑测试，确认通过**

Run: `cd frontend && npm test && npm run lint && npx vite build`
Expected: 17 套全过（`assistant.test.tsx` 里多出「✓ 任务通知」「✓ 任务进度」）；lint 0 error、warning ≤ 5；build 成功。

- [ ] **Step 9: 提交**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/lib/assistantBridge.ts frontend/src/lib/assistantTask.ts frontend/src/lib/assistantSession.ts frontend/tests/assistant.test.tsx
git commit -m "助手前端基础：确认卡与任务的类型、confirm / action 事件；恢复接口与发消息共用 SSE 读取；桥接加操作开始的通知；任务进度的纯函数与轮询钩子；会话存储处理卡片、decideAssistant 接着跑被中断的一轮、发新消息时把待确认的卡标成已取消"
```

---

### Task 6: 确认卡与任务卡界面

**Files:**
- Create: `frontend/src/components/assistant/ActionCard.tsx`
- Create: `frontend/src/components/assistant/TaskCard.tsx`
- Modify: `frontend/src/components/assistant/AssistantPanel.tsx`
- Modify: `frontend/src/styles/workspace.css`（`.assistant__tool` 附近）
- Modify: `frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`（`assistant` 一节）
- Test: `frontend/tests/assistant.test.tsx`

- [ ] **Step 1: 写失败的测试**

**(a) 改桩后端**：GET 按路径分别返回历史、出片会话、任务。把 `globalThis.fetch = …` 里这一行：

```ts
  if (method === 'GET') return new Response(JSON.stringify({ messages: history }), { status: 200 })
```

换成：

```ts
  if (method === 'GET') {
    const u = String(url)
    if (u.includes('/render/session')) return new Response(JSON.stringify(filmState), { status: 200 })
    if (u.includes('/jobs/')) return new Response(JSON.stringify(jobState), { status: jobState ? 200 : 404 })
    if (u.endsWith('/export.zip')) return new Response('zip', { status: 200, headers: { 'content-disposition': 'attachment; filename="p.zip"' } })
    return new Response(JSON.stringify({ messages: history }), { status: 200 })
  }
```

并在 `let history` 旁边声明：

```ts
let filmState: unknown = { clips: [{ id: 'C1', state: 'running' }, { id: 'C2', state: 'done' }], final: null }
let jobState: unknown = null
```

**(b) 在文件末尾（最后一个面板测试块之后、整个文件结束之前）追加确认卡的测试块。** 沿用已有的 `mount`、`type`、`enter`、`flush`、`$`、`$$`、`script`、`hold`、`after`、`calls`、`history`。顶部要从 `../src/lib/assistantBridge` 再导入 `onTask`（如果第 5 个任务已经导入，就不用重复）。

```ts
{
  // 确认卡：出卡 → 待确认（金额与要点）→ 点确认发 resume、按钮禁用 → action 结果 → 任务卡与通知
  const tasks: unknown[] = []
  const offTask = onTask((t) => tasks.push(t))
  const card = { id: 'i1', tool_call_id: 'f1', action: 'film_run', chapter_id: 'c1', chapter: '第一章',
                 version_id: 'v1', amount: 1.5, currency: 'cny', detail: { clips: 2 } }
  history = []
  let root = await mount('n-card')
  script = [{ event: 'confirm', data: card }]
  await type('第一章出片')
  await enter()
  const box = () => $$('assistant-card').at(-1)!
  must(box().getAttribute('data-outcome') === 'pending', '待确认的卡')
  must((box().textContent ?? '').includes('1.50') && (box().textContent ?? '').includes('2'), '金额与段数')
  must(!!$('assistant-card-approve') && !($('assistant-card-approve') as HTMLButtonElement).disabled, '可以确认')
  must(!$$('assistant-tool').length, '操作工具不出折叠的工具行')

  let release!: () => void
  hold = new Promise<void>((r) => { release = r })
  script = [{ event: 'action', data: { tool_call_id: 'f1', action: 'film_run', outcome: 'approved', card,
                                       task: { kind: 'film', chapter_id: 'c1', version_id: 'v1' } } }]
  after = [{ event: 'token', data: { text: '开始了' } }]
  await act(async () => { $('assistant-card-approve')!.click() })
  await flush()
  const last = calls[calls.length - 1]
  must(last.url.endsWith('/assistant/resume') && JSON.parse(last.body!).id === 'i1' && JSON.parse(last.body!).decision === 'approve',
       '点确认发 resume，带中断编号')
  must(box().getAttribute('data-outcome') === 'approved', 'action 到了就是已确认')
  release()
  await flush()
  hold = null
  after = []
  must(tasks.length === 1 && (tasks[0] as { kind: string }).kind === 'film', '通知工作台')
  must(!!$('assistant-task') && ($('assistant-task')!.textContent ?? '').includes('1'), '任务卡显示进度')
  must(($$('assistant-bot').at(-1)!.textContent ?? '').includes('开始了'), '恢复后的文字接在同一条回答')
  await act(async () => { root.unmount() })

  // 发送中禁用：再出一张卡，点取消，流还没回来时按钮都禁用
  history = []
  root = await mount('n-card2')
  script = [{ event: 'confirm', data: { ...card, id: 'i2', tool_call_id: 'f2' } }]
  await type('出片')
  await enter()
  hold = new Promise<void>((r) => { release = r })
  script = []
  after = [{ event: 'action', data: { tool_call_id: 'f2', action: 'film_run', outcome: 'rejected', card } }]
  await act(async () => { $('assistant-card-reject')!.click() })
  await flush()
  must(($('assistant-card-approve') as HTMLButtonElement).disabled && ($('assistant-card-reject') as HTMLButtonElement).disabled,
       '请求回来之前两个按钮都禁用')
  release()
  await flush()
  hold = null
  after = []
  must(box().getAttribute('data-outcome') === 'rejected' && !!$('assistant-card-rejected'), '取消后显示已取消')
  await act(async () => { root.unmount() })

  // 有待确认的卡时发新消息：卡本地标成已取消
  history = []
  root = await mount('n-card3')
  script = [{ event: 'confirm', data: { ...card, id: 'i3', tool_call_id: 'f3' } }]
  await type('出片')
  await enter()
  script = [{ event: 'token', data: { text: '好的' } }]
  await type('算了')
  await enter()
  must($$('assistant-card')[0].getAttribute('data-outcome') === 'rejected', '发新消息后待确认的卡变已取消')
  await act(async () => { root.unmount() })

  // 历史里待确认的卡能直接点；金额变了的卡有提示；没做成的卡显示原因；导出给下载按钮；生成分镜写按用量计费
  history = [
    { role: 'user', text: '做几件事' },
    { role: 'assistant', text: '', tools: [], goto: [], cards: [
      { tool_call_id: 'x1', action: 'compose', outcome: 'failed', error: '还有说话人没选音色' },
      { tool_call_id: 'x2', action: 'export_fcpxml', outcome: 'done',
        card: { ...card, tool_call_id: 'x2', action: 'export_fcpxml', amount: null, currency: null, detail: {} },
        task: { kind: 'export', chapter_id: 'c1', version_id: 'v1' } },
      { tool_call_id: 'x3', action: 'generate_storyboard', outcome: 'approved',
        card: { ...card, tool_call_id: 'x3', action: 'generate_storyboard', amount: null, currency: 'usd', detail: { chars: 300, archived: true } },
        task: { kind: 'job', chapter_id: 'c1', version_id: 'j1', job_id: 'j1' } },
      { tool_call_id: 'x4', action: 'film_run', outcome: 'pending',
        card: { ...card, id: 'i4', tool_call_id: 'x4', amount: 2, changed: true, previous_amount: 1.5 } },
    ] },
  ]
  jobState = { id: 'j1', status: 'running', log: [], result: null, quality_report: null, error: null,
               progress: { batches: 2, batch: 1, total_chars: 100, done_chars: 40, attempt: 1, max_attempts: 3, phase: 'generating' } }
  root = await mount('n-card4')
  const cards = $$('assistant-card')
  must(cards.length === 4, '四张卡')
  must(!!$('assistant-card-failed') && ($('assistant-card-failed')!.textContent ?? '').includes('音色'), '没做成的原因')
  must(!!$('assistant-download'), '导出给下载按钮')
  must(cards[2].textContent!.includes('40'), '生成分镜的进度百分比')
  must(!!$('assistant-card-changed') && $('assistant-card-changed')!.textContent!.includes('1.50'), '金额变了的提示带原金额')
  must(!($('assistant-card-approve') as HTMLButtonElement).disabled, '历史里待确认的卡能点')
  must(!$$('assistant-error').some((e) => e.textContent?.includes('重试')), '有待确认的卡时不给重试')
  jobState = null
  await act(async () => { root.unmount() })
  offTask()
  console.log('✓ 确认卡与任务卡')
}
```

上面用到了 `history`、`script`、`hold`、`after`、`calls` 这几个已有变量。如果它们是 `const` 或者签名与这里不同，按文件里实际的写法调整。断言的含义不能改。

`flush` 只推进 0ms 的定时器，任务卡的下一次轮询（1.5–5 秒）不会在测试里触发；每块结束都 `unmount`，定时器随之清掉，不会拖住进程。

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd frontend && npm test`
Expected: `assistant.test.tsx` 失败于「✗ 待确认的卡」（还没有卡片组件）。

- [ ] **Step 3: 文案**

`src/i18n/zh.ts` 的 `assistant` 一节：
- 把 `empty` 改成 `'我能查进度、镜头、角色和出片状态，也能替你生成分镜、出片、合成和导出；花钱的会先请你确认。'`
- 在 `toolUnknown` 之后加：

```ts
    action: {
      generate_storyboard: '生成分镜', film_run: '出片', compose: '配音合成', export_fcpxml: '导出剪辑工程',
    },
    card: {
      confirm: '确认',
      reject: '取消',
      modelCost: '按模型用量计费，无法预估',
      cny: '约 ¥{n}',
      clips: '{n} 段',
      chars: '原文 {n} 字',
      ttsChars: '配音 {n} 字',
      archived: '本章已有采用版，新版本只存档',
      draft: '草稿合成（缺视频的段用关键帧补位）',
      changed: '金额有变化（原 ¥{n}），请重新确认',
      approved: '已确认',
      rejected: '已取消',
      failed: '没做成：{msg}',
    },
    task: {
      loading: '查询中…',
      jobStarting: '排队中',
      jobRunning: '生成中 {pct}%',
      jobOk: '分镜已生成',
      jobFailed: '生成失败：{msg}',
      gone: '任务记录已不在（服务重启过），去这一章看看结果',
      filmRunning: '已出 {done} / 共 {total} 段，在跑 {flying} 段',
      filmOk: '已出 {done} / 共 {total} 段',
      filmFailed: '已出 {done} / 共 {total} 段，{failed} 段失败',
      composeRunning: '合成中{step}',
      composeOk: '成片已合成',
      composeFailed: '合成失败：{msg}',
      unknownError: '未知原因',
      download: '下载剪辑工程',
      downloadFailed: '下载失败：{msg}',
    },
```

`src/i18n/en.ts` 对应位置：
- `empty: 'I can check progress, shots, characters and render status, and start storyboards, renders, mixes and exports for you. Anything that costs money asks you first.'`
- 再加：

```ts
    action: {
      generate_storyboard: 'Generate storyboard', film_run: 'Render video', compose: 'Voice & mix', export_fcpxml: 'Export editing project',
    },
    card: {
      confirm: 'Confirm',
      reject: 'Cancel',
      modelCost: 'Billed by model usage; cannot be estimated',
      cny: 'About ¥{n}',
      clips: '{n} clips',
      chars: '{n} characters of source text',
      ttsChars: '{n} characters to voice',
      archived: 'This chapter already has an adopted version; the new one is only archived',
      draft: 'Draft mix (clips without video use keyframes)',
      changed: 'The estimate changed (was ¥{n}); please confirm again',
      approved: 'Confirmed',
      rejected: 'Cancelled',
      failed: 'Did not go through: {msg}',
    },
    task: {
      loading: 'Checking…',
      jobStarting: 'Queued',
      jobRunning: 'Generating {pct}%',
      jobOk: 'Storyboard ready',
      jobFailed: 'Generation failed: {msg}',
      gone: 'The job record is gone (the server restarted); check the chapter for the result',
      filmRunning: '{done} of {total} clips done, {flying} running',
      filmOk: '{done} of {total} clips done',
      filmFailed: '{done} of {total} clips done, {failed} failed',
      composeRunning: 'Mixing{step}',
      composeOk: 'Final video ready',
      composeFailed: 'Mix failed: {msg}',
      unknownError: 'unknown reason',
      download: 'Download editing project',
      downloadFailed: 'Download failed: {msg}',
    },
```

- [ ] **Step 4: 任务卡**

新建 `src/components/assistant/TaskCard.tsx`：

```tsx
/** 助手任务卡：按任务种类显示进度，结束后给跳转；导出就是一个下载按钮。只在挂载（面板显示）时轮询。 */
import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { exportFcpxml } from '@/api'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import { useTaskView } from '@/lib/assistantTask'
import type { TaskView } from '@/lib/assistantTask'
import type { AssistantGoto, AssistantStep, AssistantTask } from '@/types'

/** 结束后去哪一步：分镜生成完去检查，出片去出片，合成完去下载（失败回合成） */
const NEXT: Record<AssistantTask['kind'], AssistantStep> = { job: 'review', film: 'render', compose: 'download', export: 'download' }

function taskText(t: (k: MsgKey, v?: Record<string, string | number>) => string, kind: AssistantTask['kind'], v: TaskView): string {
  if (v.state === 'loading') return t('assistant.task.loading')
  if (v.state === 'gone') return t('assistant.task.gone')
  const msg = v.error || t('assistant.task.unknownError')
  if (kind === 'job') {
    if (v.state === 'running') return v.pct == null ? t('assistant.task.jobStarting') : t('assistant.task.jobRunning', { pct: v.pct })
    return v.state === 'ok' ? t('assistant.task.jobOk') : t('assistant.task.jobFailed', { msg })
  }
  if (kind === 'film') {
    const n = { done: v.done ?? 0, total: v.total ?? 0, flying: v.flying ?? 0, failed: v.failed ?? 0 }
    return t(v.state === 'running' ? 'assistant.task.filmRunning' : v.state === 'ok' ? 'assistant.task.filmOk' : 'assistant.task.filmFailed', n)
  }
  if (v.state === 'running') return t('assistant.task.composeRunning', { step: v.step ? t('common.paren', { text: v.step }) : '' })
  return v.state === 'ok' ? t('assistant.task.composeOk') : t('assistant.task.composeFailed', { msg })
}

export function TaskCard({ novelId, task, chapter, onGoto }: {
  novelId: string
  task: AssistantTask
  chapter: string
  onGoto: (g: AssistantGoto) => void
}) {
  const { t } = useI18n()
  const v = useTaskView(novelId, task)
  const [saving, setSaving] = useState(false)

  if (task.kind === 'export') {
    const save = async () => {
      setSaving(true)
      try {
        await exportFcpxml(novelId, task.chapter_id, task.version_id ?? '')
      } catch (e) {
        toast.error(t('assistant.task.downloadFailed', { msg: e instanceof Error ? e.message : String(e) }))
      } finally {
        setSaving(false)
      }
    }
    return (
      <Button variant="outline" size="sm" className="self-start" disabled={saving} data-testid="assistant-download"
              onClick={() => void save()}>
        {saving && <Loader2 className="size-3 animate-spin" />}
        {t('assistant.task.download')}
      </Button>
    )
  }

  const running = v.state === 'loading' || v.state === 'running'
  const step: AssistantStep = task.kind === 'compose' && v.state === 'failed' ? 'compose' : NEXT[task.kind]
  return (
    <div className="assistant__task" data-testid="assistant-task" data-state={v.state}>
      <span className="inline-flex items-center gap-1">
        {running && <Loader2 className="size-3 animate-spin" />}
        {taskText(t, task.kind, v)}
      </span>
      {!running && (
        <Button variant="outline" size="sm" className="self-start" data-testid="assistant-task-goto"
                onClick={() => onGoto({ chapter_id: task.chapter_id, step })}>
          {t('assistant.goto', { chapter, step: t(`flow.steps.${step}` as MsgKey) })}
        </Button>
      )}
    </div>
  )
}
```

- [ ] **Step 5: 确认卡**

新建 `src/components/assistant/ActionCard.tsx`：

```tsx
/** 助手对话里的操作卡：标题、金额与要点；待确认时给「确认」「取消」（请求回来之前禁用）；
 *  确认后或不需确认的操作下面挂任务卡；没做成的写原因。 */
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import type { AssistantCard, AssistantGoto } from '@/types'
import { TaskCard } from './TaskCard'

export function ActionCard({ novelId, c, busy, onDecide, onGoto }: {
  novelId: string
  c: AssistantCard
  /** 正在回答（或别的卡在发送）：按钮禁用 */
  busy: boolean
  onDecide: (decision: 'approve' | 'reject') => void
  onGoto: (g: AssistantGoto) => void
}) {
  const { t } = useI18n()
  const info = c.card
  const title = t(`assistant.action.${c.action}` as MsgKey) + (info?.chapter ? ` · ${info.chapter}` : '')
  const cost = !info || info.currency === null ? null
    : info.amount === null ? t('assistant.card.modelCost') : t('assistant.card.cny', { n: info.amount.toFixed(2) })
  const d = info?.detail ?? {}
  const notes = [
    d.clips !== undefined ? t('assistant.card.clips', { n: d.clips }) : null,
    d.chars !== undefined ? t(c.action === 'compose' ? 'assistant.card.ttsChars' : 'assistant.card.chars', { n: d.chars }) : null,
    d.archived ? t('assistant.card.archived') : null,
    c.action === 'compose' && d.draft ? t('assistant.card.draft') : null,
  ].filter((x): x is string => !!x)
  const locked = busy || !!c.sending
  return (
    <div className="assistant__card" data-testid="assistant-card" data-outcome={c.outcome}>
      <p className="font-medium">{title}</p>
      {cost && <p data-testid="assistant-card-cost">{cost}</p>}
      {!!notes.length && <p className="text-xs text-muted-foreground">{notes.join(t('common.listSep'))}</p>}
      {info?.changed && (
        <p className="text-xs text-warning" data-testid="assistant-card-changed">
          {t('assistant.card.changed', { n: (info.previous_amount ?? 0).toFixed(2) })}
        </p>
      )}
      {c.outcome === 'pending' && (
        <div className="flex gap-2">
          <Button size="sm" disabled={locked} data-testid="assistant-card-approve" onClick={() => onDecide('approve')}>
            {c.sending && <Loader2 className="size-3 animate-spin" />}
            {t('assistant.card.confirm')}
          </Button>
          <Button size="sm" variant="outline" disabled={locked} data-testid="assistant-card-reject" onClick={() => onDecide('reject')}>
            {t('assistant.card.reject')}
          </Button>
        </div>
      )}
      {c.outcome === 'approved' && <p className="text-xs text-muted-foreground">{t('assistant.card.approved')}</p>}
      {c.outcome === 'rejected' && (
        <p className="text-xs text-muted-foreground" data-testid="assistant-card-rejected">{t('assistant.card.rejected')}</p>
      )}
      {c.outcome === 'failed' && (
        <p className="text-xs text-destructive" data-testid="assistant-card-failed">{t('assistant.card.failed', { msg: c.error ?? '' })}</p>
      )}
      {c.task && (c.outcome === 'approved' || c.outcome === 'done') && (
        <TaskCard novelId={novelId} task={c.task} chapter={info?.chapter ?? ''} onGoto={onGoto} />
      )}
    </div>
  )
}
```

- [ ] **Step 6: 面板接上卡片**

`src/components/assistant/AssistantPanel.tsx`：
- 导入加 `decideAssistant`（来自 `@/lib/assistantSession`）与 `ActionCard`（来自 `./ActionCard`）。
- 文件头注释补「操作卡（确认、取消、任务进度）在 ActionCard」。
- 在助手消息里，`{!!m.text && <MiniMd text={m.text} />}` 之后、跳转按钮之前插入：

```tsx
            {(m.cards ?? []).map((c) => (
              <ActionCard key={c.tool_call_id} novelId={novelId} c={c} busy={busy} onGoto={onGoto}
                          onDecide={(d) => void decideAssistant(novelId, c.tool_call_id, d, opts())} />
            ))}
```

- 报错行的「重试」条件改成：有待确认的卡时不给重试（重试会重发问题，等于取消那张卡）：

```tsx
                {i === msgs.length - 1 && !busy && !(m.cards ?? []).some((c) => c.outcome === 'pending') && (
                  <Button variant="ghost" size="sm" onClick={retry}>{t('assistant.retry')}</Button>
                )}
```

- [ ] **Step 7: 样式**

`src/styles/workspace.css`，在 `.assistant__tool pre` 之后加：

```css
.assistant__card { border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.assistant__task { font-size: 12px; color: var(--ui-muted-foreground); display: flex; flex-direction: column; gap: 4px; }
```

- [ ] **Step 8: 跑测试，确认通过**

Run: `cd frontend && npm test && npm run lint && npx vite build`
Expected: 17 套全过，`assistant.test.tsx` 多出「✓ 确认卡与任务卡」；lint 0 error、warning ≤ 5；build 成功。

- [ ] **Step 9: 提交**

```bash
git add frontend/src/components/assistant/ActionCard.tsx frontend/src/components/assistant/TaskCard.tsx frontend/src/components/assistant/AssistantPanel.tsx frontend/src/styles/workspace.css frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/assistant.test.tsx
git commit -m "助手确认卡与任务卡：卡上写操作、章节、金额（生成分镜写按用量计费）与要点，金额变了提示原金额；待确认时确认与取消，请求回来之前禁用；确认后挂任务卡（生成分镜百分比、出片段数、合成步骤），结束后给跳转；导出给下载按钮；有待确认的卡时不给重试"
```

---

### Task 7: 页面联动（任务巡检、出片会话重读）

**Files:**
- Modify: `frontend/src/App.tsx`（`watchJobs` 定义之后）
- Modify: `frontend/src/components/TimelineCanvas.tsx`（`reloadFilm` 那段 effect 之后，约 145 行）
- Test: `frontend/tests/film.test.tsx`

- [ ] **Step 1: 写失败的测试**

`tests/film.test.tsx` 里，在「9b. 保存完重读出片会话」那个块之后加：

```ts
// 9c. 助手对这一版发起出片 / 合成：重读出片会话；别的版本不读
{
  const { notifyTask } = await import('../src/lib/assistantBridge')
  const gets = () => calls.filter((c) => c === 'GET /session').length
  const n0 = gets()
  await act(async () => { notifyTask({ kind: 'film', chapter_id: 'c1', version_id: 'v1' }) })
  await settle()
  must(gets() > n0, '助手对这一版出片后重读出片会话')
  const n1 = gets()
  await act(async () => { notifyTask({ kind: 'compose', chapter_id: 'c1', version_id: 'other' }) })
  await settle()
  must(gets() === n1, '别的版本不重读')
  console.log('9c. 助手发起后重读 ✓')
}
```

文件里画布用的版本编号如果不是 `v1`，换成实际的编号。

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd frontend && npm test`
Expected: `film.test.tsx` 失败于「✗ 助手对这一版出片后重读出片会话」。

- [ ] **Step 3: 画布订阅**

`src/components/TimelineCanvas.tsx`：
- 导入 `import { onTask } from '@/lib/assistantBridge'`（按文件里已有的导入写法，用 `@/` 或相对路径）。
- 在「保存完重读出片会话」的 effect 之后加：

```tsx
  // 助手对这一版发起了出片或合成：重读出片会话（在跑的段让轮询变勤，合成面板跟着会话变）
  const filmVid = version?.vid
  useEffect(() => onTask((t) => {
    if ((t.kind === 'film' || t.kind === 'compose') && t.version_id && t.version_id === filmVid) void reloadFilm()
  }), [filmVid, reloadFilm])
```

- [ ] **Step 4: App 订阅**

`src/App.tsx`：
- 从 `./lib/assistantBridge` 的导入里加上 `onTask`（这个文件已经从那里导入 `requestStep`、`cancelStep`）。
- 在 `watchJobs` 定义之后、常驻巡检的 effect 附近加：

```tsx
  // 助手发起了操作：转换让任务巡检立刻刷新（动态里马上出现）；各种操作都让小说概览重算
  useEffect(() => onTask((t) => {
    if (t.kind === 'job') void watchJobs()
    bumpSummary()
  }), [watchJobs, bumpSummary])
```

- [ ] **Step 5: 跑测试，确认通过**

Run: `cd frontend && npm test && npm run lint && npx vite build`
Expected: 17 套全过，`film.test.tsx` 多出「9c. 助手发起后重读 ✓」；lint 0 error、warning ≤ 5；build 成功。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/App.tsx frontend/src/components/TimelineCanvas.tsx frontend/tests/film.test.tsx
git commit -m "助手发起操作后页面联动：转换让任务巡检立刻刷新，出片与合成让正在看这一版的画布重读出片会话，各种操作都让小说概览重算"
```

---

## 自查（写计划时已做）

- **spec 覆盖**：
  - §7.1 四个操作与前提 → Task 1、2；
  - 关并行 → Task 3；
  - 重新出卡、确认金额二次校验 → Task 2；
  - §7.2 事件 → Task 3；`resume` 接口 → Task 4；历史 `cards` → Task 3；
  - 发新消息取消 → Task 3（`cancel_pending`）、Task 4（接口）、Task 5（前端本地）；
  - §7.3 确认卡、任务卡 → Task 6；页面联动 → Task 7；文案 → Task 6；
  - §7.4 测试 → 各任务的 Step 1。
- **类型一致**：
  - 后端 `action_view` 的形状 `{tool_call_id, action, outcome, card?, task?, error?}` 和前端 `AssistantCard` 一致。
  - `confirm_view` 的形状是卡加 `id`，和 `AssistantCardInfo & { id }` 一致。
  - 任务形状 `{kind, chapter_id, version_id, job_id?}` 前后端一致。
  - `ops` 的六个名字在 Task 1（定义）、Task 2（调用与测试替身）、Task 4（注入）一致。
- **占位**：无 TBD。有三处让实施者按文件实际情况调整：Task 3 Step 1 的 `as_node`、Task 6 Step 1 的已有变量、Task 7 Step 1 的版本编号。每处都写明了要保持不变的断言含义。
