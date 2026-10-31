# 画布出片界面（A2）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在时间轴画布里出片：「成片」泳道、侧栏「出片」页签（设置、前置检查、总览与主按钮、段详情、花钱前确认）、预览窗「播成片」，接上 A1 已完成的 `/render` 接口。

**Architecture:** 后端只补两处（读取会话时报告验证门结果、可选项带费率依据）。前端按「纯计算 / 数据钩子 / 组件」三层：`src/film.ts`（段在时间轴上的位置、横条文字、主按钮、确认清单、轮询间隔，单测覆盖）→ `src/useFilm.ts`（读取、建立、改设置、出片含确认金额、采用、静音、轮询、片段文件 blob URL）→ `src/components/FilmPanel.tsx`（侧栏页）+ `TimelineCanvas.tsx` 里的泳道、开关与预览窗。

**Tech Stack:** React 19 + TypeScript（vite），happy-dom 脚本式测试（`npm test`）；后端 FastAPI，脚本式测试（`.venv/bin/python tests/...`）。

**Spec:** `docs/specs/2026-10-28-video-generation-design.md` 第 2 节（画布交互）；第 6 节是 A1 的实施裁定（本计划在其后续写）。

---

## 全局约束

- 提交只 `git add` 具体文件，不用 `git add -A` / `git commit -a`；提交信息用中文、风格同 `git log --oneline -5`，**不带任何 Claude 署名**（无 `Co-Authored-By`、无 `Claude-Session`）。
- 不读、不打印 `backend/.env`。测试不联网、不花钱：后端用假厂商，前端用桩 `fetch`。
- 后端命令在 `backend/` 下执行；前端命令在 `frontend/` 下执行。
- 未跟踪的 `docs/specs/2026-10-27-commercialization-design-contract.md` 不要碰。
- 现有类型 `RenderClip` / `RenderPack` 是「渲染任务包」（列表视图的「渲染」页签）的，出片一律用 `Film*` 前缀，不要混用。

## 实施裁定（与设计文档第 2 节的差异，Task 6 写回设计文档）

1. **音色分配挪到 A3**：现在没有 TTS 音色表，「出片」设置里只写一句说明。
2. **「合成整章」、整集播放与下载成片字幕挪到 A3**：总览主按钮到「出剩余 N 段」为止，出完写「配音与合成整章在下一步」。
3. **费率依据**：各厂商带 `rate_note`（如实写出处、是否经账单核对），`view()` 的 `options.rate_note` 原样给界面，批量确认框照抄。不沿用 `plan.py` 的 `RATE_SOURCE`（那是渲染任务包按 2026-03 报道的估算，和出片用的 2026-10 刊例价不是一回事）。
4. **验证门预检**：`GET …/render/session` 附 `gate: {ok, message}`，只报告不拦；建会话、改设置、出片几个接口照旧过门拦截。
5. **会话不自动建立**：「出片」页签里点「建立出片会话（不花钱）」才 `POST`。
6. **只有存进后端的版本有出片**：画布没有 `version`（本地 JSON、分批预览）时不出现任何出片元素，也不请求出片接口。
7. **视频与缩略图**：`<video>` / `<image>` 带不了 token，按需取成 blob URL；泳道缩略图用采用那次的尾帧图。
8. **播成片**：预览窗里的视频跟着播放头走，偏差超过 0.3 秒才拖；静音跟 `mute_native`，倍速跟画布倍速。
9. **轮询之外加「刷新」**：页签开着且有段在跑每 5 秒、否则每 30 秒，总览里另有「刷新」。
10. **横条横跨所含镜头**（按可播时长的时间轴）；被截断的段照样横跨，标 ✂。
11. **上限按版本计**（A1 裁定 17）：设置里写明。

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/render/providers/base.py` | 修改：`VideoProvider` 增加 `rate_note` |
| `backend/render/providers/seedance.py`、`fake.py` | 修改：各自的 `rate_note` |
| `backend/render/session.py` | 修改：`view()` 的 `options.rate_note` |
| `backend/server/app.py` | 修改：`_gate_status`，`GET …/render/session` 附 `gate` |
| `frontend/src/types.ts` | 修改：`FilmSession`、`FilmClip`、`FilmAttempt`、`FilmSettings`、`AudioMode`、`FilmClipState` |
| `frontend/src/labels.ts` | 修改：`AUDIO_MODE`、`FILM_STATE`、`ATTEMPT_STATE` |
| `frontend/src/api.ts` | 修改：出片接口 8 个函数 + `conflictCny` |
| `frontend/src/film.ts` | 新建：纯计算 |
| `frontend/src/useFilm.ts` | 新建：数据钩子 |
| `frontend/src/components/FilmPanel.tsx` | 新建：侧栏「出片」页 |
| `frontend/src/components/TimelineCanvas.tsx` | 修改：泳道、页签、开关、预览窗 |
| `frontend/src/index.css` | 修改：末尾追加出片样式 |
| `frontend/tests/film-lane.test.ts` | 新建：纯计算单测 |
| `frontend/tests/film.test.tsx` | 新建：画布出片界面回归 |
| `frontend/tests/canvas.test.tsx` | 修改：桩后端对出片会话回 404 |
| `frontend/package.json` | 修改：`test` 脚本加两个测试 |

---

### Task 1: 后端：读取时报告验证门、可选项带费率依据

**Files:**
- Modify: `backend/render/providers/base.py`（`class VideoProvider(Protocol)` 的属性）
- Modify: `backend/render/providers/seedance.py`（`class Seedance`）
- Modify: `backend/render/providers/fake.py`（`class FakeVideo`）
- Modify: `backend/render/session.py`（`view()`）
- Modify: `backend/server/app.py`（`render_session_get` 与其上方）
- Test: `backend/tests/server/test_render.py`（末尾 `print("\nALL PASS")` 之前）

- [ ] **Step 1: 写失败测试**

In `backend/tests/server/test_render.py`, add `from fastapi import HTTPException` next to the other imports at the top (after `from fastapi.testclient import TestClient  # noqa: E402`, with the same `# noqa: E402`). Then insert this block immediately before the final `print("\nALL PASS")` in `main()`:

```python
    # ---------- 画布出片（A2）接口补充 ----------

    # 12. 读取时报告验证门结果（只报告不拦）；可选项带费率依据
    novels.create_version(uid, nid, cid, "v9", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v9", "succeeded", result=copy.deepcopy(DOC))
    R9 = f"/novels/{nid}/chapters/{cid}/versions/v9/render"
    assert c.post(R9 + "/session", headers=H, json={}).status_code == 200
    s = c.get(R9 + "/session", headers=H).json()
    assert s["gate"] == {"ok": True, "message": None}, s["gate"]
    assert "假厂商" in s["options"]["rate_note"], s["options"]
    real_gate = app_mod._render_gate

    def failing_gate(doc, record):
        raise HTTPException(422, detail={"message": "分镜未通过独立验证，禁止进入付费渲染",
                                         "verification": {"ok": False}})

    app_mod._render_gate = failing_gate
    try:
        r = c.get(R9 + "/session", headers=H)
        assert r.status_code == 200, "读取不被验证门拦下"
        assert r.json()["gate"] == {"ok": False, "message": "分镜未通过独立验证，禁止进入付费渲染"}
        assert c.post(R9 + "/run", headers=H, json={"expected_cny": 1}).status_code == 422
    finally:
        app_mod._render_gate = real_gate
    print("12. 读取报告验证门、费率依据 ✓")
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_render.py`
Expected: FAIL with `KeyError: 'gate'`

- [ ] **Step 3: 厂商的费率依据**

In `backend/render/providers/base.py`, inside `class VideoProvider(Protocol):`, add after the existing attribute declarations (before the first `def`):

```python
    rate_note: str      # 费率依据：如实写出处、是否经账单核对；出片确认框照抄
```

In `backend/render/providers/seedance.py`, add as the first class attribute of `class Seedance` (right after its docstring if it has one, otherwise right after the `class` line):

```python
    rate_note = ("2026-10 方舟官方刊例价（2.0 为 46、fast 为 37、mini 为 23 元/百万 token，"
                 "token ≈ 秒 × 宽 × 高 × 24 / 1024），未经账单核对")
```

In `backend/render/providers/fake.py`, add as the first class attribute of `class FakeVideo`:

```python
    rate_note = "假厂商：不联网、不花钱，金额只用于演示"
```

In `backend/render/session.py` `view()`, add one key to the `out["options"]` dict (after `"audio_modes": list(compose.AUDIO_MODES)`):

```python
                      "audio_modes": list(compose.AUDIO_MODES),
                      "rate_note": getattr(provider, "rate_note", "")}
```

(that is: replace the closing `}` of the options dict so `rate_note` is its last key).

- [ ] **Step 4: 读取时报告验证门**

In `backend/server/app.py`, add this function right above `@app.get(_R + "/session")`:

```python
def _gate_status(user: dict, nid: str, cid: str, vid: str) -> dict:
    """出片页签的前置检查：验证门结果。读取时只报告不拦（建会话、出片照旧过门）。"""
    record = _novel_call(novels.get_version, user["id"], nid, cid, vid)
    doc = record.get("result") or {}
    if not doc.get("episodes"):
        return {"ok": False, "message": "这个版本还没有分镜产物"}
    try:
        _render_gate(copy.deepcopy(doc), record)
    except HTTPException as e:
        d = e.detail
        return {"ok": False, "message": d.get("message") if isinstance(d, dict) else str(d)}
    return {"ok": True, "message": None}
```

Then in `render_session_get`, replace the last line `return _render_call(render_session.view, s)` with:

```python
    out = _render_call(render_session.view, s)
    out["gate"] = _gate_status(user, nid, cid, vid)
    return out
```

and change its docstring to `"""查询；按当前已保存的分镜重算指纹并标过期（在跑的段不动），附验证门结果（只报告）。"""`.

- [ ] **Step 5: 运行，确认通过**

Run: `cd backend && .venv/bin/python tests/server/test_render.py && for t in tests/render/test_*.py; do .venv/bin/python $t | tail -1; done`
Expected: test_render prints `12. 读取报告验证门、费率依据 ✓` and `ALL PASS`; each render test prints `ALL PASS`

- [ ] **Step 6: 提交**

```bash
git add render/providers/base.py render/providers/seedance.py render/providers/fake.py render/session.py server/app.py tests/server/test_render.py
git commit -m "出片接口补充：读取会话时附验证门结果（只报告不拦）；可选项带厂商的费率依据，供画布确认框照抄"
```

---

### Task 2: 前端类型、中文标签与出片接口

**Files:**
- Modify: `frontend/src/types.ts`（末尾追加）
- Modify: `frontend/src/labels.ts`（import 与末尾追加）
- Modify: `frontend/src/api.ts`（import 与「静帧预演：关键帧」一节之后）

- [ ] **Step 1: 类型**

Append to the end of `frontend/src/types.ts`:

```ts
/* ---------- 出片（视频生成会话，…/versions/{vid}/render/session） ---------- */

export type FilmClipState = 'planned' | 'queued' | 'running' | 'downloading' | 'done' | 'failed' | 'stale'
export type AudioMode = 'tts_all' | 'dialogue_native' | 'all_native' | 'silent'

/** 一段的一次出片尝试 */
export interface FilmAttempt {
  task_id: string | null
  state: 'submitting' | 'running' | 'succeeded' | 'failed'
  cost_cny: number
  /** 会话目录下的相对路径，用 filmFileUrl 取 */
  file: string | null
  last_frame: string | null
  error: string | null
  at: string
  fingerprint: string
  first_frame_used: string | null
}

export interface FilmClip {
  id: string
  episode: string
  shots: string[]
  duration: number
  /** 超出单段上限，尾部被截断 */
  truncated: boolean
  prompt: string
  /** 带图的参考资产；dropped 为超出名额被裁的；missing 为没有图、只写文字描述的 */
  refs: string[]
  dropped_refs: string[]
  missing_refs: string[]
  /** keyframe:<镜头 id> | relay:<上一段 id> | null */
  first_frame: string | null
  frame_mode: 'frame' | 'ref' | null
  fingerprint: string
  estimate_cny: number
  attempts: FilmAttempt[]
  /** 采用第几次（attempts 的下标） */
  chosen: number | null
  mute_native: boolean
  /** 厂商那边可能还有这一段的任务（提交结果不明、查询放弃）：请到控制台核对，批量出片跳过 */
  uncertain: boolean
  error: string | null
  state: FilmClipState
  queued_at?: string
}

export interface FilmSettings {
  provider?: string
  model?: string
  resolution?: string
  audio_mode?: AudioMode
  budget_cny?: number
  confirm_over_cny?: number
}

export interface FilmSession {
  provider: string
  model: string
  resolution: string
  audio_mode: AudioMode
  /** 上限按版本计 */
  budget_cny: number
  /** 单段预估超过它要先确认 */
  confirm_over_cny: number
  spent_cny: number
  clips: FilmClip[]
  orphaned: { id: string; shots: string[]; attempts: FilmAttempt[]; chosen: number | null }[]
  counts: Partial<Record<FilmClipState, number>>
  /** 批量「出剩余各段」的预估（不含待核对的段） */
  remaining_cny: number
  /** 在排队 / 生成中的段的预估 */
  reserved_cny: number
  uncertain_count: number
  /** 验证门：只有读取时带；没有就当已通过（建会话、出片这几个接口本身过门） */
  gate?: { ok: boolean; message: string | null }
  options: {
    providers: string[]
    models: Record<string, { label: string }>
    resolutions: string[]
    cny_per_sec: Record<string, number>
    max_clip_sec: number
    max_refs: number
    audio_modes: AudioMode[]
    rate_note: string
  }
}
```

- [ ] **Step 2: 中文标签**

In `frontend/src/labels.ts`, replace the import block at the top with:

```ts
import type {
  AudioMode, CameraAngle, CameraMovement, Derivation, DialogueType, FidelityMode, FilmAttempt, FilmClipState,
  JobStatus, LifecycleEntry, LifecycleType, LocationAngle, Mood, NarrationMode, ShotSize, TimeOfDay,
  Transition, UnitKind,
} from './types'
```

Append to the end of `frontend/src/labels.ts`:

```ts
/** 出片的声音模式（设计文档 1.3 / 3.4） */
export const AUDIO_MODE: Record<AudioMode, string> = {
  tts_all: '全部配音（视频只出环境音，字一定对）',
  dialogue_native: '台词原声（有口型，不保证逐字）',
  all_native: '全部原声（最省事）',
  silent: '无声（画面 + 字幕）',
}

export const FILM_STATE: Record<FilmClipState, string> = {
  planned: '未出片', queued: '排队中', running: '生成中', downloading: '下载中',
  done: '已完成', failed: '失败', stale: '已过期',
}

export const ATTEMPT_STATE: Record<FilmAttempt['state'], string> = {
  submitting: '提交中', running: '生成中', succeeded: '成功', failed: '失败',
}
```

- [ ] **Step 3: 出片接口**

In `frontend/src/api.ts`, add `FilmSession, FilmSettings,` to the `import type { … } from './types'` list (e.g. on the line with `KeyframePrompt`). Then insert this section right before `/* ---------- 管理后台 ---------- */`:

```ts
/* ---------- 出片（视频生成会话） ---------- */

const filmPath = (nid: string, cid: string, vid: string) => `${versionPath(nid, cid, vid)}/render`

/** 读取出片会话（附验证门结果）；还没建过是 404 */
export function getFilm(nid: string, cid: string, vid: string): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/session`)
}

/** 建立（或按当前设置重建）出片会话：过验证门、切段，不花钱 */
export function createFilm(nid: string, cid: string, vid: string,
                           settings: FilmSettings = {}): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/session`, jsonPost(settings))
}

/** 改设置：按新设置重新切段（不花钱）；有段在跑时 409 */
export function patchFilm(nid: string, cid: string, vid: string,
                          settings: FilmSettings): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/session`, jsonBody('PATCH', settings))
}

/** 出这一段（试段 / 重做）。超过确认线时要带用户确认过的金额 */
export function runFilmClip(nid: string, cid: string, vid: string, clipId: string,
                            expectedCny?: number): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/clips/${enc(clipId)}/run`,
             jsonPost(expectedCny === undefined ? {} : { expected_cny: expectedCny }))
}

/** 批量出剩余各段：必须带确认金额，服务端重算不一致 409 */
export function runFilmRest(nid: string, cid: string, vid: string,
                            expectedCny: number): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/run`, jsonPost({ expected_cny: expectedCny }))
}

/** 采用这一段的第几次 */
export function chooseFilmAttempt(nid: string, cid: string, vid: string, clipId: string,
                                  attempt: number): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/clips/${enc(clipId)}/chosen`, jsonBody('PUT', { attempt }))
}

/** 合成时这一段的视频原声静音 */
export function muteFilmClip(nid: string, cid: string, vid: string, clipId: string,
                             mute: boolean): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/clips/${enc(clipId)}`, jsonBody('PATCH', { mute_native: mute }))
}

/** 取会话目录下的文件（片段视频、尾帧）。<video>/<image> 带不了 token，转成 blob URL（用完要 revoke） */
export async function filmFileUrl(nid: string, cid: string, vid: string, path: string): Promise<string> {
  const res = await send(`${filmPath(nid, cid, vid)}/files/${path.split('/').map(enc).join('/')}`)
  return URL.createObjectURL(await res.blob())
}

/** 出片 409 里服务端重算的金额（确认金额对不上、或单段需要确认时附带）；不是这种错误返回 null */
export function conflictCny(e: unknown): number | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null
  const d = e.detail as { expected_cny?: unknown } | null
  return d && typeof d === 'object' && typeof d.expected_cny === 'number' ? d.expected_cny : null
}
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npm run typecheck`
Expected: exits 0 with no errors

- [ ] **Step 5: 提交**

```bash
git add src/types.ts src/labels.ts src/api.ts
git commit -m "画布出片：出片会话的前端类型与中文标签；读取、建立、改设置、单段与批量出片、采用、静音、取片段文件的接口函数"
```

---

### Task 3: 出片纯计算（`film.ts`）

**Files:**
- Create: `frontend/src/film.ts`
- Test: `frontend/tests/film-lane.test.ts`
- Modify: `frontend/package.json`（`test` 脚本）

- [ ] **Step 1: 写失败测试**

Create `frontend/tests/film-lane.test.ts`:

```ts
/** 出片的纯计算：段在时间轴上的位置、横条文字与样式、主按钮、确认清单、轮询间隔、前置检查。
 *  画布交互由 film.test.tsx 覆盖。跑法：npm test */
import { readFileSync } from 'node:fs'
import { buildTimeline } from '../src/timeline'
import {
  batchSummary, chosenAttempt, clipOffset, clipSpans, firstFrameText, laneKind, laneText, laneTitle,
  mainAction, needsConfirm, pollDelay, POLL_FAST_MS, POLL_SLOW_MS, precheck, spanAt,
} from '../src/film'
import type { FilmAttempt, FilmClip, FilmSession, Storyboard } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const doc: Storyboard = JSON.parse(
  readFileSync('../backend/tests/real_text_yao/output_merged.json', 'utf8'))
const tl = buildTimeline(doc)
const [a, b, c3] = tl.shots

const clip = (id: string, shots: string[], over: Partial<FilmClip> = {}): FilmClip => ({
  id, episode: 'E01', shots, duration: 8, truncated: false, prompt: 'p', refs: [], dropped_refs: [],
  missing_refs: [], first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 8,
  attempts: [], chosen: null, mute_native: false, uncertain: false, error: null, state: 'planned', ...over,
})
const ok: FilmAttempt = {
  task_id: 't1', state: 'succeeded', cost_cny: 7.5, file: 'clips/x.t1.mp4', last_frame: 'clips/x.t1.last.jpg',
  error: null, at: '2026-10-31T03:00:00+00:00', fingerprint: 'fp', first_frame_used: null,
}
const session = (clips: FilmClip[], over: Partial<FilmSession> = {}): FilmSession => ({
  provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, clips, orphaned: [], counts: {}, reserved_cny: 0, uncertain_count: 0,
  remaining_cny: clips.filter((x) => (x.state === 'planned' || x.state === 'failed') && !x.uncertain)
    .reduce((n, x) => n + x.estimate_cny, 0),
  options: { providers: ['fake'], models: {}, resolutions: ['720p'], cny_per_sec: {}, max_clip_sec: 10,
             max_refs: 3, audio_modes: ['tts_all'], rate_note: '' },
  ...over,
})

// 1. 位置：段横跨所含镜头；镜头不在分镜里的段不画；按开始时间排序
{
  const s = session([clip('E01-C02', [c3.id]), clip('E01-C01', [a.id, b.id]), clip('E09-C01', ['NOPE'])])
  const spans = clipSpans(tl, s)
  must(spans.length === 2, '找不到镜头的段不画')
  must(spans[0].clip.id === 'E01-C01' && spans[0].start === a.start && spans[0].end === b.end, '第一段横跨前两镜')
  must(spans[1].start === c3.start && spans[1].end === c3.end, '第二段就是第三镜')
  must(spanAt(spans, (a.start + b.end) / 2)?.clip.id === 'E01-C01', '播放头在段内')
  must(spanAt(spans, tl.total + 1) === undefined, '片尾之后没有段')
  must(clipOffset(spans[1], c3.start + 1.5) === 1.5 && clipOffset(spans[1], 0) === 0, '段内偏移')
  console.log('1. 段的位置 ✓')
}

