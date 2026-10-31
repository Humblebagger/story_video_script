# 画布配音与合成界面（A3b）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 画布「出片」页签下半部分加「配音与合成」：各说话人的音色、每集 BGM 上传与选曲参考、草稿合成开关、合成整章（配音金额先确认，409 换新金额再确认）、合成中进度、失败原因与 ffmpeg 输出、成片过期提示、每集成片播放与下载（mp4、字幕）、合成报告；没装 ffmpeg 时写明怎么装。

**Architecture:** 纯计算放 `src/compose.ts`（能不能合成及原因、状态文字、对齐说明、选曲参考、BGM 类型、何时重读）；`src/useCompose.ts` 管请求、确认、轮询与成片 blob；`src/components/ComposePanel.tsx` 只画。`FilmPanel` 在有出片会话时挂上它。后端先补三处小改：没有要配音的语音条时音色接口不要配音密钥、ffmpeg 提示写上 Linux 装法、合成预览直接带上报告内容。

**Tech Stack:** React 19 + TypeScript 6、Vite 8 SSR 构建跑测试、happy-dom（测试）；后端 FastAPI（A3a 已完成）。

**Spec:** `docs/specs/2026-10-28-video-generation-design.md` 2.3 第 2 条（合成后在此播放、下载成片与字幕）、3.4（BGM 与 `music.curve` 选曲参考）、3.6；第 7 节 1–2 条（音色分配、合成整章挪到 A3）；第 8 节（A3a 裁定，接口形态以它为准）。

---

## 全局约束

- 提交只 `git add` 具体文件，不用 `git add -A` / `git commit -a`；提交信息用中文、风格同 `git log --oneline -5`，**不带任何 Claude 署名**（无 `Co-Authored-By`、无 `Claude-Session`）。
- 不读、不打印 `backend/.env`。测试不联网、不花钱（假 TTS / 前端桩后端）。
- 后端命令在 `backend/` 下执行（`.venv/bin/python tests/…`，每个脚本以 `ALL PASS` 结束）；前端命令在 `frontend/` 下执行：`npm test`（含 `tsc -b --force` 类型检查，现有 8 套 + 本计划新增 1 套）、`npm run lint`（只允许已有的 warning，0 error）。
- 本机没装 ffmpeg（用户在开发全部完成后再装）：前端测试一律用桩后端；不要提醒用户装 ffmpeg。
- 未跟踪的 `docs/specs/2026-10-27-commercialization-design-contract.md` 不要碰。
- 界面文字全中文；金额一律写在按钮上（`¥x.xx`）。

## 后端接口（A3a 已有，前缀 `/novels/{nid}/chapters/{cid}/versions/{vid}/render`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/voices` | `{provider, rate_note, voices: [{id, name, gender}], speakers: [{key, name, hint, voice, chosen}], missing: [key]}`；`voice` 为当前用的（选的或按提示默认），`chosen` 为用户选的 |
| PUT | `/voices` | 体 `{voices: {说话人: 音色 id 或 ""}}`（空串为清除），返回同 GET |
| GET | `/compose?draft=true` | `{lines, tts_chars, tts_cny, missing_voices, voices, no_video, fingerprint, final, bgm: [集号], tools: bool, music: {集号: {mood, style_hint, curve}}}`；`final` 为 `null` 或 `{state: queued/running/done/failed, step, files, report, error, detail, draft, started_at, finished_at, stale, …}` |
| POST | `/compose` | 体 `{expected_cny, draft}`；配音金额对不上 409 `{message, expected_cny}`；预览后音色被改过 409 `{message, expected_cny: null}`；正在合成 / 有段在跑 409；没装 ffmpeg、缺音色、草稿关掉时缺段 422；超上限 422；成功返回出片会话（`final.state = running`） |
| PUT | `/bgm/{集号}` | 体为音频文件，`Content-Type` 为 `audio/mpeg`、`audio/wav`、`audio/mp4`、`audio/aac` 等；≤ 30MB |
| DELETE | `/bgm/{集号}` | 删除 |
| GET | `/files/final/E01.mp4` 等 | 成片文件（带 token，前端转 blob URL） |

## 实施裁定（Task 5 写回设计文档第 9 节）

1. **合成区挂在「出片」页签里**，在设置、总览、段详情之后；只有建了出片会话才出现。不新增页签。
2. **有未保存的修改、验证门没过时也禁止合成**，与出片一致（合成只用已保存的版本）。
3. **配音金额为 0 时不弹确认**（全部命中缓存或这个声音模式不配音），按钮写「不花钱」；大于 0 时先弹确认，确认框写配音金额、已花、执行后累计与上限、费率依据。
4. **预览随出片会话变化重读**：声音模式、分辨率、各段状态 / 采用 / 静音、音色、成片状态任一变化就重读；合成在跑时 3 秒一读，跑完让出片会话也重读（已花金额变了）。
5. **成片文件按合成完成时间区分缓存**：重新合成后同名文件取新的，旧的 blob 回收。
6. **合成失败时仍列出上一次的成片**（标明是上一次的、是否过期），ffmpeg 输出折叠显示。
7. **后端小改**：没有要配音的语音条时 `GET /voices` 返回空表、不要配音密钥；没装 ffmpeg 的提示同时写 macOS 与 Ubuntu / Debian 的装法；`GET /compose` 带上合成报告内容（读不到或坏了为 `null`）。

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/server/app.py` | 修改：`render_voices` 没有语音条时空表；ffmpeg 提示；`_compose_preview` 带 `report` |
| `backend/tests/server/test_compose.py` | 修改：第 4、9 步断言，新增第 10 步 |
| `frontend/src/types.ts` | 修改：`TtsVoice`、`VoiceSpeaker`、`VoicesInfo`、`FinalState`、`MixNote`、`MixReport`、`ComposePreview`；`FilmSession` 加 `voices`、`final` |
| `frontend/src/api.ts` | 修改：`getVoices`、`putVoices`、`getCompose`、`startCompose`、`putBgm`、`deleteBgm` |
| `frontend/src/useFilm.ts` | 修改：返回 `ids`（`{nid, cid, vid}`） |
| `frontend/src/compose.ts` | 新建：纯计算 |
| `frontend/src/useCompose.ts` | 新建：请求、确认、轮询、成片 blob |
| `frontend/src/components/ComposePanel.tsx` | 新建：配音与合成区 |
| `frontend/src/components/FilmPanel.tsx` | 修改：挂 `ComposePanel`；总览「没有要出的段了」的文案 |
| `frontend/src/index.css` | 修改：`.compose*` 样式 |
| `frontend/tests/compose.test.tsx` | 新建：纯计算 + 界面回归 |
| `frontend/tests/film.test.tsx` | 修改：桩后端对合成接口回 404 且不记录调用 |
| `frontend/package.json` | 修改：`test` 脚本加 compose 一套 |

---

### Task 1: 后端小改（音色空表、ffmpeg 提示、预览带报告）

**Files:**
- Modify: `backend/server/app.py`（「配音与合成」一节）
- Test: `backend/tests/server/test_compose.py`

- [ ] **Step 1: 改测试**

In `backend/tests/server/test_compose.py`:

(a) In step 4, change

```python
    assert r.status_code == 422 and "brew install ffmpeg" in r.json()["detail"]
```

to

```python
    assert r.status_code == 422 and "brew install ffmpeg" in r.json()["detail"] \
        and "apt install ffmpeg" in r.json()["detail"], "没装 ffmpeg 的提示写 macOS 与 Linux 两种装法"
```

(b) In step 9, change

```python
        assert c.get(R + "/voices", headers=H).status_code == 422, "音色表仍要配音厂商"
```

to

```python
        v = c.get(R + "/voices", headers=H)
        assert v.status_code == 200 and v.json()["speakers"] == [] and v.json()["voices"] == [], \
            "没有要配音的语音条：音色表为空，不要配音密钥"
```

and change the step-9 print to `print("9. 无声模式不需要配音密钥（预览、合成、音色表） ✓")`.

(c) Right before the line `    mix.tools, mix.compose = real_tools, real_compose` at the end of `main()`, insert:

```python
    # 10. 合成报告随预览返回；读不到或坏了为 None
    assert c.get(R + "/compose", headers=H).json()["report"] is None, "第 9 步的成片没写报告文件"
    (root / "final").mkdir(exist_ok=True)
    (root / "final" / "mix_report.json").write_text(json.dumps({"episodes": [], "size": "720x1280"}),
                                                    encoding="utf-8")
    with render_session.mutate(root) as s_:
        s_["final"].update(state="done", files=["final/E01.mp4"], report="final/mix_report.json")
    assert c.get(R + "/compose", headers=H).json()["report"]["size"] == "720x1280"
    (root / "final" / "mix_report.json").write_text("{坏", encoding="utf-8")
    assert c.get(R + "/compose", headers=H).json()["report"] is None
    print("10. 合成报告随预览返回 ✓")
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python tests/server/test_compose.py`
Expected: FAIL at step 4 (`apt install ffmpeg` not in detail)

- [ ] **Step 3: 改 `app.py`**

In `backend/server/app.py`:

(a) Make sure `import json` is among the stdlib imports at the top (add it next to `import copy` if missing).

(b) In `render_voices`, replace the body from `s = _session_or_404(root)` through the `return {...}` with:

```python
    s = _session_or_404(root)
    lines = render_voice.tts_lines(render_voice.speech_lines(doc), s["audio_mode"])
    if not lines:       # 这个声音模式不配音：不取配音厂商，没配密钥也能看
        return {"provider": None, "rate_note": "", "voices": [], "speakers": [], "missing": []}
    tts = _tts()
    voices, missing = render_voice.resolve_voices(doc, lines, s.get("voices") or {}, tts.caps)
    info = render_voice.speakers(doc)
    chosen = s.get("voices") or {}
    return {"provider": tts.name, "rate_note": tts.rate_note,
            "voices": [{"id": x.id, "name": x.name, "gender": x.gender} for x in tts.caps.voices],
            "speakers": [{"key": k, "name": (info.get(k) or {}).get("name") or k or "（未标说话人）",
                          "hint": (info.get(k) or {}).get("hint"), "voice": voices.get(k), "chosen": chosen.get(k)}
                         for k in dict.fromkeys(x["speaker"] for x in lines)],
            "missing": missing}
