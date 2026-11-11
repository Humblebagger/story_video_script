# 出片画布节点图与自由节点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 出片画布加「节点图」视图（资产、剧本段、自由节点三列，连线显示谁参考了谁），并支持在剧本之外拉一个自由节点补拍：不挂靠时是独立素材，挂靠某段时成为那一段的一次新尝试。

**Architecture:**
- **后端**：
  - 出片会话 `session.json` 里与 `clips` 并列加 `free` 列表和 `free_seq` 序号。
  - `session.py` 的迁移函数改为按 id 在两个列表里查找；所有「有没有在跑」的判断统一走 `items()` / `any_in_flight()`。
  - 新模块 `render/free.py` 负责接口侧的新建、派生、修改、删除、排队与采用。
  - `compose.request_for_free` 按节点存的正文，再按 `refs` 顺序拼参考行，组装厂商请求。
  - 挂靠节点下载成功后，`session.downloaded` 把这次尝试复制进目标段。
- **前端**：
  - 纯函数 `nodeGraph.ts` 算三列布局与连线。
  - `NodeGraph.tsx` 盖在时间轴上面，负责平移、缩放和高亮；`NodeCards.tsx` 是三种卡片。
  - `TimelineCanvas` 顶栏切换「时间轴 / 节点图」。
  - 出片面板能显示自由节点的详情。

**Tech Stack:** FastAPI（Python 3.12）；React 19、TypeScript、Tailwind v4、shadcn；测试为自写脚本（后端 `.venv/bin/python`，前端 `vite build --ssr` + node + happy-dom）。

**Spec:** `docs/specs/2026-11-11-film-node-graph-design.md`（已并入 Fable 设计审查意见）。

---

## 全局约束

- **提交**：
  - 只 `git add` 具体文件。不用 `git add -A` / `git add -N` / `git commit -a`。
  - 提交信息用中文、描述式，**不带任何 Claude 署名**：不要 `Co-Authored-By`，不要 `Claude-Session`。
- **后端检查**：在 `backend/` 下用 `.venv/bin/python` 直接跑脚本（venv 里没有 pytest）。每个任务结束时，下面的脚本都要打印 `ALL PASS`（本计划新建的脚本只算到当前任务为止已存在的）：
  - 已有：
    - `tests/render/test_session.py`、`tests/render/test_runner.py`、`tests/render/test_compose.py`、`tests/render/test_export_fcpxml.py`
    - `tests/server/test_render.py`、`tests/server/test_compose.py`、`tests/server/test_novels.py`、`tests/server/test_assistant_ops.py`、`tests/server/test_assistant.py`
  - 新建：
    - `tests/render/test_free.py`（Task 1）、`tests/render/test_free_compose.py`（Task 2）、`tests/render/test_free_runner.py`（Task 5）
    - `tests/server/test_render_free.py`（Task 6）
  - 一次跑完的命令：

    ```bash
    cd backend && for f in tests/render/test_session.py tests/render/test_runner.py tests/render/test_compose.py tests/render/test_export_fcpxml.py tests/render/test_free*.py tests/server/test_render*.py tests/server/test_compose.py tests/server/test_novels.py tests/server/test_assistant_ops.py tests/server/test_assistant.py; do printf "%s: " $f; .venv/bin/python $f 2>&1 | tail -1; done
    ```
- **前端检查**（在 `frontend/` 下）：
  - `npm test` 全部通过。现在 17 套，Task 9 后 18 套，Task 11 后 19 套。
  - `npm run lint`：0 error，warning **不超过 5 个**（现在正好 5 个，新代码不能再加 warning：`react-hooks/exhaustive-deps` 要写全依赖；组件文件只导出组件）。
  - `npx vite build` 成功。
- **不花钱**：
  - 测试一律用假厂商 `FakeVideo`。
  - 不运行 `backend/render/smoke.py`、`backend/assistant/smoke.py`，不调真实厂商，不往运行中的服务发请求。
- **密钥**：不读、不打印 `backend/.env`。
- **不碰**：`docs/specs/2026-10-27-commercialization-design-contract.md`（保持未跟踪、不修改）。
- **风格**：
  - 跟随周边代码：中文注释、注释密度与命名习惯一致。
  - 后端报错文字用中文。
  - 前端界面文字进 `src/i18n/zh.ts` 与 `src/i18n/en.ts`，两边键一致（类型检查强制）；源码里注释以外不写中文。

## 实施裁定

spec 没写死、或与现有代码有出入的地方，按下面执行：

1. **超出单章上限的状态码**：沿用现有映射 `BudgetExceeded → 422`（`_render_call`），不按 spec §2 表里写的 409。剧本段接口一直如此，前端也按 422 处理。
2. **PATCH 只校验传了的字段**：
   - 传了 `refs` 或 `first_frame` 时再查参考位数量；
   - 传了 `target` 时连带查时长；
   - 生成（run）时全量校验。

   这样关键帧被删了也不会挡住改正文。
3. **自由节点卡的「设为这一段的采用」**：只针对卡片当前显示的那次尝试（用 ‹ › 在自身尝试间切换）。spec 原文是「每次成功尝试旁都有」，这里不在卡片上列全部尝试。
4. **花钱前的确认**放在卡片里（显示金额 + 确认 / 取消），不用出片面板的 `MoneyConfirm` 对话框。`useFilm` 新增 `runClipNow` / `runFree`：服务端 409 带了新金额时返回新金额，由卡片再问一次。
5. **节点图是盖在时间轴上的绝对定位层**（`.ngv`，z-index 1；底部工具条 `.tlc__bar` 是 z-index 2，仍在上面），不卸载时间轴。
   - 平移、缩放的事件在这一层内处理，不往下传。
   - Esc 用 window 捕获阶段监听：有选中时先取消选中并 `preventDefault`。画布自己的 Esc 处理遇到 `defaultPrevented` 会直接返回，不会关掉画布。
6. **资产分组**：风格 → 角色 → 生物 → 场景 → 道具。spec §5.2 里「主要角色 / 其他角色」不单独分组，角色组内按「被几段剧本段用到」降序，再按资产卡顺序。
7. **卡片高度**：剧本段卡 208，自由节点卡 340（spec 写的 176 放不下卡片内容）。常量在 `nodeGraph.ts`。
8. **没有版本时不显示「时间轴 / 节点图」切换**，与「出片」页签同一判断（`film.enabled`），不做禁用加提示。
9. **删除节点时**，先在会话锁内改记录，出锁后再删文件。只删没有被剧本段（含 orphaned）复制件引用的文件。
10. **独立素材的「下载」是两步**：先取 blob，取到后变成下载链接。原因是 `filmFileUrl` 要带 token，`<a href>` 不能直接用接口地址。
11. **会话视图的 `options` 增加 `first_frame`、`frame_with_refs`**：前端要据此算参考位上限（首帧是否占位）。
12. **新测试放新文件**，不往已有的大 `main()` 里插：
    - 后端：`test_free.py`、`test_free_compose.py`、`test_free_runner.py`、`test_render_free.py`。
    - 前端：纯函数 `tests/node-graph.test.ts`；界面测试 `tests/graph-view.test.tsx`。界面测试不叫 `node-graph.test.tsx`，因为与纯函数测试会生成同名的 `.ssrout/node-graph.test.js`。
    - 例外：`film-lane.test.ts`、`test_export_fcpxml.py` 只在末尾追加一块。

## 文件结构

**后端**
- 改 `backend/render/session.py`：
  - `FREE_PREFIX`、`is_free`、`items`、`any_in_flight`、`_item`、`_sync_free`、`_deliver`；
  - `build` 保留与同步 `free`；`view` 带 `free` / `free_seq` / `over_refs` / 新 `options`；
  - 迁移函数按 id 查两个列表；`recover`、`begin_compose`、`queue_run`、`begin_submit` 统一遍历；
  - `_style_outdated` 豁免复制件。
- 改 `backend/render/compose.py`：`free_slots_needed`、`ASSET_ROLES`、`asset_slot`、`FreeInvalid`、`request_for_free`。
- 新建 `backend/render/free.py`：`Ctx`、`derive_prompt`、`tail_source`、`tail_frame`、`validate`、`create`、`update`、`delete`、`queue`、`set_chosen`。
- 改 `backend/render/runner.py`：遍历 `sess.items(s)`、`_settle` 用 `any_in_flight`、`FreeInvalid` 记失败。
- 改 `backend/server/novels.py`：`delete_version` 用 `any_in_flight`。
- 改 `backend/server/app.py`：`_render_request` 按 id 分派；新接口 `/free`、`/free/{fid}`、`/free/{fid}/run`、`/free/{fid}/chosen`。
- 改 `backend/render/export_fcpxml.py`：`extra_media`、`readme(..., extras)`、`export` 打包 `media/extra/`。
- 新测试：`backend/tests/render/test_free.py`、`test_free_compose.py`、`test_free_runner.py`、`backend/tests/server/test_render_free.py`。
- 改测试：`backend/tests/render/test_export_fcpxml.py`（末尾追加）。

**前端**
- 改 `frontend/src/types.ts`：`FilmFreeNode`、`FreePatch`、`FilmAttempt.free_id`、`FilmSession.free / free_seq / options.first_frame / options.frame_with_refs`。
- 改 `frontend/src/api.ts`：`createFreeNode`、`patchFreeNode`、`deleteFreeNode`、`runFreeNode`、`chooseFreeAttempt`。
- 改 `frontend/src/film.ts`：
  - 新增 `STYLE_REF`、`freeNodes`、`anyInFlight`、`slotsNeeded`、`tailSources`、`copyIndex`；
  - `inFlight`、`chosenAttempt`、`firstFrameText` 放宽参数类型；
  - `pollDelay` 看自由节点，`mainAction` 忽略复制件。
- 改 `frontend/src/useFilm.ts`：`runClipNow`、`createFree`、`patchFree`、`deleteFree`、`runFree`、`chooseFree`。
- 新建 `frontend/src/nodeGraph.ts`（纯函数）。
- 新建 `frontend/src/components/NodeGraph.tsx`（视图）、`frontend/src/components/NodeCards.tsx`（卡片）。
- 新建 `frontend/src/styles/nodegraph.css`；改 `frontend/src/styles/app.css`（引入）。
- 改 `frontend/src/components/TimelineCanvas.tsx`（切换与挂载）、`frontend/src/components/FilmPanel.tsx`（设置判断在跑、自由节点详情）。
- 改 `frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`（`film.tail`、`graph.*`）。
- 新测试：`frontend/tests/node-graph.test.ts`、`frontend/tests/graph-view.test.tsx`。
- 改：`frontend/tests/film-lane.test.ts`（末尾追加）、`frontend/package.json`（`test` 脚本加两套）。

---

### Task 1: 会话里的 free 列表、统一遍历与 build 同步

**Files:**
- Modify: `backend/render/session.py`
- Modify: `backend/render/compose.py`（只加 `free_slots_needed`）
- Create: `backend/tests/render/test_free.py`

- [ ] **Step 1: 写失败的测试 `backend/tests/render/test_free.py`**

```python
#!/usr/bin/env python3
"""自由节点（会话侧）：旧会话兼容、统一遍历与查找、build 保留与挂靠同步、迁移函数、重启恢复、合成互锁与上限。
后续任务在这里追加：新建、派生、修改、删除、排队与采用；挂靠节点下载后复制进目标段。

全程临时目录 + 假厂商，不联网、不花钱。用法: python3 tests/render/test_free.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"

from render import providers, session as sess  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}
DOC = json.loads(YAO.read_text(encoding="utf-8"))
FAKE = FakeVideo()
providers.register("fake", lambda: FAKE)
_TMP = tempfile.TemporaryDirectory()


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def rich(doc):
    """给资产卡补上可用的参考图（http 地址），参考位才有图可用。"""
    d = copy.deepcopy(doc)
    for kind in ("characters", "creatures", "props"):
        for card in d["assets"].get(kind) or []:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
    for card in d["assets"]["locations"]:
        for a in card.get("angles") or []:
            a["uri"] = f"https://img/{card['id']}-{a['angle']}.png"
    return d


def new_root(name):
    return Path(_TMP.name) / name / "render" / "v"


def build(root, doc=DOC, allow_in_flight=False, **patch):
    return sess.build(root, doc, owner=OWNER, patch=patch, keyframes={}, allow_in_flight=allow_in_flight)


def node(fid="F01", **over):
    n = {"id": fid, "target": None, "target_shots": None, "target_lost": False, "prompt": "雨夜街头，一盏路灯",
         "refs": [], "first_frame": None, "duration": 4.0, "estimate_cny": 4.0, "state": "planned",
         "error": None, "uncertain": False, "attempts": [], "chosen": None,
         "created_at": "2026-11-11T00:00:00+00:00"}
    n.update(over)
    return n


def put_free(root, *nodes, seq=None):
    """直接写会话里的自由节点（不经接口），测试会话侧的行为。"""
    with sess.mutate(root) as s:
        s["free"] = list(nodes)
        s["free_seq"] = len(nodes) if seq is None else seq


def item(s, iid):
    return next(x for x in sess.items(s) if x["id"] == iid)


def finish(root, iid):
    """不经出片线程把一条（已排队的段或自由节点）走完：提交 → 成功 → 下载。返回任务 id。"""
    snap = sess.begin_submit(root, iid)
    assert snap is not None, iid
    s = sess.load(root)
    req = base.ClipRequest(prompt=snap["prompt"], model=s["model"], duration=snap["duration"],
                           resolution=s["resolution"])
    tid = FAKE.submit(req)
    sess.submitted(root, iid, tid, None)
    st = FAKE.poll(tid)
    sess.poll_update(root, iid, st)
    files = FAKE.download(st, sess.clip_dest(root, iid, tid))
    sess.downloaded(root, iid, files, FAKE.cost(st, req))
    return tid


def part_session():
    root = new_root("session")
    caps = FAKE.caps("fake-1")

    # 1. 旧会话没有 free：读出来补空列表；视图带 free、free_seq 与厂商能力
    s = build(root)
    assert s["free"] == [] and s["free_seq"] == 0
    with sess.mutate(root) as raw:
        raw.pop("free")
        raw.pop("free_seq")
    s = build(root)
    assert s["free"] == [] and s["free_seq"] == 0
    v = sess.view(s)
    assert v["free"] == [] and v["free_seq"] == 0
    assert v["options"]["first_frame"] is True and v["options"]["frame_with_refs"] is False
    print("1. 旧会话兼容 ✓")

    # 2. 统一遍历与按 id 查找
    first, second = s["clips"][0], s["clips"][1]
    put_free(root, node("F01"), node("F02", state="queued"))
    s = sess.load(root)
    assert [x["id"] for x in sess.items(s)][-2:] == ["F01", "F02"]
    assert sess.any_in_flight(s) and sess.is_free("F01") and not sess.is_free(first["id"])
    assert sess._item(s, "F02")["state"] == "queued" and sess._item(s, first["id"])["id"] == first["id"]
    must_raise(sess.NotFound, sess._item, s, "F09")
    print("2. 统一遍历 ✓")

    # 3. build 保留 free 与序号；挂靠节点时长跟随目标段；在跑的节点原样不动；有节点在跑时不能改设置
    put_free(root, node("F01", target=first["id"], target_shots=list(first["shots"]), duration=1.0),
             node("F02", state="queued", target="E99-C01", target_shots=["X"]), seq=7)
    s = build(root, allow_in_flight=True)
    f1, f2 = item(s, "F01"), item(s, "F02")
    assert s["free_seq"] == 7
    assert f1["duration"] == first["duration"]
    assert f1["estimate_cny"] == base.estimate_cny(first["duration"], caps, "720p")
    assert f2["target"] == "E99-C01" and not f2["target_lost"], "在跑的节点不动"
    must_raise(sess.Conflict, build, root, resolution="480p")
    print("3. build 保留与同步 ✓")

    # 4. 目标段消失或同 id 换了镜头 → 转独立素材；改分辨率重算预估
    put_free(root, node("F01", target="E99-C01", target_shots=["X"]),
             node("F02", target=first["id"], target_shots=["E01-SH999"]),
             node("F03", target=second["id"], target_shots=list(second["shots"])))
    s = build(root)
    assert item(s, "F01")["target"] is None and item(s, "F01")["target_lost"]
    assert item(s, "F02")["target"] is None and item(s, "F02")["target_lost"], "同 id 换了镜头也算没了"
    assert item(s, "F03")["target"] == second["id"] and not item(s, "F03")["target_lost"]
    s = build(root, resolution="480p")
    assert item(s, "F01")["estimate_cny"] == base.estimate_cny(4.0, caps, "480p")
    build(root, resolution="720p")
    print("4. 目标段消失 ✓")

    # 5. 视图：在跑预留含自由节点；参考位超限标记；计数只看剧本段
    put_free(root, node("F01", state="queued", estimate_cny=3.0),
             node("F02", refs=["a", "b", "c"], first_frame="keyframe:x"))
    v = sess.view(sess.load(root))
    assert v["reserved_cny"] == 3.0
    assert [x["over_refs"] for x in v["free"]] == [False, True]
    assert "queued" not in v["counts"], "计数只看剧本段"
    print("5. 视图 ✓")

    # 6. 迁移函数按 id 也认自由节点：提交、轮询、下载；文件按节点 id 命名；花费计入已花
    put_free(root, node("F01", state="queued"))
    spent0 = sess.load(root)["spent_cny"]
    tid = finish(root, "F01")
    s = sess.load(root)
    f = item(s, "F01")
    assert f["state"] == "done" and f["chosen"] == 0 and f["attempts"][0]["fingerprint"] is None
    assert f["attempts"][0]["file"] == f"clips/F01.{tid}.mp4" and (root / f["attempts"][0]["file"]).is_file()
    assert s["spent_cny"] == round(spent0 + f["attempts"][0]["cost_cny"], 2) > spent0
    print("6. 迁移函数 ✓")

    # 7. 重启恢复：自由节点提交中断标失败、待核对；有自由节点在排队时报告还要续
    put_free(root, node("F01", state="queued"), node("F02", state="queued"))
    assert sess.begin_submit(root, "F01") is not None      # 提交中断：没拿到任务 id
    assert sess.recover(root) is True, "F02 还在排队"
    f1 = item(sess.load(root), "F01")
    assert f1["state"] == "failed" and f1["uncertain"] and f1["attempts"][-1]["state"] == "failed"
    put_free(root, node("F01"))
    assert sess.recover(root) is False
    print("7. 重启恢复 ✓")

    # 8. 互锁：有自由节点在跑时不能合成；排队剧本段的上限算上在跑的自由节点
    put_free(root, node("F01", state="queued", estimate_cny=150.0))
    must_raise(sess.Conflict, sess.begin_compose, root, fingerprint="fp", tts_cny=0.0, draft=True)
    put_free(root, seq=1)
    est = item(sess.load(root), first["id"])["estimate_cny"]
    build(root, budget_cny=150 + est - 0.01)
    put_free(root, node("F01", state="queued", estimate_cny=150.0))
    must_raise(sess.BudgetExceeded, sess.queue_run, root, [first["id"]])
    put_free(root, node("F01", estimate_cny=150.0))
    assert item(sess.queue_run(root, [first["id"]]), first["id"])["state"] == "queued"
    print("8. 合成互锁与上限 ✓")


def main() -> int:
    part_session()
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && .venv/bin/python tests/render/test_free.py`
Expected: FAIL，`KeyError: 'free'`（`build` 还没有带 `free`）。

- [ ] **Step 3: `compose.py` 加 `free_slots_needed`**

放在 `pick_refs` 函数之后：

```python
def free_slots_needed(refs: list, first_frame: Optional[str], caps) -> int:
    """自由节点要占几个参考位：参考图各一个；带首帧、又有参考图、厂商不能首帧与参考图同用时，
    首帧再占一个（与剧本段 frame_mode="ref" 同规则）。"""
    return len(refs) + (1 if first_frame and refs and not caps.frame_with_refs else 0)
```

- [ ] **Step 4: `session.py` 加常量与遍历辅助**

在 `COMPOSE_INTERRUPTED = …` 这一行后加：

```python
FREE_PREFIX = "F"          # 自由节点 id 前缀（F01、F02…）；段 id 是 E01-C01，不会冲突
```

在 `_clip` 函数之后加：

```python
def is_free(item_id: str) -> bool:
    return str(item_id).startswith(FREE_PREFIX)


def items(s: dict) -> list:
    """出片线程要推进的全部条目：剧本段在前，自由节点在后。凡是「有没有在跑」「在跑预留多少」都按它算。"""
    return list(s["clips"]) + list(s.get("free") or [])


def any_in_flight(s: dict) -> bool:
    return any(c["state"] in IN_FLIGHT for c in items(s))


def _item(s: dict, item_id: str) -> dict:
    """按 id 在剧本段与自由节点里找（出片线程的迁移函数用）。"""
    for c in items(s):
        if c["id"] == item_id:
            return c
    raise NotFound(f"没有这一段：{item_id}")
```

- [ ] **Step 5: `session.py` 的 `build` 保留并同步 `free`**

在 `def build(` 之前加：

```python
def _sync_free(nodes: list, clips: list, caps, resolution: str) -> list:
    """重建会话时带上自由节点：在跑的原样不动（落地之后的下一次重建再同步）；挂靠的段不在了或同 id
    换了镜头就转为独立素材（target_lost）；挂靠的时长跟随目标段；预估按当前设置重算。"""
    by_id = {c["id"]: c for c in clips}
    for n in nodes:
        if n["state"] in IN_FLIGHT:
            continue
        if n.get("target"):
            t = by_id.get(n["target"])
            if t is None or t["shots"] != n.get("target_shots"):
                n.update(target=None, target_shots=None, target_lost=True)
            else:
                n["duration"] = t["duration"]
        n["estimate_cny"] = base.estimate_cny(n["duration"], caps, resolution)
    return nodes
```

在 `build` 里把

```python
        flying = {cid: c for cid, c in olds.items() if c["state"] in IN_FLIGHT}
        if flying and (not allow_in_flight or any(v is not None for v in (patch or {}).values())):
            raise Conflict("有段在排队或生成中，等它们结束再改设置")
```