// 2. 横条：五种样式与文字；悬停说明；只有成功的那次算采用
{
  const now = Date.parse('2026-10-31T03:01:05+00:00')
  must(laneKind(clip('x', [])) === 'planned' && laneText(clip('E01-C01', []), now) === 'C01 · 8s · 约 ¥8.00', '未出片')
  const busy = clip('x', [], { state: 'running', queued_at: '2026-10-31T03:00:00+00:00' })
  must(laneKind(busy) === 'busy' && laneText(busy, now) === '生成中 · 已等 1:05', '生成中显示已等时间')
  must(laneKind(clip('x', [], { state: 'downloading' })) === 'busy', '下载中也算生成中')
  const done = clip('E01-C03', [], { state: 'done', attempts: [{ ...ok, state: 'failed', file: null }, ok], chosen: 1 })
  must(laneKind(done) === 'done' && laneText(done, now) === 'C03 · 第 2 次 · ¥7.50', '已完成写第几次与费用')
  must(laneText(clip('x', [], { state: 'failed', error: '内容审核未通过' }), now) === '内容审核未通过', '失败写原因')
  must(laneText(clip('x', [], { state: 'stale', attempts: [ok], chosen: 0 }), now) === '已过期 · 仍可播放旧版', '过期')
  const t = laneTitle(clip('E01-C04', ['S1'], { dropped_refs: ['P01'], truncated: true }))
  must(t.includes('⚠') && t.includes('P01') && t.includes('✂'), '悬停列出被裁参考图与截断')
  must(chosenAttempt(done) === ok, '采用的那次')
  must(chosenAttempt(clip('x', [], { attempts: [{ ...ok, state: 'failed' }], chosen: 0 })) === null, '失败的那次不算采用')
  console.log('2. 横条样式与文字 ✓')
}

// 3. 主按钮：先试一段 → 出剩余；待核对的段不在批量里
{
  const fresh = session([clip('C1', []), clip('C2', []), clip('C3', [])])
  const m1 = mainAction(fresh, null)
  must(m1.kind === 'try' && m1.clip.id === 'C1', '一段都没出过：先试第一段')
  const m2 = mainAction(fresh, 'C2')
  must(m2.kind === 'try' && m2.clip.id === 'C2', '选中的段能出就试它')
  const tried = session([clip('C1', [], { state: 'done', attempts: [ok], chosen: 0 }), clip('C2', []),
                         clip('C3', [], { state: 'failed', uncertain: true })])
  const m3 = mainAction(tried, null)
  must(m3.kind === 'rest' && m3.count === 1 && m3.cny === 8, '出过之后：出剩余各段，跳过待核对')
  must(mainAction(session([clip('C1', [], { state: 'done', attempts: [ok], chosen: 0 })]), null).kind === 'none',
       '没有要出的段')
  console.log('3. 主按钮 ✓')
}

// 4. 确认：批量清单与上限；单段超过确认线
{
  const s = session([clip('C1', [], { estimate_cny: 30 }), clip('C2', [], { estimate_cny: 25 })],
                    { spent_cny: 150, budget_cny: 200 })
  const sum = batchSummary(s)
  must(sum.rows.length === 2 && sum.total === 55 && sum.after === 205 && sum.over, '批量清单、累计与超限')
  must(needsConfirm(s.clips[0], s) && !needsConfirm(clip('C3', [], { estimate_cny: 20 }), s), '超过确认线才确认')
  console.log('4. 确认清单 ✓')
}

// 5. 轮询、前置检查、首帧说明
{
  const busy = session([clip('C1', [], { state: 'queued' })])
  must(pollDelay(busy, true) === POLL_FAST_MS && pollDelay(busy, false) === POLL_SLOW_MS, '页签开着且在跑才快轮询')
  must(pollDelay(session([clip('C1', [])]), true) === POLL_SLOW_MS && pollDelay(null, true) === POLL_SLOW_MS,
       '没在跑就慢轮询')
  const p = precheck(session([clip('C1', [], { missing_refs: ['S02', 'C01'] }),
                              clip('C2', [], { missing_refs: ['C01'], dropped_refs: ['P1'], truncated: true })]))
  must(p.missing.join() === 'C01,S02' && p.trimmed.join() === 'C2' && p.truncated.join() === 'C2', '前置检查去重')
  must(firstFrameText(clip('x', [], { first_frame: 'keyframe:E01-SH002', frame_mode: 'ref' }))
       === '关键帧 E01-SH002（占第一个参考位）', '关键帧首帧')
  must(firstFrameText(clip('x', [], { first_frame: 'relay:E01-C01', frame_mode: 'frame' }))
       === '接力上一段（E01-C01）的尾帧', '尾帧接力')
  must(firstFrameText(clip('x', [])) === '不带首帧', '无首帧')
  console.log('5. 轮询、前置检查、首帧 ✓')
}

console.log('\nALL PASS')
```

In `frontend/package.json`, append to the end of the `"test"` script string (after `node .ssrout/admin.test.js`):

```
 && vite build --ssr tests/film-lane.test.ts --outDir .ssrout --logLevel error && node .ssrout/film-lane.test.js
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd frontend && npx vite build --ssr tests/film-lane.test.ts --outDir .ssrout --logLevel error`
Expected: FAIL — cannot resolve `../src/film`

- [ ] **Step 3: 写 `film.ts`**

Create `frontend/src/film.ts`:

```ts
/** 出片（视频生成）在画布上的纯计算：段在时间轴上的位置、横条文字与样式、总览主按钮、
 *  确认清单、轮询间隔、前置检查。useFilm 与画布组件只吃这里的结果；单测见 tests/film-lane.test.ts。 */
import { fmtClock } from './timeline'
import type { TShot, Timeline } from './timeline'
import type { FilmAttempt, FilmClip, FilmSession } from './types'

export const IN_FLIGHT: FilmClip['state'][] = ['queued', 'running', 'downloading']
/** 「出片」页签开着且有段在跑时 5 秒轮询一次，否则 30 秒 */
export const POLL_FAST_MS = 5000
export const POLL_SLOW_MS = 30000

export interface ClipSpan { clip: FilmClip; start: number; end: number }

/** 段横跨它所含的镜头（按可播时长的时间轴）；镜头已不在分镜里的段不画 */
export function clipSpans(tl: Timeline, s: FilmSession): ClipSpan[] {
  const byId = new Map(tl.shots.map((x) => [x.id, x]))
  const out: ClipSpan[] = []
  for (const clip of s.clips) {
    const shots = clip.shots.map((id) => byId.get(id)).filter((x): x is TShot => !!x)
    if (!shots.length) continue
    out.push({ clip, start: Math.min(...shots.map((x) => x.start)), end: Math.max(...shots.map((x) => x.end)) })
  }
  return out.sort((p, q) => p.start - q.start)
}

/** 时刻 t 所在的段 */
export function spanAt(spans: ClipSpan[], t: number): ClipSpan | undefined {
  return spans.find((s) => s.start <= t && t < s.end)
}

/** 播放头在段内的偏移（秒）：视频从这里开始播 */
export const clipOffset = (span: ClipSpan, t: number) => Math.max(0, t - span.start)

export const inFlight = (c: FilmClip) => IN_FLIGHT.includes(c.state)

/** 采用的那一次（成功且有文件）；没有就 null */
export function chosenAttempt(c: FilmClip): FilmAttempt | null {
  const a = c.chosen === null ? undefined : c.attempts[c.chosen]
  return a && a.state === 'succeeded' && a.file ? a : null
}

export type LaneKind = 'planned' | 'busy' | 'done' | 'failed' | 'stale'

/** 横条样式：未出片 / 排队与生成中（含下载）/ 已完成 / 失败 / 过期 */
export function laneKind(c: FilmClip): LaneKind {
  if (inFlight(c)) return 'busy'
  if (c.state === 'done' || c.state === 'failed' || c.state === 'stale') return c.state
  return 'planned'
}

const shortId = (id: string) => id.replace(/^E\d+-/, '')
const yuan = (n: number) => `¥${n.toFixed(2)}`

/** 横条上的文字（画的时候再按宽度截断）；now 为毫秒时间戳 */
export function laneText(c: FilmClip, now: number): string {
  switch (laneKind(c)) {
    case 'busy': {
      const since = c.queued_at ? Math.max(0, (now - Date.parse(c.queued_at)) / 1000) : 0
      return `生成中 · 已等 ${fmtClock(since)}`
    }
    case 'done':
      return `${shortId(c.id)} · 第 ${(c.chosen ?? 0) + 1} 次 · ${yuan(chosenAttempt(c)?.cost_cny ?? 0)}`
    case 'failed':
      return c.error ?? '失败'
    case 'stale':
      return '已过期 · 仍可播放旧版'
    default:
      return `${shortId(c.id)} · ${c.duration}s · 约 ${yuan(c.estimate_cny)}`
  }
}

/** 横条悬停说明：所含镜头、被裁的参考图、截断、待核对、错误原文 */
export function laneTitle(c: FilmClip): string {
  const lines = [`${c.id} · ${c.shots.join('、')} · ${c.duration}s`]
  if (c.dropped_refs.length) lines.push(`⚠ 参考图超出名额被裁：${c.dropped_refs.join('、')}`)
  if (c.truncated) lines.push('✂ 超出单段上限，尾部被截断')
  if (c.uncertain) lines.push('厂商那边可能还有这一段的任务，请到控制台核对')
  if (c.error) lines.push(c.error)
  return lines.join('\n')
}

/** 批量「出剩余各段」的范围：未出片或失败，且不是待核对的（与服务端 _remaining 一致） */
export const remainingClips = (s: FilmSession) =>
  s.clips.filter((c) => (c.state === 'planned' || c.state === 'failed') && !c.uncertain)

export type MainAction =
  | { kind: 'try'; clip: FilmClip }
  | { kind: 'rest'; count: number; cny: number }
  | { kind: 'none' }

/** 总览主按钮：一段都还没出过 → 先试一段（选中的段能出就试它）；否则出剩余各段 */
export function mainAction(s: FilmSession, selected: string | null): MainAction {
  const rest = remainingClips(s)
  if (!rest.length) return { kind: 'none' }
  if (!s.clips.some((c) => c.attempts.length > 0)) {
    return { kind: 'try', clip: rest.find((c) => c.id === selected) ?? rest[0] }
  }
  return { kind: 'rest', count: rest.length, cny: s.remaining_cny }
}

/** 批量确认框：各段时长与费用、合计、已花、在跑预留、执行后累计与上限 */
export function batchSummary(s: FilmSession) {
  const rows = remainingClips(s).map((c) => ({ id: c.id, duration: c.duration, cny: c.estimate_cny }))
  const total = s.remaining_cny
  const after = Math.round((s.spent_cny + s.reserved_cny + total) * 100) / 100
  return { rows, total, spent: s.spent_cny, reserved: s.reserved_cny, after,
           budget: s.budget_cny, over: after > s.budget_cny + 1e-9 }
}

/** 单段出片要不要先弹确认：预估超过确认线（默认 20 元） */
export const needsConfirm = (c: FilmClip, s: FilmSession) => c.estimate_cny > s.confirm_over_cny

/** 下一次轮询隔多久 */
export function pollDelay(s: FilmSession | null, tabOpen: boolean): number {
  return s && tabOpen && s.clips.some(inFlight) ? POLL_FAST_MS : POLL_SLOW_MS
}

/** 前置检查：缺参考图的资产、参考图被裁的段、被截断的段 */
export function precheck(s: FilmSession) {
  return {
    missing: [...new Set(s.clips.flatMap((c) => c.missing_refs))].sort(),
    trimmed: s.clips.filter((c) => c.dropped_refs.length).map((c) => c.id),
    truncated: s.clips.filter((c) => c.truncated).map((c) => c.id),
  }
}