```

(c) In `render_compose_post`, replace

```python
        raise HTTPException(422, "没有装 ffmpeg：先在终端执行 brew install ffmpeg，再重启后端")
```

with

```python
        raise HTTPException(422, "服务器没有装 ffmpeg：macOS 执行 brew install ffmpeg，"
                                 "Ubuntu / Debian 执行 apt install ffmpeg，装好后重启后端")
```

(d) In `_compose_preview`, right after the `p["final"] = …` if/else block and before `p["bgm"] = sorted(bgm)`, insert:

```python
    rep = Path(root) / f["report"] if f and f.get("files") and f.get("report") else None
    try:
        p["report"] = json.loads(rep.read_text(encoding="utf-8")) if rep and rep.is_file() else None
    except (OSError, ValueError):
        p["report"] = None      # 报告坏了不影响预览
```

Update the `render_compose_get` docstring to `"""合成预览（配音条数、未缓存字数与费用、缺音色、缺视频的段、BGM、选曲参考）、当前成片状态与合成报告。"""`.

- [ ] **Step 4: 运行，确认通过**

Run: `.venv/bin/python tests/server/test_compose.py && .venv/bin/python tests/server/test_render.py | tail -1`
Expected: ten `✓` lines then `ALL PASS`（step 6 prints an expected RuntimeError traceback）; test_render `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add server/app.py tests/server/test_compose.py
git commit -m "合成接口补：不配音的声音模式下音色表为空、不要配音密钥；没装 ffmpeg 的提示写 macOS 与 Ubuntu/Debian 两种装法；合成预览带上报告内容"
```

---

### Task 2: 类型、接口、纯计算（`compose.ts`）

**Files:**
- Modify: `frontend/src/types.ts`（「出片」一节末尾）
- Modify: `frontend/src/api.ts`（「出片」一节 `conflictCny` 之后）
- Modify: `frontend/src/useFilm.ts`（返回值）
- Create: `frontend/src/compose.ts`
- Create: `frontend/tests/compose.test.tsx`（本任务只有纯计算部分，Task 4 整个替换）
- Modify: `frontend/package.json`

- [ ] **Step 1: 写失败测试**

Create `frontend/tests/compose.test.tsx`:

```tsx
/** 配音与合成的纯计算：能不能合成及原因、状态文字、成片按集分组、对齐说明、选曲参考、BGM 类型、按钮文字。
 *  界面回归在 Task 4 补上。跑法：npm test */
import {
  bgmType, composeBlockers, composeKey, composeLabel, composing, curveText, finalEpisodes, finalText, noteText,
} from '../src/compose'
import type { ComposePreview, FilmSession, FinalState, VoicesInfo } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const P: ComposePreview = {
  lines: 3, tts_chars: 30, tts_cny: 0.01, missing_voices: ['C09'], voices: { narration: 'fake-male' },
  no_video: ['E01-C02'], fingerprint: 'fp', final: null, bgm: [], tools: true, music: {}, report: null,
}
const S = {
  audio_mode: 'tts_all', resolution: '720p', budget_cny: 200, spent_cny: 10, voices: {}, final: null,
  clips: [{ id: 'E01-C01', state: 'done', chosen: 0, mute_native: false },
          { id: 'E01-C02', state: 'planned', chosen: null, mute_native: false }],
} as unknown as FilmSession
const V: VoicesInfo = {
  provider: 'fake', rate_note: '假配音', voices: [{ id: 'fake-male', name: '假男声', gender: 'male' }],
  speakers: [{ key: 'C09', name: '路人', hint: null, voice: null, chosen: null }], missing: ['C09'],
}
const base = { dirty: false, gate: null, draft: true }

must(composeBlockers(P, S, V, base).join('|') === '还有 1 个说话人没选音色：路人', '缺音色写说话人名字')
must(composeBlockers({ ...P, missing_voices: [] }, S, V, base).length === 0, '草稿合成时缺段不拦')
must(composeBlockers({ ...P, missing_voices: [] }, S, V, { ...base, draft: false })[0]
  .startsWith('1 段还没有可用的视频'), '关掉草稿合成时缺段要拦')
const all = composeBlockers({ ...P, tools: false, tts_cny: 500, missing_voices: [] },
  { ...S, clips: [{ ...S.clips[0], state: 'running' }] } as FilmSession, V,
  { dirty: true, gate: '分镜未通过独立验证', draft: true })
must(all.length === 5 && all[0].includes('先保存再合成') && all[1].includes('分镜未通过独立验证')
  && all[2].includes('apt install ffmpeg') && all[3].includes('排队或生成中') && all[4].includes('超过上限'),
  `各种拦截按顺序列出：${all.join(' / ')}`)
const busy: FinalState = { state: 'running', step: '混音 E01', files: [], report: null, error: null, detail: null }
must(composing({ ...P, final: busy }) && !composing(P), '合成中')
must(composeBlockers({ ...P, missing_voices: [], final: busy }, S, V, base)[0] === '正在合成，等它结束再合成',
  '合成中不能再合成')
console.log('1. 能不能合成及原因 ✓')

must(finalText(busy) === '合成中 · 混音 E01', '合成中写步骤')
must(finalText({ ...busy, state: 'failed', error: '混音 E01 失败' }) === '合成失败：混音 E01 失败', '失败写原因')
must(finalText({ ...busy, state: 'done', stale: false }) === '成片是最新的', '最新')
must(finalText({ ...busy, state: 'done', stale: true }).startsWith('成片已过期'), '过期')
const eps = finalEpisodes(['final/E01.mp4', 'final/E01.srt', 'final/E02.mp4', 'final/mix_report.json'])
must(JSON.stringify(eps) === JSON.stringify([
  { episode: 'E01', video: 'final/E01.mp4', srt: 'final/E01.srt' }, { episode: 'E02', video: 'final/E02.mp4' }]),
  '成片按集分组')
console.log('2. 成片状态与分组 ✓')

must(noteText({ shot: 'S2', kind: 'speedup', speed: 1.1 }) === 'S2：语速提到 1.1×', '提速说明')
must(noteText({ shot: 'S3', kind: 'freeze', speed: 1.15, extend: 0.61 })
  === 'S3：按 1.15× 念仍超出镜头，段尾定格延长 0.61 秒', '定格说明')
must(curveText({ from_shot: 'E01-SH001', to_shot: 'E01-SH010', mood: 'calm', intensity: 'low', note: '秋夜' })
  === 'E01-SH001–E01-SH010 · 平静 · 弱 · 秋夜', '选曲参考')
must(curveText({ mood: 'tense' }) === '紧张', '选曲参考缺项')
console.log('3. 对齐说明与选曲参考 ✓')

must(bgmType({ name: 'a.mp3', type: 'audio/mpeg' }) === 'audio/mpeg', '浏览器给的类型')
must(bgmType({ name: 'b.M4A', type: '' }) === 'audio/mp4', '没有类型按扩展名')
must(bgmType({ name: 'c.wav', type: 'audio/x-wav' }) === 'audio/x-wav', 'x-wav 也认')
must(bgmType({ name: 'd.txt', type: 'text/plain' }) === null, '不是音频')
must(composeLabel(P) === '合成整章（配音约 ¥0.01）' && composeLabel({ ...P, tts_cny: 0 }) === '合成整章（不花钱）',
  '按钮写金额')
const k1 = composeKey(S)
must(composeKey({ ...S, voices: { C09: 'fake-male' } } as FilmSession) !== k1
  && composeKey({ ...S, clips: [S.clips[0], { ...S.clips[1], state: 'done' }] } as FilmSession) !== k1
  && composeKey({ ...S, spent_cny: 99 } as FilmSession) === k1, '音色、段状态变了才重读；已花变了不重读')
console.log('4. BGM 类型、按钮文字、重读时机 ✓')

console.log('\nALL PASS')
```

In `frontend/package.json`, append to the end of the `test` script (inside the string):

```
 && vite build --ssr tests/compose.test.tsx --outDir .ssrout --logLevel error && node .ssrout/compose.test.js
```

- [ ] **Step 2: 运行，确认失败**

Run: `npm test 2>&1 | tail -5`
Expected: FAIL — typecheck errors (`Cannot find module '../src/compose'`, missing types)

- [ ] **Step 3: 类型**

Append to the end of the 出片 section of `frontend/src/types.ts` (after `interface FilmSession`):

```ts
/* ---------- 配音与合成（…/render/voices、…/render/compose） ---------- */

export interface TtsVoice { id: string; name: string; gender: 'male' | 'female' }

export interface VoiceSpeaker {
  /** narration 为旁白，其余为角色 id */
  key: string
  name: string
  /** 分镜里的抽象音色提示（male_elder…） */
  hint: string | null
  /** 现在用的音色（选的或按提示默认）；null 为缺音色 */
  voice: string | null
  /** 用户选的；null 为按提示默认 */
  chosen: string | null
}

export interface VoicesInfo {
  /** 这个声音模式不配音时为 null（音色表为空） */
  provider: string | null
  rate_note: string
  voices: TtsVoice[]
  speakers: VoiceSpeaker[]
  missing: string[]
}