改成

```python
        flying = {cid: c for cid, c in olds.items() if c["state"] in IN_FLIGHT}
        old_free = list((old or {}).get("free") or [])
        free_flying = any(n["state"] in IN_FLIGHT for n in old_free)
        if (flying or free_flying) and (not allow_in_flight or any(v is not None for v in (patch or {}).values())):
            raise Conflict("有段在排队或生成中，等它们结束再改设置")
```

把 `s = {"version": 1, …}` 那一段改成（新增 `free`、`free_seq` 两个键）：

```python
        s = {"version": 1, "owner": owner, **settings,
             "spent_cny": (old or {}).get("spent_cny", 0.0), "clips": clips,
             "orphaned": list(orph.values()),
             "free": _sync_free(old_free, clips, caps, settings["resolution"]),
             "free_seq": int((old or {}).get("free_seq") or 0),
             "voices": (old or {}).get("voices", {}), "final": (old or {}).get("final"),
             "created_at": (old or {}).get("created_at") or _now()}
```

- [ ] **Step 6: `session.py` 的 `view`**

把

```python
    out["reserved_cny"] = round(sum(c["estimate_cny"] for c in s["clips"]
                                    if c["state"] in IN_FLIGHT), 2)
```

改成

```python
    out["reserved_cny"] = round(sum(c["estimate_cny"] for c in items(s)
                                    if c["state"] in IN_FLIGHT), 2)
    # 自由节点：参考位超出当前厂商上限（改了设置）时标出来，删减之前生成会被拒
    out["free"] = [dict(n, uncertain=bool(n.get("uncertain")),
                        over_refs=compose.free_slots_needed(n["refs"], n.get("first_frame"), caps) > caps.max_refs)
                   for n in s.get("free") or []]
    out["free_seq"] = int(s.get("free_seq") or 0)
```

在 `out["options"] = {…}` 字典里，`"max_refs": caps.max_refs,` 后面加两项：

```python
                      "first_frame": caps.first_frame, "frame_with_refs": caps.frame_with_refs,
```

- [ ] **Step 7: `session.py` 的排队、提交与各迁移函数**

1. `queue_run` 里把
   ```python
           reserved = sum(c["estimate_cny"] for c in s["clips"] if c["state"] in IN_FLIGHT)
   ```
   改成
   ```python
           reserved = sum(c["estimate_cny"] for c in items(s) if c["state"] in IN_FLIGHT)
   ```

2. `begin_submit` 里：
   - `c = _clip(s, clip_id)` 改成 `c = _item(s, clip_id)`；
   - `running = sum(x["estimate_cny"] for x in s["clips"] if x["state"] in ("running", "downloading"))` 改成 `running = sum(x["estimate_cny"] for x in items(s) if x["state"] in ("running", "downloading"))`；
   - 追加尝试那行的 `"fingerprint": c["fingerprint"]` 改成 `"fingerprint": c.get("fingerprint")`（自由节点没有指纹）。

3. `submitted`、`submit_failed`、`poll_update`、`note_error`、`download_failed` 里的 `c = _clip(s, clip_id)` / `_clip(s, clip_id)["error"] = msg` 全部改用 `_item`。

4. `downloaded` 整个函数换成：

```python
def downloaded(root, clip_id: str, files: dict, cost: float) -> None:
    with mutate(root) as s:
        c = _item(s, clip_id)
        if c["state"] != "downloading":
            return
        a = c["attempts"][-1]
        a.update(state="succeeded", file=_rel(root, files["video"]),
                 last_frame=_rel(root, files.get("last_frame")), cost_cny=cost)
        s["spent_cny"] = round(s["spent_cny"] + cost, 2)
        c["chosen"] = len(c["attempts"]) - 1
        if is_free(c["id"]):
            c["state"] = "done"         # 自由节点不依赖分镜，没有过期
        else:
            c["state"] = "done" if a["fingerprint"] == c["fingerprint"] else "stale"
        c["error"] = None
```

- [ ] **Step 8: `session.py` 的 `recover` 与 `begin_compose`**

`recover` 里：
- `for c in s["clips"]:` 改成 `for c in items(s):`；
- 最后一行 `return any(c["state"] in IN_FLIGHT for c in s["clips"])` 改成 `return any_in_flight(s)`。

`begin_compose` 里把

```python
        if any(c["state"] in IN_FLIGHT for c in s["clips"]):
```

改成

```python
        if any_in_flight(s):
```

（提示文字不变。）

- [ ] **Step 9: 运行新测试，确认通过**

Run: `cd backend && .venv/bin/python tests/render/test_free.py`
Expected: 1–8 各行 ✓，最后 `ALL PASS`。

- [ ] **Step 10: 跑全局约束里的后端脚本**

Run: 全局约束里的一次跑完命令。
Expected: 每个脚本都是 `ALL PASS`（现有出片测试不改即通过）。

- [ ] **Step 11: Commit**

```bash
git add backend/render/session.py backend/render/compose.py backend/tests/render/test_free.py
git commit -m "出片会话加自由节点列表：free 与 free_seq 随重建保留，挂靠节点跟随目标段时长、目标段消失或换镜头转独立素材；在跑判断、在跑预留、上限、合成互锁、重启恢复与出片线程的迁移函数统一覆盖剧本段与自由节点；视图带参考位超限标记与首帧能力"
```

---

### Task 2: 自由节点的厂商请求 `request_for_free`

**Files:**
- Modify: `backend/render/compose.py`
- Create: `backend/tests/render/test_free_compose.py`

- [ ] **Step 1: 写失败的测试 `backend/tests/render/test_free_compose.py`**

```python
#!/usr/bin/env python3
"""自由节点的厂商请求：按 refs 顺序拼参考行与参考图（编号一致，改顺序后照样一致）、首帧两种来源、
首帧占参考位、风格图、复查不过抛 FreeInvalid。用法: python3 tests/render/test_free_compose.py
"""
import copy
import dataclasses
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import compose  # noqa: E402
from render.plan import assets_index  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from render.providers.seedance import rewrite_refs  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
SESSION = {"provider": "fake", "model": "fake-1", "resolution": "720p", "audio_mode": "tts_all"}


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def rich(doc):
    d = copy.deepcopy(doc)
    for kind in ("characters", "creatures", "props"):
        for card in d["assets"].get(kind) or []:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
    for card in d["assets"]["locations"]:
        for a in card.get("angles") or []:
            a["uri"] = f"https://img/{card['id']}-{a['angle']}.png"
    return d


def main() -> int:
    plain = json.loads(YAO.read_text(encoding="utf-8"))
    doc = rich(plain)
    idx = assets_index(doc)
    caps = FakeVideo().caps("fake-1")          # max_refs 3，首帧与参考图不能同用
    chars = [c["id"] for c in doc["assets"]["characters"]]
    loc = next(c for c in doc["assets"]["locations"] if c.get("angles"))
    shot = doc["episodes"][0]["shots"][0]["id"]
    tmp = Path(tempfile.mkdtemp())
    kf = tmp / "kf.png"
    kf.write_bytes(PNG)
    tail = tmp / "x.last.jpg"
    tail.write_bytes(b"\xff\xd8\xff\xe0jpg")

    def name(aid):
        return compose.asset_slot(idx, aid)["name"]

    def node(**over):
        return {"id": "F01", "prompt": "雨夜街头", "refs": [], "first_frame": None, "duration": 4.0, **over}

    def req_for(n, d=doc, keyframes=None, tail_frame=None, use_caps=caps, style=None):
        return compose.request_for_free(d, SESSION, n, keyframes=keyframes or {}, tail_frame=tail_frame,
                                        caps=use_caps, rewrite=rewrite_refs, style=style)

    # 1. 按 id 取参考位：类别由 id 所在的那一类决定，不分着装 / 机位；参考位计数
    sl = compose.asset_slot(idx, chars[0])
    assert sl["role"] == "character" and sl["variant"] is None
    assert sl["name"] == doc["assets"]["characters"][0]["name"]
    assert compose.asset_slot(idx, loc["id"])["role"] == "location"
    assert compose.asset_slot(idx, "ZZ") is None
    assert compose.free_slots_needed(["a", "b"], "keyframe:x", caps) == 3
    assert compose.free_slots_needed([], "keyframe:x", caps) == 0
    assert compose.free_slots_needed(["a"], None, caps) == 1
    print("1. 资产参考位 ✓")

    # 2. 参考行按 refs 顺序编号，参考图同序；换顺序后编号跟着走
    for refs in ([chars[0], loc["id"]], [loc["id"], chars[0]]):
        req, used = req_for(node(refs=refs))
        lines = req.prompt.splitlines()
        assert lines[0] == "雨夜街头" and used is None and req.first_frame is None
        assert lines[1:] == [f"【参考】@图片{i + 1} {name(a)}" for i, a in enumerate(refs)], lines
        assert [r.asset_id for r in req.refs] == refs and req.refs[0].source.startswith("https://img/")
        assert (req.duration, req.model, req.resolution, req.style_ref) == (4.0, "fake-1", "720p", None)
    print("2. 参考编号与顺序 ✓")

    # 3. 关键帧作首帧：有参考且厂商不能同用 → 首帧占第一个参考位，【首帧】行排在最前；超位抛错
    req, used = req_for(node(refs=chars[:2], first_frame=f"keyframe:{shot}"), keyframes={shot: kf})
    assert used == f"keyframe:{shot}" and req.first_frame is None
    assert [r.role for r in req.refs] == ["first_frame", "character", "character"]
    lines = req.prompt.splitlines()
    assert lines[1].startswith("【首帧】@图片1") and lines[2].startswith("【参考】@图片2")
    must_raise(compose.FreeInvalid, req_for, node(refs=chars[:3], first_frame=f"keyframe:{shot}"),
               keyframes={shot: kf})
    print("3. 首帧占参考位 ✓")

    # 4. 尾帧作首帧、不带参考：直接作首帧
    req, used = req_for(node(first_frame="tail:E01-C01"), tail_frame=tail)
    assert used == "tail:E01-C01" and req.first_frame.startswith("data:image/jpeg;base64,") and req.refs == []
    print("4. 尾帧作首帧 ✓")

    # 5. 风格图：按 refs 里的位置放，带上哈希
    style = {"source": "data:image/png;base64,AAAA", "hash": "h1"}
    req, _ = req_for(node(refs=[chars[0], compose.STYLE_ID]), style=style)
    assert [r.role for r in req.refs] == ["character", "style"] and req.style_ref == "h1"
    assert req.prompt.splitlines()[2] == f"【参考】@图片2 {compose.STYLE_TEXT}"
    print("5. 风格图 ✓")

    # 6. 复查不过：抛 FreeInvalid（不提交、不花钱）
    for n, kw in (
        (node(prompt="  "), {}),
        (node(refs=[chars[0]]), {"d": plain}),                    # 资产图被删
        (node(refs=["ZZ"]), {}),
        (node(refs=[compose.STYLE_ID]), {}),                       # 风格图已删
        (node(first_frame=f"keyframe:{shot}"), {}),                # 关键帧没了
        (node(first_frame="tail:E01-C01"), {"tail_frame": tmp / "nope.jpg"}),
        (node(first_frame="tail:E01-C01"), {}),
        (node(first_frame=f"keyframe:{shot}"), {"keyframes": {shot: kf},
                                                "use_caps": dataclasses.replace(caps, first_frame=False)}),
    ):
        must_raise(compose.FreeInvalid, req_for, n, **kw)
    print("6. 复查不过 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && .venv/bin/python tests/render/test_free_compose.py`
Expected: FAIL，`AttributeError: module 'render.compose' has no attribute 'asset_slot'`。

- [ ] **Step 3: 在 `compose.py` 实现**

在 `free_slots_needed`（Task 1 加的）之后加：

```python
ASSET_ROLES = {"characters": "character", "creatures": "creature", "locations": "location", "props": "prop"}


def asset_slot(assets_idx: dict, asset_id: str) -> Optional[dict]:
    """自由节点按资产 id 取参考位：类别由 id 所在的那一类决定，不分着装 / 机位（image_for 取第一张可用图）。"""
    for kind, role in ASSET_ROLES.items():
        card = assets_idx[kind].get(asset_id)
        if card is not None:
            return {"asset_id": asset_id, "role": role, "variant": None, "name": card.get("name", asset_id)}
    return None
```

在 `class Stale` 之后加：

```python
class FreeInvalid(Exception):
    """自由节点提交前复查没过（参考图或尾帧没了、参考位不够、提示词为空）：记失败、不提交、不花钱。"""
```

在 `request_for` 函数之后加：

```python
def request_for_free(doc: dict, session: dict, node: dict, *, keyframes: dict, tail_frame,
                     caps, rewrite, style: Optional[dict] = None) -> tuple:
    """自由节点 → 厂商请求。返回 (ClipRequest, 实际使用的首帧来源或 None)。

    node["prompt"] 只是正文；这里按 refs 顺序补【首帧】/【参考】行再整体改写，占位符编号与请求里
    图片的顺序一致（Seedance 按出现顺序编 @图片n）。tail_frame：首帧为 tail:<id> 时那次尝试的尾帧文件。
    """
    if not (node.get("prompt") or "").strip():
        raise FreeInvalid("提示词是空的")
    idx = assets_index(doc)
    slots = []
    for aid in node.get("refs") or []:
        if aid == STYLE_ID:
            if not style:
                raise FreeInvalid("风格图已删除，请从参考里去掉它")
            slots.append({"asset_id": STYLE_ID, "role": "style", "text": STYLE_TEXT, "source": style["source"]})
            continue
        slot = asset_slot(idx, aid)
        src = image_for(slot, idx) if slot else None
        if not src:
            raise FreeInvalid(f"{aid} 没有可用的参考图了")
        slots.append({**slot, "text": slot["name"], "source": src})
    ff = node.get("first_frame")
    image, used = None, None
    if ff:
        if not caps.first_frame:
            raise FreeInvalid("当前厂商不支持指定首帧")
        if ff.startswith("keyframe:"):
            path = keyframes.get(ff[len("keyframe:"):])
            if not path or not Path(path).is_file():
                raise FreeInvalid(f"首帧用的关键帧没了：{ff[len('keyframe:'):]}")
        elif ff.startswith("tail:"):
            path = tail_frame
            if path is None or not Path(path).is_file():
                raise FreeInvalid(f"首帧用的尾帧找不到了：{ff[len('tail:'):]}")
        else:
            raise FreeInvalid(f"看不懂的首帧来源：{ff}")
        image, used = data_uri(Path(path)), ff
    frame_mode = ("ref" if slots and not caps.frame_with_refs else "frame") if image else None
    need = len(slots) + (1 if frame_mode == "ref" else 0)
    if need > caps.max_refs:
        raise FreeInvalid(f"参考超出当前厂商上限（{need} / {caps.max_refs}）")
    lines, refs = [node["prompt"].strip()], []
    if frame_mode == "ref":
        lines.append(f"【首帧】{ref(FIRST)} 本段开场画面，保持构图与人物位置")
        refs.append(RefImage(FIRST, "first_frame", image))
        image = None
    for sl in slots:
        lines.append(f"【参考】{ref(sl['asset_id'])} {sl['text']}")
        refs.append(RefImage(sl["asset_id"], sl["role"], sl["source"]))
    aspect = (doc.get("meta") or {}).get("video", {}).get("aspect_ratio", "9:16")
    req = ClipRequest(prompt=rewrite("\n".join(lines)), model=session["model"], duration=node["duration"],
                      resolution=session["resolution"], aspect=aspect,
                      audio=session["audio_mode"] != "silent" and caps.native_audio,
                      refs=refs, first_frame=image,
                      style_ref=style["hash"] if style and STYLE_ID in (node.get("refs") or []) else None)
    return req, used
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd backend && .venv/bin/python tests/render/test_free_compose.py`
Expected: 1–6 ✓，`ALL PASS`。

- [ ] **Step 5: 跑全局约束里的后端脚本**

Expected: 全部 `ALL PASS`。

- [ ] **Step 6: Commit**

```bash
git add backend/render/compose.py backend/tests/render/test_free_compose.py
git commit -m "自由节点的厂商请求：正文之后按参考顺序拼首帧行与参考行再整体改写，占位编号与参考图顺序一致；首帧可用关键帧或某次尝试的尾帧，与参考图不能同用时占第一个参考位；风格图按位置放并记哈希；参考图、尾帧、关键帧缺失或超位时抛 FreeInvalid，不提交"
```

---

### Task 3: 自由节点的新建、派生、修改、删除、排队与采用（`render/free.py`）

**Files:**
- Create: `backend/render/free.py`
- Modify: `backend/tests/render/test_free.py`

- [ ] **Step 1: 在 `test_free.py` 追加失败的测试**

1. 在顶部导入区 `from render import providers, session as sess  # noqa: E402` 这一行改成：

```python
from render import compose, free, providers, session as sess  # noqa: E402
```

2. 在 `def main()` 之前加：

```python
def part_crud():
    root = new_root("crud")
    doc = rich(DOC)
    s = build(root, doc)
    ctx = free.Ctx(doc, {}, False)
    caps = FAKE.caps("fake-1")
    clips = s["clips"]
    with_refs = next(c for c in clips if c["refs"])
    ids = [c["id"] for c in doc["assets"]["characters"]]

    # 9. 新建空白节点：编号递增，默认 5 秒、带预估
    s = free.create(root, ctx)
    f1 = item(s, "F01")
    assert (f1["target"], f1["prompt"], f1["refs"], f1["duration"], f1["state"]) == (None, "", [], 5.0, "planned")
    assert f1["estimate_cny"] == base.estimate_cny(5.0, caps, "720p") and s["free_seq"] == 1
    print("9. 新建 ✓")

    # 10. 派生：预填正文（去掉参考行与占位）、参考、时长、挂靠
    assert free.derive_prompt("雨夜\n【参考】@图片1 角色\n【首帧】{ref:__first__} 开场\n他看向@图片2 的方向") \
        == "雨夜\n他看向 的方向"
    s = free.create(root, ctx, with_refs["id"])
    f2 = item(s, "F02")
    assert f2["target"] == with_refs["id"] and f2["target_shots"] == with_refs["shots"]
    assert f2["refs"] == with_refs["refs"] and f2["duration"] == with_refs["duration"]
    assert f2["prompt"] and "【参考】" not in f2["prompt"] and "[参考" not in f2["prompt"]
    must_raise(sess.NotFound, free.create, root, ctx, "E99-C01")
    print("10. 派生 ✓")

    # 11. 派生时接力换成尾帧：上一段还没出 → 不带；出完 → tail:<上一段>
    root2 = new_root("relay")
    s2 = build(root2)
    relay = next(c for c in s2["clips"] if (c.get("first_frame") or "").startswith("relay:"))
    prev = relay["first_frame"][len("relay:"):]
    ctx2 = free.Ctx(DOC, {}, False)
    assert item(free.create(root2, ctx2, relay["id"]), "F01")["first_frame"] is None
    sess.queue_run(root2, [prev])
    finish(root2, prev)
    assert item(free.create(root2, ctx2, relay["id"]), "F02")["first_frame"] == f"tail:{prev}"
    print("11. 接力换尾帧 ✓")

    # 12. 修改与校验：不合法整条不写
    s = free.update(root, ctx, "F01", {"prompt": "雨夜街头", "refs": with_refs["refs"][:1]})
    assert item(s, "F01")["prompt"] == "雨夜街头" and item(s, "F01")["refs"] == with_refs["refs"][:1]
    for bad in ({"refs": ["ZZ"]}, {"refs": [ids[0], ids[0]]}, {"refs": ids[:4]}, {"refs": [compose.STYLE_ID]},
                {"first_frame": f"keyframe:{clips[0]['shots'][0]}"}, {"first_frame": "tail:F01"},
                {"first_frame": f"tail:{clips[0]['id']}"}, {"first_frame": "foo"},
                {"duration": 0.5}, {"duration": 11}, {"prompt": "长" * 2001}, {"bogus": 1}):
        must_raise(sess.SessionError, free.update, root, ctx, "F01", bad)
    must_raise(sess.SessionError, free.update, root, free.Ctx(DOC, {}, False), "F01", {"refs": [ids[0]]})
    assert item(sess.load(root), "F01")["prompt"] == "雨夜街头", "校验不过不写"
    s = free.update(root, free.Ctx(doc, {}, True), "F01", {"refs": [compose.STYLE_ID]})
    assert item(s, "F01")["refs"] == [compose.STYLE_ID]
    kshot = clips[0]["shots"][0]
    s = free.update(root, free.Ctx(doc, {kshot: "/kf.png"}, False), "F01", {"first_frame": f"keyframe:{kshot}"})
    assert item(s, "F01")["first_frame"] == f"keyframe:{kshot}"
    s = free.update(root, ctx, "F01", {"duration": 3})
    assert item(s, "F01")["duration"] == 3.0 and item(s, "F01")["estimate_cny"] == base.estimate_cny(3.0, caps, "720p")
    must_raise(sess.SessionError, free.update, root, ctx, "F02", {"duration": 3})   # 挂靠的跟随目标段
    s = free.update(root, ctx, "F01", {"target": with_refs["id"]})
    assert item(s, "F01")["duration"] == with_refs["duration"] and item(s, "F01")["target_shots"] == with_refs["shots"]
    s = free.update(root, ctx, "F01", {"target": None})
    assert item(s, "F01")["target"] is None
    must_raise(sess.NotFound, free.update, root, ctx, "F01", {"target": "E99-C01"})
    must_raise(sess.NotFound, free.update, root, ctx, "F09", {"prompt": "x"})
    print("12. 修改与校验 ✓")

    # 13. 排队：没写提示词不能生成；超确认线要带金额，金额不符重新确认；上限；在跑时不能再排、不能改、不能删；合成中不能生成
    free.create(root, ctx)                                              # F03 空白
    must_raise(sess.SessionError, free.queue, root, ctx, "F03")
    free.update(root, ctx, "F03", {"prompt": "空镜：河面", "duration": 10})
    with sess.mutate(root) as raw:
        raw["confirm_over_cny"] = 5.0
    e = must_raise(sess.Conflict, free.queue, root, ctx, "F03")
    total = item(sess.load(root), "F03")["estimate_cny"]
    assert e.expected_cny == total
    must_raise(sess.Conflict, free.queue, root, ctx, "F03", total + 1)
    with sess.mutate(root) as raw:
        raw["budget_cny"] = raw["spent_cny"] + total - 0.01
    must_raise(sess.BudgetExceeded, free.queue, root, ctx, "F03", total)
    with sess.mutate(root) as raw:
        raw["budget_cny"] = 100000.0
    s = free.queue(root, ctx, "F03", total)
    assert item(s, "F03")["state"] == "queued"
    must_raise(sess.Conflict, free.queue, root, ctx, "F03", total)
    must_raise(sess.Conflict, free.update, root, ctx, "F03", {"prompt": "改"})
    must_raise(sess.Conflict, free.delete, root, "F03")
    with sess.mutate(root) as raw:
        raw["final"] = {"state": "running"}
    must_raise(sess.Conflict, free.queue, root, ctx, "F01")
    with sess.mutate(root) as raw:
        raw["final"] = None
    print("13. 排队 ✓")

    # 14. 采用：只能采用成功的那次
    finish(root, "F03")
    assert item(free.set_chosen(root, "F03", 0), "F03")["chosen"] == 0
    must_raise(sess.SessionError, free.set_chosen, root, "F03", 3)
    print("14. 采用 ✓")

    # 15. 删除：被别的节点当尾帧来源时不能删；只删属于它自己的文件；编号不复用
    free.update(root, ctx, "F01", {"first_frame": "tail:F03"})
    must_raise(sess.Conflict, free.delete, root, "F03")
    free.update(root, ctx, "F01", {"first_frame": None})
    f3 = item(sess.load(root), "F03")
    own = root / f3["attempts"][0]["file"]
    with sess.mutate(root) as raw:          # 模拟已复制进剧本段的一次：共用同一文件
        raw["clips"][0]["attempts"].append(dict(f3["attempts"][0], free_id="F03", cost_cny=0.0))
    s = free.delete(root, "F03")
    assert "F03" not in [x["id"] for x in s["free"]] and own.is_file(), "共用的文件保留"
    s = free.create(root, ctx)
    assert s["free"][-1]["id"] == "F04" and s["free_seq"] == 4, "编号不复用"
    with sess.mutate(root) as raw:
        item(raw, "F04").update(prompt="x", state="queued")
    finish(root, "F04")
    a4 = item(sess.load(root), "F04")["attempts"][0]
    paths = [root / a4["file"], root / a4["last_frame"]]
    free.delete(root, "F04")
    assert not any(p.exists() for p in paths), "只属于它的文件一并删掉"
    print("15. 删除 ✓")
```