/** 首帧来源的中文说明 */
export function firstFrameText(c: FilmClip): string {
  const f = c.first_frame
  if (!f) return '不带首帧'
  if (f.startsWith('keyframe:')) {
    return `关键帧 ${f.slice('keyframe:'.length)}${c.frame_mode === 'ref' ? '（占第一个参考位）' : ''}`
  }
  if (f.startsWith('relay:')) return `接力上一段（${f.slice('relay:'.length)}）的尾帧`
  return f
}
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd frontend && npx vite build --ssr tests/film-lane.test.ts --outDir .ssrout --logLevel error && node .ssrout/film-lane.test.js && npm run typecheck`
Expected: five `✓` lines then `ALL PASS`; typecheck exits 0

- [ ] **Step 5: 提交**

```bash
git add src/film.ts tests/film-lane.test.ts package.json
git commit -m "画布出片纯计算：段在时间轴上横跨所含镜头、横条五种样式与文字、先试一段再出剩余的主按钮、批量确认清单与上限、轮询间隔、前置检查与首帧说明"
```

---

### Task 4: 数据钩子 `useFilm` 与侧栏「出片」页

**Files:**
- Create: `frontend/src/useFilm.ts`
- Create: `frontend/src/components/FilmPanel.tsx`
- Modify: `frontend/src/index.css`（末尾追加）

这两个文件的行为由 Task 5 的界面回归覆盖（它们只有接进画布才能点），本任务以类型检查为准。

- [ ] **Step 1: 写 `useFilm.ts`**

Create `frontend/src/useFilm.ts`:

```ts
/** 画布上的出片会话：读取、建立、改设置、出片（含确认金额）、采用、静音、轮询，以及片段文件的 blob URL。
 *
 *  只有存进后端的版本才有出片（version 为空 = 本地 JSON / 分批预览，什么都不做、不发请求）。
 *  花钱的两步（单段超过确认线、批量出剩余各段）先进 confirm，用户点确认才发请求；
 *  服务端重算的金额对不上（409）就把新金额放回 confirm 让用户再确认。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError, chooseFilmAttempt, conflictCny, createFilm, filmFileUrl, getFilm, muteFilmClip, patchFilm,
  runFilmClip, runFilmRest,
} from './api'
import { needsConfirm, pollDelay } from './film'
import type { FilmClip, FilmSession, FilmSettings, VersionRef } from './types'

export type FilmConfirm =
  | { kind: 'clip'; clipId: string; cny: number; changed: boolean }
  | { kind: 'rest'; cny: number; changed: boolean }

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function useFilm(version: VersionRef | null | undefined, opts: { active: boolean }) {
  const { nid, cid, vid } = version ?? {}
  const enabled = !!(nid && cid && vid)
  const [session, setSession] = useState<FilmSession | null>(null)
  /** off：没有版本（不出片）；none：还没建会话 */
  const [status, setStatus] = useState<'off' | 'loading' | 'none' | 'ready'>(enabled ? 'loading' : 'off')
  const [error, setError] = useState<string | null>(null)
  /** 验证门没过的原因（读取时报告的，或出片被 422 拦下的） */
  const [gate, setGate] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<FilmConfirm | null>(null)
  /** 会话目录下的相对路径 → blob URL */
  const [files, setFiles] = useState<Record<string, string>>({})
  const live = useRef<Record<string, string>>({})
  const asking = useRef(new Set<string>())
  /** 换版本 / 卸载时加一：之前没取回来的文件取回后直接回收 */
  const gen = useRef(0)

  const accept = useCallback((s: FilmSession) => {
    setSession(s)
    setStatus('ready')
    setGate(s.gate && !s.gate.ok ? (s.gate.message ?? '分镜未通过独立验证') : null)
  }, [])

  /** 验证门拦截记到 gate（按钮据此禁用），其余显示原因 */
  const fail = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.verification) setGate(e.message)
    else setError(msg(e))
  }, [])

  const load = useCallback(async () => {
    if (!nid || !cid || !vid) return
    try {
      accept(await getFilm(nid, cid, vid))
      setError(null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setSession(null)
        setStatus('none')
      } else {
        fail(e)
        setStatus((st) => (st === 'loading' ? 'none' : st))
      }
    }
  }, [nid, cid, vid, accept, fail])

  useEffect(() => {
    setSession(null)
    setError(null)
    setGate(null)
    setConfirm(null)
    setStatus(enabled ? 'loading' : 'off')
    if (enabled) void load()
  }, [enabled, load])

  // 轮询：页签开着且有段在跑 5 秒，否则 30 秒
  useEffect(() => {
    if (status !== 'ready') return
    const id = setTimeout(() => void load(), pollDelay(session, opts.active))
    return () => clearTimeout(id)
  }, [status, session, opts.active, load])

  /** 不花钱的操作：忙标记、清错误、成功后收下新会话 */
  const apply = useCallback(async (fn: () => Promise<FilmSession>) => {
    setBusy(true)
    setError(null)
    try {
      accept(await fn())
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }, [accept, fail])

  /** 花钱的操作：409 带了重算金额就放回确认框，等用户再确认 */
  const spend = async (fn: () => Promise<FilmSession>, again: (cny: number) => FilmConfirm) => {
    setBusy(true)
    setError(null)
    try {
      accept(await fn())
      setConfirm(null)
    } catch (e) {
      const fresh = conflictCny(e)
      if (fresh !== null) {
        setConfirm(again(fresh))
      } else {
        setConfirm(null)
        fail(e)
      }
    } finally {
      setBusy(false)
    }
  }
  const sendClip = (clipId: string, cny?: number) =>
    spend(() => runFilmClip(nid!, cid!, vid!, clipId, cny),
          (fresh) => ({ kind: 'clip', clipId, cny: fresh, changed: cny !== undefined }))
  const sendRest = (cny: number) =>
    spend(() => runFilmRest(nid!, cid!, vid!, cny), (fresh) => ({ kind: 'rest', cny: fresh, changed: true }))

  /** 取一个片段文件（视频、尾帧）的 blob URL：每个只取一次 */
  const ensure = useCallback((path: string | null | undefined) => {
    if (!path || !nid || !cid || !vid || live.current[path] || asking.current.has(path)) return
    const mine = gen.current
    asking.current.add(path)
    filmFileUrl(nid, cid, vid, path)
      .then((url) => {
        if (gen.current !== mine) { URL.revokeObjectURL(url); return }
        live.current[path] = url
        setFiles({ ...live.current })
      })
      .catch((e) => { if (gen.current === mine) setError(`读取片段文件失败：${msg(e)}`) })
      .finally(() => asking.current.delete(path))
  }, [nid, cid, vid])
  useEffect(() => () => {
    gen.current += 1
    for (const u of Object.values(live.current)) URL.revokeObjectURL(u)
    live.current = {}
    asking.current.clear()
    setFiles({})
  }, [nid, cid, vid])

  return {
    enabled, session, status, error, gate, busy, confirm, files, load, ensure,
    create: () => apply(() => createFilm(nid!, cid!, vid!)),
    saveSettings: (patch: FilmSettings) => apply(() => patchFilm(nid!, cid!, vid!, patch)),
    /** 出这一段：超过确认线先弹确认，确认后才发请求 */
    runClip: (c: FilmClip) => {
      if (session && needsConfirm(c, session)) {
        setConfirm({ kind: 'clip', clipId: c.id, cny: c.estimate_cny, changed: false })
        return Promise.resolve()
      }
      return sendClip(c.id)
    },
    /** 批量出剩余各段：一律先弹确认 */
    runRest: () => {
      if (session) setConfirm({ kind: 'rest', cny: session.remaining_cny, changed: false })
    },
    confirmNow: () => (!confirm ? Promise.resolve()
      : confirm.kind === 'clip' ? sendClip(confirm.clipId, confirm.cny) : sendRest(confirm.cny)),
    cancelConfirm: () => setConfirm(null),
    choose: (clipId: string, attempt: number) =>
      apply(() => chooseFilmAttempt(nid!, cid!, vid!, clipId, attempt)),
    mute: (clipId: string, mute: boolean) => apply(() => muteFilmClip(nid!, cid!, vid!, clipId, mute)),
  }
}

export type Film = ReturnType<typeof useFilm>
```

- [ ] **Step 2: 写 `FilmPanel.tsx`**

Create `frontend/src/components/FilmPanel.tsx`:

```tsx
/** 画布侧栏「出片」页：设置、前置检查、总览与主按钮、选中段详情、花钱前的确认框。
 *
 *  花钱的按钮上都写着金额；批量和超过确认线的单段先弹确认（useFilm 决定发不发请求）。
 *  有未保存的改动或验证门没过时，所有出片按钮禁用并写明原因。 */
import { useEffect, useState } from 'react'
import { ATTEMPT_STATE, AUDIO_MODE, FILM_STATE, label } from '../labels'
import { batchSummary, firstFrameText, inFlight, mainAction, precheck } from '../film'
import type { Film } from '../useFilm'
import type { AudioMode, FilmClip, FilmSession, FilmSettings } from '../types'

const yuan = (n: number) => `¥${n.toFixed(2)}`
const p2 = (n: number) => String(n).padStart(2, '0')
/** 尝试时间按本地时区显示到分钟 */
const when = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso
    : `${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`
}

interface Props {
  film: Film
  /** 「成片」泳道上选中的段 */
  selected: string | null
  /** 点段里的镜头：画布选中那一镜 */
  onPickShot: (shotId: string) => void
  /** 有未保存的改动：出片只认已保存的版本 */
  dirty: boolean
}

export function FilmPanel({ film, selected, onPickShot, dirty }: Props) {
  const s = film.session
  if (film.status === 'loading') return <p className="tlc__kfnote">读取出片会话…</p>
  const blocked = dirty ? '有未保存的修改：先保存再出片（出片只用已保存的版本）'
    : film.gate ? `${film.gate}：先在分镜页修好再出片` : null
  const clip = s?.clips.find((c) => c.id === selected)
  return (
    <div className="film">
      {film.error && <p className="tlc__kferr">{film.error}</p>}
      {blocked && <p className="tlc__notice">{blocked}</p>}
      {film.confirm && s && <ConfirmBox s={s} film={film} blocked={blocked} />}
      {!s ? (
        <section>
          <p className="tlc__kfnote">按厂商能力把镜头切成段、组装提示词（不花钱）；先试一段，满意后再出剩余各段。</p>
          <button className="btn btn--sm" disabled={!!blocked || film.busy} onClick={() => void film.create()}>
            建立出片会话（不花钱）
          </button>
        </section>
      ) : (
        <>
          <Settings key={[s.provider, s.model, s.resolution, s.audio_mode, s.budget_cny, s.confirm_over_cny].join('|')}
                    s={s} film={film} />
          <Precheck s={s} />
          <Overview s={s} film={film} selected={selected} blocked={blocked} />
          {clip
            ? <ClipDetail key={clip.id} c={clip} film={film} blocked={blocked} onPickShot={onPickShot} />
            : <p className="tlc__kfnote">点「成片」泳道上的一段看详情、重做或换用别的一次。</p>}
        </>
      )}
    </div>
  )
}