export interface FinalState {
  state: 'queued' | 'running' | 'done' | 'failed'
  step?: string
  /** 现有成片（会话目录下的相对路径）；失败时仍是上一次的 */
  files: string[]
  report: string | null
  error: string | null
  /** ffmpeg 的错误输出 */
  detail: string | null
  draft?: boolean
  started_at?: string
  finished_at?: string
  /** 只在合成预览里有：现有成片是否已过期 */
  stale?: boolean
}

export interface MixNote { shot: string; kind: 'speedup' | 'freeze'; speed: number; extend?: number }

export interface MixReport {
  audio_mode: AudioMode
  size: string
  draft: boolean
  alignment: string
  warning?: string
  episodes: { episode: string; seconds: number; notes: MixNote[]; placeholders: string[]; stale: string[] }[]
}

export interface ComposePreview {
  /** 走 TTS 的语音条数 */
  lines: number
  /** 还没缓存的字数与配音费用（合成前要确认） */
  tts_chars: number
  tts_cny: number
  missing_voices: string[]
  voices: Record<string, string>
  /** 没有可用视频的段 */
  no_video: string[]
  fingerprint: string
  final: FinalState | null
  /** 已上传 BGM 的集号 */
  bgm: string[]
  /** 服务器装了 ffmpeg */
  tools: boolean
  /** 各集的选曲参考（分镜 music） */
  music: Record<string, { mood?: Mood; style_hint?: string; curve?: MusicSegment[] }>
  report: MixReport | null
}
```

In `interface FilmSession`, add these two fields right after `spent_cny: number`:

```ts
  /** 说话人 → 用户选的音色 id */
  voices?: Record<string, string>
  /** 合成状态与成片（没合成过为 null 或没有） */
  final?: FinalState | null
```

- [ ] **Step 4: 接口**

In `frontend/src/api.ts`, add `ComposePreview` and `VoicesInfo` to the existing type import from `./types` (the import that already lists `FilmSession, FilmSettings`), then insert after the `conflictCny` function:

```ts
/* ---------- 配音与合成 ---------- */

/** 音色表与各说话人现在用的音色；这个声音模式不配音时为空表 */
export function getVoices(nid: string, cid: string, vid: string): Promise<VoicesInfo> {
  return req(`${filmPath(nid, cid, vid)}/voices`)
}

/** 选音色：说话人 → 音色 id，空串为恢复按提示默认 */
export function putVoices(nid: string, cid: string, vid: string,
                          voices: Record<string, string>): Promise<VoicesInfo> {
  return req(`${filmPath(nid, cid, vid)}/voices`, jsonBody('PUT', { voices }))
}

/** 合成预览（不花钱）：配音条数与金额、缺音色、缺视频的段、BGM、选曲参考、成片状态与报告 */
export function getCompose(nid: string, cid: string, vid: string, draft: boolean): Promise<ComposePreview> {
  return req(`${filmPath(nid, cid, vid)}/compose?draft=${draft}`)
}

/** 合成整章（后台）：带用户确认过的配音金额，服务端重算不一致 409 */
export function startCompose(nid: string, cid: string, vid: string, draft: boolean,
                             expectedCny: number): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/compose`, jsonPost({ expected_cny: expectedCny, draft }))
}

/** 上传一集的 BGM（原样作为请求体） */
export function putBgm(nid: string, cid: string, vid: string, episode: string, file: Blob,
                       type: string): Promise<{ episode: string; bytes: number }> {
  return req(`${filmPath(nid, cid, vid)}/bgm/${enc(episode)}`,
             { method: 'PUT', headers: { 'Content-Type': type }, body: file })
}

export function deleteBgm(nid: string, cid: string, vid: string, episode: string): Promise<{ deleted: string }> {
  return req(`${filmPath(nid, cid, vid)}/bgm/${enc(episode)}`, { method: 'DELETE' })
}
```

- [ ] **Step 5: `useFilm` 返回版本 id**

In `frontend/src/useFilm.ts`, in the returned object, change the first line

```ts
    enabled, session, status, error, gate, busy, confirm, files, load, ensure,
```

to

```ts
    enabled, session, status, error, gate, busy, confirm, files, load, ensure,
    /** 版本 id（没有版本时都为 undefined）：配音与合成用同一会话 */
    ids: { nid, cid, vid },
```

- [ ] **Step 6: 纯计算**

Create `frontend/src/compose.ts`:

```ts
/** 配音与合成在「出片」页签里的纯计算：能不能合成及原因、合成状态文字、成片按集分组、对齐说明、选曲参考、
 *  BGM 上传类型、按钮文字、什么时候重读预览。useCompose 与 ComposePanel 只吃这里的结果；单测见 tests/compose.test.tsx。 */
import { inFlight } from './film'
import { label, MOOD } from './labels'
import type { ComposePreview, FilmSession, FinalState, MixNote, MusicSegment, VoicesInfo } from './types'

/** 合成在跑时多久重读一次预览 */
export const COMPOSE_POLL_MS = 3000
export const FFMPEG_HINT =
  '服务器没有装 ffmpeg：macOS 执行 brew install ffmpeg，Ubuntu / Debian 执行 apt install ffmpeg，装好后重启后端'
/** 文件选择框接受的类型 */
export const BGM_ACCEPT = 'audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/x-m4a,audio/aac,.mp3,.wav,.m4a,.aac'

const yuan = (n: number) => `¥${n.toFixed(2)}`
const BGM_TYPES = ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/wave', 'audio/mp4',
                   'audio/x-m4a', 'audio/aac']
const BGM_EXT: Record<string, string> = { mp3: 'audio/mpeg', wav: 'audio/wav', m4a: 'audio/mp4', aac: 'audio/aac' }
const INTENSITY: Record<string, string> = { low: '弱', mid: '中', high: '强' }

export const composing = (p: ComposePreview | null) =>
  !!p?.final && (p.final.state === 'queued' || p.final.state === 'running')

/** 出片会话里会改变合成预览的部分：变了才重读（已花金额、轮询时间这些不算） */
export function composeKey(s: FilmSession): string {
  return JSON.stringify([s.audio_mode, s.resolution, s.voices ?? {}, s.final?.state ?? null,
                         s.final?.finished_at ?? null, s.clips.map((c) => [c.id, c.state, c.chosen, c.mute_native])])
}

export const speakerName = (v: VoicesInfo | null, key: string) =>
  v?.speakers.find((x) => x.key === key)?.name ?? (key || '（未标说话人）')

/** 不能合成的原因（按要先处理的顺序）；空数组为可以合成 */
export function composeBlockers(p: ComposePreview, s: FilmSession, v: VoicesInfo | null,
                                o: { dirty: boolean; gate: string | null; draft: boolean }): string[] {
  const out: string[] = []
  if (o.dirty) out.push('有未保存的修改：先保存再合成（合成只用已保存的版本）')
  if (o.gate) out.push(`${o.gate}：先在分镜页修好再合成`)
  if (!p.tools) out.push(FFMPEG_HINT)
  if (composing(p)) out.push('正在合成，等它结束再合成')
  if (s.clips.some(inFlight)) out.push('有段在排队或生成中，等它们结束再合成')
  if (p.missing_voices.length) {
    out.push(`还有 ${p.missing_voices.length} 个说话人没选音色：${p.missing_voices.map((k) => speakerName(v, k)).join('、')}`)
  }
  if (!o.draft && p.no_video.length) {
    out.push(`${p.no_video.length} 段还没有可用的视频：打开「草稿合成」可用关键帧补位`)
  }
  if (s.spent_cny + p.tts_cny > s.budget_cny + 1e-9) {
    out.push(`配音约 ${yuan(p.tts_cny)}，会超过上限 ${yuan(s.budget_cny)}：先在设置里调高上限`)
  }
  return out
}

export function finalText(f: FinalState): string {
  if (f.state === 'queued' || f.state === 'running') return `合成中 · ${f.step || '开始'}`
  if (f.state === 'failed') return `合成失败：${f.error ?? '原因不明'}`
  return f.stale ? '成片已过期：分镜、音色、BGM 或采用的视频改过，重新合成才会更新' : '成片是最新的'
}

export interface FinalEpisode { episode: string; video?: string; srt?: string }

/** 成片文件按集分组（final/E01.mp4、final/E01.srt） */
export function finalEpisodes(files: string[]): FinalEpisode[] {
  const by = new Map<string, FinalEpisode>()
  for (const f of files) {
    const m = f.match(/^final\/(.+)\.(mp4|srt)$/)
    if (!m) continue
    const e = by.get(m[1]) ?? { episode: m[1] }
    if (m[2] === 'mp4') e.video = f
    else e.srt = f
    by.set(m[1], e)
  }
  return [...by.values()]
}

/** 报告里的声画对齐调整 */
export function noteText(n: MixNote): string {
  return n.kind === 'speedup' ? `${n.shot}：语速提到 ${n.speed}×`
    : `${n.shot}：按 ${n.speed}× 念仍超出镜头，段尾定格延长 ${n.extend ?? 0} 秒`
}

/** 分镜 music.curve 的一段：镜头范围 · 情绪 · 强度 · 说明 */
export function curveText(seg: MusicSegment): string {
  const range = seg.from_shot || seg.to_shot ? `${seg.from_shot ?? ''}–${seg.to_shot ?? ''}` : ''
  return [range, label(MOOD, seg.mood), seg.intensity ? INTENSITY[seg.intensity] : '', seg.note ?? '']
    .filter(Boolean).join(' · ')
}

/** 上传 BGM 用的 Content-Type：浏览器给的类型能认就用，否则按扩展名；都不认为 null */
export function bgmType(file: { name: string; type: string }): string | null {
  if (BGM_TYPES.includes(file.type)) return file.type
  return BGM_EXT[file.name.split('.').pop()?.toLowerCase() ?? ''] ?? null
}

export const composeLabel = (p: ComposePreview) =>
  p.tts_cny > 0 ? `合成整章（配音约 ${yuan(p.tts_cny)}）` : '合成整章（不花钱）'
```