3. `main()` 里在 `part_session()` 之后加一行 `part_crud()`。

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && .venv/bin/python tests/render/test_free.py`
Expected: FAIL，`ImportError: cannot import name 'free' from 'render'`。

- [ ] **Step 3: 新建 `backend/render/free.py`**

```python
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

PROMPT_MAX = 2000
FIELDS = ("prompt", "refs", "first_frame", "duration", "target")
# 派生时从段的提示词里去掉的参考行与占位（厂商无关的 {ref:…}、Seedance 的 @图片n）
_REF_LINE = re.compile(r"^【(首帧|参考)】")
_PLACEHOLDER = re.compile(r"\{ref:[^{}]+\}|@图片\d+")


class Ctx(NamedTuple):
    doc: dict
    keyframes: dict         # 镜头 id → 关键帧图路径
    has_style: bool         # 本小说当前有风格图


def _free(s: dict, fid: str) -> dict:
    for n in s.get("free") or []:
        if n["id"] == fid:
            return n
    raise sess.NotFound(f"没有这个自由节点：{fid}")


def _caps(s: dict):
    return sess._provider(s["provider"]).caps(s["model"])


def derive_prompt(text: str) -> str:
    """段的提示词 → 自由节点的正文：去掉【首帧】/【参考】行与残余占位（参考行在生成时按 refs 重新拼）。"""
    lines = [ln for ln in (text or "").splitlines() if not _REF_LINE.match(ln.strip())]
    return _PLACEHOLDER.sub("", "\n".join(lines)).strip()[:PROMPT_MAX]


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
            raise sess.SessionError("参考里有重复的资产")
        idx = assets_index(ctx.doc)
        for aid in refs:
            if aid == compose.STYLE_ID:
                if not ctx.has_style:
                    raise sess.SessionError("这部小说还没有风格图")
                continue
            slot = compose.asset_slot(idx, aid)
            if slot is None:
                raise sess.SessionError(f"分镜里没有这个资产：{aid}")
            if not compose.image_for(slot, idx):
                raise sess.SessionError(f"{slot['name']}（{aid}）没有可用的参考图")
    if fields & {"refs", "first_frame"}:
        need = compose.free_slots_needed(refs, node.get("first_frame"), caps)
        if need > caps.max_refs:
            raise sess.SessionError(f"参考超出当前厂商上限（{need} / {caps.max_refs}）")
    ff = node.get("first_frame")
    if "first_frame" in fields and ff:
        if not caps.first_frame:
            raise sess.SessionError("当前厂商不支持指定首帧")
        if ff.startswith("keyframe:"):
            if ff[len("keyframe:"):] not in ctx.keyframes:
                raise sess.SessionError(f"镜头 {ff[len('keyframe:'):]} 还没有关键帧")
        elif ff.startswith("tail:"):
            src = ff[len("tail:"):]
            if src == node["id"]:
                raise sess.SessionError("不能用自己的尾帧作首帧")
            if tail_source(root, s, src) is None:
                raise sess.SessionError(f"{src} 还没有可用的尾帧")
        else:
            raise sess.SessionError(f"看不懂的首帧来源：{ff}")
    if "duration" in fields and not node.get("target"):
        if not (1 <= node["duration"] <= caps.max_clip_sec):
            raise sess.SessionError(f"时长要在 1 到 {caps.max_clip_sec:g} 秒之间")
    if "prompt" in fields:
        if len(node["prompt"]) > PROMPT_MAX:
            raise sess.SessionError(f"提示词不能超过 {PROMPT_MAX} 字")
        if run and not node["prompt"].strip():
            raise sess.SessionError("先写提示词再生成")