/** 设置：首次展开，出过片后折叠。改了才能「应用设置」；有段在跑时不能改 */
function Settings({ s, film }: { s: FilmSession; film: Film }) {
  const [draft, setDraft] = useState<FilmSettings>({})
  const val = <K extends keyof FilmSettings>(k: K) => draft[k] ?? s[k]
  const flying = s.clips.some(inFlight)
  const tried = s.clips.some((c) => c.attempts.length > 0)
  const otherProvider = !!draft.provider && draft.provider !== s.provider
  return (
    <details className="film__settings" open={!tried}>
      <summary>
        设置 · {s.options.models[s.model]?.label ?? s.model} · {s.resolution} · {label(AUDIO_MODE, s.audio_mode)}
        {' '}· 上限 {yuan(s.budget_cny)}
      </summary>
      <label className="field">
        <span>厂商</span>
        <select value={val('provider')}
                onChange={(e) => setDraft({ ...draft, provider: e.target.value, model: undefined, resolution: undefined })}>
          {[...new Set([s.provider, ...s.options.providers])].map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </label>
      {otherProvider ? (
        <p className="tlc__kfnote">换厂商后档位与分辨率先用它的默认值，应用后再细调。</p>
      ) : (
        <>
          <label className="field">
            <span>档位</span>
            <select value={val('model')}
                    onChange={(e) => setDraft({ ...draft, model: e.target.value, resolution: undefined })}>
              {Object.entries(s.options.models).map(([id, m]) => <option key={id} value={id}>{m.label}</option>)}
            </select>
          </label>
          <label className="field">
            <span>分辨率</span>
            <select value={val('resolution')} onChange={(e) => setDraft({ ...draft, resolution: e.target.value })}>
              {s.options.resolutions.map((r) => {
                const price = s.options.cny_per_sec[r]
                return <option key={r} value={r}>{`${r}${price !== undefined ? `（约 ¥${price}/秒）` : ''}`}</option>
              })}
            </select>
          </label>
        </>
      )}
      <label className="field">
        <span>声音</span>
        <select value={val('audio_mode')}
                onChange={(e) => setDraft({ ...draft, audio_mode: e.target.value as AudioMode })}>
          {s.options.audio_modes.map((m) => <option key={m} value={m}>{label(AUDIO_MODE, m)}</option>)}
        </select>
      </label>
      <label className="field">
        <span>上限（元，按版本计）</span>
        <input type="number" min={1} step={10} value={val('budget_cny')}
               onChange={(e) => setDraft({ ...draft, budget_cny: Number(e.target.value) })} />
      </label>
      <label className="field">
        <span>单段超过多少元先确认</span>
        <input type="number" min={0} step={5} value={val('confirm_over_cny')}
               onChange={(e) => setDraft({ ...draft, confirm_over_cny: Number(e.target.value) })} />
      </label>
      <p className="tlc__kfnote">
        音色分配在配音与合成那一步做。改设置会按新设置重新切段（不花钱），已出的段标「过期」，旧视频仍可播。
      </p>
      <button className="btn btn--sm" disabled={!Object.keys(draft).length || flying || film.busy}
              onClick={() => void film.saveSettings(draft)}>
        应用设置
      </button>
      {flying && <p className="tlc__kfnote">有段在排队或生成中，等它们结束再改设置。</p>}
    </details>
  )
}

/** 前置检查：待核对的段、缺参考图的资产、被裁 / 截断的段 */
function Precheck({ s }: { s: FilmSession }) {
  const p = precheck(s)
  if (!s.uncertain_count && !p.missing.length && !p.trimmed.length && !p.truncated.length) return null
  return (
    <section className="film__check">
      {!!s.uncertain_count && (
        <p className="tlc__kferr">
          {s.uncertain_count} 段结果不明：厂商那边可能还有任务在跑或已扣费，请到厂商控制台核对；
          批量出片会跳过它们，确认没有生成再单独重做。
        </p>
      )}
      {!!p.missing.length && <p>缺参考图的资产（只写文字描述）：{p.missing.join('、')}</p>}
      {!!p.trimmed.length && <p>⚠ 参考图超出名额被裁的段：{p.trimmed.join('、')}</p>}
      {!!p.truncated.length && <p>✂ 超出单段上限被截断的段：{p.truncated.join('、')}</p>}
    </section>
  )
}

/** 总览：各状态计数、钱（已花 / 在跑预留 / 剩余预估 / 上限）、主按钮 */
function Overview({ s, film, selected, blocked }: {
  s: FilmSession; film: Film; selected: string | null; blocked: string | null
}) {
  const next = mainAction(s, selected)
  const used = Math.min(100, ((s.spent_cny + s.reserved_cny) / s.budget_cny) * 100)
  return (
    <section className="film__overview">
      <div className="film__counts">
        <b>{s.clips.length} 段</b>
        {Object.entries(s.counts).map(([k, n]) => (
          <span key={k} className={`film__count film__count--${k}`}>{label(FILM_STATE, k)} {n}</span>
        ))}
        <button className="tlc__linkbtn" onClick={() => void film.load()}>刷新</button>
      </div>
      <div className="film__money">
        <span>已花 {yuan(s.spent_cny)}</span>
        {s.reserved_cny > 0 && <span>在跑预留 {yuan(s.reserved_cny)}</span>}
        <span>剩余预估 {yuan(s.remaining_cny)}</span>
        <span>上限 {yuan(s.budget_cny)}</span>
      </div>
      <div className="film__bar" title="已花 + 在跑预留 占上限"><i style={{ width: `${used}%` }} /></div>
      {next.kind === 'try' && (
        <button className="btn btn--sm" disabled={!!blocked || film.busy} onClick={() => void film.runClip(next.clip)}>
          先试这一段（{next.clip.id}，约 {yuan(next.clip.estimate_cny)}）
        </button>
      )}
      {next.kind === 'rest' && (
        <button className="btn btn--sm" disabled={!!blocked || film.busy} onClick={film.runRest}>
          出剩余 {next.count} 段（约 {yuan(next.cny)}）
        </button>
      )}
      {next.kind === 'none' && (
        <p className="tlc__kfnote">
          {s.clips.some(inFlight) ? '各段在生成中，出完会自动刷新。' : '没有要出的段了；配音与合成整章在下一步。'}
        </p>
      )}
    </section>
  )
}

/** 选中段详情：所含镜头、提示词（只读）、参考图、首帧来源、尝试记录（播放、★ 采用）、重做、原声静音 */
function ClipDetail({ c, film, blocked, onPickShot }: {
  c: FilmClip; film: Film; blocked: string | null; onPickShot: (shotId: string) => void
}) {
  const [watch, setWatch] = useState<number | null>(null)
  const file = watch === null ? null : (c.attempts[watch]?.file ?? null)
  const { ensure } = film
  useEffect(() => { ensure(file) }, [file, ensure])
  const flying = inFlight(c)
  const redo = c.attempts.some((a) => a.state === 'succeeded')
  return (
    <section className="film__clip">
      <header>
        <b>{c.id}</b>
        <span>{label(FILM_STATE, c.state)} · {c.duration}s · 约 {yuan(c.estimate_cny)}{c.truncated ? ' · ✂ 尾部截断' : ''}</span>
      </header>
      <div className="film__shots">
        {c.shots.map((id) => (
          <button key={id} className="tlc__unit" title="在画布上选中这一镜" onClick={() => onPickShot(id)}>
            <code>{id}</code>
          </button>
        ))}
      </div>
      {c.uncertain && (
        <p className="tlc__kferr">这一段结果不明：厂商那边可能还有任务在跑或已扣费，请到厂商控制台核对，确认没有生成再重做。</p>
      )}
      {c.error && <p className="tlc__kferr">{c.error}</p>}
      <details>
        <summary>提示词（只读，要改就改镜头）</summary>
        <pre className="film__prompt">{c.prompt}</pre>
      </details>
      <p className="film__line">
        参考图：{c.refs.length ? c.refs.join('、') : '无'}
        {!!c.dropped_refs.length && <span className="film__dim">（超出名额被裁：{c.dropped_refs.join('、')}）</span>}
        {!!c.missing_refs.length && <span className="film__dim">（没有图、只写文字描述：{c.missing_refs.join('、')}）</span>}
      </p>
      <p className="film__line">首帧：{firstFrameText(c)}</p>
      {!!c.attempts.length && (
        <table className="film__attempts">
          <tbody>
            {c.attempts.map((a, i) => (
              <tr key={i} className={i === c.chosen ? 'is-chosen' : ''}>
                <td>第 {i + 1} 次</td>
                <td>{when(a.at)}</td>
                <td>{label(ATTEMPT_STATE, a.state)}</td>
                <td>{yuan(a.cost_cny)}</td>
                <td>
                  {a.state === 'succeeded' && a.file && (
                    <button className="tlc__linkbtn" onClick={() => setWatch(i)}>播放</button>
                  )}
                </td>
                <td>
                  {i === c.chosen ? <span title="采用的这一次">★</span> : a.state === 'succeeded' && (
                    <button className="tlc__linkbtn" disabled={flying || film.busy} title="改用这一次"
                            onClick={() => void film.choose(c.id, i)}>☆ 采用</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {file && (film.files[file]
        ? <video className="film__video" src={film.files[file]} controls autoPlay muted={c.mute_native} />
        : <p className="tlc__kfnote">读取视频…</p>)}
      <div className="tlc__kfacts">
        <button className="btn btn--sm" disabled={!!blocked || flying || film.busy} onClick={() => void film.runClip(c)}>
          {flying ? label(FILM_STATE, c.state) : `${redo ? '重做这一段' : '出这一段'}（约 ${yuan(c.estimate_cny)}）`}
        </button>
        <label className="check" title="合成整章时这一段的视频原声静音">
          <input type="checkbox" checked={c.mute_native} disabled={film.busy}
                 onChange={(e) => void film.mute(c.id, e.target.checked)} />
          原声静音
        </label>
      </div>
    </section>
  )
}

/** 花钱前的确认：批量列出各段；合计、已花、在跑预留、执行后累计与上限；费率依据如实照抄 */
function ConfirmBox({ s, film, blocked }: { s: FilmSession; film: Film; blocked: string | null }) {
  const cf = film.confirm!
  const rows = cf.kind === 'rest' ? batchSummary(s).rows : []
  const after = Math.round((s.spent_cny + s.reserved_cny + cf.cny) * 100) / 100
  const over = after > s.budget_cny + 1e-9
  return (
    <section className="film__confirm" role="dialog" aria-label="确认出片金额">
      <h4>{cf.kind === 'rest' ? `出剩余 ${rows.length} 段` : `出 ${cf.clipId}`}</h4>
      {cf.changed && <p className="tlc__kferr">预估金额已变为 {yuan(cf.cny)}，请重新确认。</p>}
      {!!rows.length && (
        <table className="film__rows">
          <tbody>
            {rows.map((r) => <tr key={r.id}><td>{r.id}</td><td>{r.duration}s</td><td>{yuan(r.cny)}</td></tr>)}
          </tbody>
        </table>
      )}
      <p>
        合计 <b>{yuan(cf.cny)}</b> · 已花 {yuan(s.spent_cny)}
        {s.reserved_cny > 0 ? ` · 在跑预留 ${yuan(s.reserved_cny)}` : ''} · 执行后累计 {yuan(after)} / 上限 {yuan(s.budget_cny)}
      </p>
      {over && <p className="tlc__kferr">会超过上限，服务端会拒绝：先在设置里调高上限。</p>}
      <p className="tlc__kfnote">费率依据：{s.options.rate_note || '厂商未注明'}。实际以厂商控制台账单为准。</p>
      <div className="tlc__kfacts">
        <button className="btn btn--sm" disabled={film.busy || over || !!blocked} onClick={() => void film.confirmNow()}>
          确认出片（{yuan(cf.cny)}）
        </button>
        <button className="btn btn--sm btn--ghost" onClick={film.cancelConfirm}>取消</button>
      </div>
    </section>
  )
}
```

- [ ] **Step 3: 样式**

Append to the end of `frontend/src/index.css`:

```css
/* ---------- 画布出片：成片泳道、预览窗视频、侧栏「出片」页 ---------- */
.tlc__clip { cursor: pointer; }
.tlc__clip rect { fill: none; stroke: var(--line); stroke-dasharray: 4 3; }
.tlc__clip text { font-size: 10px; fill: var(--muted); pointer-events: none; }
.tlc__clip--busy rect { stroke: var(--accent); stroke-dasharray: none; animation: tlc-busy 1.2s ease-in-out infinite; }
.tlc__clip--done rect { fill: var(--accent-soft); stroke: var(--accent); stroke-dasharray: none; }
.tlc__clip--done text { fill: var(--text); }
.tlc__clip--failed rect { stroke: var(--danger); stroke-dasharray: none; }
.tlc__clip--failed text { fill: var(--danger); }
.tlc__clip--stale rect { fill: var(--warn-bg); stroke: var(--inferred); stroke-dasharray: 2 2; }
.tlc__clip.is-sel rect { stroke-width: 2; }
@keyframes tlc-busy { 50% { stroke-opacity: 0.3; } }
.tlc__pip video { width: 100%; height: 100%; object-fit: contain; display: block; background: #000; }
.tlc__pipnote { position: absolute; top: 8px; left: 8px; padding: 2px 8px; border-radius: 4px;
                background: rgba(0, 0, 0, 0.6); color: #eee; font-size: 11px; }

.film { display: flex; flex-direction: column; gap: 12px; font-size: 12.5px; }
.film section { display: flex; flex-direction: column; gap: 6px; }
.film p { margin: 0; }
.film__settings { border: 1px solid var(--line-2); border-radius: 6px; padding: 6px 8px; }
.film__settings summary { cursor: pointer; color: var(--muted); }
.film__settings .field { margin-top: 6px; }
.film__counts { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; }
.film__count { color: var(--muted); }
.film__count--failed { color: var(--danger); }
.film__count--stale { color: var(--inferred); }
.film__money { display: flex; flex-wrap: wrap; gap: 10px; color: var(--muted); }
.film__bar { height: 6px; border-radius: 3px; background: var(--line-2); overflow: hidden; }
.film__bar i { display: block; height: 100%; background: var(--accent); }
.film__clip > header { display: flex; flex-direction: column; gap: 1px; }
.film__clip > header b { font-family: var(--mono); }
.film__clip > header span { font-size: 11.5px; color: var(--faint); }
.film__shots { display: flex; flex-wrap: wrap; gap: 4px; }
.film__prompt { white-space: pre-wrap; font-size: 11.5px; max-height: 30vh; overflow: auto;
                background: var(--panel-2); padding: 6px 8px; border-radius: 4px; margin: 4px 0 0; }
.film__dim { color: var(--faint); }
.film__attempts, .film__rows { border-collapse: collapse; font-size: 12px; }
.film__attempts td, .film__rows td { padding: 2px 8px 2px 0; }
.film__attempts tr.is-chosen { font-weight: 600; }
.film__rows { display: block; max-height: 30vh; overflow: auto; }
.film__video { width: 100%; max-height: 40vh; background: #000; border-radius: 4px; }
.film__confirm { border: 1px solid var(--accent); border-radius: 8px; padding: 10px 12px; background: var(--panel); }
.film__confirm h4 { margin: 0; }
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npm run typecheck`
Expected: exits 0 with no errors

- [ ] **Step 5: 提交**

```bash
git add src/useFilm.ts src/components/FilmPanel.tsx src/index.css
git commit -m "画布出片：数据钩子（读取、建会话、改设置、花钱前确认与金额变动重确认、采用、静音、轮询、片段文件取回）与侧栏「出片」页（设置、前置检查、总览主按钮、段详情、确认框）"
```

---

### Task 5: 接进画布：成片泳道、「出片」页签、播成片

**Files:**
- Modify: `frontend/src/components/TimelineCanvas.tsx`
- Modify: `frontend/tests/canvas.test.tsx`（桩后端）
- Test: `frontend/tests/film.test.tsx`
- Modify: `frontend/package.json`（`test` 脚本）

- [ ] **Step 1: 写失败测试**

Create `frontend/tests/film.test.tsx`:

```tsx
/** 画布出片的界面回归：没有版本不出现出片；建会话（不花钱）后出现「成片」泳道；先试一段；
 *  批量先确认、服务端金额变了再确认；单段超过确认线先确认；采用与原声静音；待核对标记；
 *  未保存与验证门拦截；播成片。桩后端在内存里模拟出片会话（出片线程的推进由测试直接改状态）。
 *  纯计算由 film-lane.test.ts 覆盖。跑法：npm test
 */
import { readFileSync } from 'node:fs'
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame = (cb: (t: number) => void) =>
  setTimeout(() => cb(performance.now()), 16) as unknown as number
g.cancelAnimationFrame = (id: number) => clearTimeout(id)

import type { FilmAttempt, FilmClip, FilmSession, Storyboard } from '../src/types'

const doc: Storyboard = JSON.parse(
  readFileSync('../backend/tests/real_text_yao/output_merged.json', 'utf8'))

/* ---------- 桩后端：内存里的出片会话 ---------- */
const R = '/novels/n1/chapters/c1/versions/v1/render'
const GATE = '分镜未通过独立验证，禁止进入付费渲染'
const IN_FLIGHT = ['queued', 'running', 'downloading']
let film: FilmSession | null = null
/** 每次出片请求记一行：`方法 子路径 请求体` */
const calls: string[] = []
/** 下一次花钱请求先回 409（模拟服务端重算的金额变了） */
let nextConflict: number | null = null
let gateFail = false
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))

function recount(s: FilmSession): FilmSession {
  const counts: Record<string, number> = {}
  for (const c of s.clips) counts[c.state] = (counts[c.state] ?? 0) + 1
  const sum = (cs: FilmClip[]) => Math.round(cs.reduce((n, c) => n + c.estimate_cny, 0) * 100) / 100
  return {
    ...s, counts,
    remaining_cny: sum(s.clips.filter((c) => (c.state === 'planned' || c.state === 'failed') && !c.uncertain)),
    reserved_cny: sum(s.clips.filter((c) => IN_FLIGHT.includes(c.state))),
    uncertain_count: s.clips.filter((c) => c.uncertain).length,
  }
}

/** 每集两镜一段，每段 ¥5 */
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
    confirm_over_cny: 20, spent_cny: 0, clips, orphaned: [], counts: {}, remaining_cny: 0,
    reserved_cny: 0, uncertain_count: 0,
    options: { providers: ['fake'], models: { 'fake-1': { label: '假厂商' } }, resolutions: ['480p', '720p'],
               cny_per_sec: { '480p': 0.5, '720p': 1 }, max_clip_sec: 10, max_refs: 3,
               audio_modes: ['tts_all', 'dialogue_native', 'all_native', 'silent'],
               rate_note: '假厂商：不联网、不花钱' },
  })
}

const clipOf = (id: string) => film!.clips.find((c) => c.id === id)!

/** 模拟出片线程跑完一次：追加一次成功的尝试并采用它 */
function finish(id: string) {
  const c = clipOf(id)
  const n = c.attempts.length + 1
  const a: FilmAttempt = {
    task_id: `t${n}`, state: 'succeeded', cost_cny: c.estimate_cny, file: `clips/${id}.t${n}.mp4`,
    last_frame: `clips/${id}.t${n}.last.jpg`, error: null, at: '2026-10-31T03:00:00+00:00',
    fingerprint: 'fp', first_frame_used: null,
  }
  c.attempts.push(a)
  c.chosen = c.attempts.length - 1
  c.state = 'done'
  film = recount({ ...film!, spent_cny: film!.spent_cny + c.estimate_cny })
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
  calls.push(`${method} ${sub}${body === undefined ? '' : ` ${JSON.stringify(body)}`}`)
  if (sub.startsWith('/files/')) {
    return { ok: true, status: 200,
             blob: async () => new Blob(['x'], { type: sub.endsWith('.mp4') ? 'video/mp4' : 'image/jpeg' }) }
  }
  if (sub === '/session' && method === 'GET') {
    return film ? ok({ ...film, gate: gateFail ? { ok: false, message: GATE } : { ok: true, message: null } })
      : fail(404, '还没有出片会话')
  }
  if (sub === '/session' && method === 'POST') {
    film = makeSession()
    return ok(film)
  }
  if (gateFail) return fail(422, { message: GATE, verification: { ok: false } })
  const spend = (targets: FilmClip[], expected: number | undefined, batch: boolean) => {
    const total = Math.round(targets.reduce((n, c) => n + c.estimate_cny, 0) * 100) / 100
    if (nextConflict !== null) {
      const fresh = nextConflict
      nextConflict = null
      return fail(409, { message: `预估金额已变为 ¥${fresh.toFixed(2)}，请重新确认`, expected_cny: fresh })
    }
    if ((batch || total > film!.confirm_over_cny) && expected === undefined) {
      return fail(409, { message: `本次约 ¥${total.toFixed(2)}，请确认金额后再出片`, expected_cny: total })
    }
    for (const c of targets) {
      Object.assign(c, { state: 'queued', queued_at: new Date().toISOString(), uncertain: false, error: null })
    }
    film = recount(film!)
    return ok(film)
  }
  let m = sub.match(/^\/clips\/([^/]+)\/run$/)
  if (m && method === 'POST') return spend([clipOf(decodeURIComponent(m[1]))], body?.expected_cny, false)
  if (sub === '/run' && method === 'POST') {
    return spend(film!.clips.filter((c) => (c.state === 'planned' || c.state === 'failed') && !c.uncertain),
                 body?.expected_cny, true)
  }
  m = sub.match(/^\/clips\/([^/]+)\/chosen$/)
  if (m && method === 'PUT') {
    clipOf(decodeURIComponent(m[1])).chosen = body.attempt
    film = recount(film!)
    return ok(film)
  }
  m = sub.match(/^\/clips\/([^/]+)$/)
  if (m && method === 'PATCH') {
    clipOf(decodeURIComponent(m[1])).mute_native = body.mute_native
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
const has = (s: string) => container.innerHTML.includes(s)
const button = (text: string) => {
  const b = [...container.querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(text))
  if (!b) throw new Error(`✗ 找不到按钮「${text}」`)
  return b as unknown as HTMLButtonElement
}
const click = async (el: Element) => {
  await act(async () => {
    el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
const tab = (name: string) =>
  [...container.querySelectorAll('.tlc__tabs button')].find((b) => b.textContent === name)
const lanes = () => [...container.querySelectorAll('.tlc__labels text')].map((t) => t.textContent)
const bar = (id: string) => {
  const el = container.querySelector(`[data-clip="${id}"]`)
  if (!el) throw new Error(`✗ 成片泳道上找不到段 ${id}`)
  return el
}
const refresh = () => click(button('刷新'))

let setDirty: (v: boolean) => void = () => {}
function Host({ withVersion }: { withVersion: boolean }) {
  const [dirty, set] = useState(false)
  setDirty = set
  return <StoryboardView doc={doc} canSave dirty={dirty} saving={false}
                         version={withVersion ? { nid: 'n1', cid: 'c1', vid: 'v1' } : null}
                         onChange={() => set(true)} onSave={() => set(false)} />
}

// 0. 没有版本（本地 JSON / 分批预览）：画布里没有出片页签，也不请求出片接口
await act(async () => { root.render(<Host withVersion={false} />) })
await click(button('时间轴画布'))
must(!!container.querySelector('.tlc') && !tab('出片'), '没有版本时不出现「出片」页签')
must(calls.length === 0 && !lanes().includes('成片'), '没有版本时不请求出片接口、没有成片泳道')
console.log('0. 没有版本不出片 ✓')

// 1. 有版本、还没会话：没有成片泳道；「出片」页签里建会话（不花钱）→ 泳道出现，每段一条
await act(async () => { root.render(<Host key="v1" withVersion />) })
await click(button('时间轴画布'))
must(calls.includes('GET /session') && !lanes().includes('成片'), '读取会话 404 → 没有成片泳道')
await click(tab('出片')!)
await click(button('建立出片会话'))
must(calls.includes('POST /session {}'), '建会话发 POST')
must(lanes().includes('成片'), '有会话后出现「成片」泳道')
must(container.querySelectorAll('.tlc__clip').length === film!.clips.length, '每段一条横条')
const first = film!.clips[0].id
must(bar(first).classList.contains('tlc__clip--planned') && (bar(first).textContent ?? '').includes('约 ¥5.00'),
     '未出片：虚线框、写预估')
console.log(`1. 建会话 → 成片泳道 ${film!.clips.length} 段 ✓`)

// 2. 先试一段（¥5，不超过确认线）：不弹确认直接排队，横条变「生成中」
await click(button('先试这一段'))
must(calls.includes(`POST /clips/${first}/run {}`), '试段直接发请求、不带金额')
must(bar(first).classList.contains('tlc__clip--busy') && (bar(first).textContent ?? '').includes('生成中'),
     '横条变生成中')
console.log('2. 先试一段 ✓')

// 3. 出片线程跑完 → 刷新：横条填色、第 1 次，缩略图取了尾帧
finish(first)
await refresh()
await settle()
must(bar(first).classList.contains('tlc__clip--done') && (bar(first).textContent ?? '').includes('第 1 次'),
     '已完成：第 1 次')
must(calls.includes(`GET /files/clips/${first}.t1.last.jpg`) && !!bar(first).querySelector('image'),
     '缩略图用采用那次的尾帧')
console.log('3. 出完 → 填色与缩略图 ✓')

// 4. 批量：主按钮变「出剩余 N 段」；点了先弹确认（列各段、费率依据），不发请求
const n = film!.clips.length - 1
await click(button(`出剩余 ${n} 段`))
must(has('确认出片') && has('费率依据：假厂商'), '弹出确认框、写费率依据')
must(container.querySelectorAll('.film__rows tr').length === n, '确认框列出各段')
must(!calls.some((c) => c.startsWith('POST /run')), '确认前不发批量请求')
console.log('4. 批量先确认 ✓')

// 5. 服务端重算金额变了（409）→ 确认框换成新金额并提示；再确认才排队
nextConflict = 123.45
await click(button('确认出片'))
must(has('预估金额已变为 ¥123.45'), '金额变了要重新确认')
await click(button('确认出片（¥123.45）'))
must(calls[calls.length - 1] === 'POST /run {"expected_cny":123.45}', '再确认时带新金额')
must(!has('确认出片') && film!.clips.filter((c) => c.state === 'queued').length === n, '剩余各段都排上队')
console.log('5. 金额变动重新确认 ✓')

// 6. 单段超过确认线：失败的一段改成 ¥25，选中它 →「出这一段（约 ¥25.00）」先弹确认，确认才带金额发请求
const second = film!.clips[1].id
Object.assign(clipOf(second), { state: 'failed', error: '厂商返回失败：内容审核未通过', estimate_cny: 25 })
film = recount(film!)
await refresh()
await click(bar(second))
must(has('厂商返回失败：内容审核未通过'), '段详情写失败原因')
let before = calls.length
await click(button('出这一段（约 ¥25.00）'))
must(!calls.slice(before).some((c) => c.includes('/run')) && has('确认出片（¥25.00）'), '超过确认线先确认')
await click(button('确认出片（¥25.00）'))
must(calls.slice(before).includes(`POST /clips/${second}/run {"expected_cny":25}`), '确认后带金额')
console.log('6. 单段超线先确认 ✓')

// 7. 采用与静音：出过两次的段可以改用第 1 次；原声静音写回
finish(first)
await refresh()
await click(bar(first))
must(has('第 2 次'), '第二次成功后采用第 2 次')
await click(button('☆ 采用'))
must(calls[calls.length - 1] === `PUT /clips/${first}/chosen {"attempt":0}`, '改用第 1 次')
before = calls.length
const mute = container.querySelector('.film__clip input[type=checkbox]') as unknown as HTMLInputElement
await act(async () => { mute.click() })
await settle()
must(calls.slice(before).includes(`PATCH /clips/${first} {"mute_native":true}`), '原声静音写回')
console.log('7. 采用与原声静音 ✓')

// 8. 待核对：总览与段详情都提示到控制台核对
const third = film!.clips[2].id
Object.assign(clipOf(third), { state: 'failed', uncertain: true, error: '提交时连接中断，不确定厂商是否已受理' })
film = recount(film!)
await refresh()
must(has('1 段结果不明'), '总览提示待核对的段数')
await click(bar(third))
must(has('请到厂商控制台核对'), '段详情提示到控制台核对')
console.log('8. 待核对标记 ✓')

// 9. 未保存的改动：出片按钮禁用并提示先保存
await act(async () => { setDirty(true) })
await settle()
must(has('先保存再出片') && button('出这一段').disabled, '有未保存改动时不能出片')
await act(async () => { setDirty(false) })
await settle()
console.log('9. 未保存拦截 ✓')

// 10. 验证门：读取时报告没过 → 提示并禁用；修好后恢复
gateFail = true
await refresh()
must(has(GATE) && button('出这一段').disabled, '验证门没过时不能出片')
gateFail = false
await refresh()
must(!has(GATE) && !button('出这一段').disabled, '验证门通过后恢复')
console.log('10. 验证门拦截 ✓')

// 11. 播成片：有已出的段才有开关；切到「播成片」后播放，预览窗里是采用那次的视频
await click(button('播关键帧'))
must(!!button('播成片'), '切到播成片')
await click(bar(first))
await click(button('▶ 播放'))
await settle(150)
must(!!container.querySelector('.tlc__pip video'), '预览窗里播视频')
must(calls.includes(`GET /files/clips/${first}.t1.mp4`), '取的是采用那次（第 1 次）的视频')
await click(button('❚❚ 暂停'))
console.log('11. 播成片 ✓')

await act(async () => { root.unmount() })
console.log('\nALL PASS')
```

In `frontend/package.json`, append to the end of the `"test"` script string (after the `film-lane` part added in Task 3):

```
 && vite build --ssr tests/film.test.tsx --outDir .ssrout --logLevel error && node .ssrout/film.test.js
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd frontend && npx vite build --ssr tests/film.test.tsx --outDir .ssrout --logLevel error && node .ssrout/film.test.js`
Expected: step 0 passes (`0. 没有版本不出片 ✓`), then FAIL `✗ 读取会话 404 → 没有成片泳道`（画布还不请求出片接口）

- [ ] **Step 3: 画布的 import、泳道高度、页签类型、泳道布局**

In `frontend/src/components/TimelineCanvas.tsx`:

Add these imports below `import { buildIndex } from '../resolve'`:

```ts
import { chosenAttempt, clipOffset, clipSpans, laneKind, laneText, laneTitle, spanAt } from '../film'
import { useFilm } from '../useFilm'
import { FilmPanel } from './FilmPanel'
```

Replace:

```ts
const ROW = { episode: 24, scene: 26, shot: 38, frame: 72, char: 44, speech: 30, music: 26 }
```

with:

```ts
const ROW = { episode: 24, scene: 26, shot: 38, clip: 34, frame: 72, char: 44, speech: 30, music: 26 }
```

Replace `type PanelTab = 'shot' | 'source' | 'assets' | 'novel' | 'tasks'` with:

```ts
type PanelTab = 'shot' | 'source' | 'assets' | 'film' | 'novel' | 'tasks'
```

Replace the `layoutRows` signature line and the shot push:

```ts
function layoutRows(tl: Timeline, withFrames: boolean): { rows: Row[]; height: number } {
```

with:

```ts
function layoutRows(tl: Timeline, withFrames: boolean, withClips: boolean): { rows: Row[]; height: number } {
```

and

```ts
  push('shot', '镜头', ROW.shot)
```

with:

```ts
  push('shot', '镜头', ROW.shot)
  // 有出片会话才出这条泳道：每段一条横条，横跨所含镜头
  if (withClips) push('clip', '成片', ROW.clip)
```

- [ ] **Step 4: 画布的出片状态**

Right after the line `const [focusUnit, setFocusUnit] = useState<string | null>(null)`, insert:

```ts
  /** 出片会话（只有存进后端的版本才有）；「出片」页签开着时轮询更勤 */
  const film = useFilm(version, { active: panel === 'film' })
  /** 「成片」泳道上选中的段 */
  const [clipSel, setClipSel] = useState<string | null>(null)
  /** 预览窗播已出的成片（采用的那一次）还是关键帧 */
  const [filmMode, setFilmMode] = useState(false)
  /** 「生成中 · 已等 m:ss」每秒走一次 */
  const [now, setNow] = useState(() => Date.now())
  const videoRef = useRef<HTMLVideoElement>(null)
```

Replace:

```ts
  const tl = useMemo(() => buildTimeline(doc), [doc])
  const withFrames = Object.keys(kf.urls).length > 0
  const { rows, height } = useMemo(() => layoutRows(tl, withFrames), [tl, withFrames])
```

with:

```ts
  const tl = useMemo(() => buildTimeline(doc), [doc])
  const withFrames = Object.keys(kf.urls).length > 0
  const spans = useMemo(() => (film.session ? clipSpans(tl, film.session) : []), [tl, film.session])
  const withClips = spans.length > 0
  const { rows, height } = useMemo(() => layoutRows(tl, withFrames, withClips), [tl, withFrames, withClips])
  const { ensure } = film
  // 成片泳道的缩略图：各段采用那次的尾帧
  useEffect(() => {
    for (const sp of spans) ensure(chosenAttempt(sp.clip)?.last_frame)
  }, [spans, ensure])
  useEffect(() => {
    if (!spans.some((sp) => laneKind(sp.clip) === 'busy')) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [spans])
```

Right after the line `const curPrompt = cur ? kf.promptOf(cur.id) : undefined`, insert:

```ts
  /** 播成片：播放头所在段采用的视频（没有就退回关键帧，标「未出片」） */
  const curSpan = filmMode ? spanAt(spans, t) : undefined
  const curVideo = curSpan ? (chosenAttempt(curSpan.clip)?.file ?? undefined) : undefined
  useEffect(() => { ensure(curVideo) }, [curVideo, ensure])
  // 视频跟着播放头走：偏差超过 0.3 秒才拖，免得每帧都打断解码
  useEffect(() => {
    const v = videoRef.current
    if (!v || !curSpan) return
    const want = clipOffset(curSpan, t)
    if (Math.abs(v.currentTime - want) > 0.3) v.currentTime = want
    v.playbackRate = speed
    if (playing) {
      if (v.paused) void v.play()?.catch(() => {})
    } else if (!v.paused) {
      v.pause()
    }
  })
```

Right after the line `const shotIndexAtStart = (sec: number) => tl.shots[shotIndexAt(tl, sec)]?.id`, insert:

```ts
  /** 点成片横条：选中该段、播放头跳到段首、侧栏切到「出片」 */
  const selectClip = (clipId: string) => {
    if (suppressClick.current) { suppressClick.current = false; return }
    const sp = spans.find((x) => x.clip.id === clipId)
    setClipSel(clipId)
    setPanel('film')
    if (sp) {
      setPlaying(false)
      setRange(null)
      seek(sp.start)
    }
  }
```

- [ ] **Step 5: 工具条开关、成片泳道、预览窗**

In the toolbar, right after the closing `</button>` of the 「预演」 button (the one with `onClick={() => setAnimatic((v) => !v)}`), insert:

```tsx
        {spans.some((sp) => chosenAttempt(sp.clip)) && (
          <button className={`btn btn--sm${filmMode ? '' : ' btn--ghost'}`}
                  title="预览窗播已出的成片（采用的那一次）；未出片的段显示关键帧"
                  onClick={() => setFilmMode((v) => !v)}>
            {filmMode ? '播成片' : '播关键帧'}
          </button>
        )}
```

In the SVG, right before the comment `{/* 画面：已上传的关键帧按镜头宽度整张放进去（不裁切），点一下选中该镜 */}`, insert:

```tsx
          {/* 成片：每段一条横条，横跨所含镜头；点一下选中该段、切到「出片」页 */}
          {rowOf.clip && spans.map((sp) => {
            const c = sp.clip
            const kind = laneKind(c)
            const w = Math.max(2, (sp.end - sp.start) * pps - 2)
            const thumb = kind === 'done' || kind === 'stale'
              ? film.files[chosenAttempt(c)?.last_frame ?? ''] : undefined
            const marks = `${c.dropped_refs.length ? '⚠' : ''}${c.truncated ? '✂' : ''}`
            return (
              <g key={`clip-${c.id}`} data-clip={c.id}
                 className={`tlc__clip tlc__clip--${kind}${c.id === clipSel ? ' is-sel' : ''}`}
                 onClick={() => selectClip(c.id)}>
                <rect x={x(sp.start) + 1} y={rowOf.clip.y + 4} width={w} height={ROW.clip - 8} rx={3} />
                {thumb && (
                  <image href={thumb} x={x(sp.start) + 2} y={rowOf.clip.y + 5}
                         width={Math.max(1, Math.min(w - 2, 40))}
                         height={ROW.clip - 10} preserveAspectRatio="xMidYMid slice" />
                )}
                <text x={x(sp.start) + (thumb ? 46 : 6)} y={rowOf.clip.y + ROW.clip / 2 + 4}>
                  {fitText(`${marks}${laneText(c, now)}`, w - (thumb ? 50 : 10), 10, 3)}
                </text>
                {/* 横条窄到写不下字时，悬停照样看得到状态 */}
                <title>{`${laneText(c, now)}\n${laneTitle(c)}`}</title>
              </g>
            )
          })}

```

In the preview window (`{playing && animatic && cur && (`), replace:

```tsx
          {kf.urls[cur.id]
            ? <img src={kf.urls[cur.id]} alt={`${cur.id} 关键帧`} />
            : (
              <div className="tlc__pipph"><p>{cur.shot.action}</p></div>
            )}
```

with:

```tsx
          {curVideo && film.files[curVideo]
            ? <video ref={videoRef} src={film.files[curVideo]} muted={curSpan?.clip.mute_native} playsInline />
            : kf.urls[cur.id]
              ? <img src={kf.urls[cur.id]} alt={`${cur.id} 关键帧`} />
              : (
                <div className="tlc__pipph"><p>{cur.shot.action}</p></div>
              )}
          {filmMode && !curVideo && <span className="tlc__pipnote">未出片</span>}
```

- [ ] **Step 6: 「出片」页签**

Replace the tab list expression:

```tsx
          {([['shot', '本镜'], ['source', '原文'], ['assets', '资产'],
             ...(bench ? [['novel', '剧情'], ['tasks', bench.converting ? '任务 ●' : '任务']] : [])] as [PanelTab, string][])
```

with:

```tsx
          {([['shot', '本镜'], ['source', '原文'], ['assets', '资产'],
             ...(film.enabled ? [['film', '出片']] : []),
             ...(bench ? [['novel', '剧情'], ['tasks', bench.converting ? '任务 ●' : '任务']] : [])] as [PanelTab, string][])
```

Right after the line `{panel === 'novel' && bench && <NovelPanel bench={bench} />}`, insert:

```tsx
        {panel === 'film' && film.enabled && (
          <FilmPanel film={film} selected={clipSel} onPickShot={selectShot} dirty={dirty} />
        )}
```

- [ ] **Step 7: 现有画布测试的桩后端**

In `frontend/tests/canvas.test.tsx`, inside `g.fetch`, insert right before the line `const m = path.match(/^\/novels\/n1\/chapters\/c1\/versions\/v1\/keyframes(?:\/(.+))?$/)`:

```ts
  // 出片会话：这个版本还没建（画布出片的交互在 film.test.tsx）
  if (path === '/novels/n1/chapters/c1/versions/v1/render/session') {
    return { ok: false, status: 404, statusText: 'Not Found', text: async () => '{"detail":"还没有出片会话"}' }
  }
```

- [ ] **Step 8: 运行，确认通过**

Run: `cd frontend && npx vite build --ssr tests/film.test.tsx --outDir .ssrout --logLevel error && node .ssrout/film.test.js && npm test 2>&1 | grep -c "ALL PASS"`
Expected: film.test prints steps 0–11 with `✓` then `ALL PASS`; the count prints `8`

- [ ] **Step 9: 提交**

```bash
git add src/components/TimelineCanvas.tsx tests/film.test.tsx tests/canvas.test.tsx package.json
git commit -m "画布出片接进时间轴：有会话才出现的「成片」泳道（五种状态、缩略图、⚠✂ 标记，点段切到出片页）、侧栏「出片」页签、预览窗「播关键帧 / 播成片」开关与视频跟播；没有版本时不出现任何出片元素"
```

---

### Task 6: 文档、设计文档写回裁定、全量回归

**Files:**
- Modify: `README.md`（「**出片（视频生成，后端）**」段落之后）
- Modify: `docs/specs/2026-10-28-video-generation-design.md`（末尾）

- [ ] **Step 1: README**

In `README.md`, right after the paragraph that starts with `**出片（视频生成，后端）**` (it ends with `画布上的出片界面、配音与合成另见后续计划。`), add:

```markdown

**出片（画布）**：在时间轴画布里出片，只对存进后端的版本出现。侧栏「出片」页签先「建立出片会话（不花钱）」，之后画布上多一条「成片」泳道（每段一条横条：虚线未出片、闪动生成中、填色已完成、红框失败、黄框过期），点横条看段详情。
总览主按钮先「先试这一段」，出过后变「出剩余 N 段（约 ¥x）」；批量和单段超过确认线（默认 20 元）先弹确认框，列各段金额、执行后累计与上限、费率依据。有未保存的改动或分镜没过验证门时出片按钮禁用。
段详情里可看提示词、参考图、首帧来源、每次尝试（播放、★ 采用）、重做、原声静音；结果不明的段标「请到控制台核对」，批量跳过。工具条「播关键帧 / 播成片」切换预览窗。音色分配与合成整章在配音合成（A3）里做。
```

- [ ] **Step 2: 设计文档写回裁定**

Append to the end of `docs/specs/2026-10-28-video-generation-design.md`:

```markdown

## 7. 实施裁定（2026-10-31，画布出片界面 A2 计划）

1. **音色分配挪到 A3**：现在没有 TTS 音色表，「出片」设置里只写一句说明。替代 2.3 第 1 条的音色分配。
2. **「合成整章」、整集播放与下载成片字幕挪到 A3**：总览主按钮到「出剩余 N 段」为止。替代 2.3 第 2 条的「合成整章」。
3. **费率依据**：各厂商带 `rate_note`，`view()` 的 `options.rate_note` 原样给确认框。不沿用渲染任务包的 `RATE_SOURCE`（那是 2026-03 报道的估算）。替代 2.4 的「沿用 `RATE_SOURCE`」。
4. **验证门预检**：`GET …/render/session` 附 `gate: {ok, message}`，只报告不拦；建会话、改设置、出片照旧过门。
5. **会话不自动建立**：「出片」页签里点「建立出片会话（不花钱）」才建。
6. **只有存进后端的版本有出片**：画布没有版本（本地 JSON、分批预览）时不出现任何出片元素，也不请求出片接口。
7. **视频与缩略图**按需取成 blob URL（带 token）；泳道缩略图是采用那次的尾帧图。
8. **播成片**：预览窗视频跟播放头，偏差超过 0.3 秒才拖；静音跟 `mute_native`，倍速跟画布。
9. **轮询之外**总览里有「刷新」。
10. **横条横跨所含镜头**（可播时长时间轴），被截断的段照样横跨并标 ✂。
11. **上限按版本计**（第 6 节第 17 条），设置里写明。
```

- [ ] **Step 3: 全量回归**

Run:
```bash
cd backend && for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py; do printf "%s: " $t; .venv/bin/python $t 2>&1 | tail -1; done
cd ../frontend && npm test 2>&1 | grep -c "ALL PASS" && npm run lint
```
Expected: 每个后端文件 `ALL PASS`；前端打印 `8`；lint 无 error

- [ ] **Step 4: 提交**

```bash
git add README.md docs/specs/2026-10-28-video-generation-design.md
git commit -m "画布出片文档：README 补出片页签、成片泳道、确认与播成片的用法；设计文档写回 A2 实施裁定（音色与合成挪到 A3、费率依据、验证门预检等）"
```

- [ ] **Step 5: 手动验证（由用户执行）**

1. `cd backend && STORYBOARD_VIDEO_PROVIDER=fake .venv/bin/uvicorn server.app:app --reload`（假厂商，不花钱）与 `cd frontend && npm run dev`。
2. 打开一个已转换的章节版本 → 时间轴画布 → 「出片」→ 建会话 → 先试一段 → 等横条变填色 → 「出剩余 N 段」确认 → 播成片。
3. 真实厂商（花钱）等 `render.smoke` 核对过账单再用。