- [ ] **Step 7: 运行，确认通过**

Run: `npm test 2>&1 | grep -E "ALL PASS|✗|error" ; npm run lint 2>&1 | tail -3`
Expected: nine `ALL PASS` lines（8 existing + compose）, no `✗`/error; lint 0 errors

- [ ] **Step 8: 提交**

```bash
git add src/types.ts src/api.ts src/useFilm.ts src/compose.ts tests/compose.test.tsx package.json
git commit -m "配音与合成前端底层：音色、合成预览、成片与报告的类型；音色、合成、BGM 接口；纯计算（能不能合成及原因、合成状态、成片按集分组、对齐说明、选曲参考、BGM 类型、重读时机）"
```

---

### Task 3: `useCompose` 与合成区界面

**Files:**
- Create: `frontend/src/useCompose.ts`
- Create: `frontend/src/components/ComposePanel.tsx`
- Modify: `frontend/src/components/FilmPanel.tsx`
- Modify: `frontend/src/index.css`（`.film__confirm h4` 一行之后）
- Modify: `frontend/tests/film.test.tsx`（桩后端）

- [ ] **Step 1: `useCompose`**

Create `frontend/src/useCompose.ts`:

```ts
/** 「出片」页签里的配音与合成：读预览与音色表、改音色、上传删除 BGM、合成（配音金额先确认）、合成中轮询、
 *  成片文件的 blob URL。
 *
 *  预览随出片会话里会影响合成的部分变化重读（composeKey）；合成在跑时 3 秒一读，跑完让出片会话也重读
 *  （配音费计入了已花）。配音金额大于 0 先进 confirm；服务端重算对不上（409 带金额）就换成新金额再确认。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { conflictCny, deleteBgm, filmFileUrl, getCompose, getVoices, putBgm, putVoices, startCompose } from './api'
import { COMPOSE_POLL_MS, bgmType, composeKey, composing } from './compose'
import type { ComposePreview, VoicesInfo } from './types'
import type { Film } from './useFilm'

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function useCompose(film: Film) {
  const { nid, cid, vid } = film.ids
  const key = film.session ? composeKey(film.session) : ''
  const reloadFilm = film.load
  const [preview, setPreview] = useState<ComposePreview | null>(null)
  const [voices, setVoices] = useState<VoicesInfo | null>(null)
  const [draft, setDraft] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  /** 每次读取结束加一：合成中的轮询定时器据此重排 */
  const [tick, setTick] = useState(0)
  const [confirm, setConfirm] = useState<{ cny: number; changed: boolean } | null>(null)
  /** `合成完成时间|相对路径` → blob URL */
  const [files, setFiles] = useState<Record<string, string>>({})
  const live = useRef<Record<string, string>>({})
  const asking = useRef(new Set<string>())
  /** 换版本 / 卸载时加一：之前的响应一律丢弃 */
  const gen = useRef(0)

  const load = useCallback(async () => {
    if (!nid || !cid || !vid) return
    const mine = gen.current
    try {
      const p = await getCompose(nid, cid, vid, draft)
      if (gen.current !== mine) return
      const v = p.lines ? await getVoices(nid, cid, vid) : null
      if (gen.current !== mine) return
      setPreview(p)
      setVoices(v)
      setError(null)
    } catch (e) {
      if (gen.current === mine) setError(msg(e))
    } finally {
      if (gen.current === mine) setTick((n) => n + 1)
    }
  }, [nid, cid, vid, draft])

  useEffect(() => { void load() }, [load, key])

  const running = composing(preview)
  useEffect(() => {
    if (!running) return
    const id = setTimeout(() => void load(), COMPOSE_POLL_MS)
    return () => clearTimeout(id)
  }, [running, load, tick])

  // 合成跑完（在跑 → 不在跑）：出片会话也重读
  const was = useRef(false)
  useEffect(() => {
    if (was.current && !running) void reloadFilm()
    was.current = running
  }, [running, reloadFilm])

  /** 成片文件按合成完成时间区分：重新合成后同一路径取新的 */
  const stamp = preview?.final?.finished_at ?? ''
  const ensure = useCallback((path?: string | null) => {
    if (!path || !nid || !cid || !vid) return
    const k = `${stamp}|${path}`
    if (live.current[k] || asking.current.has(k)) return
    const mine = gen.current
    asking.current.add(k)
    filmFileUrl(nid, cid, vid, path)
      .then((url) => {
        if (gen.current !== mine) { URL.revokeObjectURL(url); return }
        live.current[k] = url
        setFiles({ ...live.current })
      })
      .catch((e) => { if (gen.current === mine) setError(`读取成片文件失败：${msg(e)}`) })
      .finally(() => asking.current.delete(k))
  }, [nid, cid, vid, stamp])
  const url = (path?: string | null) => (path ? files[`${stamp}|${path}`] : undefined)

  // 换了一次合成：上一次的 blob 回收
  useEffect(() => {
    for (const [k, u] of Object.entries(live.current)) {
      if (!k.startsWith(`${stamp}|`)) {
        URL.revokeObjectURL(u)
        delete live.current[k]
      }
    }
    setFiles({ ...live.current })
  }, [stamp])
  useEffect(() => () => {
    gen.current += 1
    for (const u of Object.values(live.current)) URL.revokeObjectURL(u)
    live.current = {}
    asking.current.clear()
  }, [nid, cid, vid])

  /** 不花钱的操作：忙标记、清错误、成功后重读预览 */
  const apply = useCallback(async (fn: () => Promise<unknown>) => {
    const mine = gen.current
    setBusy(true)
    setError(null)
    try {
      await fn()
      if (gen.current === mine) await load()
    } catch (e) {
      if (gen.current === mine) setError(msg(e))
    } finally {
      if (gen.current === mine) setBusy(false)
    }
  }, [load])

  /** 花钱的一步：带确认过的配音金额发请求；409 带金额就放回确认框，不带（音色刚改过、正在合成）就写原因 */
  const send = async (cny: number) => {
    const mine = gen.current
    setBusy(true)
    setError(null)
    try {
      await startCompose(nid!, cid!, vid!, draft, cny)
      if (gen.current !== mine) return
      setConfirm(null)
      await Promise.all([load(), reloadFilm()])
    } catch (e) {
      if (gen.current !== mine) return
      const fresh = conflictCny(e)
      if (fresh !== null) setConfirm({ cny: fresh, changed: true })
      else {
        setConfirm(null)
        setError(msg(e))
      }
      void load()
    } finally {
      if (gen.current === mine) setBusy(false)
    }
  }

  return {
    preview, voices, draft, error, busy, confirm, load, ensure, url,
    setDraft,
    setVoice: (speaker: string, voice: string) => apply(() => putVoices(nid!, cid!, vid!, { [speaker]: voice })),
    uploadBgm: (episode: string, file: File) => {
      const type = bgmType(file)
      if (!type) {
        setError('BGM 只支持 mp3、wav、m4a、aac')
        return Promise.resolve()
      }
      return apply(() => putBgm(nid!, cid!, vid!, episode, file, type))
    },
    removeBgm: (episode: string) => apply(() => deleteBgm(nid!, cid!, vid!, episode)),
    /** 合成整章：配音金额大于 0 先弹确认 */
    start: () => {
      if (!preview) return
      if (preview.tts_cny > 0) setConfirm({ cny: preview.tts_cny, changed: false })
      else void send(0)
    },
    confirmNow: () => (confirm ? send(confirm.cny) : Promise.resolve()),
    cancelConfirm: () => setConfirm(null),
  }
}

export type Compose = ReturnType<typeof useCompose>
```

- [ ] **Step 2: 合成区**

Create `frontend/src/components/ComposePanel.tsx`:

```tsx
/** 「出片」页签下半部分：配音（各说话人的音色）、BGM 与选曲参考、合成整章（草稿合成、金额确认）、
 *  成片（状态、播放下载、合成报告）。
 *
 *  配音花钱：金额写在按钮上，大于 0 时先弹确认（useCompose 决定发不发请求）。
 *  不能合成时按钮禁用，原因逐条写出（composeBlockers）。 */
import { useEffect, useState } from 'react'
import { AUDIO_MODE, MOOD, label } from '../labels'
import {
  BGM_ACCEPT, composeBlockers, composeLabel, curveText, finalEpisodes, finalText, noteText,
} from '../compose'
import type { FinalEpisode } from '../compose'
import { useCompose } from '../useCompose'
import type { Compose } from '../useCompose'
import type { Film } from '../useFilm'
import type { FilmSession } from '../types'

const yuan = (n: number) => `¥${n.toFixed(2)}`

export function ComposePanel({ film, dirty }: { film: Film; dirty: boolean }) {
  const c = useCompose(film)
  const s = film.session!
  const p = c.preview
  if (!p) {
    return (
      <section className="compose">
        <h4>配音与合成</h4>
        {c.error ? <p className="tlc__kferr">{c.error}</p> : <p className="tlc__kfnote">读取合成预览…</p>}
      </section>
    )
  }
  const blockers = composeBlockers(p, s, c.voices, { dirty, gate: film.gate, draft: c.draft })
  return (
    <section className="compose">
      <div className="compose__head">
        <h4>配音与合成</h4>
        <button className="tlc__linkbtn" onClick={() => void c.load()}>刷新合成</button>
      </div>
      {c.error && <p className="tlc__kferr">{c.error}</p>}
      <Voices c={c} />
      <Music c={c} />
      {c.confirm && <ComposeConfirm s={s} c={c} blocked={blockers.length > 0} />}
      <div className="compose__run">
        <p>
          配音 {p.lines} 条{p.lines ? ` · 未缓存 ${p.tts_chars} 字 · 约 ${yuan(p.tts_cny)}` : ''}
          {p.no_video.length ? ` · ${p.no_video.length} 段还没出片` : ''}
        </p>
        <label className="check">
          <input type="checkbox" checked={c.draft} disabled={c.busy} onChange={(e) => c.setDraft(e.target.checked)} />
          草稿合成（没出的段用关键帧定格补位，没有关键帧用黑场）
        </label>
        {blockers.map((b) => <p key={b} className="tlc__notice">{b}</p>)}
        <button className="btn btn--sm" disabled={!!blockers.length || c.busy} onClick={c.start}>
          {composeLabel(p)}
        </button>
      </div>
      {p.final && <Final c={c} />}
    </section>
  )
}

/** 各说话人的音色：缺音色的展开并标红；选「按提示默认」恢复默认 */
function Voices({ c }: { c: Compose }) {
  const v = c.voices
  if (!c.preview!.lines) return <p className="tlc__kfnote">这个声音模式下没有要配音的语音条。</p>
  if (!v) return <p className="tlc__kfnote">读取音色表…</p>
  const name = (id: string | null) => v.voices.find((x) => x.id === id)?.name ?? id ?? ''
  return (
    <details className="compose__box" open={v.missing.length > 0}>
      <summary>音色 · {v.provider}{v.missing.length ? ` · 缺 ${v.missing.length} 个` : ''}</summary>
      <table className="compose__table">
        <tbody>
          {v.speakers.map((sp) => (
            <tr key={sp.key} className={sp.voice ? '' : 'is-missing'}>
              <td>{sp.name}{sp.hint && <span className="film__dim">（{sp.hint}）</span>}</td>
              <td>
                <select aria-label={`${sp.name} 的音色`} value={sp.chosen ?? ''} disabled={c.busy}
                        onChange={(e) => void c.setVoice(sp.key, e.target.value)}>
                  <option value="">
                    {sp.chosen ? '按提示默认' : sp.voice ? `默认：${name(sp.voice)}` : '请选择音色'}
                  </option>
                  {v.voices.map((x) => (
                    <option key={x.id} value={x.id}>{x.name}（{x.gender === 'male' ? '男' : '女'}）</option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="tlc__kfnote">音色只存在这次出片里，不改分镜。费率依据：{v.rate_note || '厂商未注明'}。</p>
    </details>
  )
}

/** 每集 BGM：上传 / 换一段 / 删除；分镜的选曲参考 */
function Music({ c }: { c: Compose }) {
  const p = c.preview!
  const eps = Object.entries(p.music)
  return (
    <details className="compose__box">
      <summary>BGM · 已上传 {p.bgm.length} / {eps.length} 集</summary>
      {eps.map(([ep, m]) => {
        const has = p.bgm.includes(ep)
        return (
          <div key={ep} className="compose__ep">
            <div className="compose__eprow">
              <b>{ep}</b>
              {has ? <span>已上传</span> : <span className="film__dim">没有 BGM</span>}
              <label className="tlc__linkbtn">
                {has ? '换一段' : '上传'}
                <input type="file" hidden accept={BGM_ACCEPT} aria-label={`${ep} 的 BGM`} disabled={c.busy}
                       onChange={(e) => {
                         const f = e.target.files?.[0]
                         e.target.value = ''
                         if (f) void c.uploadBgm(ep, f)
                       }} />
              </label>
              {has && (
                <button className="tlc__linkbtn" disabled={c.busy} onClick={() => void c.removeBgm(ep)}>删除</button>
              )}
            </div>
            {(m.mood || m.style_hint) && (
              <p className="film__dim">{[label(MOOD, m.mood), m.style_hint ?? ''].filter(Boolean).join(' · ')}</p>
            )}
            {!!m.curve?.length && (
              <ul className="compose__curve">{m.curve.map((seg, i) => <li key={i}>{curveText(seg)}</li>)}</ul>
            )}
          </div>
        )
      })}
      <p className="tlc__kfnote">每集一段（mp3 / wav / m4a / aac，≤ 30MB），合成时循环铺满，有人声时自动压低；选曲参考来自分镜。</p>
    </details>
  )
}

/** 成片：状态、失败时的 ffmpeg 输出、各集播放与下载、合成报告 */
function Final({ c }: { c: Compose }) {
  const f = c.preview!.final!
  const r = c.preview!.report
  const eps = finalEpisodes(f.files)
  const [open, setOpen] = useState<string | null>(null)
  const sel = eps.find((e) => e.episode === open)
  const { ensure } = c
  useEffect(() => {
    ensure(sel?.video)
    ensure(sel?.srt)
  }, [sel?.video, sel?.srt, ensure])
  const tone = f.state === 'failed' ? 'tlc__kferr' : f.stale ? 'tlc__notice' : 'tlc__kfnote'
  return (
    <section className="compose__final">
      <p className={tone}>{finalText(f)}</p>
      {f.state === 'failed' && f.detail && (
        <details>
          <summary>ffmpeg 输出</summary>
          <pre className="film__prompt">{f.detail}</pre>
        </details>
      )}
      {!!eps.length && f.state !== 'done' && (
        <p className="film__dim">下面是上一次合成的成片{f.stale ? '（已过期）' : ''}。</p>
      )}
      {!!eps.length && (
        <table className="compose__table">
          <tbody>
            {eps.map((e) => {
              const rep = r?.episodes.find((x) => x.episode === e.episode)
              return (
                <tr key={e.episode}>
                  <td><b>{e.episode}</b></td>
                  <td>{rep ? `${rep.seconds.toFixed(1)} 秒` : ''}</td>
                  <td><button className="tlc__linkbtn" onClick={() => setOpen(e.episode)}>播放 / 下载</button></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {sel && <EpisodeFiles c={c} e={sel} />}
      {r && (
        <details className="compose__box">
          <summary>合成报告</summary>
          <p>{r.size} · {label(AUDIO_MODE, r.audio_mode)}{r.draft ? ' · 草稿合成' : ''}</p>
          {r.warning && <p className="tlc__notice">{r.warning}</p>}
          <p className="film__dim">{r.alignment}</p>
          {r.episodes.map((x) => (
            <div key={x.episode} className="compose__ep">
              <b>{x.episode}</b>
              {!!x.placeholders.length && <p>补位（关键帧或黑场）：{x.placeholders.join('、')}</p>}
              {!!x.stale.length && <p>用的是过期的段：{x.stale.join('、')}</p>}
              {x.notes.map((n, i) => <p key={i}>{noteText(n)}</p>)}
              {!x.placeholders.length && !x.stale.length && !x.notes.length && (
                <p className="film__dim">声画都对得上，没有调整。</p>
              )}
            </div>
          ))}
        </details>
      )}
    </section>
  )
}

/** 一集的成片播放与下载（文件取回成 blob 后才有链接） */
function EpisodeFiles({ c, e }: { c: Compose; e: FinalEpisode }) {
  const video = c.url(e.video)
  const srt = c.url(e.srt)
  return (
    <div className="compose__play">
      {e.video && (video
        ? <video className="film__video" src={video} controls />
        : <p className="tlc__kfnote">读取成片…</p>)}
      <div className="tlc__kfacts">
        {video && <a className="btn btn--sm" href={video} download={`${e.episode}.mp4`}>下载 {e.episode}.mp4</a>}
        {srt && <a className="btn btn--sm btn--ghost" href={srt} download={`${e.episode}.srt`}>下载字幕</a>}
      </div>
    </div>
  )
}

/** 配音花钱前的确认：配音金额、已花、执行后累计与上限、费率依据 */
function ComposeConfirm({ s, c, blocked }: { s: FilmSession; c: Compose; blocked: boolean }) {
  const cf = c.confirm!
  const after = Math.round((s.spent_cny + cf.cny) * 100) / 100
  const over = after > s.budget_cny + 1e-9
  return (
    <section className="film__confirm" role="dialog" aria-label="确认配音金额">
      <h4>合成整章</h4>
      {cf.changed && <p className="tlc__kferr">配音金额已变为 {yuan(cf.cny)}，请重新确认。</p>}
      <p>
        配音 <b>{yuan(cf.cny)}</b>（未缓存的 {c.preview!.tts_chars} 字）· 已花 {yuan(s.spent_cny)}
        {' '}· 执行后累计 {yuan(after)} / 上限 {yuan(s.budget_cny)}
      </p>
      {over && <p className="tlc__kferr">会超过上限，服务端会拒绝：先在设置里调高上限。</p>}
      <p className="tlc__kfnote">
        费率依据：{c.voices?.rate_note || '厂商未注明'}。合成本身不花钱；实际以厂商控制台账单为准。
      </p>
      <div className="tlc__kfacts">
        <button className="btn btn--sm" disabled={c.busy || over || blocked} onClick={() => void c.confirmNow()}>
          确认合成（{yuan(cf.cny)}）
        </button>
        <button className="btn btn--sm btn--ghost" onClick={c.cancelConfirm}>取消</button>
      </div>
    </section>
  )
}
```

- [ ] **Step 3: 挂进「出片」页签**

In `frontend/src/components/FilmPanel.tsx`:

(a) Add the import after `import type { Film } from '../useFilm'`:

```tsx
import { ComposePanel } from './ComposePanel'
```