def create(root, ctx: Ctx, from_clip: Optional[str] = None) -> dict:
    """新建自由节点；from_clip 时从这一段派生：预填正文、参考、时长，挂靠这一段，接力首帧换成那一段的尾帧。"""
    with sess.mutate(root) as s:
        caps = _caps(s)
        seq = int(s.get("free_seq") or 0) + 1
        node = {"id": f"{sess.FREE_PREFIX}{seq:02d}", "target": None, "target_shots": None,
                "target_lost": False, "prompt": "", "refs": [], "first_frame": None,
                "duration": float(min(5, caps.max_clip_sec)), "state": "planned", "error": None,
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
        node["estimate_cny"] = base.estimate_cny(node["duration"], caps, s["resolution"])
        s["free_seq"] = seq
        s["free"] = list(s.get("free") or []) + [node]
        return s


def update(root, ctx: Ctx, fid: str, patch: dict) -> dict:
    """改正文、参考、首帧、时长、挂靠（传了哪些改哪些，只校验这些）。挂靠某段时时长跟随那一段。"""
    unknown = set(patch) - set(FIELDS)
    if unknown:
        raise sess.SessionError(f"不能改这些字段：{sorted(unknown)}")
    with sess.mutate(root) as s:
        n = _free(s, fid)
        if n["state"] in sess.IN_FLIGHT:
            raise sess.Conflict("这个节点正在生成，等它结束再改")
        caps = _caps(s)
        if "target" in patch:
            if patch["target"] is None:
                n.update(target=None, target_shots=None)
            else:
                c = sess._clip(s, patch["target"])
                n.update(target=c["id"], target_shots=list(c["shots"]), duration=c["duration"], target_lost=False)
        if "duration" in patch:
            if n.get("target"):
                raise sess.SessionError("挂靠某一段的节点时长跟随那一段，不能单独改")
            n["duration"] = round(float(patch["duration"]), 1)
        if "prompt" in patch:
            n["prompt"] = str(patch["prompt"] or "")
        if "refs" in patch:
            n["refs"] = [str(x) for x in (patch["refs"] or [])]
        if "first_frame" in patch:
            n["first_frame"] = patch["first_frame"] or None
        validate(root, s, n, ctx, caps, set(patch) | ({"duration"} if "target" in patch else set()))
        n["estimate_cny"] = base.estimate_cny(n["duration"], caps, s["resolution"])
        return s


def delete(root, fid: str) -> dict:
    """删节点与只属于它的文件；已复制进剧本段（含 orphaned）的尝试共用的文件保留。"""
    with sess.mutate(root) as s:
        n = _free(s, fid)
        if n["state"] in sess.IN_FLIGHT:
            raise sess.Conflict("这个节点正在生成，等它结束再删")
        users = [x["id"] for x in s.get("free") or [] if x.get("first_frame") == f"tail:{fid}"]
        if users:
            raise sess.Conflict(f"{users[0]} 用它的尾帧作首帧，先改掉那边")
        shared = {a.get("file") for c in list(s["clips"]) + list(s.get("orphaned") or [])
                  for a in c.get("attempts") or [] if a.get("free_id") == fid}
        doomed = [a[k] for a in n["attempts"] if a.get("file") not in shared
                  for k in ("file", "last_frame") if a.get(k)]
        s["free"] = [x for x in s["free"] if x["id"] != fid]
    for rel in doomed:                      # 记录先改，文件后删：写回失败时不会留下指向已删文件的记录
        (Path(root) / rel).unlink(missing_ok=True)
    return s


def queue(root, ctx: Ctx, fid: str, expected_cny: Optional[float] = None) -> dict:
    """排队生成一次：全量校验；超过确认线要带金额，与服务端不一致 → Conflict（附金额）；过单章上限。"""
    with sess.mutate(root) as s:
        if (s.get("final") or {}).get("state") in sess.COMPOSE_BUSY:
            raise sess.Conflict("正在合成，等它结束再生成")
        n = _free(s, fid)
        if n["state"] in sess.IN_FLIGHT:
            raise sess.Conflict(f"{fid} 已在排队或生成中")
        validate(root, s, n, ctx, _caps(s), run=True)
        total = n["estimate_cny"]
        if total > s["confirm_over_cny"] and expected_cny is None:
            raise sess.Conflict(f"本次约 ¥{total:.2f}，请确认金额后再生成", total)
        if expected_cny is not None and abs(expected_cny - total) > 0.005:
            raise sess.Conflict(f"预估金额已变为 ¥{total:.2f}，请重新确认", total)
        reserved = sum(c["estimate_cny"] for c in sess.items(s) if c["state"] in sess.IN_FLIGHT)
        if s["spent_cny"] + reserved + total > s["budget_cny"] + 1e-9:
            raise sess.BudgetExceeded(f"超出单章上限 ¥{s['budget_cny']:g}：已花 ¥{s['spent_cny']:.2f}，"
                                      f"在跑预留 ¥{reserved:.2f}，本次约 ¥{total:.2f}")
        n.update(state="queued", error=None, queued_at=sess._now(), uncertain=False)
        return s


def set_chosen(root, fid: str, index: int) -> dict:
    with sess.mutate(root) as s:
        n = _free(s, fid)
        if n["state"] in sess.IN_FLIGHT:
            raise sess.Conflict("这个节点正在生成，等它结束再换")
        if not (0 <= index < len(n["attempts"])) or n["attempts"][index].get("state") != "succeeded":
            raise sess.SessionError("只能采用成功的那几次")
        n["chosen"] = index
        return s
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd backend && .venv/bin/python tests/render/test_free.py`
Expected: 1–15 ✓，`ALL PASS`。

- [ ] **Step 5: 跑全局约束里的后端脚本**

Expected: 全部 `ALL PASS`。

- [ ] **Step 6: Commit**

```bash
git add backend/render/free.py backend/tests/render/test_free.py
git commit -m "自由节点的增删改与排队：新建空白节点或从某段派生（正文去掉参考行与占位、接力首帧换成那一段的尾帧）；修改只校验传了的字段，参考须有图且不超位，首帧须有关键帧或已出的尾帧；生成全量校验并沿用确认线与单章上限；删除只删不被剧本段共用的文件，编号不复用"
```

---

### Task 4: 挂靠节点下载后复制进目标段

**Files:**
- Modify: `backend/render/session.py`
- Modify: `backend/tests/render/test_free.py`

- [ ] **Step 1: 在 `test_free.py` 追加失败的测试**

在 `def main()` 之前加：

```python
def part_deliver():
    root = new_root("deliver")
    doc = rich(DOC)
    s = build(root, doc)
    ctx = free.Ctx(doc, {}, False)
    x, y = s["clips"][0], s["clips"][1]

    # 16. 目标段空闲：复制追加到末尾，花费记 0、带 free_id、指纹为目标段当前指纹；不自动采用
    free.create(root, ctx, x["id"])
    free.update(root, ctx, "F01", {"prompt": "重拍"})
    free.queue(root, ctx, "F01")
    tid = finish(root, "F01")
    s = sess.load(root)
    cx = item(s, x["id"])
    cp = cx["attempts"][-1]
    assert cp["free_id"] == "F01" and cp["task_id"] == tid and cp["cost_cny"] == 0.0
    assert cp["fingerprint"] == cx["fingerprint"] and cx["chosen"] is None and cx["state"] == "planned"
    assert item(s, "F01")["attempts"][0]["cost_cny"] > 0
    s = sess.set_chosen(root, x["id"], len(cx["attempts"]) - 1)
    assert item(s, x["id"])["state"] == "done"
    print("16. 复制到空闲的目标段 ✓")

    # 17. 目标段在提交窗口（排队、最后一次是 submitting）或生成中：复制插在在跑那次之前，随后的写回落到真正那次
    sess.queue_run(root, [y["id"]])
    assert sess.begin_submit(root, y["id"]) is not None
    free.create(root, ctx, y["id"])                                     # F02
    free.update(root, ctx, "F02", {"prompt": "重拍二"})
    free.queue(root, ctx, "F02")
    finish(root, "F02")
    cy = item(sess.load(root), y["id"])
    assert [a.get("free_id") for a in cy["attempts"]] == ["F02", None]
    assert cy["attempts"][-1]["state"] == "submitting"
    s_now = sess.load(root)
    req = base.ClipRequest(prompt=cy["prompt"], model=s_now["model"], duration=cy["duration"],
                           resolution=s_now["resolution"])
    real = FAKE.submit(req)
    sess.submitted(root, y["id"], real, None)
    free.queue(root, ctx, "F02")
    finish(root, "F02")
    cy = item(sess.load(root), y["id"])
    assert [a.get("free_id") for a in cy["attempts"]] == ["F02", "F02", None]
    assert cy["attempts"][-1]["task_id"] == real
    st = FAKE.poll(real)
    sess.poll_update(root, y["id"], st)
    sess.downloaded(root, y["id"], FAKE.download(st, sess.clip_dest(root, y["id"], real)), FAKE.cost(st, req))
    cy = item(sess.load(root), y["id"])
    assert cy["chosen"] == 2 and cy["attempts"][2]["task_id"] == real and cy["attempts"][0]["free_id"] == "F02"
    assert cy["attempts"][0]["file"] != cy["attempts"][2]["file"]
    print("17. 提交窗口与生成中 ✓")

    # 18. 交付前目标段换了镜头：不复制，节点转独立素材
    free.create(root, ctx, x["id"])                                     # F03
    free.update(root, ctx, "F03", {"prompt": "三"})
    with sess.mutate(root) as raw:
        item(raw, "F03")["target_shots"] = ["E01-SH999"]
    n_before = len(item(sess.load(root), x["id"])["attempts"])
    free.queue(root, ctx, "F03")
    finish(root, "F03")
    s = sess.load(root)
    assert len(item(s, x["id"])["attempts"]) == n_before
    f3 = item(s, "F03")
    assert f3["target"] is None and f3["target_lost"] and f3["state"] == "done"
    print("18. 目标段变了不复制 ✓")

    # 19. 采用复制件的段不因风格图误报「可按新图重出」
    with sess.mutate(root) as raw:
        cx = item(raw, x["id"])
        cx["style"], cx["style_hash"] = "used", "h-new"
    v = sess.view(sess.load(root))
    assert not item(v, x["id"])["style_outdated"]
    print("19. 风格图不误报 ✓")
```

`main()` 里在 `part_crud()` 之后加 `part_deliver()`。

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && .venv/bin/python tests/render/test_free.py`
Expected: 16 处 FAIL（`KeyError: 'free_id'`，还没有复制）。

- [ ] **Step 3: 在 `session.py` 实现**

在 `downloaded` 函数之前加：

```python
def _deliver(s: dict, node: dict, a: dict) -> None:
    """挂靠的自由节点成功一次：把这次尝试复制进目标段（free_id 标来源，花费记在节点上这里为 0，
    指纹记目标段此刻的指纹），不自动采用。目标段不在了或镜头变了：不复制，节点转为独立素材。

    目标段最后一次尝试正在提交或生成（runner 认 attempts[-1] 为在跑的那次）：插到它前面。
    chosen 只可能指向更早的尝试，下标不受影响。
    """
    t = next((c for c in s["clips"] if c["id"] == node.get("target")), None)
    if t is None or t["shots"] != node.get("target_shots"):
        node.update(target=None, target_shots=None, target_lost=True)
        return
    cp = dict(a, free_id=node["id"], cost_cny=0.0, fingerprint=t["fingerprint"])
    last = t["attempts"][-1] if t["attempts"] else None
    if last and last.get("state") in ("submitting", "running"):
        t["attempts"].insert(len(t["attempts"]) - 1, cp)
    else:
        t["attempts"].append(cp)
```

`downloaded` 里把

```python
        if is_free(c["id"]):
            c["state"] = "done"         # 自由节点不依赖分镜，没有过期
```

改成

```python
        if is_free(c["id"]):
            c["state"] = "done"         # 自由节点不依赖分镜，没有过期
            if c.get("target"):
                _deliver(s, c, a)
```

`_style_outdated` 换成：

```python
def _style_outdated(c: dict) -> bool:
    """已出完、本段带风格图，但采用的那次尝试用的不是当前风格图（旧会话没记录按 None 算）。
    采用的是自由节点复制来的那次：带不带风格图由用户在节点上定，不算过期。"""
    if c["state"] != "done" or c.get("style") != "used" or c.get("chosen") is None:
        return False
    a = c["attempts"][c["chosen"]]
    if a.get("free_id"):
        return False
    return a.get("style_ref") != c.get("style_hash")
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd backend && .venv/bin/python tests/render/test_free.py`
Expected: 1–19 ✓，`ALL PASS`。

- [ ] **Step 5: 跑全局约束里的后端脚本**

Expected: 全部 `ALL PASS`。

- [ ] **Step 6: Commit**

```bash
git add backend/render/session.py backend/tests/render/test_free.py
git commit -m "挂靠的自由节点出完一次就复制进目标段：标来源、花费记 0、指纹记目标段当前指纹，不自动采用；目标段正在提交或生成时插在在跑那次之前，不打乱出片线程的写回；交付前目标段没了或换了镜头就不复制、转独立素材；采用复制件的段不再误报风格图过期"
```

---

### Task 5: 出片线程推进自由节点、删版本检查、请求分派

**Files:**
- Modify: `backend/render/runner.py`
- Modify: `backend/server/novels.py`
- Modify: `backend/server/app.py`（只改 `_render_request` 与导入）
- Create: `backend/tests/render/test_free_runner.py`

- [ ] **Step 1: 写失败的测试 `backend/tests/render/test_free_runner.py`**

```python
#!/usr/bin/env python3
"""出片线程推进自由节点：只有自由节点在跑时不被丢下、与剧本段共用并发上限、请求按节点组装、
复查不过记失败不提交、重启续上。用法: python3 tests/render/test_free_runner.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"

from render import compose, free, providers, session as sess  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from render.runner import Runner  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}


def rich(doc):
    d = copy.deepcopy(doc)
    for kind in ("characters", "creatures", "props"):
        for card in d["assets"].get(kind) or []:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
    for card in d["assets"]["locations"]:
        for a in card.get("angles") or []:
            a["uri"] = f"https://img/{card['id']}-{a['angle']}.png"
    return d


def drain(rn, limit=50):
    for _ in range(limit):
        if not rn.watching():
            return
        rn.tick()
    raise AssertionError("没跑完")


def main() -> int:
    plain = json.loads(YAO.read_text(encoding="utf-8"))
    doc = rich(plain)
    current = {"doc": doc}
    fake = FakeVideo()
    providers.register("fake", lambda: fake)
    tmp = tempfile.TemporaryDirectory()
    data = Path(tmp.name)
    root = data / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    s = sess.build(root, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    ctx = free.Ctx(doc, {}, False)
    char = doc["assets"]["characters"][0]["id"]

    def builder(r, s_now, c):
        caps = fake.caps(s_now["model"])
        if sess.is_free(c["id"]):
            return compose.request_for_free(current["doc"], s_now, c, keyframes={},
                                            tail_frame=free.tail_frame(r, s_now, c), caps=caps,
                                            rewrite=fake.rewrite_prompt)
        return compose.request_for(current["doc"], s_now, c, keyframes={},
                                   relay_frame=sess.relay_frame(r, s_now, c), caps=caps,
                                   rewrite=fake.rewrite_prompt)

    def node(fid="F01"):
        return next(n for n in sess.load(root)["free"] if n["id"] == fid)

    runner = Runner(builder, sleep=lambda _s: None, max_parallel=1)

    # 1. 只有一个自由节点在跑：每轮都还盯着，直到下载完；请求是节点的正文 + 参考行
    free.create(root, ctx)
    free.update(root, ctx, "F01", {"prompt": "空镜：河面起雾", "refs": [char]})
    free.queue(root, ctx, "F01")
    runner.watch(root)
    runner.tick()
    assert node()["state"] == "running" and runner.watching() == [root], "提交后还在盯"
    drain(runner)
    assert node()["state"] == "done"
    req = fake.submitted[-1]
    assert req.prompt.startswith(f"空镜：河面起雾\n【参考】[参考{char}]") and [r.asset_id for r in req.refs] == [char]
    print("1. 只有自由节点在跑 ✓")

    # 2. 与剧本段共用并发上限：上限 1 时一轮只提交一个
    first = s["clips"][0]["id"]
    sess.queue_run(root, [first])
    free.queue(root, ctx, "F01")
    runner.watch(root)
    n0 = len(fake.submitted)
    runner.tick()
    assert len(fake.submitted) == n0 + 1
    now = sess.load(root)
    running = [x["id"] for x in sess.items(now) if x["state"] == "running"]
    assert len(running) == 1, running
    drain(runner)
    print("2. 共用并发上限 ✓")

    # 3. 复查不过：参考图被删 → 记失败、写明原因、不提交
    free.queue(root, ctx, "F01")
    current["doc"] = plain
    n0 = len(fake.submitted)
    runner.watch(root)
    runner.tick()
    f = node()
    assert f["state"] == "failed" and "参考图" in f["error"] and len(fake.submitted) == n0
    current["doc"] = doc
    print("3. 复查不过不提交 ✓")

    # 4. 重启续跑：自由节点生成中 → 新线程 recover 认得，接着查、接着下
    free.queue(root, ctx, "F01")
    runner.watch(root)
    runner.tick()
    assert node()["state"] == "running"
    runner2 = Runner(builder, sleep=lambda _s: None, max_parallel=1)
    assert runner2.recover(data) == 1 and runner2.watching() == [root]
    drain(runner2)
    assert node()["state"] == "done"
    print("4. 重启续跑 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && .venv/bin/python tests/render/test_free_runner.py`
Expected: FAIL 在第 1 步，`AssertionError: 提交后还在盯`（runner 只看剧本段，第一轮就丢下了会话），或节点停在 `queued`。

- [ ] **Step 3: 改 `runner.py`**

1. `__init__` 的文档字符串改成：

   ```python
           """request_builder(root, session, item) → (ClipRequest, 实际首帧来源)；item 是剧本段或自由节点。
           分镜改了抛 compose.Stale；自由节点复查不过抛 compose.FreeInvalid。"""
   ```

2. `tick` 里两处 `for c in s["clips"]:` 都改成 `for c in sess.items(s):`。

3. `busy = sum(1 for _, s in loaded for c in s["clips"] if c["state"] in BUSY)` 改成 `busy = sum(1 for _, s in loaded for c in sess.items(s) if c["state"] in BUSY)`。

4. `_settle` 里 `if s is None or not any(c["state"] in sess.IN_FLIGHT for c in s["clips"]):` 改成 `if s is None or not sess.any_in_flight(s):`。

5. `_submit` 里在 `except compose.Stale:` 分支之后、`except Exception as e:  # 组装失败不能卡住整个队列` 之前插入：

   ```python
           except compose.FreeInvalid as e:          # 自由节点的参考图、尾帧或关键帧没了：不提交、不花钱
               sess.submit_failed(root, c["id"], str(e))
               return False
   ```

- [ ] **Step 4: 改 `novels.py` 的 `delete_version`**

把

```python
                if s and any(c.get("state") in render_session.IN_FLIGHT for c in s.get("clips", [])):
```

改成

```python
                if s and render_session.any_in_flight(s):
```

（提示文字「这个版本还有片段在出…」不变。）

- [ ] **Step 5: 改 `app.py` 的 `_render_request`**

导入区在 `from render import session as render_session` 下面加一行：

```python
from render import free as render_free
```

`_render_request` 整个换成：

```python
def _render_request(root, s: dict, clip: dict):
    """出片线程提交前：剧本段按已保存的分镜与关键帧重建厂商请求；自由节点按它存的正文与参考组装。"""
    o = s["owner"]
    record = novels.get_version(o["user_id"], o["nid"], o["cid"], o["vid"])
    provider = render_providers.get_video(s["provider"])
    kfs = _keyframe_paths(o["user_id"], o["nid"], o["cid"], o["vid"])
    style = _style_for(o["user_id"], o["nid"])
    if render_session.is_free(clip["id"]):
        return render_compose.request_for_free(
            record.get("result") or {}, s, clip, keyframes=kfs, tail_frame=render_free.tail_frame(root, s, clip),
            caps=provider.caps(s["model"]), rewrite=provider.rewrite_prompt, style=style)
    return render_compose.request_for(
        record.get("result") or {}, s, clip,
        keyframes=kfs, relay_frame=render_session.relay_frame(root, s, clip),
        caps=provider.caps(s["model"]), rewrite=provider.rewrite_prompt, style=style)
```

- [ ] **Step 6: 运行，确认通过**

Run: `cd backend && .venv/bin/python tests/render/test_free_runner.py`
Expected: 1–4 ✓，`ALL PASS`。

- [ ] **Step 7: 跑全局约束里的后端脚本**

Expected: 全部 `ALL PASS`（`test_render.py` 第 10 步删版本 409 的提示文字不变）。

- [ ] **Step 8: Commit**

```bash
git add backend/render/runner.py backend/server/novels.py backend/server/app.py backend/tests/render/test_free_runner.py
git commit -m "出片线程推进自由节点：提交、轮询、下载与并发上限覆盖剧本段和自由节点，只有自由节点在跑时也不丢下会话，重启能续上；复查不过记失败不提交；删版本前的在跑检查算上自由节点；提交时按 id 分派，自由节点按存的正文与参考组装请求"
```

---

### Task 6: 自由节点接口

**Files:**
- Modify: `backend/server/app.py`
- Create: `backend/tests/server/test_render_free.py`

- [ ] **Step 1: 写失败的测试 `backend/tests/server/test_render_free.py`**

```python
#!/usr/bin/env python3
"""自由节点接口：新建与派生、修改与校验、生成（确认线、出片线程按节点组装请求、取文件）、挂靠段复制与采用、
删除与引用保护、有节点在跑时删版本被拒、编号不复用。

全程临时数据目录 + 假厂商，不联网、不花钱。用法: python3 tests/server/test_render_free.py
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
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"     # 不起后台线程，测试里手动 tick

from fastapi.testclient import TestClient  # noqa: E402
from render import providers  # noqa: E402
from render.providers.fake import FAKE_MP4, FakeVideo  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402

FAKE = FakeVideo()
providers.register("fake", lambda: FAKE)


def rich(doc):
    d = copy.deepcopy(doc)
    for kind in ("characters", "creatures", "props"):
        for card in d["assets"].get(kind) or []:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
    for card in d["assets"]["locations"]:
        for a in card.get("angles") or []:
            a["uri"] = f"https://img/{card['id']}-{a['angle']}.png"
    return d


DOC = rich(json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8")))


def drain(limit=3000):
    runner = app_mod._render_runner
    for _ in range(limit):
        if not runner.watching():
            return
        runner.tick()
    raise AssertionError("出片线程没跑完")


def pick(s, iid):
    return next(x for x in s["clips"] + s["free"] if x["id"] == iid)


def main() -> int:
    app_mod._render_runner.sleep = lambda _s: None
    c = TestClient(app_mod.app)
    uid = auth.register("bob", "secret1")["id"]
    H = {"Authorization": f"Bearer {auth.issue_token(uid)}"}
    nid = novels.create_novel(uid, "药")["id"]
    cid = novels.create_chapter(uid, nid, "第一章", text="原文")["id"]
    novels.create_version(uid, nid, cid, "v1", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v1", "succeeded", result=copy.deepcopy(DOC))
    V = f"/novels/{nid}/chapters/{cid}/versions/v1"
    R = V + "/render"

    # 1. 没有会话 404；建会话后新建空白节点、派生；派生不存在的段 404
    assert c.post(R + "/free", headers=H, json={}).status_code == 404
    s = c.post(R + "/session", headers=H, json={}).json()
    assert s["free"] == [] and s["options"]["first_frame"] is True
    r = c.post(R + "/free", headers=H, json={})
    assert r.status_code == 200, r.text
    f1 = pick(r.json(), "F01")
    assert f1["target"] is None and f1["over_refs"] is False
    x = next(cl for cl in s["clips"] if cl["refs"])
    r = c.post(R + "/free", headers=H, json={"from_clip": x["id"]})
    f2 = pick(r.json(), "F02")
    assert f2["target"] == x["id"] and f2["refs"] == x["refs"]
    assert c.post(R + "/free", headers=H, json={"from_clip": "E99-C01"}).status_code == 404
    print("1. 新建与派生 ✓")

    # 2. 修改：只改传了的字段；显式传 null 清掉挂靠；校验不过 422；挂靠时改时长 422；不存在 404
    char = DOC["assets"]["characters"][0]["id"]
    r = c.patch(R + "/free/F01", headers=H, json={"prompt": "空镜：河面", "refs": [char]})
    assert r.status_code == 200, r.text
    assert pick(r.json(), "F01")["prompt"] == "空镜：河面" and pick(r.json(), "F01")["refs"] == [char]
    assert c.patch(R + "/free/F01", headers=H, json={"refs": ["ZZ"]}).status_code == 422
    assert c.patch(R + "/free/F02", headers=H, json={"duration": 3}).status_code == 422
    r = c.patch(R + "/free/F02", headers=H, json={"target": None})
    assert pick(r.json(), "F02")["target"] is None
    assert c.patch(R + "/free/F09", headers=H, json={"prompt": "x"}).status_code == 404
    print("2. 修改 ✓")

    # 3. 生成：没写提示词 422；超确认线 409 带金额；带上金额排队；出片线程按节点组装请求；取文件
    c.post(R + "/free", headers=H, json={})                         # F03 空白
    assert c.post(R + "/free/F03/run", headers=H, json={}).status_code == 422
    assert c.patch(R + "/session", headers=H, json={"confirm_over_cny": 1}).status_code == 200
    r = c.post(R + "/free/F01/run", headers=H, json={})
    assert r.status_code == 409, r.text
    cny = r.json()["detail"]["expected_cny"]
    r = c.post(R + "/free/F01/run", headers=H, json={"expected_cny": cny})
    assert r.status_code == 200 and pick(r.json(), "F01")["state"] == "queued", r.text
    drain()
    s = c.get(R + "/session", headers=H).json()
    f = pick(s, "F01")
    assert f["state"] == "done" and FAKE.submitted[-1].prompt.startswith("空镜：河面\n【参考】")
    assert c.get(R + "/files/" + f["attempts"][0]["file"], headers=H).content == FAKE_MP4
    print("3. 生成 ✓")

    # 4. 挂靠节点：成功后复制进目标段，用现有采用接口设为采用 → 该段 done；节点自身的采用
    r = c.patch(R + "/free/F02", headers=H, json={"target": x["id"]})
    r = c.post(R + "/free/F02/run", headers=H, json={"expected_cny": pick(r.json(), "F02")["estimate_cny"]})
    assert r.status_code == 200, r.text
    drain()
    cx = pick(c.get(R + "/session", headers=H).json(), x["id"])
    k = next(i for i, a in enumerate(cx["attempts"]) if a.get("free_id") == "F02")
    r = c.put(R + f"/clips/{x['id']}/chosen", headers=H, json={"attempt": k})
    assert r.status_code == 200 and pick(r.json(), x["id"])["state"] == "done", r.text
    assert c.put(R + "/free/F02/chosen", headers=H, json={"attempt": 5}).status_code == 422
    assert c.put(R + "/free/F02/chosen", headers=H, json={"attempt": 0}).status_code == 200
    print("4. 挂靠与采用 ✓")

    # 5. 删除：被当尾帧来源 409；有节点在跑时删版本 409；删除后编号不复用
    assert c.patch(R + "/free/F03", headers=H, json={"first_frame": "tail:F01"}).status_code == 200
    assert c.delete(R + "/free/F01", headers=H).status_code == 409
    c.patch(R + "/free/F03", headers=H, json={"first_frame": None, "prompt": "接着拍"})
    est = pick(c.get(R + "/session", headers=H).json(), "F03")["estimate_cny"]
    assert c.post(R + "/free/F03/run", headers=H, json={"expected_cny": est}).status_code == 200
    r = c.delete(V, headers=H)
    assert r.status_code == 409 and "还有片段在出" in r.json()["detail"], r.text
    drain()
    r = c.delete(R + "/free/F03", headers=H)
    assert r.status_code == 200 and all(n["id"] != "F03" for n in r.json()["free"])
    r = c.post(R + "/free", headers=H, json={})
    assert r.json()["free"][-1]["id"] == "F04"
    print("5. 删除 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_render_free.py`
Expected: FAIL，第 1 步 `POST /free` 返回 405 或 404 以外的状态，或 `KeyError`。

- [ ] **Step 3: 在 `app.py` 加接口**

放在 `render_clip_patch` 函数之后（`@app.get(_R + "/files/{path:path}")` 之前）：

```python
class FreeCreateBody(BaseModel):
    from_clip: Optional[str] = None


class FreePatchBody(BaseModel):
    prompt: Optional[str] = Field(None, max_length=2000)
    refs: Optional[list[str]] = Field(None, max_length=20)
    first_frame: Optional[str] = None
    duration: Optional[float] = Field(None, gt=0, le=600)
    target: Optional[str] = None


def _free_ctx(user: dict, nid: str, cid: str, vid: str, gate: bool = False) -> tuple:
    """自由节点接口的前置：要有会话；按已保存的分镜刷新一次（挂靠段、时长、预估跟着走）；
    返回 (会话目录, 校验用的分镜 / 关键帧 / 有无风格图)。生成时 gate=True 过验证门。"""
    root, doc, kfs, owner = _render_ctx(user, nid, cid, vid, gate=gate)
    if render_session.load(root) is None:
        raise HTTPException(404, "还没有出片会话")
    style = _style_for(owner["user_id"], owner["nid"])
    _render_call(render_session.build, root, doc, owner=owner, patch={}, keyframes=kfs,
                 allow_in_flight=True, style=style)
    return root, render_free.Ctx(doc, kfs, style is not None)


@app.post(_R + "/free")
def render_free_create(nid: str, cid: str, vid: str, body: Optional[FreeCreateBody] = None,
                       user: dict = Depends(novel_user)):
    """新建自由节点；带 from_clip 时从这一段派生（预填正文、参考、时长，挂靠这一段）。不花钱。"""
    root, ctx = _free_ctx(user, nid, cid, vid)
    s = _render_call(render_free.create, root, ctx, body.from_clip if body else None)
    return _render_call(render_session.view, s)


@app.patch(_R + "/free/{fid}")
def render_free_patch(nid: str, cid: str, vid: str, fid: str, body: FreePatchBody,
                      user: dict = Depends(novel_user)):
    """改正文、参考、首帧、时长、挂靠：只改传了的字段（显式传 null 为清掉）。在跑 409，校验不过 422。"""
    root, ctx = _free_ctx(user, nid, cid, vid)
    s = _render_call(render_free.update, root, ctx, fid, body.model_dump(exclude_unset=True))
    return _render_call(render_session.view, s)


@app.delete(_R + "/free/{fid}")
def render_free_delete(nid: str, cid: str, vid: str, fid: str, user: dict = Depends(novel_user)):
    """删节点与只属于它的文件。在跑或被别的节点当尾帧来源时 409。"""
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid)
    s = _render_call(render_free.delete, root, fid)
    return _render_call(render_session.view, s)


@app.post(_R + "/free/{fid}/run")
def render_free_run(nid: str, cid: str, vid: str, fid: str, body: Optional[RenderRunBody] = None,
                    user: dict = Depends(novel_user)):
    """生成一次（与单段出片同一套确认线与上限）。过验证门；超过确认线要带 expected_cny。"""
    root, ctx = _free_ctx(user, nid, cid, vid, gate=True)
    s = _render_call(render_free.queue, root, ctx, fid, body.expected_cny if body else None)
    _render_runner.watch(root)
    return _render_call(render_session.view, s)


@app.put(_R + "/free/{fid}/chosen")
def render_free_chosen(nid: str, cid: str, vid: str, fid: str, body: RenderChosenBody,
                       user: dict = Depends(novel_user)):
    root = _novel_call(novels.render_dir, user["id"], nid, cid, vid)
    s = _render_call(render_free.set_chosen, root, fid, body.attempt)
    return _render_call(render_session.view, s)
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd backend && .venv/bin/python tests/server/test_render_free.py`
Expected: 1–5 ✓，`ALL PASS`。

- [ ] **Step 5: 跑全局约束里的后端脚本**

Expected: 全部 `ALL PASS`。

- [ ] **Step 6: Commit**

```bash
git add backend/server/app.py backend/tests/server/test_render_free.py
git commit -m "自由节点接口：新建与派生、修改（只改传了的字段，null 为清掉）、删除、生成（过验证门、沿用确认线与上限、交给出片线程）、切换采用；每次先按已保存的分镜刷新会话，挂靠段与时长跟着走"
```

---

### Task 7: 导出时附带独立素材

**Files:**
- Modify: `backend/render/export_fcpxml.py`
- Modify: `backend/tests/render/test_export_fcpxml.py`

- [ ] **Step 1: 在 `test_export_fcpxml.py` 末尾追加失败的测试**

1. 顶部导入区：
   - 加 `import json` 与 `import tempfile`；
   - `from render.export_fcpxml import build_fcpxml, readme  # noqa: E402` 改成 `from render.export_fcpxml import build_fcpxml, extra_media, readme  # noqa: E402`。

2. 在 `main()` 末尾 `print("ALL PASS")` 之前插入：

```python
    # 补拍素材：只附带没挂靠、有采用结果且文件还在的自由节点；说明里列出来，不写进时间线
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "clips").mkdir()
        (root / "clips" / "F01.t1.mp4").write_bytes(b"x")
        (root / "clips" / "F02.t2.mp4").write_bytes(b"x")
        s = {"free": [
            {"id": "F01", "target": None, "chosen": 0, "prompt": "空镜：河面\n第二行",
             "attempts": [{"state": "succeeded", "file": "clips/F01.t1.mp4"}]},
            {"id": "F02", "target": "E01-C01", "chosen": 0, "prompt": "挂靠的",
             "attempts": [{"state": "succeeded", "file": "clips/F02.t2.mp4"}]},
            {"id": "F03", "target": None, "chosen": None, "prompt": "没出", "attempts": []},
            {"id": "F04", "target": None, "chosen": 0, "prompt": "文件没了",
             "attempts": [{"state": "succeeded", "file": "clips/gone.mp4"}]},
        ]}
        (root / "session.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
        ex = extra_media(root)
        assert [(rel, disk.name, line) for rel, disk, line in ex] == [("media/extra/F01.mp4", "F01.t1.mp4", "空镜：河面")]
        assert extra_media(root / "nope") == []
    r = readme(TL, "t", [("media/extra/F01.mp4", "空镜：河面")])
    assert "media/extra/F01.mp4" in r and "补拍素材" in r and "Extra footage" in r
    assert "补拍素材" not in readme(TL, "t")
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && .venv/bin/python tests/render/test_export_fcpxml.py`
Expected: FAIL，`ImportError: cannot import name 'extra_media'`。

- [ ] **Step 3: 改 `export_fcpxml.py`**

1. `readme` 的签名改成 `def readme(timeline: dict, title: str, extras=()) -> str:`。在 `if ph:` 那一块之后、`return` 之前加：

```python
    if extras:
        zh.append("- 补拍素材（不在时间线上，请自己摆位置）：")
        en.append("- Extra footage (not on the timeline; place it yourself):")
        for rel, line in extras:
            zh.append(f"  - {rel}  {line}")
            en.append(f"  - {rel}  {line}")
```

2. 在 `readme` 函数之后加：

```python
def extra_media(root) -> list:
    """独立素材（没挂靠的自由节点）采用的那次视频：[(包内路径, 磁盘文件, 提示词首行)]。
    文件缺了就不附带，不拦导出；挂靠节点的结果已是剧本段的尝试，不重复导出。"""
    try:
        s = json.loads((Path(root) / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for n in s.get("free") or []:
        k = n.get("chosen")
        if n.get("target") or k is None or not (0 <= k < len(n.get("attempts") or [])):
            continue
        a = n["attempts"][k]
        disk = Path(root) / (a.get("file") or "")
        if a.get("state") != "succeeded" or not a.get("file") or not disk.is_file():
            continue
        lines = (n.get("prompt") or "").strip().splitlines()
        out.append((f"media/extra/{n['id']}.mp4", disk, lines[0] if lines else ""))
    return out
```

3. `export()` 里把

```python
    xml = build_fcpxml(tl, media, event=title)
    text = readme(tl, title)
```

改成

```python
    extras = extra_media(root)
    for rel, disk, _line in extras:
        files[rel] = disk
    xml = build_fcpxml(tl, media, event=title)
    text = readme(tl, title, [(rel, line) for rel, _disk, line in extras])
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd backend && .venv/bin/python tests/render/test_export_fcpxml.py`
Expected: `ALL PASS`。

- [ ] **Step 5: 跑全局约束里的后端脚本**

Expected: 全部 `ALL PASS`（`tests/server/test_compose.py` 里的导出用例不受影响）。

- [ ] **Step 6: Commit**

```bash
git add backend/render/export_fcpxml.py backend/tests/render/test_export_fcpxml.py
git commit -m "导出剪辑工程附带独立素材：没挂靠、有采用结果且文件还在的自由节点放进 media/extra/，说明里列出文件与提示词首行，不写进时间线；挂靠节点不重复导出"
```

---

### Task 8: 前端类型、接口、出片纯计算与 useFilm

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/film.ts`
- Modify: `frontend/src/useFilm.ts`
- Modify: `frontend/src/components/FilmPanel.tsx`（只改 `Settings` 里的在跑判断）
- Modify: `frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`（只加 `film.tail`）
- Modify: `frontend/tests/film-lane.test.ts`

- [ ] **Step 1: 在 `film-lane.test.ts` 末尾追加失败的测试**

1. 导入改成：

```ts
import {
  anyInFlight, batchSummary, chosenAttempt, clipOffset, clipSpans, copyIndex, firstFrameText, laneKind, laneText,
  laneTitle, mainAction, needsConfirm, pollDelay, POLL_FAST_MS, POLL_SLOW_MS, precheck, slotsNeeded, spanAt,
  tailSources,
} from '../src/film'
import type { FilmAttempt, FilmClip, FilmFreeNode, FilmSession, Storyboard } from '../src/types'
```

2. 在最后的 `console.log('\nALL PASS')` 之前插入：

```ts
// 6. 自由节点：在跑也快轮询；复制件不算「试段已出」；尾帧来源；参考位；首帧说明；复制件下标
{
  const n = (over: Partial<FilmFreeNode> = {}): FilmFreeNode => ({
    id: 'F01', target: null, target_shots: null, target_lost: false, prompt: 'p', refs: [], first_frame: null,
    duration: 5, estimate_cny: 5, state: 'planned', error: null, uncertain: false, attempts: [], chosen: null,
    created_at: '', over_refs: false, ...over,
  })
  const s = session([clip('C1', [])], { free: [n({ state: 'running' })] })
  must(anyInFlight(s) && pollDelay(s, true) === POLL_FAST_MS, '自由节点在跑也快轮询')
  must(!anyInFlight(session([clip('C1', [])], { free: [n()] })), '没在跑')
  const copied = session([clip('C1', [], { attempts: [{ ...ok, free_id: 'F01', cost_cny: 0 }] }), clip('C2', [])])
  must(mainAction(copied, null).kind === 'try', '复制件不算试段已出')
  const src = session([clip('C1', [], { attempts: [ok], chosen: 0, state: 'done' }), clip('C2', [])],
                      { free: [n({ id: 'F02', attempts: [ok], chosen: 0, state: 'done' }), n({ id: 'F03' })] })
  must(tailSources(src).join() === 'C1,F02', '有尾帧的才能作首帧来源')
  must(slotsNeeded(['a', 'b'], 'keyframe:x', src) === 3 && slotsNeeded([], 'keyframe:x', src) === 0
       && slotsNeeded(['a'], null, src) === 1, '首帧与参考图不能同用时首帧占一位')
  must(slotsNeeded(['a'], 'k', session([], { options: { ...src.options, frame_with_refs: true } })) === 1,
       '能同用时首帧不占位')
  must(firstFrameText({ first_frame: 'tail:F02', frame_mode: null }) === 'F02 的尾帧', '尾帧首帧说明')
  must(chosenAttempt(n({ attempts: [ok], chosen: 0 }))?.task_id === 't1', '自由节点也能取采用的那次')
  const att = session([clip('C1', [], { attempts: [ok, { ...ok, task_id: 't9', free_id: 'F01' }] })])
  must(copyIndex(att, n({ target: 'C1' }), { ...ok, task_id: 't9' }) === 1, '找到复制进段里的那次')
  must(copyIndex(att, n({ target: 'C1' }), ok) === -1 && copyIndex(att, n(), ok) === -1, '找不到为 -1')
  console.log('6. 自由节点 ✓')
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd frontend && npm test`
Expected: FAIL 在 typecheck（`anyInFlight` 等不存在、`FilmFreeNode` 不存在）。

- [ ] **Step 3: 改 `types.ts`**

1. `FilmAttempt` 里 `style_ref?: string | null` 之后加：

```ts
  /** 自由节点生成后复制进剧本段的那次：来自哪个节点（花费记在节点上，这里为 0） */
  free_id?: string
```

2. `FilmClip` 接口之后加：

```ts
/** 自由节点（剧本之外补拍或重做一段）：target 为空是独立素材，否则成功的每一次都复制进那一段的尝试 */
export interface FilmFreeNode {
  id: string
  target: string | null
  /** 挂靠时那一段的镜头：重新切段后同 id 换了内容就转为独立素材 */
  target_shots: string[] | null
  /** 挂靠的段已不存在或换了镜头（此时 target 已为 null） */
  target_lost: boolean
  /** 画面描述正文（参考行在生成时按 refs 顺序拼上） */
  prompt: string
  /** 资产 id，顺序即发给厂商的顺序；风格图为 __style__ */
  refs: string[]
  /** keyframe:<镜头 id> | tail:<段或自由节点 id> | null */
  first_frame: string | null
  duration: number
  estimate_cny: number
  state: FilmClipState
  error: string | null
  uncertain: boolean
  attempts: FilmAttempt[]
  chosen: number | null
  created_at: string
  queued_at?: string
  /** 参考位超出当前厂商上限：删减之前不能生成 */
  over_refs: boolean
}

/** 改自由节点：传了哪些改哪些；null 为清掉 */
export interface FreePatch {
  prompt?: string
  refs?: string[]
  first_frame?: string | null
  duration?: number
  target?: string | null
}
```

3. `FilmSession` 里 `clips: FilmClip[]` 之后加：

```ts
  /** 自由节点（旧会话没有） */
  free?: FilmFreeNode[]
  free_seq?: number
```

`options` 里 `max_refs: number` 之后加：

```ts
    /** 厂商能否指定首帧；首帧与参考图能否同用（不能时首帧占一个参考位） */
    first_frame?: boolean
    frame_with_refs?: boolean
```

- [ ] **Step 4: 改 `api.ts`**

1. 顶部类型导入加 `FreePatch`。
2. 在 `muteFilmClip` 之后加：

```ts
/** 新建自由节点；带 fromClip 时从这一段派生（不花钱） */
export function createFreeNode(nid: string, cid: string, vid: string, fromClip?: string): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/free`, jsonPost(fromClip ? { from_clip: fromClip } : {}))
}

/** 改自由节点（正文、参考、首帧、时长、挂靠）；在跑时 409 */
export function patchFreeNode(nid: string, cid: string, vid: string, fid: string,
                              patch: FreePatch): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/free/${enc(fid)}`, jsonBody('PATCH', patch))
}

/** 删自由节点（只属于它的视频一并删掉） */
export function deleteFreeNode(nid: string, cid: string, vid: string, fid: string): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/free/${enc(fid)}`, { method: 'DELETE' })
}

/** 生成一次。超过确认线时要带用户确认过的金额 */
export function runFreeNode(nid: string, cid: string, vid: string, fid: string,
                            expectedCny?: number): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/free/${enc(fid)}/run`,
             jsonPost(expectedCny === undefined ? {} : { expected_cny: expectedCny }))
}

/** 自由节点自身采用第几次 */
export function chooseFreeAttempt(nid: string, cid: string, vid: string, fid: string,
                                  attempt: number): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/free/${enc(fid)}/chosen`, jsonBody('PUT', { attempt }))
}
```

- [ ] **Step 5: 改 `film.ts`**

1. 类型导入改成 `import type { FilmAttempt, FilmClip, FilmClipState, FilmFreeNode, FilmSession } from './types'`。

2. `export const inFlight = (c: FilmClip) => IN_FLIGHT.includes(c.state)` 改成：

```ts
export const inFlight = (c: { state: FilmClipState }) => IN_FLIGHT.includes(c.state)

/** 风格图占参考位时的 id（与后端 compose.STYLE_ID 一致） */
export const STYLE_REF = '__style__'

export const freeNodes = (s: FilmSession) => s.free ?? []

/** 剧本段或自由节点有在排队 / 生成中的 */
export const anyInFlight = (s: FilmSession) => s.clips.some(inFlight) || freeNodes(s).some(inFlight)
```

3. `chosenAttempt` 的签名改成 `export function chosenAttempt(c: { chosen: number | null; attempts: FilmAttempt[] }): FilmAttempt | null {`，函数体不变。

4. `mainAction` 里 `if (!s.clips.some((c) => c.attempts.some((a) => a.state === 'succeeded'))) {` 改成：

```ts
  // 自由节点复制进来的那次不算试段（它没按分镜出过）
  if (!s.clips.some((c) => c.attempts.some((a) => a.state === 'succeeded' && !a.free_id))) {
```

5. `pollDelay` 改成：

```ts
/** 下一次轮询隔多久：页签（或节点图）开着且有段或自由节点在跑时快 */
export function pollDelay(s: FilmSession | null, tabOpen: boolean): number {
  return s && tabOpen && anyInFlight(s) ? POLL_FAST_MS : POLL_SLOW_MS
}
```

6. `firstFrameText` 的签名改成 `export function firstFrameText(c: Pick<FilmClip, 'first_frame' | 'frame_mode'>): string {`，在 `if (f.startsWith('relay:')) …` 之后加一行：

```ts
  if (f.startsWith('tail:')) return tr('film.tail', { id: f.slice('tail:'.length) })
```

7. 文件末尾加：

```ts
/** 自由节点要占几个参考位：参考图各一个；带首帧、又有参考图、厂商不能同用时首帧再占一个（与后端同规则） */
export function slotsNeeded(refs: string[], firstFrame: string | null, s: FilmSession): number {
  return refs.length + (firstFrame && refs.length && !s.options.frame_with_refs ? 1 : 0)
}

/** 可作「尾帧首帧」来源的：采用的那次有尾帧的段与自由节点 */
export function tailSources(s: FilmSession): string[] {
  return [...s.clips, ...freeNodes(s)].filter((x) => chosenAttempt(x)?.last_frame).map((x) => x.id)
}

/** 自由节点的某次尝试复制进挂靠段后，在那一段尝试里的下标；没有为 -1 */
export function copyIndex(s: FilmSession, node: FilmFreeNode, a: FilmAttempt): number {
  const t = s.clips.find((c) => c.id === node.target)
  return t ? t.attempts.findIndex((x) => x.free_id === node.id && x.task_id === a.task_id) : -1
}
```

- [ ] **Step 6: i18n 加 `film.tail`**

- `zh.ts` 的 `film` 块里，`relay: '接力上一段（{id}）的尾帧',` 之后加 `tail: '{id} 的尾帧',`。
- `en.ts` 的 `film` 块里，对应 `relay` 那一行之后加 `tail: 'Last frame of {id}',`。

- [ ] **Step 7: 改 `useFilm.ts`**

1. 导入：
   - `from './api'` 加上 `chooseFreeAttempt, createFreeNode, deleteFreeNode, patchFreeNode, runFreeNode`；
   - 类型导入加 `FreePatch`。

2. 在 `const sendRest = …` 之后加：

```ts
  /** 卡片内确认的花钱操作（节点图）：成功返回 null；服务端重算的金额对不上（409 带新金额）返回新金额，由卡片再问一次 */
  const spendInline = useCallback(async (fn: () => Promise<FilmSession>): Promise<number | null> => {
    const mine = gen.current
    setBusy(true)
    setError(null)
    try {
      const got = await fn()
      if (gen.current === mine) accept(got, true)
      return null
    } catch (e) {
      if (gen.current !== mine) return null
      const fresh = conflictCny(e)
      if (fresh !== null) {
        void load()
        return fresh
      }
      fail(e)
      return null
    } finally {
      if (gen.current === mine) setBusy(false)
    }
  }, [accept, fail, load])
  /** 改自由节点（卡片上的防抖保存要用稳定的引用） */
  const patchFree = useCallback((fid: string, patch: FreePatch) =>
    apply(() => patchFreeNode(nid!, cid!, vid!, fid, patch)), [apply, nid, cid, vid])
```

3. 返回对象里 `mute: …` 之后加：

```ts
    /** 节点图卡片：确认过金额后直接出这一段 */
    runClipNow: (clipId: string, cny: number) => spendInline(() => runFilmClip(nid!, cid!, vid!, clipId, cny)),
    createFree: (fromClip?: string) => apply(() => createFreeNode(nid!, cid!, vid!, fromClip)),
    patchFree,
    deleteFree: (fid: string) => apply(() => deleteFreeNode(nid!, cid!, vid!, fid)),
    runFree: (fid: string, cny: number) => spendInline(() => runFreeNode(nid!, cid!, vid!, fid, cny)),
    chooseFree: (fid: string, attempt: number) => apply(() => chooseFreeAttempt(nid!, cid!, vid!, fid, attempt)),
```

- [ ] **Step 8: 改 `FilmPanel.tsx` 的 `Settings`**

- 导入从 `'../film'` 加 `anyInFlight`。
- `Settings` 里 `const flying = s.clips.some(inFlight)` 改成 `const flying = anyInFlight(s)`。有自由节点在跑时改设置会被服务端 409，按钮要一并禁用。

- [ ] **Step 9: 运行前端检查**

Run: `cd frontend && npm test && npm run lint && npx vite build`
Expected:
- `film-lane` 打印 `6. 自由节点 ✓`，17 套全部通过；
- lint 0 error、warning 仍是 5 个；
- 构建成功。

- [ ] **Step 10: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/film.ts frontend/src/useFilm.ts frontend/src/components/FilmPanel.tsx frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/film-lane.test.ts
git commit -m "前端出片会话认自由节点：类型与五个接口；在跑判断与快轮询算上自由节点，复制件不算试段已出；参考位计数、尾帧来源、复制件下标与尾帧首帧说明；useFilm 增加卡片内确认后直接出片与自由节点的增删改、生成、采用"
```

---

### Task 9: 节点图布局纯函数 `nodeGraph.ts`

**Files:**
- Create: `frontend/src/nodeGraph.ts`
- Create: `frontend/tests/node-graph.test.ts`
- Modify: `frontend/package.json`

- [ ] **Step 1: 写失败的测试 `frontend/tests/node-graph.test.ts`**

```ts
/** 节点图的纯计算：三列布局、资产分组与排序、集标题、挂靠节点对齐与下推、独立素材、连线种类、高亮、适应画面。
 *  组件交互由 graph-view.test.tsx 覆盖。跑法：npm test */
import {
  ASSET_H, CARD_H, CARD_W, COL_ASSET, COL_CLIP, COL_FREE, EP_H, FREE_H, GAP, assetImage, edgePath, fitView,
  layoutGraph, related,
} from '../src/nodeGraph'
import type { GNode, Graph } from '../src/nodeGraph'
import type { Assets, FilmClip, FilmFreeNode, FilmSession } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const clip = (id: string, episode: string, over: Partial<FilmClip> = {}): FilmClip => ({
  id, episode, shots: [`${id}-S`], duration: 5, truncated: false, prompt: 'p', refs: [], dropped_refs: [],
  missing_refs: [], first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 5, attempts: [],
  chosen: null, mute_native: false, uncertain: false, error: null, state: 'planned', ...over,
})
const free = (id: string, over: Partial<FilmFreeNode> = {}): FilmFreeNode => ({
  id, target: null, target_shots: null, target_lost: false, prompt: 'p', refs: [], first_frame: null, duration: 5,
  estimate_cny: 5, state: 'planned', error: null, uncertain: false, attempts: [], chosen: null, created_at: '',
  over_refs: false, ...over,
})
const session = (clips: FilmClip[], frees: FilmFreeNode[] = []): FilmSession => ({
  provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, clips, free: frees, orphaned: [], counts: {}, reserved_cny: 0,
  uncertain_count: 0, remaining_cny: 0,
  options: { providers: ['fake'], models: {}, resolutions: ['720p'], cny_per_sec: {}, max_clip_sec: 10,
             max_refs: 3, audio_modes: ['tts_all'], rate_note: '' },
})
const img = (id: string) => [{ view: 'front' as const, uri: `https://img/${id}.png` }]
const assets = {
  characters: [{ id: 'C01', name: '甲', reference_images: img('C01') }, { id: 'C02', name: '乙', reference_images: img('C02') },
               { id: 'C03', name: '丙' }],
  creatures: [{ id: 'A01', name: '狗' }],
  locations: [{ id: 'S01', name: '街', angles: [{ uri: 'local/x.png' }, { uri: 'https://img/S01.png' }] }],
  props: [{ id: 'P01', name: '灯', reference_images: [{ uri: 'local/p.png' }] }],
} as unknown as Assets
const node = (g: Graph, id: string) => {
  const n = g.nodes.find((x) => x.id === id)
  if (!n) throw new Error(`✗ 没有节点 ${id}`)
  return n
}
const ids = (g: Graph, kind: GNode['kind']) => g.nodes.filter((n) => n.kind === kind).map((n) => n.id)

// 1. 三列、资产分组与排序、集标题
{
  const s = session([
    clip('E01-C01', 'E01', { refs: ['C02', 'S01'], missing_refs: ['A01'] }),
    clip('E01-C02', 'E01', { refs: ['C02'], dropped_refs: ['C01'], first_frame: 'relay:E01-C01' }),
    clip('E02-C01', 'E02', { refs: ['C01', '__style__'] }),
  ])
  const g = layoutGraph({ session: s, assets, hasStyle: true, styleUrl: 'blob:style' })
  must(ids(g, 'asset').join() === 'asset:__style__,asset:C02,asset:C01,asset:A01,asset:S01',
       '风格在前；角色按被用段数降序；没图又没被用到的不列；缺图但被用到的要列')
  must(g.nodes.filter((n) => n.kind === 'asset').every((n) => n.x === COL_ASSET), '资产在左列')
  const style = node(g, 'asset:__style__')
  must(style.kind === 'asset' && style.role === 'style' && style.image === 'blob:style' && style.usedBy === 1, '风格图节点')
  const c02 = node(g, 'asset:C02')
  must(c02.kind === 'asset' && c02.usedBy === 2 && c02.image === 'https://img/C02.png' && c02.y === ASSET_H + GAP, '角色卡')
  const s01 = node(g, 'asset:S01')
  must(s01.kind === 'asset' && s01.image === 'https://img/S01.png', '场景取第一张可用的机位图')
  must(ids(g, 'episode').join() === 'ep:E01,ep:E02', '每集一个标题')
  must(ids(g, 'clip').join() === 'E01-C01,E01-C02,E02-C01' && g.nodes.filter((n) => n.kind === 'clip').every((n) => n.x === COL_CLIP),
       '剧本段按顺序在中列')
  const c1 = node(g, 'E01-C01'), c2 = node(g, 'E01-C02'), ep2 = node(g, 'ep:E02')
  must(node(g, 'ep:E01').y === 0 && c1.y === EP_H + GAP && c2.y === c1.y + CARD_H + GAP && ep2.y === c2.y + CARD_H + GAP,
       '集标题与段竖排')
  console.log('1. 三列与资产分组 ✓')
}

// 2. 自由节点：挂靠的从目标段那一行排起、后面的段下推；独立素材与挂靠段不存在的排在最下面
{
  const s = session([clip('E01-C01', 'E01'), clip('E01-C02', 'E01')],
    [free('F02', { target: 'E01-C01' }), free('F01', { target: 'E01-C01' }), free('F03'), free('F04', { target: 'E09-C09' })])
  const g = layoutGraph({ session: s, assets: {}, hasStyle: false })
  const f1 = node(g, 'F01'), f2 = node(g, 'F02'), c1 = node(g, 'E01-C01'), c2 = node(g, 'E01-C02')
  const f3 = node(g, 'F03'), f4 = node(g, 'F04')
  must(f1.x === COL_FREE && f1.y === c1.y && f2.y === f1.y + FREE_H + GAP && f1.h === FREE_H, '挂靠节点按 id 从目标段那一行排')
  must(c2.y === f2.y + FREE_H + GAP, '后面的段下推，不重叠')
  must(f3.y === c2.y + CARD_H + GAP && f4.y === f3.y + FREE_H + GAP, '独立素材在最下面')
  must(g.width === COL_FREE + CARD_W && g.height === f4.y + FREE_H, '画布大小')
  must(ids(g, 'asset').length === 0, '没有资产就没有左列')
  console.log('2. 自由节点位置 ✓')
}

// 3. 连线：参考 / 被裁 / 缺图 / 接力与尾帧首帧 / 挂靠；未知资产与关键帧不画；重复去重
const g3 = layoutGraph({
  session: session([
    clip('E01-C01', 'E01', { refs: ['C01', 'C01'], dropped_refs: ['C02'], missing_refs: ['A01'] }),
    clip('E01-C02', 'E01', { first_frame: 'relay:E01-C01', refs: ['ZZ'] }),
  ], [free('F01', { target: 'E01-C02', refs: ['C02'], first_frame: 'tail:E01-C01' }),
      free('F02', { first_frame: 'keyframe:E01-SH001' })]),
  assets, hasStyle: false,
})
{
  must(g3.edges.map((e) => e.id).sort().join('|') === [
    'dropped:asset:C02>E01-C01', 'frame:E01-C01>E01-C02', 'frame:E01-C01>F01', 'missing:asset:A01>E01-C01',
    'ref:asset:C01>E01-C01', 'ref:asset:C02>F01', 'target:F01>E01-C02',
  ].sort().join('|'), '连线种类与去重：' + g3.edges.map((e) => e.id).join(' '))
  console.log('3. 连线 ✓')
}

// 4. 高亮相关节点；连线路径；适应画面；资产取图
{
  const lit = related(g3, 'E01-C01')
  must(['E01-C01', 'asset:C01', 'asset:C02', 'asset:A01', 'E01-C02', 'F01'].every((id) => lit.has(id)) && !lit.has('F02'),
       '选中节点与直接相连的节点')
  must(related(g3, null).size === 0, '没选中什么都不亮')
  const a = node(g3, 'asset:C01'), c1 = node(g3, 'E01-C01'), c2 = node(g3, 'E01-C02'), f1 = node(g3, 'F01')
  must(edgePath(a, c1).startsWith(`M${a.x + a.w},${a.y + a.h / 2} C`), '左列到中列：从右边出')
  must(edgePath(f1, c2).startsWith(`M${f1.x},`) && edgePath(f1, c2).endsWith(`${c2.x + c2.w},${c2.y + c2.h / 2}`),
       '右列连回中列：从左边出、右边进')
  must(edgePath(c1, c2).includes(`${c1.x + c1.w + 60}`), '同一列：从右边绕出去')
  const v = fitView(g3, 800, 600)
  must(v.scale <= 1 && v.scale >= 0.3 && v.x === 24 && v.y === 24, '适应画面')
  must(fitView(g3, 0, 0).scale === 1, '量不到尺寸时不缩放')
  must(assetImage(assets, 'location', 'S01') === 'https://img/S01.png' && assetImage(assets, 'prop', 'P01') === null
       && assetImage(assets, 'character', 'C09') === null, '资产取第一张可用图')
  console.log('4. 高亮、路径、适应画面 ✓')
}