(b) In `FilmPanel`'s JSX, right after the `{clip ? <ClipDetail … /> : <p className="tlc__kfnote">点「成片」泳道上的一段看详情、重做或换用别的一次。</p>}` expression (still inside the `<>…</>` fragment), add:

```tsx
          <ComposePanel film={film} dirty={dirty} />
```

(c) In `Overview`, change the text `'没有要出的段了；配音与合成整章在下一步。'` to `'各段都出完了：在下面「配音与合成」合成整章。'`.

(d) Update the file's top comment first line to: `/** 画布侧栏「出片」页：设置、前置检查、总览与主按钮、选中段详情、花钱前的确认框，最后是配音与合成（ComposePanel）。`

- [ ] **Step 4: 样式**

In `frontend/src/index.css`, after the line `.film__confirm h4 { margin: 0; }`, add:

```css
.compose { border-top: 1px solid var(--line-2); padding-top: 10px; }
.compose__head { display: flex; align-items: baseline; justify-content: space-between; }
.compose__head h4 { margin: 0; }
.compose__box { border: 1px solid var(--line-2); border-radius: 6px; padding: 6px 8px; }
.compose__box summary { cursor: pointer; color: var(--muted); }
.compose__table { border-collapse: collapse; font-size: 12px; }
.compose__table td { padding: 2px 8px 2px 0; }
.compose__table tr.is-missing td:first-child { color: var(--danger); }
.compose__ep { display: flex; flex-direction: column; gap: 2px; margin-top: 6px; }
.compose__eprow { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; }
.compose__curve { margin: 0; padding-left: 16px; font-size: 11.5px; color: var(--muted); }
.compose__run, .compose__final, .compose__play { display: flex; flex-direction: column; gap: 6px; }
```

- [ ] **Step 5: 现有出片测试的桩后端**

`ComposePanel` 一挂上就会请求合成预览。现有 `tests/film.test.tsx` 的桩后端没有合成接口，并且有断言看「最后一次调用」，所以让合成接口回 404 且不记进 `calls`。In `frontend/tests/film.test.tsx`, in `g.fetch`, right after the line

```ts
  const sub = path.slice(R.length)
```

insert:

```ts
  // 配音与合成由 compose.test.tsx 覆盖：这里回 404，也不记进 calls（免得打乱「最后一次调用」的断言）
  if (sub.startsWith('/compose') || sub.startsWith('/voices')) return fail(404, '还没有出片会话')
```

- [ ] **Step 6: 运行，确认通过**

Run: `npm test 2>&1 | grep -E "ALL PASS|✗|error" ; npm run lint 2>&1 | tail -3`
Expected: nine `ALL PASS`, no `✗`/error; lint 0 errors（只有已有的 warning）

- [ ] **Step 7: 提交**

```bash
git add src/useCompose.ts src/components/ComposePanel.tsx src/components/FilmPanel.tsx src/index.css tests/film.test.tsx
git commit -m "画布配音与合成区：各说话人音色、每集 BGM 上传与选曲参考、草稿合成、合成整章（配音金额先确认、409 换新金额再确认）、合成中轮询、失败原因与 ffmpeg 输出、成片过期提示、每集播放与下载、合成报告"
```

---

### Task 4: 合成区界面回归测试

**Files:**
- Modify (replace whole file): `frontend/tests/compose.test.tsx`

- [ ] **Step 1: 写测试**

Replace the whole content of `frontend/tests/compose.test.tsx` with:

```tsx
/** 配音与合成：纯计算（能不能合成及原因、状态文字、成片分组、对齐说明、选曲参考、BGM 类型、按钮文字、重读时机），
 *  以及「出片」页签里合成区的界面回归：缺音色拦截与选音色、没装 ffmpeg 的提示、配音金额先确认与 409 换新金额、
 *  合成中、完成后播放下载与报告、过期、失败、草稿合成开关、BGM 上传删除、未保存拦截、不配音的模式。
 *  桩后端在内存里模拟合成预览（后台合成的推进由测试直接改状态）。跑法：npm test
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

import {
  bgmType, composeBlockers, composeKey, composeLabel, composing, curveText, finalEpisodes, finalText, noteText,
} from '../src/compose'
import type {
  ComposePreview, FilmClip, FilmSession, FinalState, MixReport, Storyboard, VoicesInfo,
} from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

/* ---------- 纯计算 ---------- */
{
  const P: ComposePreview = {
    lines: 3, tts_chars: 30, tts_cny: 0.01, missing_voices: ['C09'], voices: { narration: 'fake-male' },
    no_video: ['E01-C02'], fingerprint: 'fp', final: null, bgm: [], tools: true, music: {}, report: null,
  }
  const S = {
    audio_mode: 'tts_all', resolution: '720p', budget_cny: 200, spent_cny: 10, voices: {}, final: null,
    clips: [{ id: 'E01-C01', state: 'done', chosen: 0, mute_native: false },
            { id: 'E01-C02', state: 'planned', chosen: null, mute_native: false }],
  } as unknown as FilmSession
  const V: VoicesInfo = {
    provider: 'fake', rate_note: '假配音', voices: [{ id: 'fake-male', name: '假男声', gender: 'male' }],
    speakers: [{ key: 'C09', name: '路人', hint: null, voice: null, chosen: null }], missing: ['C09'],
  }
  const base = { dirty: false, gate: null, draft: true }

  must(composeBlockers(P, S, V, base).join('|') === '还有 1 个说话人没选音色：路人', '缺音色写说话人名字')
  must(composeBlockers({ ...P, missing_voices: [] }, S, V, base).length === 0, '草稿合成时缺段不拦')
  must(composeBlockers({ ...P, missing_voices: [] }, S, V, { ...base, draft: false })[0]
    .startsWith('1 段还没有可用的视频'), '关掉草稿合成时缺段要拦')
  const all = composeBlockers({ ...P, tools: false, tts_cny: 500, missing_voices: [] },
    { ...S, clips: [{ ...S.clips[0], state: 'running' }] } as FilmSession, V,
    { dirty: true, gate: '分镜未通过独立验证', draft: true })
  must(all.length === 5 && all[0].includes('先保存再合成') && all[1].includes('分镜未通过独立验证')
    && all[2].includes('apt install ffmpeg') && all[3].includes('排队或生成中') && all[4].includes('超过上限'),
    `各种拦截按顺序列出：${all.join(' / ')}`)
  const busy: FinalState = { state: 'running', step: '混音 E01', files: [], report: null, error: null, detail: null }
  must(composing({ ...P, final: busy }) && !composing(P), '合成中')
  must(composeBlockers({ ...P, missing_voices: [], final: busy }, S, V, base)[0] === '正在合成，等它结束再合成',
    '合成中不能再合成')
  console.log('1. 能不能合成及原因 ✓')

  must(finalText(busy) === '合成中 · 混音 E01', '合成中写步骤')
  must(finalText({ ...busy, state: 'failed', error: '混音 E01 失败' }) === '合成失败：混音 E01 失败', '失败写原因')
  must(finalText({ ...busy, state: 'done', stale: false }) === '成片是最新的', '最新')
  must(finalText({ ...busy, state: 'done', stale: true }).startsWith('成片已过期'), '过期')
  const eps = finalEpisodes(['final/E01.mp4', 'final/E01.srt', 'final/E02.mp4', 'final/mix_report.json'])
  must(JSON.stringify(eps) === JSON.stringify([
    { episode: 'E01', video: 'final/E01.mp4', srt: 'final/E01.srt' }, { episode: 'E02', video: 'final/E02.mp4' }]),
    '成片按集分组')
  console.log('2. 成片状态与分组 ✓')

  must(noteText({ shot: 'S2', kind: 'speedup', speed: 1.1 }) === 'S2：语速提到 1.1×', '提速说明')
  must(noteText({ shot: 'S3', kind: 'freeze', speed: 1.15, extend: 0.61 })
    === 'S3：按 1.15× 念仍超出镜头，段尾定格延长 0.61 秒', '定格说明')
  must(curveText({ from_shot: 'E01-SH001', to_shot: 'E01-SH010', mood: 'calm', intensity: 'low', note: '秋夜' })
    === 'E01-SH001–E01-SH010 · 平静 · 弱 · 秋夜', '选曲参考')
  must(curveText({ mood: 'tense' }) === '紧张', '选曲参考缺项')
  console.log('3. 对齐说明与选曲参考 ✓')

  must(bgmType({ name: 'a.mp3', type: 'audio/mpeg' }) === 'audio/mpeg', '浏览器给的类型')
  must(bgmType({ name: 'b.M4A', type: '' }) === 'audio/mp4', '没有类型按扩展名')
  must(bgmType({ name: 'c.wav', type: 'audio/x-wav' }) === 'audio/x-wav', 'x-wav 也认')
  must(bgmType({ name: 'd.txt', type: 'text/plain' }) === null, '不是音频')
  must(composeLabel(P) === '合成整章（配音约 ¥0.01）' && composeLabel({ ...P, tts_cny: 0 }) === '合成整章（不花钱）',
    '按钮写金额')
  const k1 = composeKey(S)
  must(composeKey({ ...S, voices: { C09: 'fake-male' } } as FilmSession) !== k1
    && composeKey({ ...S, clips: [S.clips[0], { ...S.clips[1], state: 'done' }] } as FilmSession) !== k1
    && composeKey({ ...S, spent_cny: 99 } as FilmSession) === k1, '音色、段状态变了才重读；已花变了不重读')
  console.log('4. BGM 类型、按钮文字、重读时机 ✓')
}

/* ---------- 界面：桩后端 ---------- */
const doc: Storyboard = JSON.parse(
  readFileSync('../backend/tests/real_text_yao/output_merged.json', 'utf8'))
const R = '/novels/n1/chapters/c1/versions/v1/render'
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))
/** 每次合成相关请求记一行：`方法 子路径 请求体`（BGM 记 Content-Type） */
const calls: string[] = []
let nextConflict: number | null = null

/** 每集两镜一段；最后一段还没出片 */
function makeSession(): FilmSession {
  const clips: FilmClip[] = []
  for (const ep of doc.episodes) {
    for (let i = 0; i < ep.shots.length; i += 2) {
      const id = `${ep.id}-C${String(clips.length + 1).padStart(2, '0')}`
      clips.push({
        id, episode: ep.id, shots: ep.shots.slice(i, i + 2).map((s) => s.id), duration: 5, truncated: false,
        prompt: '提示词', refs: [], dropped_refs: [], missing_refs: [], first_frame: null, frame_mode: null,
        fingerprint: 'fp', estimate_cny: 5, chosen: 0, mute_native: false, uncertain: false, error: null,
        state: 'done',
        attempts: [{ task_id: 't1', state: 'succeeded', cost_cny: 5, file: `clips/${id}.t1.mp4`,
                     last_frame: null, error: null, at: '2026-10-31T03:00:00+00:00', fingerprint: 'fp',
                     first_frame_used: null }],
      })
    }
  }
  const last = clips[clips.length - 1]
  Object.assign(last, { state: 'planned', attempts: [], chosen: null })
  return {
    provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
    confirm_over_cny: 20, spent_cny: 100, voices: {}, final: null, clips, orphaned: [],
    counts: { done: clips.length - 1, planned: 1 }, remaining_cny: 5, reserved_cny: 0, uncertain_count: 0,
    options: { providers: ['fake'], models: { 'fake-1': { label: '假厂商' } }, resolutions: ['720p'],
               cny_per_sec: { '720p': 1 }, max_clip_sec: 10, max_refs: 3,
               audio_modes: ['tts_all', 'dialogue_native', 'all_native', 'silent'], rate_note: '假厂商' },
  }
}
let film = makeSession()
const lastClip = film.clips[film.clips.length - 1].id

const voicesInfo: VoicesInfo = {
  provider: 'fake', rate_note: '假配音：不联网、不花钱',
  voices: [{ id: 'fake-male', name: '假男声', gender: 'male' }, { id: 'fake-female', name: '假女声', gender: 'female' }],
  speakers: [
    { key: 'narration', name: '旁白', hint: 'male_mature', voice: 'fake-male', chosen: null },
    { key: 'C01', name: '老栓', hint: 'male_elder', voice: 'fake-male', chosen: null },
    { key: 'C09', name: '路人', hint: null, voice: null, chosen: null },
  ],
  missing: ['C09'],
}
const preview: ComposePreview = {
  lines: 40, tts_chars: 600, tts_cny: 0.18, missing_voices: ['C09'],
  voices: { narration: 'fake-male', C01: 'fake-male' }, no_video: [lastClip], fingerprint: 'fp1', final: null,
  bgm: [], tools: true,
  music: Object.fromEntries(doc.episodes.map((ep) => [ep.id, ep.music ?? {}])), report: null,
}
const REPORT: MixReport = {
  audio_mode: 'tts_all', size: '720x1280', draft: true, alignment: '段内镜头切换时刻由视频模型决定，属近似对齐',
  episodes: [{ episode: 'E01', seconds: 61.5, placeholders: [], stale: [],
               notes: [{ shot: 'E01-SH002', kind: 'speedup', speed: 1.1 },
                       { shot: 'E01-SH003', kind: 'freeze', speed: 1.15, extend: 0.61 }] },
             { episode: 'E04', seconds: 40, placeholders: [lastClip], stale: [], notes: [] }],
}
const FILES = ['final/E01.mp4', 'final/E01.srt', 'final/E04.mp4', 'final/E04.srt']

const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => clone(data) })
const fail = (status: number, detail: unknown) =>
  ({ ok: false, status, statusText: '', text: async () => JSON.stringify({ detail }) })

g.fetch = async (url: string, init?: { method?: string; body?: unknown; headers?: Record<string, string> }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  if (path === '/render/keyframes') return ok({ keyframes: [] })
  if (path === '/novels/n1/chapters/c1/versions/v1/keyframes') return ok({ shots: [] })
  if (!path.startsWith(R)) throw new Error(`桩后端未实现的路径: ${method} ${path}`)
  const sub = path.slice(R.length)
  if (sub === '/session' && method === 'GET') {
    calls.push('GET /session')
    return ok({ ...film, gate: { ok: true, message: null } })
  }
  if (sub.startsWith('/files/')) {
    calls.push(`GET ${sub}`)
    return { ok: true, status: 200,
             blob: async () => new Blob(['x'], { type: sub.endsWith('.mp4') ? 'video/mp4' : 'text/plain' }) }
  }
  const m = sub.match(/^\/bgm\/([^/]+)$/)
  if (m) {
    const ep = decodeURIComponent(m[1])
    if (method === 'PUT') {
      calls.push(`PUT /bgm/${ep} ${init?.headers?.['Content-Type']}`)
      if (!preview.bgm.includes(ep)) preview.bgm.push(ep)
      return ok({ episode: ep, bytes: 3 })
    }
    calls.push(`DELETE /bgm/${ep}`)
    preview.bgm = preview.bgm.filter((x) => x !== ep)
    return ok({ deleted: ep })
  }
  const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
  calls.push(`${method} ${sub}${body === undefined ? '' : ` ${JSON.stringify(body)}`}`)
  if (sub.startsWith('/compose') && method === 'GET') {
    const draft = new URL(`http://x${sub}`).searchParams.get('draft') !== 'false'
    return ok({ ...preview, fingerprint: draft ? 'fp1' : 'fp1-nodraft' })
  }
  if (sub === '/voices' && method === 'GET') return ok(voicesInfo)
  if (sub === '/voices' && method === 'PUT') {
    for (const [k, v] of Object.entries(body.voices as Record<string, string>)) {
      const sp = voicesInfo.speakers.find((x) => x.key === k)!
      sp.chosen = v || null
      sp.voice = v || (sp.hint ? 'fake-male' : null)
    }
    voicesInfo.missing = voicesInfo.speakers.filter((x) => !x.voice).map((x) => x.key)
    preview.missing_voices = [...voicesInfo.missing]
    film = { ...film, voices: Object.fromEntries(voicesInfo.speakers.filter((x) => x.chosen).map((x) => [x.key, x.chosen!])) }
    return ok(voicesInfo)
  }
  if (sub === '/compose' && method === 'POST') {
    if (nextConflict !== null) {
      preview.tts_cny = nextConflict
      nextConflict = null
      return fail(409, { message: `本次配音约 ¥${preview.tts_cny.toFixed(2)}，请确认金额后再合成`,
                         expected_cny: preview.tts_cny })
    }
    if (body.expected_cny !== preview.tts_cny) {
      return fail(409, { message: '请确认金额后再合成', expected_cny: preview.tts_cny })
    }
    const f: FinalState = { state: 'running', step: '开始', files: [], report: null, error: null, detail: null,
                            draft: body.draft, started_at: '2026-10-31T04:00:00+00:00' }
    preview.final = { ...f, stale: false }
    film = { ...film, final: f }
    return ok(film)
  }
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}