console.log('\nALL PASS')
```

- [ ] **Step 2: 把新测试加进 `package.json` 的 `test` 脚本**

在 `"test"` 的字符串里，把

```
node .ssrout/film-lane.test.js &&
```

改成

```
node .ssrout/film-lane.test.js && vite build --ssr tests/node-graph.test.ts --outDir .ssrout --logLevel error && node .ssrout/node-graph.test.js &&
```

- [ ] **Step 3: 运行，确认失败**

Run: `cd frontend && npm test`
Expected: FAIL 在 typecheck（`../src/nodeGraph` 不存在）。

- [ ] **Step 4: 新建 `frontend/src/nodeGraph.ts`**

```ts
/** 节点图的纯计算：资产、剧本段、自由节点三列自动布局与连线（设计文档 docs/specs/2026-11-11-film-node-graph-design.md §5.2）。
 *  不读 DOM，组件 NodeGraph 只按这里的坐标画；单测见 tests/node-graph.test.ts。 */
import { STYLE_REF, freeNodes } from './film'
import type { Assets, FilmClip, FilmFreeNode, FilmSession } from './types'

export const ASSET_W = 180
export const ASSET_H = 72
export const CARD_W = 260
/** 剧本段卡高；自由节点卡带编辑项，更高 */
export const CARD_H = 208
export const FREE_H = 340
export const EP_H = 28
export const GAP = 24
export const COL_GAP = 160
export const COL_ASSET = 0
export const COL_CLIP = ASSET_W + COL_GAP
export const COL_FREE = COL_CLIP + CARD_W + COL_GAP
/** 同一列之间的连线（接力、自由节点互作首帧）从右边绕出去的距离 */
const BULGE = 60
const PAD = 24

export type AssetRole = 'style' | 'character' | 'creature' | 'location' | 'prop'
interface Box { id: string; x: number; y: number; w: number; h: number }
export type GNode =
  | (Box & { kind: 'asset'; assetId: string; role: AssetRole; name: string; image: string | null; usedBy: number })
  | (Box & { kind: 'episode'; episode: string })
  | (Box & { kind: 'clip'; clip: FilmClip })
  | (Box & { kind: 'free'; node: FilmFreeNode })
export type EdgeKind = 'ref' | 'dropped' | 'missing' | 'frame' | 'target'
export interface GEdge { id: string; from: string; to: string; kind: EdgeKind }
export interface Graph { nodes: GNode[]; edges: GEdge[]; width: number; height: number }

export const assetNodeId = (assetId: string) => `asset:${assetId}`

const usable = (uri?: string | null): uri is string => !!uri && /^(https?:|data:image\/)/.test(uri)

type ImageCard = { id: string; name?: string; reference_images?: { uri?: string }[] }

/** 资产卡的第一张可用图（与后端自由节点取图同一规则：不分着装 / 机位） */
export function assetImage(assets: Assets, role: AssetRole, id: string): string | null {
  if (role === 'location') {
    return assets.locations?.find((x) => x.id === id)?.angles?.find((a) => usable(a.uri))?.uri ?? null
  }
  const list = (role === 'character' ? assets.characters : role === 'creature' ? assets.creatures
    : role === 'prop' ? assets.props : undefined) as ImageCard[] | undefined
  return list?.find((x) => x.id === id)?.reference_images?.find((r) => usable(r.uri))?.uri ?? null
}

export interface GraphInput {
  session: FilmSession
  assets: Assets
  /** 本小说当前有风格图 */
  hasStyle: boolean
  styleUrl?: string | null
}

export function layoutGraph({ session, assets, hasStyle, styleUrl = null }: GraphInput): Graph {
  const clips = session.clips
  const frees = freeNodes(session)
  // 每个资产被几段剧本段用到（只数 refs）；出现在任何连线里的资产都要上图
  const usedBy = new Map<string, number>()
  const mentioned = new Set<string>()
  for (const c of clips) {
    for (const id of c.refs) usedBy.set(id, (usedBy.get(id) ?? 0) + 1)
    for (const id of [...c.refs, ...c.dropped_refs, ...c.missing_refs]) mentioned.add(id)
  }
  for (const n of frees) for (const id of n.refs) mentioned.add(id)

  const nodes: GNode[] = []
  let y = 0
  const pushAsset = (assetId: string, role: AssetRole, name: string, image: string | null) => {
    nodes.push({ kind: 'asset', id: assetNodeId(assetId), assetId, role, name, image, usedBy: usedBy.get(assetId) ?? 0,
                 x: COL_ASSET, y, w: ASSET_W, h: ASSET_H })
    y += ASSET_H + GAP
  }
  if (hasStyle || mentioned.has(STYLE_REF)) pushAsset(STYLE_REF, 'style', '', styleUrl)
  // 角色按被用段数降序（同数按资产卡顺序）；其余各组按资产卡顺序
  const chars = (assets.characters ?? []).map((a, i) => ({ a, i }))
    .sort((p, q) => (usedBy.get(q.a.id) ?? 0) - (usedBy.get(p.a.id) ?? 0) || p.i - q.i).map((x) => x.a)
  const groups: [AssetRole, { id: string; name?: string }[]][] = [
    ['character', chars], ['creature', assets.creatures ?? []], ['location', assets.locations ?? []],
    ['prop', assets.props ?? []],
  ]
  for (const [role, list] of groups) {
    for (const a of list) {
      const image = assetImage(assets, role, a.id)
      if (mentioned.has(a.id) || image) pushAsset(a.id, role, a.name ?? a.id, image)
    }
  }
  const assetBottom = y

  // 中列剧本段（每集前一行集标题）；右列挂靠的自由节点从目标段那一行排起，排不下就把后面的段下推
  y = 0
  const clipIds = new Set(clips.map((c) => c.id))
  const attached = new Map<string, FilmFreeNode[]>()
  const standalone: FilmFreeNode[] = []
  for (const n of [...frees].sort((p, q) => p.id.localeCompare(q.id))) {
    if (n.target && clipIds.has(n.target)) attached.set(n.target, [...(attached.get(n.target) ?? []), n])
    else standalone.push(n)
  }
  let ep: string | null = null
  for (const c of clips) {
    if (c.episode !== ep) {
      ep = c.episode
      nodes.push({ kind: 'episode', id: `ep:${ep}`, episode: ep, x: COL_CLIP, y, w: CARD_W, h: EP_H })
      y += EP_H + GAP
    }
    nodes.push({ kind: 'clip', id: c.id, clip: c, x: COL_CLIP, y, w: CARD_W, h: CARD_H })
    const mine = attached.get(c.id) ?? []
    mine.forEach((n, i) => nodes.push({ kind: 'free', id: n.id, node: n, x: COL_FREE, y: y + i * (FREE_H + GAP),
                                        w: CARD_W, h: FREE_H }))
    y += Math.max(CARD_H, mine.length * (FREE_H + GAP) - GAP) + GAP
  }
  for (const n of standalone) {
    nodes.push({ kind: 'free', id: n.id, node: n, x: COL_FREE, y, w: CARD_W, h: FREE_H })
    y += FREE_H + GAP
  }

  const has = new Set(nodes.map((n) => n.id))
  const edges: GEdge[] = []
  const seen = new Set<string>()
  const add = (from: string, to: string, kind: EdgeKind) => {
    const id = `${kind}:${from}>${to}`
    if (!has.has(from) || !has.has(to) || seen.has(id)) return
    seen.add(id)
    edges.push({ id, from, to, kind })
  }
  for (const c of clips) {
    for (const id of c.refs) add(assetNodeId(id), c.id, 'ref')
    for (const id of c.dropped_refs) add(assetNodeId(id), c.id, 'dropped')
    for (const id of c.missing_refs) add(assetNodeId(id), c.id, 'missing')
    if (c.first_frame?.startsWith('relay:')) add(c.first_frame.slice('relay:'.length), c.id, 'frame')
  }
  for (const n of frees) {
    for (const id of n.refs) add(assetNodeId(id), n.id, 'ref')
    if (n.first_frame?.startsWith('tail:')) add(n.first_frame.slice('tail:'.length), n.id, 'frame')
    if (n.target) add(n.id, n.target, 'target')
  }
  return { nodes, edges, width: COL_FREE + CARD_W, height: Math.max(0, Math.max(assetBottom, y) - GAP) }
}

/** 连线路径（三次贝塞尔）：从左往右的从源右边出、目标左边进；从右往左的反过来；同一列的从右边绕出去 */
export function edgePath(a: Box, b: Box): string {
  const ay = a.y + a.h / 2
  const by = b.y + b.h / 2
  if (a.x === b.x) {
    const x = a.x + a.w
    return `M${x},${ay} C${x + BULGE},${ay} ${x + BULGE},${by} ${x},${by}`
  }
  const right = a.x < b.x
  const sx = right ? a.x + a.w : a.x
  const ex = right ? b.x : b.x + b.w
  const dx = Math.max(40, Math.abs(ex - sx) / 2) * (right ? 1 : -1)
  return `M${sx},${ay} C${sx + dx},${ay} ${ex - dx},${by} ${ex},${by}`
}

/** 与 id 直接相连的节点（含自己）；没选中返回空集 */
export function related(g: Graph, id: string | null): Set<string> {
  const out = new Set<string>()
  if (!id) return out
  out.add(id)
  for (const e of g.edges) {
    if (e.from === id) out.add(e.to)
    if (e.to === id) out.add(e.from)
  }
  return out
}

/** 适应画面：整张图放进 w × h（留边），不放大，最小 0.3；量不到尺寸时原样 */
export function fitView(g: Graph, w: number, h: number) {
  if (w <= 0 || h <= 0 || !g.width || !g.height) return { scale: 1, x: PAD, y: PAD }
  const scale = Math.min(1, Math.max(0.3, Math.min((w - 2 * PAD) / g.width, (h - 2 * PAD) / g.height)))
  return { scale, x: PAD, y: PAD }
}
```

- [ ] **Step 5: 运行前端检查**

Run: `cd frontend && npm test && npm run lint && npx vite build`
Expected:
- `node-graph` 打印 1–4 ✓，18 套全部通过；
- lint 0 error、warning 仍是 5 个；
- 构建成功。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/nodeGraph.ts frontend/tests/node-graph.test.ts frontend/package.json
git commit -m "节点图布局纯函数：资产（风格、按被用段数排序的角色、生物、场景、道具）、剧本段（按集分组）、自由节点三列自动排布，挂靠节点从目标段那一行排起并下推后续段；参考、被裁、缺图、首帧来源、挂靠五种连线；选中高亮、连线路径与适应画面"
```

---

### Task 10: 节点图视图与卡片（组件、样式、文字）

**Files:**
- Create: `frontend/src/components/NodeCards.tsx`
- Create: `frontend/src/components/NodeGraph.tsx`
- Create: `frontend/src/styles/nodegraph.css`
- Modify: `frontend/src/styles/app.css`
- Modify: `frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`

本任务只建组件，Task 11 才挂进画布并写界面测试。本任务的检查是类型检查、lint 与构建。

- [ ] **Step 1: i18n 加 `graph` 块**

`zh.ts` 顶层，紧接在 `film: { … },` 这一整块结束之后加：

```ts
  graph: {
    timeline: '时间轴',
    graph: '节点图',
    viewAria: '画布视图',
    noSession: '先在出片页签选好厂商与档位',
    openFilm: '打开出片页签',
    fit: '适应画面',
    newFree: '新建自由节点',
    style: '风格参考',
    usedBy: '被 {n} 段用到',
    noImage: '无图',
    noResult: '还没有结果',
    openAssets: '打开资产',
    kind: { style: '风格', character: '角色', creature: '生物', location: '场景', prop: '道具' },
    attempts: '{n} 次尝试',
    spent: '已花 {spent} · 约 {est}',
    run: '出这一段 {cost}',
    redo: '重出 {cost}',
    derive: '派生自由节点',
    fromFree: '来自 {id}',
    prev: '上一次',
    next: '下一次',
    attemptOf: '{n}/{total}',
    confirmCost: '约 {cost}，确认花这笔钱？',
    confirm: '确认',
    cancel: '取消',
    free: {
      replaces: '顶替 {id}',
      standalone: '独立素材',
      lost: '原段已不存在或已变，已转为独立素材',
      promptPh: '写这一段的画面描述',
      saving: '保存中…',
      saved: '已保存',
      duration: '时长',
      sec: '{n} 秒',
      firstFrame: '首帧',
      none: '无',
      keyframe: '关键帧 {id}',
      tail: '{id} 的尾帧',
      refs: '参考（{n}/{max}）',
      target: '挂靠',
      noTarget: '不挂靠（独立素材）',
      generate: '生成 {cost}',
      adopt: '设为这一段的采用',
      download: '下载',
      delete: '删除',
      deleteConfirm: '已下载的视频也会删掉，确定删除？',
      overRefs: '参考超出当前厂商上限（{n} / {max}）',
      detail: '自由节点 {id}',
    },
  },
```

`en.ts` 同一位置加：

```ts
  graph: {
    timeline: 'Timeline',
    graph: 'Node graph',
    viewAria: 'Canvas view',
    noSession: 'Pick a provider and tier in the Film tab first',
    openFilm: 'Open Film tab',
    fit: 'Fit',
    newFree: 'New free node',
    style: 'Style reference',
    usedBy: 'Used by {n} clips',
    noImage: 'No image',
    noResult: 'No result yet',
    openAssets: 'Open assets',
    kind: { style: 'Style', character: 'Character', creature: 'Creature', location: 'Location', prop: 'Prop' },
    attempts: '{n} attempts',
    spent: 'Spent {spent} · est. {est}',
    run: 'Render {cost}',
    redo: 'Re-render {cost}',
    derive: 'Derive free node',
    fromFree: 'From {id}',
    prev: 'Previous attempt',
    next: 'Next attempt',
    attemptOf: '{n}/{total}',
    confirmCost: 'About {cost}. Spend it?',
    confirm: 'Confirm',
    cancel: 'Cancel',
    free: {
      replaces: 'Replaces {id}',
      standalone: 'Standalone',
      lost: 'The original clip is gone or changed; now standalone',
      promptPh: 'Describe the shot',
      saving: 'Saving…',
      saved: 'Saved',
      duration: 'Duration',
      sec: '{n}s',
      firstFrame: 'First frame',
      none: 'None',
      keyframe: 'Keyframe {id}',
      tail: 'Last frame of {id}',
      refs: 'References ({n}/{max})',
      target: 'Attach to',
      noTarget: 'None (standalone)',
      generate: 'Generate {cost}',
      adopt: 'Use for this clip',
      download: 'Download',
      delete: 'Delete',
      deleteConfirm: 'Downloaded videos will be deleted too. Delete?',
      overRefs: 'Too many references for this provider ({n} / {max})',
      detail: 'Free node {id}',
    },
  },
```

- [ ] **Step 2: 新建 `frontend/src/components/NodeCards.tsx`**

```tsx
/** 节点图上的卡片：资产、剧本段、自由节点（设计文档 2026-11-11 §5.4）。
 *  卡片上能直接出这一段 / 重出、换采用、派生、生成；花钱前在卡片里确认金额（不弹窗）。
 *  视频只在悬停或选中时才取（filmFileUrl 会把整个文件取成 blob），平时显示尾帧图。
 *  这个文件只导出组件（Fast Refresh 要求），共用的计算在 film.ts / nodeGraph.ts。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { StatusPill } from '@/components/common/StatusPill'
import type { Tone } from '@/components/common/StatusPill'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import { FILM_STATE, label } from '../labels'
import { chosenAttempt, copyIndex, inFlight, needsConfirm, slotsNeeded, tailSources } from '../film'
import type { Film } from '../useFilm'
import type { AssetRole } from '../nodeGraph'
import type { FilmAttempt, FilmClip, FilmClipState, FilmFreeNode, FilmSession } from '../types'

const yuan = (n: number) => `¥${n.toFixed(2)}`
const TONE: Record<FilmClipState, Tone> = {
  planned: 'idle', queued: 'live', running: 'live', downloading: 'live', done: 'ok', failed: 'err', stale: 'warn',
}

/** 结果区：悬停或选中时播采用的那次（静音循环），平时显示它的尾帧；没有结果时显示首帧来源图 */
function Preview({ film, attempt, fallback, hot }: {
  film: Film; attempt: FilmAttempt | null; fallback: string | null; hot: boolean
}) {
  const { t } = useI18n()
  const { ensure, files } = film
  const poster = attempt?.last_frame ?? null
  const file = attempt?.file ?? null
  useEffect(() => { ensure(poster) }, [poster, ensure])
  useEffect(() => { if (hot) ensure(file) }, [hot, file, ensure])
  const video = hot && file ? files[file] : undefined
  const still = (poster && files[poster]) || fallback
  if (video) return <video className="ngv__media" src={video} autoPlay muted loop playsInline />
  if (still) return <img className="ngv__media" src={still} alt="" />
  return <div className="ngv__media ngv__media--empty">{t('graph.noResult')}</div>
}

/** 花钱的按钮：不用确认就直接发；要确认（超过确认线、待核对）或服务端金额变了就在卡片里问一次 */
function SpendButton({ text, cny, must, disabled, onSpend }: {
  text: string; cny: number; must: boolean; disabled: boolean
  /** 发请求；服务端金额变了返回新金额 */
  onSpend: (cny: number) => Promise<number | null>
}) {
  const { t } = useI18n()
  const [asking, setAsking] = useState<number | null>(null)
  const go = async (amount: number) => setAsking(await onSpend(amount))
  if (asking !== null) {
    return (
      <span className="ngv__ask" data-testid="ngv-ask">
        <span>{t('graph.confirmCost', { cost: yuan(asking) })}</span>
        <Button size="sm" disabled={disabled} onClick={() => void go(asking)}>{t('graph.confirm')}</Button>
        <Button size="sm" variant="ghost" onClick={() => setAsking(null)}>{t('graph.cancel')}</Button>
      </span>
    )
  }
  return <Button size="sm" disabled={disabled} onClick={() => (must ? setAsking(cny) : void go(cny))}>{text}</Button>
}

/** 在成功的几次之间切换采用（at 为当前采用的那次在列表里的位置，没有为 -1） */
function AttemptNav({ at, total, disabled, onPick }: {
  at: number; total: number; disabled: boolean; onPick: (k: number) => void
}) {
  const { t } = useI18n()
  return (
    <span className="ngv__nav">
      <button type="button" className="tlc__linkbtn" disabled={disabled || at <= 0} aria-label={t('graph.prev')}
              onClick={() => onPick(at - 1)}>‹</button>
      <span>{t('graph.attemptOf', { n: at + 1, total })}</span>
      <button type="button" className="tlc__linkbtn" disabled={disabled || at >= total - 1} aria-label={t('graph.next')}
              onClick={() => onPick(at + 1)}>›</button>
    </span>
  )
}

export function AssetCard({ role, name, image, usedBy, onOpen }: {
  role: AssetRole; name: string; image: string | null; usedBy: number; onOpen: () => void
}) {
  const { t } = useI18n()
  return (
    <>
      {image ? <img className="ngv__thumb" src={image} alt="" />
        : <div className="ngv__thumb ngv__thumb--empty">{t('graph.noImage')}</div>}
      <div className="ngv__meta">
        <b>{role === 'style' ? t('graph.style') : name}</b>
        <span className="ngv__dim">{t(`graph.kind.${role}` as MsgKey)} · {t('graph.usedBy', { n: usedBy })}</span>
        {role !== 'style' && (
          <button type="button" className="tlc__linkbtn" onClick={(e) => { e.stopPropagation(); onOpen() }}>
            {t('graph.openAssets')}
          </button>
        )}
      </div>
    </>
  )
}

export function ClipCard({ clip: c, s, film, blocked, hot, fallback, onDerive }: {
  clip: FilmClip; s: FilmSession; film: Film; blocked: string | null; hot: boolean
  /** 没有结果时显示的首帧来源图（关键帧或上一段尾帧） */
  fallback: string | null
  onDerive: () => void
}) {
  const { t } = useI18n()
  const ok = c.attempts.map((a, i) => ({ a, i })).filter((x) => x.a.state === 'succeeded' && x.a.file)
  const at = ok.findIndex((x) => x.i === c.chosen)
  const lock = !!blocked || inFlight(c) || film.busy
  const spent = c.attempts.reduce((n, a) => n + (a.cost_cny ?? 0), 0)
  const chosen = chosenAttempt(c)
  const redo = c.attempts.some((a) => a.state === 'succeeded')
  return (
    <>
      <header className="ngv__head">
        <b>{c.id}</b><span className="ngv__dim">{c.duration}s</span>
        <StatusPill tone={TONE[c.state]}>{label(FILM_STATE, c.state)}</StatusPill>
      </header>
      <Preview film={film} attempt={chosen} fallback={fallback} hot={hot} />
      {chosen?.free_id && <p className="ngv__dim">{t('graph.fromFree', { id: chosen.free_id })}</p>}
      <p className="ngv__prompt">{c.prompt}</p>
      <p className="ngv__dim">
        {t('graph.spent', { spent: yuan(spent), est: yuan(c.estimate_cny) })} · {t('graph.attempts', { n: c.attempts.length })}
      </p>
      {c.error && <p className="ngv__err">{c.error}</p>}
      <div className="ngv__acts" onClick={(e) => e.stopPropagation()}>
        <SpendButton text={t(redo ? 'graph.redo' : 'graph.run', { cost: yuan(c.estimate_cny) })} cny={c.estimate_cny}
                     must={c.uncertain || needsConfirm(c, s)} disabled={lock}
                     onSpend={(cny) => film.runClipNow(c.id, cny)} />
        {ok.length > 1 && (
          <AttemptNav at={at} total={ok.length} disabled={lock} onPick={(k) => void film.choose(c.id, ok[k].i)} />
        )}
        <Button size="sm" variant="ghost" disabled={film.busy} onClick={onDerive}>{t('graph.derive')}</Button>
      </div>
    </>
  )
}

export function FreeCard({ node: n, s, film, blocked, hot, fallback, kfShots, assetOptions }: {
  node: FilmFreeNode; s: FilmSession; film: Film; blocked: string | null; hot: boolean
  fallback: string | null
  /** 有关键帧的镜头 */
  kfShots: string[]
  /** 参考可选项：左列有图的资产与风格图 */
  assetOptions: { id: string; name: string }[]
}) {
  const { t } = useI18n()
  const lock = !!blocked || inFlight(n) || film.busy
  const { patchFree } = film
  const [text, setText] = useState(n.prompt)
  const [saving, setSaving] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [askDel, setAskDel] = useState(false)
  // 服务端的正文变了（派生、别处改的）且本地没有未保存的输入：跟着服务端
  const server = useRef(n.prompt)
  useEffect(() => {
    setText((cur) => (cur === server.current ? n.prompt : cur))
    server.current = n.prompt
  }, [n.prompt])
  const timer = useRef<number | undefined>(undefined)
  const flush = useCallback((value: string) => {
    window.clearTimeout(timer.current)
    setSaving('saving')
    void patchFree(n.id, { prompt: value }).then(() => setSaving('saved'))
  }, [patchFree, n.id])
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const onType = (value: string) => {
    setText(value)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => flush(value), 800)
  }

  const max = s.options.max_refs
  const used = slotsNeeded(n.refs, n.first_frame, s)
  const toggleRef = (id: string) =>
    void patchFree(n.id, { refs: n.refs.includes(id) ? n.refs.filter((x) => x !== id) : [...n.refs, id] })
  const tails = tailSources(s).filter((id) => id !== n.id)
  const ok = n.attempts.map((a, i) => ({ a, i })).filter((x) => x.a.state === 'succeeded' && x.a.file)
  const at = ok.findIndex((x) => x.i === n.chosen)
  const chosen = chosenAttempt(n)
  const target = n.target ? s.clips.find((c) => c.id === n.target) : undefined
  const copy = target && chosen ? copyIndex(s, n, chosen) : -1
  const url = chosen?.file ? film.files[chosen.file] : undefined
  return (
    <>
      <header className="ngv__head">
        <b>{n.id}</b>
        <StatusPill tone={TONE[n.state]}>{label(FILM_STATE, n.state)}</StatusPill>
        <span className="ngv__dim">{n.target ? t('graph.free.replaces', { id: n.target }) : t('graph.free.standalone')}</span>
      </header>
      {n.target_lost && !n.target && <p className="ngv__warn">{t('graph.free.lost')}</p>}
      {n.over_refs && <p className="ngv__warn">{t('graph.free.overRefs', { n: used, max })}</p>}
      <Preview film={film} attempt={chosen} fallback={fallback} hot={hot} />
      <div className="ngv__form" onClick={(e) => e.stopPropagation()}>
        <textarea className="ngv__text" value={text} disabled={lock} placeholder={t('graph.free.promptPh')}
                  onChange={(e) => onType(e.target.value)}
                  onBlur={() => { if (text !== n.prompt && saving !== 'saving') flush(text) }} />
        {saving !== 'idle' && (
          <span className="ngv__dim">{saving === 'saving' ? t('graph.free.saving') : t('graph.free.saved')}</span>
        )}
        <label className="ngv__field">{t('graph.free.duration')}
          {n.target ? <span>{t('graph.free.sec', { n: n.duration })}</span> : (
            <input key={n.duration} type="number" min={1} max={s.options.max_clip_sec} step={0.5}
                   defaultValue={n.duration} disabled={lock}
                   onBlur={(e) => {
                     const v = Number(e.target.value)
                     if (v && v !== n.duration) void patchFree(n.id, { duration: v })
                   }} />
          )}
        </label>
        <label className="ngv__field">{t('graph.free.firstFrame')}
          <select value={n.first_frame ?? ''} disabled={lock}
                  onChange={(e) => void patchFree(n.id, { first_frame: e.target.value || null })}>
            <option value="">{t('graph.free.none')}</option>
            {kfShots.map((id) => <option key={id} value={`keyframe:${id}`}>{t('graph.free.keyframe', { id })}</option>)}
            {tails.map((id) => <option key={id} value={`tail:${id}`}>{t('graph.free.tail', { id })}</option>)}
          </select>
        </label>
        <details className="ngv__refs">
          <summary>{t('graph.free.refs', { n: used, max })}</summary>
          {assetOptions.map((o) => {
            const on = n.refs.includes(o.id)
            const full = !on && slotsNeeded([...n.refs, o.id], n.first_frame, s) > max
            return (
              <label key={o.id} className="check">
                <input type="checkbox" checked={on} disabled={lock || full} onChange={() => toggleRef(o.id)} />
                {o.name}
              </label>
            )
          })}
        </details>
        <label className="ngv__field">{t('graph.free.target')}
          <select value={n.target ?? ''} disabled={lock}
                  onChange={(e) => void patchFree(n.id, { target: e.target.value || null })}>
            <option value="">{t('graph.free.noTarget')}</option>
            {s.clips.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
          </select>
        </label>
      </div>
      {n.error && <p className="ngv__err">{n.error}</p>}
      <div className="ngv__acts" onClick={(e) => e.stopPropagation()}>
        <SpendButton text={t('graph.free.generate', { cost: yuan(n.estimate_cny) })} cny={n.estimate_cny}
                     must={n.uncertain || n.estimate_cny > s.confirm_over_cny}
                     disabled={lock || n.over_refs || !n.prompt.trim()}
                     onSpend={(cny) => film.runFree(n.id, cny)} />
        {ok.length > 1 && (
          <AttemptNav at={at} total={ok.length} disabled={lock} onPick={(k) => void film.chooseFree(n.id, ok[k].i)} />
        )}
        {target && copy >= 0 && target.chosen !== copy && (
          <Button size="sm" variant="secondary" disabled={lock || inFlight(target)}
                  onClick={() => void film.choose(target.id, copy)}>{t('graph.free.adopt')}</Button>
        )}
        {!n.target && chosen?.file && (url
          ? <a className="tlc__linkbtn" href={url} download={`${n.id}.mp4`}>{t('graph.free.download')}</a>
          : <button type="button" className="tlc__linkbtn" onClick={() => film.ensure(chosen.file)}>
              {t('graph.free.download')}
            </button>)}
        {askDel ? (
          <span className="ngv__ask">
            <span>{t('graph.free.deleteConfirm')}</span>
            <Button size="sm" variant="destructive" disabled={lock} onClick={() => void film.deleteFree(n.id)}>
              {t('graph.free.delete')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setAskDel(false)}>{t('graph.cancel')}</Button>
          </span>
        ) : (
          <Button size="sm" variant="ghost" disabled={lock}
                  onClick={() => (n.attempts.some((a) => a.state === 'succeeded') ? setAskDel(true)
                    : void film.deleteFree(n.id))}>
            {t('graph.free.delete')}
          </Button>
        )}
      </div>
    </>
  )
}
```

- [ ] **Step 3: 新建 `frontend/src/components/NodeGraph.tsx`**

```tsx
/** 出片画布的「节点图」视图：资产、剧本段、自由节点三列，连线显示谁参考了谁（设计文档 2026-11-11 §5）。
 *  布局由 nodeGraph.ts 的纯函数算好，这里只管平移缩放、高亮和把卡片摆上去。
 *  盖在时间轴上面（时间轴不卸载），指针与滚轮事件在这一层处理、不往下传；Esc 先取消选中，再交给画布关闭。 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as RPointerEvent, WheelEvent as RWheelEvent } from 'react'
import { Maximize2, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { chosenAttempt, freeNodes } from '../film'
import { edgePath, fitView, layoutGraph, related } from '../nodeGraph'
import type { Film } from '../useFilm'
import type { Storyboard } from '../types'
import { AssetCard, ClipCard, FreeCard } from './NodeCards'

const ZOOM = { min: 0.3, max: 1.5 }

export function NodeGraph({ film, doc, styleUrl, kfUrls, selected, blocked, onSelect, onOpenAssets, onOpenFilm }: {
  film: Film
  doc: Storyboard
  styleUrl: string | null
  /** 镜头 id → 关键帧图 */
  kfUrls: Record<string, string>
  /** 选中的段或自由节点（与侧栏「出片」页同一个） */
  selected: string | null
  /** 有未保存的改动或没过验证门：花钱的按钮禁用 */
  blocked: string | null
  onSelect: (id: string) => void
  onOpenAssets: () => void
  onOpenFilm: () => void
}) {
  const { t } = useI18n()
  const s = film.session
  const assets = doc.assets
  const graph = useMemo(() => (s ? layoutGraph({ session: s, assets: assets ?? {}, hasStyle: !!styleUrl, styleUrl }) : null),
                        [s, assets, styleUrl])
  const [view, setView] = useState({ scale: 1, x: 24, y: 24 })
  const [focus, setFocus] = useState<string | null>(selected)
  const [hover, setHover] = useState<string | null>(null)
  useEffect(() => { setFocus(selected) }, [selected])
  const box = useRef<HTMLDivElement>(null)
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null)
  // Esc 先取消选中：捕获阶段抢在画布的「Esc 关闭」前面，preventDefault 后画布就不处理了
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || (!focus && !hover)) return
      e.preventDefault()
      setFocus(null)
      setHover(null)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [focus, hover])
  const key = hover ?? focus
  const lit = useMemo(() => (graph ? related(graph, key) : new Set<string>()), [graph, key])

  const stop = (e: { stopPropagation: () => void }) => e.stopPropagation()
  if (!s || !graph) {
    return (
      <div className="ngv" data-testid="node-graph" onPointerDown={stop} onWheel={stop}>
        <div className="ngv__empty">
          <p>{t('graph.noSession')}</p>
          <Button size="sm" onClick={onOpenFilm}>{t('graph.openFilm')}</Button>
        </div>
      </div>
    )
  }

  const down = (e: RPointerEvent<HTMLDivElement>) => {
    e.stopPropagation()
    if ((e.target as HTMLElement).closest('.ngv__node, .ngv__tools')) return
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }
  }
  const move = (e: RPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (d) setView((v) => ({ ...v, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y }))
  }
  const up = () => { drag.current = null }
  const wheel = (e: RWheelEvent<HTMLDivElement>) => {
    e.stopPropagation()
    const rect = box.current?.getBoundingClientRect()
    const px = e.clientX - (rect?.left ?? 0)
    const py = e.clientY - (rect?.top ?? 0)
    setView((v) => {
      const scale = Math.min(ZOOM.max, Math.max(ZOOM.min, v.scale * Math.exp(-e.deltaY * 0.001)))
      const k = scale / v.scale
      return { scale, x: px - (px - v.x) * k, y: py - (py - v.y) * k }
    })
  }
  const fit = () => { if (box.current) setView(fitView(graph, box.current.clientWidth, box.current.clientHeight)) }

  /** 首帧来源图：关键帧，或那一段 / 那个节点采用的那次的尾帧（由它自己的卡片取回） */
  const frameOf = (ff: string | null): string | null => {
    if (!ff) return null
    if (ff.startsWith('keyframe:')) return kfUrls[ff.slice('keyframe:'.length)] ?? null
    const src = ff.replace(/^(relay|tail):/, '')
    const it = [...s.clips, ...freeNodes(s)].find((x) => x.id === src)
    const lf = it ? chosenAttempt(it)?.last_frame : null
    return lf ? film.files[lf] ?? null : null
  }
  const kfShots = Object.keys(kfUrls)
  const assetOptions = graph.nodes.flatMap((n) => (n.kind === 'asset' && n.image
    ? [{ id: n.assetId, name: n.role === 'style' ? t('graph.style') : n.name }] : []))
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const dimmed = lit.size > 0

  return (
    <div className="ngv" ref={box} data-testid="node-graph" onPointerDown={down} onPointerMove={move}
         onPointerUp={up} onPointerLeave={up} onWheel={wheel}
         onClick={(e) => { if (!(e.target as HTMLElement).closest('.ngv__node, .ngv__tools')) setFocus(null) }}>
      <div className="ngv__tools">
        <Button size="sm" variant="ghost" onClick={fit}><Maximize2 aria-hidden />{t('graph.fit')}</Button>
        <Button size="sm" variant="ghost" disabled={film.busy} onClick={() => void film.createFree()}>
          <Plus aria-hidden />{t('graph.newFree')}
        </Button>
        {film.error && <span className="ngv__err">{film.error}</span>}
        {blocked && <span className="ngv__err">{blocked}</span>}
      </div>
      <div className="ngv__world"
           style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`, width: graph.width, height: graph.height }}>
        <svg className="ngv__edges" width={graph.width + 80} height={graph.height} aria-hidden="true">
          {graph.edges.map((e) => {
            const on = key !== null && (e.from === key || e.to === key)
            return (
              <path key={e.id} data-edge={e.id} d={edgePath(byId.get(e.from)!, byId.get(e.to)!)}
                    className={cn('ngv__edge', `ngv__edge--${e.kind}`, dimmed && (on ? 'is-lit' : 'is-dim'))} />
            )
          })}
        </svg>
        {graph.nodes.map((n) => {
          const style = { left: n.x, top: n.y, width: n.w, height: n.h }
          const cls = cn('ngv__node', `ngv__node--${n.kind}`, n.id === focus && 'is-on',
                         dimmed && (lit.has(n.id) ? 'is-lit' : 'is-dim'))
          if (n.kind === 'episode') return <div key={n.id} className={cls} style={style}>{n.episode}</div>
          const pick = () => {
            setFocus(n.id)
            if (n.kind === 'clip' || n.kind === 'free') onSelect(n.id)
          }
          const hot = hover === n.id || focus === n.id
          return (
            <div key={n.id} className={cls} style={style} data-node={n.id} tabIndex={0}
                 onClick={pick} onKeyDown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) pick() }}
                 onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}>
              {n.kind === 'asset' && (
                <AssetCard role={n.role} name={n.name} image={n.image} usedBy={n.usedBy} onOpen={onOpenAssets} />
              )}
              {n.kind === 'clip' && (
                <ClipCard clip={n.clip} s={s} film={film} blocked={blocked} hot={hot}
                          fallback={frameOf(n.clip.first_frame)} onDerive={() => void film.createFree(n.clip.id)} />
              )}
              {n.kind === 'free' && (
                <FreeCard node={n.node} s={s} film={film} blocked={blocked} hot={hot}
                          fallback={frameOf(n.node.first_frame)} kfShots={kfShots} assetOptions={assetOptions} />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: 新建 `frontend/src/styles/nodegraph.css`，并在 `app.css` 引入**

`frontend/src/styles/nodegraph.css`：

```css
/* 出片画布「节点图」视图（NodeGraph.tsx）：盖在时间轴上（z-index 1，底部工具条 .tlc__bar 是 2，仍在上面），
 * 三列卡片 + 连线。卡片尺寸由 nodeGraph.ts 的常量决定，这里只管样子。 */
.ngv { position: absolute; inset: 0; z-index: 1; overflow: hidden; background: var(--background); cursor: grab; touch-action: none; }
.ngv__tools { position: absolute; top: 12px; right: 12px; z-index: 2; display: flex; align-items: center; gap: 6px; }
.ngv__world { position: absolute; left: 0; top: 0; transform-origin: 0 0; }
.ngv__edges { position: absolute; left: 0; top: 0; overflow: visible; pointer-events: none; }
.ngv__edge { fill: none; stroke: var(--ui-muted-foreground); stroke-width: 1.5; opacity: .35; transition: opacity .15s ease-out; }
.ngv__edge--dropped { stroke-dasharray: 6 4; }
.ngv__edge--missing { stroke-dasharray: 2 4; }
.ngv__edge--frame { stroke: var(--primary); }
.ngv__edge--target { stroke: var(--warning); stroke-width: 2.5; stroke-dasharray: 8 5; }
.ngv__edge.is-lit { opacity: 1; }
.ngv__edge.is-dim { opacity: .08; }
.ngv__node {
  position: absolute; box-sizing: border-box; display: flex; flex-direction: column; gap: 4px; padding: 8px;
  overflow: hidden; border: 1px solid var(--border); border-radius: 10px; background: var(--card); font-size: 12px;
  cursor: default; transition: opacity .15s ease-out, box-shadow .15s ease-out;
}
.ngv__node--asset { flex-direction: row; align-items: center; }
.ngv__node--episode { border: 0; background: none; padding: 4px 0; font-weight: 600; color: var(--ui-muted-foreground); }
.ngv__node.is-on { box-shadow: 0 0 0 2px var(--primary); }
.ngv__node.is-dim { opacity: .35; }
.ngv__head { display: flex; align-items: center; gap: 6px; }
.ngv__head b { font-family: ui-monospace, monospace; }
.ngv__media { flex: none; width: 100%; height: 72px; border-radius: 6px; object-fit: cover; background: var(--muted); }
.ngv__media--empty, .ngv__thumb--empty { display: grid; place-items: center; color: var(--ui-muted-foreground); }
.ngv__thumb { flex: none; width: 56px; height: 56px; border-radius: 6px; object-fit: cover; background: var(--muted); }
.ngv__meta { display: flex; min-width: 0; flex-direction: column; gap: 2px; padding-left: 8px; }
.ngv__prompt { display: -webkit-box; margin: 0; overflow: hidden; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.ngv__dim { margin: 0; color: var(--ui-muted-foreground); }
.ngv__err { margin: 0; color: var(--destructive); }
.ngv__warn { margin: 0; color: var(--warning); }
.ngv__form { display: flex; flex-direction: column; gap: 4px; }
.ngv__text { width: 100%; min-height: 48px; resize: none; border: 1px solid var(--border); border-radius: 6px; padding: 4px 6px; background: var(--background); }
.ngv__field { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.ngv__field select, .ngv__field input { max-width: 150px; }
.ngv__refs summary { cursor: pointer; }
.ngv__acts { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-top: auto; }
.ngv__nav { display: inline-flex; align-items: center; gap: 2px; }
.ngv__ask { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.ngv__empty { display: grid; height: 100%; place-items: center; align-content: center; gap: 8px; }
```

`frontend/src/styles/app.css` 里，在 `@import "./film.css" layer(components);` 这一行后加：

```css
@import "./nodegraph.css" layer(components);
```

- [ ] **Step 5: 运行前端检查**

Run: `cd frontend && npm test && npm run lint && npx vite build`
Expected:
- 18 套全部通过（组件还没挂载，只做类型检查）；
- lint 0 error、warning 仍是 5 个；
- 构建成功。

如果 lint 报了 `exhaustive-deps` 或 `only-export-components`，按提示补依赖，或把非组件导出移出组件文件，直到 warning 回到 5 个。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/NodeCards.tsx frontend/src/components/NodeGraph.tsx frontend/src/styles/nodegraph.css frontend/src/styles/app.css frontend/src/i18n/zh.ts frontend/src/i18n/en.ts
git commit -m "节点图视图与卡片：三列卡片与五种连线，拖动平移、滚轮缩放、适应画面，选中或悬停只亮相关连线，Esc 先取消选中；剧本段卡显示尾帧封面、悬停才取视频，可出这一段、换采用、派生；自由节点卡可改正文（防抖保存）、时长、首帧、参考与挂靠，生成前在卡片里确认金额，可设为挂靠段的采用、下载与删除"
```

---

### Task 11: 挂进画布、出片面板的自由节点详情、界面测试

**Files:**
- Modify: `frontend/src/components/TimelineCanvas.tsx`
- Modify: `frontend/src/components/FilmPanel.tsx`
- Create: `frontend/tests/graph-view.test.tsx`
- Modify: `frontend/package.json`

- [ ] **Step 1: 写失败的界面测试 `frontend/tests/graph-view.test.tsx`**

```tsx
/** 节点图的界面回归：切到节点图（没会话时的空状态与打开出片页签）；建会话后每段一张卡、缺图资产与连线；
 *  选中高亮、Esc 只取消选中；封面只取尾帧、选中才取视频；派生自由节点、正文防抖保存；超过确认线在卡片里确认；
 *  设为挂靠段的采用；删除前确认；切回时间轴。桩后端在内存里模拟出片会话。纯计算由 node-graph.test.ts 覆盖。
 *  跑法：npm test
 */
import { readFileSync } from 'node:fs'
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'PointerEvent', 'MouseEvent', 'matchMedia', 'ResizeObserver', 'DOMRect',
                 'MutationObserver']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame = (cb: (t: number) => void) =>
  setTimeout(() => cb(performance.now()), 16) as unknown as number
g.cancelAnimationFrame = (id: number) => clearTimeout(id)

import type { FilmAttempt, FilmClip, FilmFreeNode, FilmSession, Storyboard } from '../src/types'

const doc: Storyboard = JSON.parse(
  readFileSync('../backend/tests/real_text_yao/output_merged.json', 'utf8'))

/* ---------- 桩后端：内存里的出片会话（含自由节点） ---------- */
const R = '/novels/n1/chapters/c1/versions/v1/render'
const IN_FLIGHT = ['queued', 'running', 'downloading']
let film: FilmSession | null = null
let seq = 0
const calls: string[] = []
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))

function recount(s: FilmSession): FilmSession {
  const counts: Record<string, number> = {}
  for (const c of s.clips) counts[c.state] = (counts[c.state] ?? 0) + 1
  const sum = (cs: { estimate_cny: number }[]) => Math.round(cs.reduce((n, c) => n + c.estimate_cny, 0) * 100) / 100
  return {
    ...s, counts,
    remaining_cny: sum(s.clips.filter((c) => (c.state === 'planned' || c.state === 'failed') && !c.uncertain)),
    reserved_cny: sum([...s.clips, ...(s.free ?? [])].filter((c) => IN_FLIGHT.includes(c.state))),
    uncertain_count: s.clips.filter((c) => c.uncertain).length,
  }
}