const { act, useState } = await import('react')
const { createRoot } = await import('react-dom/client')
const { StoryboardView } = await import('../src/components/StoryboardView')

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
const change = async (el: Element, set: () => void) => {
  await act(async () => {
    set()
    el.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
const tab = (name: string) =>
  [...container.querySelectorAll('.tlc__tabs button')].find((b) => b.textContent === name)
const refresh = () => click(button('刷新合成'))
const composeBtn = () => button('合成整章')
const since = (n: number) => calls.slice(n)

let setDirty: (v: boolean) => void = () => {}
function Host() {
  const [dirty, set] = useState(false)
  setDirty = set
  return <StoryboardView doc={doc} canSave dirty={dirty} saving={false} version={{ nid: 'n1', cid: 'c1', vid: 'v1' }}
                         onChange={() => set(true)} onSave={() => set(false)} />
}

// 5. 打开「出片」页签：合成区读预览与音色表；缺音色时按钮禁用并写出说话人；选曲参考来自分镜
await act(async () => { root.render(<Host />) })
await click(button('时间轴画布'))
await click(tab('出片')!)
await settle()
must(calls.includes('GET /compose?draft=true') && calls.includes('GET /voices'), '读合成预览与音色表')
must(has('配音与合成') && has('配音 40 条 · 未缓存 600 字 · 约 ¥0.18') && has('1 段还没出片'), '预览数字')
must(has('还有 1 个说话人没选音色：路人') && composeBtn().disabled, '缺音色拦截')
must(has('秋夜死寂'), '选曲参考来自分镜 music.curve')
console.log('5. 合成区预览与缺音色拦截 ✓')

// 6. 给路人选音色 → PUT /voices → 重读后按钮可用、写配音金额
const sel = container.querySelector('select[aria-label="路人 的音色"]') as unknown as HTMLSelectElement
await change(sel, () => { sel.value = 'fake-female' })
must(calls.includes('PUT /voices {"voices":{"C09":"fake-female"}}'), '选音色写回')
must(!has('没选音色') && !composeBtn().disabled && (composeBtn().textContent ?? '').includes('配音约 ¥0.18'),
  '选完可以合成，按钮写金额')
console.log('6. 选音色 ✓')

// 7. 服务器没装 ffmpeg：写明 macOS 与 Linux 的装法，按钮禁用
preview.tools = false
await refresh()
must(has('apt install ffmpeg') && has('brew install ffmpeg') && composeBtn().disabled, '没装 ffmpeg 的提示')
preview.tools = true
await refresh()
must(!composeBtn().disabled, '装好后恢复')
console.log('7. 没装 ffmpeg 的提示 ✓')

// 8. 合成：先弹确认（配音金额、费率依据），不发请求；服务端金额变了（409）→ 换新金额再确认 → 带新金额发请求
let n0 = calls.length
await click(composeBtn())
must(has('确认合成（¥0.18）') && has('费率依据：假配音') && !since(n0).some((c) => c.startsWith('POST')),
  '确认前不发请求')
nextConflict = 0.21
await click(button('确认合成'))
must(has('配音金额已变为 ¥0.21'), '金额变了要重新确认')
n0 = calls.length
await click(button('确认合成（¥0.21）'))
must(since(n0).includes('POST /compose {"expected_cny":0.21,"draft":true}'), '带新金额与草稿设置')
must(!has('确认合成') && has('合成中 · 开始') && has('正在合成，等它结束再合成') && composeBtn().disabled,
  '合成中：写步骤、不能再合成')
console.log('8. 配音金额确认与 409 重新确认 ✓')

// 9. 后台合成完成 → 刷新：成片是最新的；出片会话跟着重读；播放 / 下载取 blob；报告写对齐调整
preview.final = { state: 'done', step: '完成', files: FILES, report: 'final/mix_report.json', error: null,
                  detail: null, draft: true, finished_at: '2026-10-31T04:05:00+00:00', stale: false }
preview.report = REPORT
film = { ...film, final: { ...preview.final, stale: undefined }, spent_cny: 100.21 }
n0 = calls.filter((c) => c === 'GET /session').length
await refresh()
await settle()
must(has('成片是最新的'), '完成')
must(calls.filter((c) => c === 'GET /session').length > n0, '合成跑完后出片会话重读（已花变了）')
await click(button('播放 / 下载'))
await settle()
must(calls.includes('GET /files/final/E01.mp4') && calls.includes('GET /files/final/E01.srt'), '取成片与字幕')
must(!!container.querySelector('.compose__play video'), '播放成片')
const links = [...container.querySelectorAll('.compose__play a')].map((a) => a.getAttribute('download'))
must(links.includes('E01.mp4') && links.includes('E01.srt'), '下载 mp4 与字幕')
must(has('61.5 秒') && has('E01-SH002：语速提到 1.1×') && has('段尾定格延长 0.61 秒')
  && has(`补位（关键帧或黑场）：${lastClip}`), '合成报告')
console.log('9. 完成后播放、下载与报告 ✓')

// 10. 过期与失败：失败时写原因、ffmpeg 输出，并说明下面是上一次的成片
preview.final = { ...preview.final, stale: true }
await refresh()
must(has('成片已过期'), '过期提示')
preview.final = { ...preview.final, state: 'failed', error: '混音 E01 失败（ffmpeg 退出码 1）',
                  detail: 'Invalid argument', stale: false }
await refresh()
must(has('合成失败：混音 E01 失败') && has('Invalid argument') && has('下面是上一次合成的成片'), '失败')
console.log('10. 过期与失败 ✓')

// 11. 草稿合成开关：关掉后按 draft=false 重读，缺段拦截；再打开恢复
const draftBox = container.querySelector('.compose__run input[type=checkbox]') as unknown as HTMLInputElement
await act(async () => { draftBox.click() })
await settle()
must(calls.includes('GET /compose?draft=false'), '按关掉草稿合成重读')
must(has('1 段还没有可用的视频') && composeBtn().disabled, '关掉草稿合成时缺段拦截')
await act(async () => { draftBox.click() })
await settle()
must(!has('1 段还没有可用的视频') && !composeBtn().disabled, '打开后恢复')
console.log('11. 草稿合成开关 ✓')

// 12. BGM：上传（按扩展名补类型）→ 已上传 → 删除；不是音频的不发请求
const pick = async (name: string, type: string) => {
  const input = container.querySelector('input[aria-label="E01 的 BGM"]') as unknown as HTMLInputElement
  const file = new win.File(['ID3'], name, { type }) as unknown as File
  await change(input, () => { Object.defineProperty(input, 'files', { value: [file], configurable: true }) })
}
await pick('theme.mp3', '')
must(calls.includes('PUT /bgm/E01 audio/mpeg') && has('已上传 1 /'), '上传 BGM')
n0 = calls.length
await pick('notes.txt', 'text/plain')
must(has('BGM 只支持 mp3、wav、m4a、aac') && !since(n0).some((c) => c.startsWith('PUT /bgm')), '不是音频不上传')
await click(button('删除'))
must(calls.includes('DELETE /bgm/E01') && has('已上传 0 /'), '删除 BGM')
console.log('12. BGM 上传与删除 ✓')

// 13. 有未保存的修改：不能合成
await act(async () => { setDirty(true) })
await settle()
must(has('先保存再合成') && composeBtn().disabled, '未保存拦截')
await act(async () => { setDirty(false) })
await settle()
console.log('13. 未保存拦截 ✓')

// 14. 不配音的声音模式：不读音色表，按钮写「不花钱」
Object.assign(preview, { lines: 0, tts_chars: 0, tts_cny: 0, missing_voices: [], voices: {} })
n0 = calls.length
await refresh()
must(!since(n0).includes('GET /voices') && has('这个声音模式下没有要配音的语音条'), '不读音色表')
must((composeBtn().textContent ?? '').includes('不花钱'), '按钮写不花钱')
n0 = calls.length
await click(composeBtn())
must(since(n0).includes('POST /compose {"expected_cny":0,"draft":true}') && !has('确认合成'), '金额 0 不弹确认')
console.log('14. 不配音的模式 ✓')

await act(async () => { root.unmount() })
console.log('\nALL PASS')
```

- [ ] **Step 2: 运行**

Run: `npm test 2>&1 | grep -E "ALL PASS|✗|error|✓" | tail -20`
Expected: compose suite prints fourteen `✓` lines then `ALL PASS`; nine `ALL PASS` total. If a UI step fails, decide whether the test or the component is wrong against this plan's behavior (component text in Task 3 is the source of truth for strings), fix the wrong side, and report each change.

- [ ] **Step 3: 提交**

```bash
git add tests/compose.test.tsx
git commit -m "合成区界面回归：缺音色拦截与选音色、没装 ffmpeg 提示、配音金额确认与 409 重新确认、合成中、完成后播放下载与报告、过期与失败、草稿合成开关、BGM 上传删除、未保存拦截、不配音的模式"
```

---

### Task 5: 文档、设计文档写回裁定、全量回归

**Files:**
- Modify: `README.md`（「**配音与合成（后端）**」段落）
- Modify: `docs/specs/2026-10-28-video-generation-design.md`（末尾）

- [ ] **Step 1: README**

In `README.md`, in the paragraph that starts with `**配音与合成（后端）**`:
- replace `合成要 ffmpeg（`brew install ffmpeg`）。` with `合成要 ffmpeg（macOS `brew install ffmpeg`，Ubuntu / Debian `apt install ffmpeg`；部署到服务器时装在跑后端的那台机器上）。`
- replace the sentence `画布上的音色分配与合成区另见 A3b 计划。` with `画布「出片」页签最下面是「配音与合成」：选各说话人的音色、每集上传 BGM（旁边列出分镜的选曲参考）、草稿合成开关，「合成整章」按钮写配音金额（大于 0 先确认），合成完在这里播放、下载每集的 mp4 与字幕，看合成报告（提速、定格、补位）。`

- [ ] **Step 2: 设计文档写回裁定**

Append to the end of `docs/specs/2026-10-28-video-generation-design.md`:

```markdown

## 9. 实施裁定（2026-10-31，画布配音与合成界面 A3b 计划）

1. **合成区挂在「出片」页签里**，在设置、总览、段详情之后；只有建了出片会话才出现，不新增页签。
2. **有未保存的修改、验证门没过时也禁止合成**，与出片一致。
3. **配音金额为 0 时不弹确认**，按钮写「不花钱」；大于 0 先弹确认（配音金额、已花、执行后累计与上限、费率依据），409 带新金额就换上再确认，不带金额（音色刚改过、正在合成）就写原因并重读。
4. **预览随出片会话变化重读**（声音模式、分辨率、各段状态 / 采用 / 静音、音色、成片状态）；合成在跑时 3 秒一读，跑完出片会话也重读。
5. **成片文件按合成完成时间区分缓存**，重新合成后同名文件取新的，旧 blob 回收。
6. **合成失败时仍列出上一次的成片**并标明，ffmpeg 输出折叠显示。
7. **后端小改**：不配音的声音模式下 `GET /voices` 为空表、不要配音密钥；没装 ffmpeg 的提示写 macOS 与 Ubuntu / Debian 两种装法；`GET /compose` 带合成报告内容（读不到或坏了为 `null`）。
```

- [ ] **Step 3: 全量回归**

Run:
```bash
cd backend && for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py; do printf "%s: " $t; .venv/bin/python $t 2>&1 | tail -1; done
cd ../frontend && npm test 2>&1 | grep -c "ALL PASS" && npm run lint 2>&1 | tail -2
```
Expected: every backend file ends with `ALL PASS`（`test_mix_e2e.py` 是「ALL PASS（跳过：没装 ffmpeg…）」）；frontend prints `9`；lint 0 errors

- [ ] **Step 4: 提交**

```bash
git add README.md docs/specs/2026-10-28-video-generation-design.md
git commit -m "配音与合成界面文档：README 补合成区用法与服务器装 ffmpeg；设计文档写回 A3b 实施裁定"
```