/** 每集两镜一段，每段 ¥5，都缺 C01 的图 */
function makeSession(): FilmSession {
  const clips: FilmClip[] = []
  for (const ep of doc.episodes) {
    for (let i = 0; i < ep.shots.length; i += 2) {
      clips.push({
        id: `${ep.id}-C${String(clips.length + 1).padStart(2, '0')}`, episode: ep.id,
        shots: ep.shots.slice(i, i + 2).map((s) => s.id), duration: 5, truncated: false,
        prompt: `${ep.id} 第 ${i / 2 + 1} 段的提示词`, refs: [], dropped_refs: [], missing_refs: ['C01'],
        first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 5, attempts: [], chosen: null,
        mute_native: false, uncertain: false, error: null, state: 'planned',
      })
    }
  }
  return recount({
    provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 100000,
    confirm_over_cny: 20, spent_cny: 0, clips, free: [], free_seq: 0, orphaned: [], counts: {}, remaining_cny: 0,
    reserved_cny: 0, uncertain_count: 0,
    options: { providers: ['fake'], models: { 'fake-1': { label: '假厂商' } }, resolutions: ['480p', '720p'],
               cny_per_sec: { '480p': 0.5, '720p': 1 }, max_clip_sec: 10, max_refs: 3, first_frame: true,
               frame_with_refs: false, audio_modes: ['tts_all', 'dialogue_native', 'all_native', 'silent'],
               rate_note: '假厂商：不联网、不花钱' },
  })
}

const clipOf = (id: string) => film!.clips.find((c) => c.id === id)!
const freeOf = (id: string) => film!.free!.find((n) => n.id === id)!
const attempt = (id: string, n: number, cost: number): FilmAttempt => ({
  task_id: `${id}-t${n}`, state: 'succeeded', cost_cny: cost, file: `clips/${id}.t${n}.mp4`,
  last_frame: `clips/${id}.t${n}.last.jpg`, error: null, at: '2026-11-11T03:00:00+00:00', fingerprint: 'fp',
  first_frame_used: null,
})

/** 模拟出片线程跑完一段 */
function finish(id: string) {
  const c = clipOf(id)
  c.attempts.push(attempt(id, c.attempts.length + 1, c.estimate_cny))
  c.chosen = c.attempts.length - 1
  c.state = 'done'
  film = recount(film!)
}

/** 模拟出片线程跑完一个自由节点：挂靠的复制一份进目标段（花费 0、带来源） */
function finishFree(id: string) {
  const n = freeOf(id)
  const a = attempt(id, n.attempts.length + 1, n.estimate_cny)
  n.attempts.push(a)
  n.chosen = n.attempts.length - 1
  n.state = 'done'
  if (n.target) clipOf(n.target).attempts.push({ ...a, free_id: id, cost_cny: 0 })
  film = recount(film!)
}

const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => clone(data) })
const fail = (status: number, detail: unknown) =>
  ({ ok: false, status, statusText: '', text: async () => JSON.stringify({ detail }) })

g.fetch = async (url: string, init?: { method?: string; body?: unknown }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  const body = init?.body ? JSON.parse(String(init.body)) : undefined
  if (path === '/render/keyframes') return ok({ keyframes: [] })
  if (path === '/novels/n1/chapters/c1/versions/v1/keyframes') return ok({ shots: [] })
  if (!path.startsWith(R)) throw new Error(`桩后端未实现的路径: ${method} ${path}`)
  const sub = path.slice(R.length)
  if (sub.startsWith('/compose') && method === 'GET') {
    return ok({ lines: 0, tts_chars: 0, tts_cny: 0, missing_voices: [], voices: {}, no_video: [], fingerprint: 'fp',
                final: null, bgm: [], tools: true, music: {}, report: null })
  }
  if (sub === '/voices' && method === 'GET') {
    return ok({ provider: 'fake', rate_note: '', voices: [], speakers: [], missing: [] })
  }
  calls.push(`${method} ${sub}${body === undefined ? '' : ` ${JSON.stringify(body)}`}`)
  if (sub.startsWith('/files/')) {
    return { ok: true, status: 200,
             blob: async () => new Blob(['x'], { type: sub.endsWith('.mp4') ? 'video/mp4' : 'image/jpeg' }) }
  }
  if (sub === '/session' && method === 'GET') {
    return film ? ok({ ...film, gate: { ok: true, message: null } }) : fail(404, '还没有出片会话')
  }
  if (sub === '/session' && method === 'POST') {
    film = makeSession()
    return ok(film)
  }
  let m = sub.match(/^\/clips\/([^/]+)\/chosen$/)
  if (m && method === 'PUT') {
    clipOf(decodeURIComponent(m[1])).chosen = body.attempt
    film = recount(film!)
    return ok(film)
  }
  if (sub === '/free' && method === 'POST') {
    seq += 1
    const id = `F${String(seq).padStart(2, '0')}`
    const from = body?.from_clip ? clipOf(body.from_clip) : null
    const n: FilmFreeNode = {
      id, target: from?.id ?? null, target_shots: from?.shots ?? null, target_lost: false,
      prompt: from ? from.prompt : '', refs: from ? [...from.refs] : [], first_frame: null,
      duration: from?.duration ?? 5, estimate_cny: from ? from.estimate_cny : 25, state: 'planned', error: null,
      uncertain: false, attempts: [], chosen: null, created_at: '', over_refs: false,
    }
    film = recount({ ...film!, free: [...(film!.free ?? []), n], free_seq: seq })
    return ok(film)
  }
  m = sub.match(/^\/free\/([^/]+)$/)
  if (m && method === 'PATCH') {
    Object.assign(freeOf(m[1]), body)
    film = recount(film!)
    return ok(film)
  }
  if (m && method === 'DELETE') {
    const fid = m[1]
    film = recount({ ...film!, free: film!.free!.filter((n) => n.id !== fid) })
    return ok(film)
  }
  m = sub.match(/^\/free\/([^/]+)\/run$/)
  if (m && method === 'POST') {
    const n = freeOf(m[1])
    if (n.estimate_cny > film!.confirm_over_cny && body?.expected_cny === undefined) {
      return fail(409, { message: `本次约 ¥${n.estimate_cny.toFixed(2)}，请确认金额后再生成`, expected_cny: n.estimate_cny })
    }
    Object.assign(n, { state: 'queued', queued_at: new Date().toISOString() })
    film = recount(film!)
    return ok(film)
  }
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}

const { act, useState } = await import('react')
const { createRoot } = await import('react-dom/client')
const { StoryboardView } = await import('../src/components/StoryboardView')

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 50) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}
const has = (s: string) => win.document.body.innerHTML.includes(s)
const button = (text: string) => {
  const b = [...win.document.body.querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(text))
  if (!b) throw new Error(`✗ 找不到按钮「${text}」`)
  return b as unknown as HTMLButtonElement
}
const exact = (text: string) => {
  const b = [...container.querySelectorAll('button')].find((x) => x.textContent === text)
  if (!b) throw new Error(`✗ 找不到按钮「${text}」`)
  return b as unknown as HTMLButtonElement
}
const card = (id: string) => {
  const el = container.querySelector(`[data-node="${id}"]`)
  if (!el) throw new Error(`✗ 节点图上找不到 ${id}`)
  return el as unknown as HTMLElement
}
const inCard = (id: string, text: string) => {
  const b = [...card(id).querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(text))
  if (!b) throw new Error(`✗ ${id} 卡片里找不到按钮「${text}」`)
  return b as unknown as HTMLButtonElement
}
const click = async (el: Element) => {
  await act(async () => {
    el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
const type = async (el: Element, value: string) => {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!
    setter.call(el, value)
    el.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
}
const tab = (name: string) =>
  [...container.querySelectorAll('.tlc__tabs button')].find((b) => b.textContent === name)
const refresh = () => click(button('刷新'))

function Host() {
  const [dirty, set] = useState(false)
  return <StoryboardView doc={doc} canSave dirty={dirty} saving={false}
                         version={{ nid: 'n1', cid: 'c1', vid: 'v1' }}
                         onChange={() => set(true)} onSave={() => set(false)} />
}

// 0. 切到节点图：没会话时空状态，按钮打开出片页签；建会话后每段一张卡、缺图资产与连线
await act(async () => { root.render(<Host />) })
await click(button('时间轴画布'))
await click(exact('节点图'))
must(!!container.querySelector('[data-testid="node-graph"]') && has('先在出片页签选好厂商与档位'), '没会话时的空状态')
await click(button('打开出片页签'))
must(tab('出片')?.getAttribute('aria-pressed') === 'true', '打开出片页签')
await click(button('建立出片会话'))
must(container.querySelectorAll('.ngv__node--clip').length === film!.clips.length, '每段一张卡')
must(!!card('asset:C01'), '缺图但被用到的资产也上图')
must(container.querySelectorAll('[data-edge^="missing:"]').length === film!.clips.length, '每段一条缺图连线')
console.log(`0. 节点图 ${film!.clips.length} 段 ✓`)

// 1. 选中高亮：选中段与相连的资产亮，其余变淡；侧栏显示这一段；Esc 只取消选中，不关画布
const first = film!.clips[0].id
const second = film!.clips[1].id
await click(card(first))
must(card(first).classList.contains('is-on') && card('asset:C01').classList.contains('is-lit')
     && card(second).classList.contains('is-dim'), '选中高亮相关节点')
must((container.querySelector('.film__clip')?.textContent ?? '').includes(first), '侧栏显示选中的段')
await act(async () => {
  win.document.body.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }) as unknown as Event)
})
await settle()
must(!!container.querySelector('.tlc') && !container.querySelector('.ngv__node.is-on'), 'Esc 先取消选中，不关画布')
console.log('1. 选中高亮与 Esc ✓')

// 2. 封面只取尾帧；没悬停或选中不取视频；选中才取
finish(first)
await refresh()
must(calls.some((c) => c.startsWith(`GET /files/clips/${first}.t1.last.jpg`)), '封面取尾帧')
must(!calls.some((c) => c.includes('.mp4')), '没悬停或选中不取视频')
await click(card(first))
must(calls.some((c) => c.startsWith(`GET /files/clips/${first}.t1.mp4`)), '选中才取视频')
console.log('2. 视频按需取 ✓')

// 3. 派生自由节点：挂靠这一段；正文停止输入后保存；点自由卡侧栏显示详情
await click(inCard(first, '派生自由节点'))
must(calls.includes(`POST /free {"from_clip":"${first}"}`) && (card('F01').textContent ?? '').includes(`顶替 ${first}`),
     '派生并挂靠这一段')
await type(card('F01').querySelector('textarea')!, '换个机位重拍')
await settle(900)
must(calls.includes('PATCH /free/F01 {"prompt":"换个机位重拍"}'), '停止输入后保存正文')
await click(card('F01'))
must(!!container.querySelector('[data-testid="free-detail"]'), '侧栏显示自由节点详情')
console.log('3. 派生与保存 ✓')

// 4. 新建独立素材：超过确认线时先在卡片里确认，确认后才发请求
await click(button('新建自由节点'))
await type(card('F02').querySelector('textarea')!, '空镜：河面')
await settle(900)
const n0 = calls.length
await click(inCard('F02', '生成 ¥25.00'))
must((card('F02').textContent ?? '').includes('约 ¥25.00，确认花这笔钱？')
     && !calls.slice(n0).some((c) => c.startsWith('POST /free/F02/run')), '超过确认线先在卡片里确认')
await click(inCard('F02', '确认'))
must(calls.includes('POST /free/F02/run {"expected_cny":25}') && freeOf('F02').state === 'queued', '确认后生成')
console.log('4. 卡片内确认 ✓')

// 5. 挂靠节点出完：设为这一段的采用（走现有采用接口，复制件在段里的下标）
finishFree('F01')
await refresh()
await click(inCard('F01', '设为这一段的采用'))
must(calls.includes(`PUT /clips/${first}/chosen {"attempt":1}`), '用现有采用接口设为采用')
console.log('5. 设为采用 ✓')

// 6. 删除：有结果时先确认
await click(inCard('F01', '删除'))
must((card('F01').textContent ?? '').includes('已下载的视频也会删掉，确定删除？') && !calls.includes('DELETE /free/F01'),
     '有结果时先确认')
await click(inCard('F01', '删除'))
must(calls.includes('DELETE /free/F01') && !container.querySelector('[data-node="F01"]'), '确认后删除')
console.log('6. 删除 ✓')

// 7. 切回时间轴：节点图收起
await click(exact('时间轴'))
must(!container.querySelector('[data-testid="node-graph"]'), '切回时间轴')
console.log('7. 切回时间轴 ✓')

await act(async () => { root.unmount() })
console.log('\nALL PASS')
```

（结尾与 `film.test.tsx` 一致：卸载后打印 `ALL PASS`，不调 `process.exit`。）

- [ ] **Step 2: 把新测试加进 `package.json` 的 `test` 脚本**

在 `"test"` 字符串里，把

```
node .ssrout/film.test.js &&
```

改成

```
node .ssrout/film.test.js && vite build --ssr tests/graph-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/graph-view.test.js &&
```

- [ ] **Step 3: 运行，确认失败**

Run: `cd frontend && npm test`
Expected: graph-view 第 0 步 FAIL，`✗ 找不到按钮「节点图」`。

- [ ] **Step 4: 改 `TimelineCanvas.tsx`**

1. 导入加一行（在 `import { FilmPanel } from './FilmPanel'` 之后）：

```tsx
import { NodeGraph } from './NodeGraph'
```

2. 把

```tsx
  /** 出片会话（只有存进后端的版本才有）；「出片」页签开着时轮询更勤 */
  const film = useFilm(version, { active: shown === 'film' })
```

改成

```tsx
  /** 画布视图：时间轴（播放、对齐、合成）或节点图（谁参考了谁、补拍） */
  const [view, setView] = useState<'timeline' | 'graph'>('timeline')
  /** 出片会话（只有存进后端的版本才有）；「出片」页签或节点图开着时轮询更勤 */
  const film = useFilm(version, { active: shown === 'film' || view === 'graph' })
```

3. 工具条里，紧接在

```tsx
           onPointerDown={(e) => e.stopPropagation()}>
        {editable && (
```

的 `onPointerDown…>` 之后、`{editable && (` 之前插入：

```tsx
        {film.enabled && (
          <span className="tlc__speed" role="group" aria-label={tt('graph.viewAria')}>
            {(['timeline', 'graph'] as const).map((v) => (
              <button key={v} type="button" aria-pressed={view === v} className={view === v ? 'is-on' : ''}
                      onClick={() => setView(v)}>{tt(v === 'timeline' ? 'graph.timeline' : 'graph.graph')}</button>
            ))}
          </span>
        )}
```

4. 把

```tsx
               onBlur={() => finishNodeEdit(true)} />
      )}

      </div>
```

改成

```tsx
               onBlur={() => finishNodeEdit(true)} />
      )}

      {view === 'graph' && film.enabled && (
        <NodeGraph film={film} doc={doc} styleUrl={styleUrl} kfUrls={kf.urls} selected={clipSel}
                   blocked={dirty ? tt('film.panel.blockedDirty')
                     : film.gate ? tt('film.panel.blockedGate', { gate: film.gate }) : null}
                   onSelect={(id) => { setClipSel(id); setPanel('film') }}
                   onOpenAssets={() => setPanel('assets')} onOpenFilm={() => setPanel('film')} />
      )}

      </div>
```

- [ ] **Step 5: 改 `FilmPanel.tsx`：选中自由节点时显示详情**

1. 类型导入加 `FilmFreeNode`。
2. `FilmPanel` 里 `const clip = s?.clips.find((c) => c.id === selected)` 之后加：

```tsx
  const freeSel = s?.free?.find((n) => n.id === selected)
```

把

```tsx
          {clip
            ? <ClipDetail key={clip.id} c={clip} film={film} blocked={blocked} onPickShot={onPickShot} />
            : <p className="tlc__kfnote">{t('film.panel.pickClip')}</p>}
```

改成

```tsx
          {clip
            ? <ClipDetail key={clip.id} c={clip} film={film} blocked={blocked} onPickShot={onPickShot} />
            : freeSel ? <FreeDetail key={freeSel.id} n={freeSel} film={film} />
            : <p className="tlc__kfnote">{t('film.panel.pickClip')}</p>}
```

3. 在 `ClipDetail` 函数之后加：

```tsx
/** 选中的自由节点：完整正文、参考、首帧、全部尝试（可播放）、失败原因；编辑与生成在节点图的卡片上 */
function FreeDetail({ n, film }: { n: FilmFreeNode; film: Film }) {
  const { t } = useI18n()
  const sep = t('common.listSep')
  const [watch, setWatch] = useState<number | null>(null)
  const file = watch === null ? null : (n.attempts[watch]?.file ?? null)
  const { ensure } = film
  useEffect(() => { ensure(file) }, [file, ensure])
  return (
    <section className="film__clip film__card" data-testid="free-detail">
      <header>
        <b><i className={`film__dot film__dot--${n.state}`} aria-hidden="true" />{t('graph.free.detail', { id: n.id })}</b>
        <span>{label(FILM_STATE, n.state)} · {n.duration}s · {yuan(n.estimate_cny)}</span>
      </header>
      {n.error && <p className="tlc__kferr">{n.error}</p>}
      <pre className="film__prompt">{n.prompt || t('film.panel.none')}</pre>
      <p className="film__line">{t('film.panel.refs', { list: n.refs.length ? n.refs.join(sep) : t('film.panel.none') })}</p>
      <p className="film__line">{t('film.panel.firstFrame', { v: firstFrameText({ first_frame: n.first_frame, frame_mode: null }) })}</p>
      {!!n.attempts.length && (
        <table className="film__attempts">
          <tbody>
            {n.attempts.map((a, i) => (
              <tr key={i} className={i === n.chosen ? 'is-chosen' : ''}>
                <td>{t('film.panel.attemptN', { n: i + 1 })}</td>
                <td>{when(a.at)}</td>
                <td>{label(ATTEMPT_STATE, a.state)}</td>
                <td>{yuan(a.cost_cny)}</td>
                <td>
                  {a.state === 'succeeded' && a.file && (
                    <button className="tlc__linkbtn" onClick={() => setWatch(i)}>{t('film.panel.play')}</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {file && (film.files[file]
        ? <video className="film__video" src={film.files[file]} controls autoPlay muted />
        : <p className="tlc__kfnote">{t('film.panel.readingVideo')}</p>)}
    </section>
  )
}
```

- [ ] **Step 6: 运行前端检查**

Run: `cd frontend && npm test && npm run lint && npx vite build`
Expected:
- graph-view 打印 0–7 ✓，19 套全部通过；
- `canvas.test.tsx` 的「工具条无中文」照旧通过（切换按钮走 i18n）；
- lint 0 error、warning 仍是 5 个；
- 构建成功。

如果 happy-dom 里 Esc 那一步没有被节点图拦下（画布被关），先确认 `NodeGraph` 的监听是 `addEventListener('keydown', onKey, true)`，并且测试从 `document.body` 派发事件。

- [ ] **Step 7: 跑一遍后端全部脚本（回归）**

Run: 全局约束里的一次跑完命令。
Expected: 全部 `ALL PASS`。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/TimelineCanvas.tsx frontend/src/components/FilmPanel.tsx frontend/tests/graph-view.test.tsx frontend/package.json
git commit -m "节点图挂进出片画布：顶栏切换时间轴与节点图，节点图开着时出片会话照样快轮询；点段卡或自由卡侧栏切到出片页并显示详情，出片面板新增自由节点详情（正文、参考、首帧、全部尝试可播放）；补节点图界面回归测试"
```

---

## 自查记录

**Spec 覆盖：**

| spec 条目 | 实现位置 |
|---|---|
| §1 数据、`free_seq` | Task 1 |
| §1.1 状态、尝试、`style_ref` | Task 1 迁移函数；Task 2 `request_for_free` 的 `style_ref` |
| §1.2 复制到目标段、插入位置、`_style_outdated` | Task 4 |
| §1.3 校验 | Task 3 `validate`；生成前的复查在 Task 2 |
| §1.4 派生 | Task 3 |
| §1.5 重新切段 | Task 1 `_sync_free` 与 `build` |
| §1.6 花费与互锁 | Task 1（`queue_run` / `begin_submit` / `view` / `begin_compose`）；Task 3 `queue` 的合成中检查 |
| §1.7 删除 | Task 3 |
| §2 接口 | Task 6 |
| §3.1 遍历在跑项 | Task 1（session）、Task 5（runner、novels） |
| §3.2 请求组装与分派 | Task 2、Task 5 |
| §4 导出 | Task 7 |
| §5.1 入口、轮询、`mainAction` | Task 8、Task 11 |
| §5.2 布局 | Task 9 |
| §5.3 交互 | Task 10 |
| §5.4 卡片 | Task 10 |
| §6 出错处理 | 分散在各任务（422 / 409、FreeInvalid、over_refs、target_lost 提示） |
| §7 测试 | 各任务的测试文件 |

与 spec 的差异都已写在「实施裁定」。

**占位扫描：** 没有 TBD、TODO，也没有「同上」；每个改代码的步骤都给了代码。

**类型一致：**
- `FilmFreeNode`、`FreePatch`、`slotsNeeded`、`tailSources`、`copyIndex`、`anyInFlight`、`STYLE_REF`、`freeNodes` 在 Task 8 定义，Task 9–11 使用，名字一致。
- 后端 `free.Ctx`、`free.tail_frame`、`compose.request_for_free`、`compose.FreeInvalid`、`compose.asset_slot`、`compose.free_slots_needed`、`sess.items`、`sess.any_in_flight`、`sess.is_free`、`sess.FREE_PREFIX` 在 Task 1–3 定义，Task 4–6 使用。
