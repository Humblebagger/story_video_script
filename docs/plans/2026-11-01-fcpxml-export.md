# 导出剪辑工程（FCPXML）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 已合成的章节可以导出 zip 工程包，里面有：
- 每集一条时间轴的 `project.fcpxml`；
- 规整后的各段视频、各句配音（提速的已预渲染）、BGM；
- 字幕 srt；
- README。

这个包可以导入 Final Cut Pro 或 DaVinci Resolve 接着精修。

**Architecture:**
- **合成时记时间轴**：`render/mix.py` 的 `compose` 在写成片的同时写 `final/timeline.json`，记下实际的时间轴。
- **导出模块**：新模块 `render/export_fcpxml.py`。
  - 纯函数 `build_fcpxml` 生成 XML。
  - `export` 负责预渲染提速的配音、打 zip。
- **接口**：`server/app.py` 加一个下载接口；合成状态里加 `exportable` 和 `export_reason`。
- **前端**：⑥ 下载页加一个导出按钮。

**Tech Stack:** FastAPI（Python 3.12）、ffmpeg / ffprobe（本机已装 9.0.2）、`xml.etree`、`zipfile`；React 19、TS。

**Spec:** `docs/specs/2026-11-01-fcpxml-export-design.md`

---

## 全局约束

- **提交**：
  - 只 `git add` 具体文件，不用 `git add -A` / `git commit -a`。
  - 提交信息用中文、写成描述式，**不带任何 Claude 署名**（不要 `Co-Authored-By`、不要 `Claude-Session`）。
- **后端检查**（在 `backend/` 下执行，venv 里没有 pytest，测试脚本直接用 python 跑）。每个任务结束时，以下各脚本都要打印 `ALL PASS`：
  - `tests/render/` 下：`test_mix.py`、`test_mix_e2e.py`、`test_session.py`、`test_compose.py`
  - `tests/server/` 下：`test_render.py`、`test_novels.py`
  - 新建的：`tests/render/test_export_fcpxml.py`
- **前端检查**（在 `frontend/` 下执行）：
  - `npm test`：16 套全部通过。
  - `npm run lint`：0 error，warning 不超过 5 个。
  - `npx vite build`：成功。
- **不花钱**：导出只读本地文件、跑本地 ffmpeg，不调任何厂商。测试用 `FakeTts` 和 ffmpeg 测试源。
- **不改的行为**：
  - 合成的指纹、成片的内容、`compose` 返回的 `files` 列表都不变。
  - `test_mix.py` 和 `test_mix_e2e.py` 的现有断言不改。
- **后端报错文字**：沿用中文。
- **前端文字**：
  - 新文字进 `zh.ts` / `en.ts`。
  - 源码里注释以外不许有中文。
- **不碰**：`backend/.env`、`docs/specs/2026-10-27-commercialization-design-contract.md`。

## 实施裁定

1. **不放 DTD**：规格第 6 节要求仓库放 FCPXML 1.10 的公开 DTD，用 `xmllint` 校验。
   - 查下来，Apple 的 DTD 随 Final Cut 分发，网上没有可靠的公开下载源，放进仓库还有授权问题。
   - 改为在 `test_export_fcpxml.py` 里写结构校验函数 `check_structure(xml)`，按 FCPXML 1.10 的要求逐条检查（见 Task 2）。
   - 同一次提交里改规格第 6 节对应那条。
   - 代价：可能漏掉 DTD 才能发现的细节。用户第一次在 DaVinci 或 Final Cut 里导入时会暴露，到时再修。
2. **时间写法**：
   - 所有时间统一为 `f"{n}/30s"`（`n = round(秒 * 30)`）。`n == 0` 时写 `"0s"`。
   - 帧率取 `timeline["fps"]`，就是现在的 `mix.FPS = 30`。
3. **配音和 BGM 怎么挂**：都是连接片段（connected clip），挂在主故事线的视频段上。
   - 每句配音挂在**起点所在**的那一段（`seg.start <= t < seg.start + seg.duration`；最后一段包含终点）上，`offset = 段内偏移`（秀 `= 配音起点 - 段起点`，素材 `start` 为 0）。
   - 配音 `lane="-1"`，BGM `lane="-2"`。BGM 挂在第一段上，`offset="0s"`，`duration` 为本集总长。
   - 连接片段超出所挂段的结尾是合法的。
4. **时间轴里记的配音时长**：`speech` 每项多记 `duration`，表示**提速后**的时长，等于原时长除以 `speed`。不在 `voiced` 里的语音条不进 `speech`（现状如此，它们只进字幕）。
5. **素材时长**：`build_fcpxml(timeline, media)` 的 `media` 由 `export` 准备，键为时间轴里的原路径，值为 `{"rel": 包内相对路径, "seconds": 时长, "audio": bool, "video": bool}`。视频段和 BGM 的时长用 ffprobe 量（`mix.media_seconds`），配音用提速后文件的实测时长。
6. **可导出的判定**：`_compose_preview` 里已经算出 `final` 和它的 `stale`。在此基础上：
   - `exportable = final 存在 and final.files 非空 and not stale and (root / "final/timeline.json").is_file()`。
   - `export_reason` 取 `"none"`（还没有成片）、`"stale"`（成片已过期）、`"no_timeline"`（旧成片，需要重新合成）、`"busy"`（合成中）之一；可导出时为 `null`。
   - 前端按这个值选文案。
7. **zip 放在哪**：生成到 `final/export/<安全文件名>.zip`，每次请求重新打包，覆盖旧的。打包用临时文件写完再改名。提速配音的缓存放在 `final/export/voice/`。

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/render/mix.py` | 修改：`plan_episode` 的 `speech` 加 `duration`；新纯函数 `timeline_doc`；`compose` 写 `final/timeline.json` |
| `backend/render/export_fcpxml.py` | 新建：`build_fcpxml`（纯函数）、`readme`（纯函数）、`export`（执行） |
| `backend/server/app.py` | 修改：`GET …/render/export.zip`；合成状态加 `exportable` 和 `export_reason` |
| `backend/tests/render/test_export_fcpxml.py` | 新建：纯函数与结构校验 |
| `backend/tests/render/test_mix_e2e.py` | 修改：在末尾追加时间轴文件与导出的端到端检查 |
| `backend/tests/server/test_render.py` | 修改：接口用例 |
| `frontend/src/api.ts`、`types.ts` | 修改：`exportFcpxml`、`ComposePreview.exportable` 和 `export_reason` |
| `frontend/src/components/workflow/DownloadStep.tsx` | 修改：导出按钮 |
| `frontend/src/i18n/zh.ts`、`en.ts` | 修改 |
| `frontend/tests/workflow-ui.test.tsx` | 修改：下载页用例 |
| `docs/specs/2026-11-01-fcpxml-export-design.md` | 修改：第 6 节 DTD 那条（实施裁定 1） |

---

### Task 1: 合成时记下时间轴

**Files:**
- Modify: `backend/render/mix.py`
- Test: `backend/tests/render/test_mix.py`（纯函数部分）、`backend/tests/render/test_mix_e2e.py`（追加）

- [ ] **Step 1: 先写失败测试**：
  - **`test_mix.py`**：
    - `plan_episode` 的结果里，每条 `speech` 都有 `duration`，等于 `voiced` 时长除以 `speed`，误差小于 1e-6。
    - `timeline_doc` 能把两集计划组装成规格 4.1 的结构：`version == 1`，有 `fps`、`size`、`draft`、`bgm_db`，每集的 `segments` 里带 `file` 和 `placeholder`。
  - **`test_mix_e2e.py`**：在第一次完整合成之后追加检查：
    - `final/timeline.json` 存在。
    - 读出后：`episodes[0].segments` 的段数、`start`、`duration` 与 `plan_episode` 一致。
    - 每个 `file` 都在会话目录下真实存在。
    - `speech` 的条数等于本集已配音的语音条数。
    - 有 BGM 的集，`bgm` 指向的文件存在。
    - 在已有的「中途失败、`final/` 不变」那段之后断言：失败那次没有留下新的 `timeline.json`，旧的文件内容不变。
- [ ] **Step 2: 跑一下，确认失败**。
- [ ] **Step 3: 实现**：
  - **`plan_episode`**：往 `speech` 里追加时多写 `"duration": round(dur, 3)`。`dur` 是现有的提速后时长变量。
  - **新纯函数**：

```python
def timeline_doc(plans: list, *, size: tuple, draft: bool) -> dict:
    """导出用的时间轴记录（final/timeline.json）。plans：每集 {"plan", "files", "placeholders", "bgm"}，
    files 为各段规整后文件的会话内相对路径（与 plan["segments"] 一一对应）。不进合成指纹。"""
    return {"version": 1, "fps": FPS, "size": list(size), "draft": draft, "bgm_db": BGM_DB,
            "episodes": [{"episode": p["plan"]["episode"], "total": p["plan"]["total"],
                          "segments": [dict(seg, file=f, placeholder=seg["clip"] in p["placeholders"])
                                       for seg, f in zip(p["plan"]["segments"], p["files"])],
                          "speech": p["plan"]["speech"], "bgm": p["bgm"]}
                         for p in plans]}
```

  - **`compose`**：
    - 每集循环里，把 `segs` 转成相对会话目录 `root` 的 POSIX 路径（`Path(x).relative_to(root).as_posix()`）。
    - 语音文件 `speech[].file` 也转成相对路径。转不了（不在 `root` 下）就原样保留绝对路径，并在代码注释里说明原因。
    - BGM：存在就记相对路径，没有就是 `None`。
    - 收集进 `plans`。
    - 所有集都成功之后，把 `json.dumps(timeline_doc(...), ensure_ascii=False, indent=2)` 写进 `nxt / "timeline.json"`，和 `mix_report.json` 一起挪进 `final/`。
    - 返回值里的 `files` **不加**这个文件。
- [ ] **Step 4:** 后端各项检查通过。
- [ ] **Step 5: 提交**

```bash
git add backend/render/mix.py backend/tests/render/test_mix.py backend/tests/render/test_mix_e2e.py
git commit -m "合成时记下实际时间轴（各段规整后文件、配音起点与提速后时长、BGM、画面尺寸与帧率）写进 final/timeline.json，供导出剪辑工程；不进合成指纹、不进成片列表"
```

---

### Task 2: FCPXML 纯函数与结构校验

**Files:**
- Create: `backend/render/export_fcpxml.py`（这一步只写纯函数部分）、`backend/tests/render/test_export_fcpxml.py`
- Modify: `docs/specs/2026-11-01-fcpxml-export-design.md`（第 6 节，实施裁定 1）

- [ ] **Step 1: 先写失败测试**（`test_export_fcpxml.py`，`main()` 最后打印 `ALL PASS`，写法同其他测试脚本）：
  - **手写一份时间轴**：两集。
    - E01：三段（0–6.2、6.2–10、10–14.5）；两句配音（起点 0.4、6.5，时长 3.0、2.1），第二句 `speed` 1.1；BGM `bgm/E01.mp3`。
    - E02：一段，无配音，无 BGM。
  - **`media`** 按实施裁定 5 手写。
  - **`check_structure(xml: str) -> list[str]`**（写在测试文件里，返回问题列表，空表示通过）逐条检查：
    1. 根元素是 `fcpxml`，`version == "1.10"`；子元素依次是 `resources`、`library`。
    2. `resources` 里恰好一个 `format`：`frameDuration == "1/30s"`，`width` / `height` 与 `size` 一致。
    3. 每个 `asset` 有 `id`、`name`、`start`、`duration`、`hasVideo`、`hasAudio`；子元素 `media-rep` 的 `kind == "original-media"`，`src` 是相对路径（不以 `/`、`file:` 开头）。
    4. 所有时间属性（`offset`、`start`、`duration`、`tcStart`）都匹配 `^(0s|\d+/30s)$`。
    5. `library` → 一个 `event` → 每集一个 `project`，`project` → `sequence`（`format` 引用存在的 `format` id，`duration` 等于本集总帧数）→ `spine`。
    6. `spine` 里的 `asset-clip`：
       - `offset` 连续：每一段的 `offset` 等于上一段的 `offset` 加 `duration`，第一段是 `0s`；
       - `ref` 都指向存在的 `asset`。
    7. 连接片段（`asset-clip` 下的 `asset-clip`）都有 `lane`，`ref` 存在。
  - **用例**：
    - `check_structure(build_fcpxml(tl, media)) == []`。
    - E01 第二句配音挂在第二段上：`offset == "9/30s"`（6.5 − 6.2 = 0.3 秒，即 9 帧），`lane == "-1"`，`duration == "63/30s"`（2.1 秒）。
    - BGM 挂在 E01 第一段上：`lane == "-2"`，`offset == "0s"`，`duration` 为 14.5 秒（435 帧），带 `adjust-volume amount="-14dB"`。
    - E02 的 `project` 里没有连接片段。
    - 结构校验确实能抓错：对生成结果做两处破坏（某段 `offset` 改错；某个 `src` 改成 `/abs/x.mp4`），各自返回非空。
    - `readme(timeline, title)`：包含中文和英文两段；有占位段时列出占位段 ID；包含「srt」和「LUFS」字样。
- [ ] **Step 2: 跑一下，确认失败**。
- [ ] **Step 3: 实现**（`export_fcpxml.py`）：

```python
"""导出剪辑工程（FCPXML 1.10）：纯函数生成 XML 与说明；export 负责预渲染提速配音、打包。"""
import xml.etree.ElementTree as ET


def tc(sec: float, fps: int = 30) -> str:
    n = round(sec * fps)
    return "0s" if n == 0 else f"{n}/{fps}s"


def build_fcpxml(timeline: dict, media: dict, *, event: str = "Storyboard") -> str:
    fps = timeline["fps"]
    w, h = timeline["size"]
    root = ET.Element("fcpxml", version="1.10")
    res = ET.SubElement(root, "resources")
    ET.SubElement(res, "format", id="r1", frameDuration=f"1/{fps}s", width=str(w), height=str(h))
    ids = {}
    def asset(path: str) -> str:
        if path not in ids:
            m = media[path]
            ids[path] = f"a{len(ids) + 1}"
            a = ET.SubElement(res, "asset", id=ids[path], name=m["rel"].rsplit("/", 1)[-1].rsplit(".", 1)[0],
                              start="0s", duration=tc(m["seconds"], fps),
                              hasVideo="1" if m["video"] else "0", hasAudio="1" if m["audio"] else "0")
            if m["video"]:
                a.set("format", "r1")
            if m["audio"]:
                a.set("audioSources", "1"); a.set("audioChannels", "2"); a.set("audioRate", "48000")
            ET.SubElement(a, "media-rep", kind="original-media", src=m["rel"])
        return ids[path]
    lib = ET.SubElement(root, "library")
    ev = ET.SubElement(lib, "event", name=event)
    for ep in timeline["episodes"]:
        proj = ET.SubElement(ev, "project", name=ep["episode"])
        seq = ET.SubElement(proj, "sequence", format="r1", duration=tc(ep["total"], fps), tcStart="0s",
                            tcFormat="NDF", audioLayout="stereo", audioRate="48k")
        spine = ET.SubElement(seq, "spine")
        clips = []
        for seg in ep["segments"]:
            c = ET.SubElement(spine, "asset-clip", ref=asset(seg["file"]), name=seg["clip"],
                              offset=tc(seg["start"], fps), start="0s", duration=tc(seg["duration"], fps),
                              format="r1", tcFormat="NDF")
            clips.append((seg, c))
        for sp in ep["speech"]:
            seg, parent = next(((s, c) for s, c in clips if s["start"] <= sp["start"] < s["start"] + s["duration"]),
                               clips[-1])
            ET.SubElement(parent, "asset-clip", ref=asset(sp["file"]), name=sp["line"], lane="-1",
                          offset=tc(sp["start"] - seg["start"], fps), start="0s", duration=tc(sp["duration"], fps))
        if ep.get("bgm") and clips:
            b = ET.SubElement(clips[0][1], "asset-clip", ref=asset(ep["bgm"]), name=f"BGM {ep['episode']}",
                              lane="-2", offset="0s", start="0s", duration=tc(ep["total"], fps))
            ET.SubElement(b, "adjust-volume", amount=f"{timeline['bgm_db']}dB")
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode") + "\n"
```

  - **注意**：
    - 段内偏移要按帧取整：`tc(sp["start"] - seg["start"])`。不要分别取整再相减，否则会差一帧。
    - 提速配音的 `media` 键：`export` 会把 `sp["file"]` 换成预渲染后的路径，`build_fcpxml` 不关心。
  - **`readme(timeline: dict, title: str) -> str`**：中文、英文各一段，内容是：
    - Final Cut Pro 导入：文件 → 导入 → XML。
    - DaVinci Resolve 导入：文件 → 导入 → 时间线。
    - 素材离线时，把整个 `media/` 文件夹重新链接上。
    - 字幕在 `subtitles/*.srt`，要手动导入。
    - 最终导出时自己做响度归一，目标 −16 LUFS。
    - 有占位段时，列出「这些段用的是关键帧静帧占位：E01/K03 …」。
- [ ] **Step 4:** 按实施裁定 1，把规格第 6 节「DTD 校验」那条改为「结构校验（见实施计划实施裁定 1）」。
- [ ] **Step 5:** 新测试通过，后端其他检查照常通过。
- [ ] **Step 6: 提交**

```bash
git add backend/render/export_fcpxml.py backend/tests/render/test_export_fcpxml.py docs/specs/2026-11-01-fcpxml-export-design.md
git commit -m "FCPXML 1.10 生成：每集一条时间轴，视频段在主故事线，配音与 BGM 为连接片段（BGM -14dB），时间按帧对齐；中英文导入说明；测试内置结构校验代替 DTD"
```

---

### Task 3: 导出执行（提速配音预渲染与打包）

**Files:**
- Modify: `backend/render/export_fcpxml.py`
- Test: `backend/tests/render/test_mix_e2e.py`（在 Task 1 追加的检查之后）

- [ ] **Step 1: 先写失败测试**（`test_mix_e2e.py`，没装 ffmpeg 时与现有部分一样跳过）：
  - 第一次完整合成之后，调用 `export_fcpxml.export(root, title="药-第一章-v1", tools=mix.tools())`，拿到 zip 路径。
  - zip 里有 `药-第一章-v1/project.fcpxml`、`README.txt`、`subtitles/E01.srt`。fcpxml 里每个 `media-rep src` 都能在 zip 里找到（前面加顶层目录）。
  - 把测试里的 `check_structure` 抽到 `tests/render/fcpxml_check.py`，两个测试共用，解压出的 fcpxml 校验结果为 `[]`。
  - 构造一条 `speed > 1` 的配音：沿用测试里已有的「语音过长、触发提速」的夹具；没有就加一镜很长的旁白。导出的 `media/voice/` 里，它的时长（用 `mix.media_seconds` 量）约等于原时长除以 `speed`，误差不超过 0.05 秒。
  - 再导出一次：提速缓存（`final/export/voice/` 下的文件）的修改时间不变（没有重做），zip 被覆盖。
  - 删掉 `final/timeline.json` 后再导出，抛出 `ExportError`，消息里有「重新合成」。
- [ ] **Step 2: 跑一下，确认失败**。
- [ ] **Step 3: 实现**：
  - `class ExportError(Exception)`。
  - `export(root, *, title: str, tools: tuple) -> Path`：
    1. 读 `root/final/timeline.json`。没有就 `raise ExportError("这份成片是旧版合成的，重新合成一次即可导出（会复用已有配音与规整结果，不花钱）")`。
    2. **组装 `media`**：
       - 视频段：`rel = f"media/clips/{ep}-{clip}.mp4"`；`video`、`audio` 都为真（规整后的段一定有音轨，`normalize_cmd` 会补静音，写之前确认这一点）。
       - 配音：`speed == 1` 时直接用原文件；否则用 `ffmpeg -i src -filter:a atempo=<speed> -ar 48000 <cache>`，缓存名是 `sha256(源文件路径 + 大小 + 修改时间 + speed)[:16].wav`，已存在就跳过。`rel = f"media/voice/{line}.wav"`。
       - BGM：`rel = f"media/bgm/{ep}{后缀}"`。
       - 时长都用 `mix.media_seconds` 量。
    3. **生成文本**：`xml = build_fcpxml(tl, media, event=title)`，`text = readme(tl, title)`。
    4. **打包**：用 `zipfile.ZipFile(tmp, "w", ZIP_STORED)`，媒体已经是压缩格式，不再压。
       - 顶层目录：`safe = re.sub(r'[\\/:*?"<>|\s]+', "_", title)[:80]`。
       - 写进 `safe/project.fcpxml`、`safe/README.txt`、`safe/subtitles/<集>.srt`（取自 `final/<集>.srt`），以及 `media` 里每个文件。
       - 完成后 `tmp.replace(final/export/<safe>.zip)`。
    5. 返回 zip 路径。
  - ffmpeg 失败时 `raise ExportError(f"预渲染配音 {line} 失败")`，ffmpeg 的输出写进异常的 `stderr` 属性，不放进消息。
- [ ] **Step 4:** 后端各项检查通过。
- [ ] **Step 5: 提交**

```bash
git commit -m "导出执行：读时间轴，提速的配音用 atempo 预渲染并缓存，打包 fcpxml、各段视频、配音、BGM、字幕与说明为 zip；旧成片没有时间轴时提示重新合成"
```

---

### Task 4: 接口与可导出状态

**Files:**
- Modify: `backend/server/app.py`
- Test: `backend/tests/server/test_render.py`

- [ ] **Step 1: 先写失败测试**（沿用 `test_render.py` 里合成相关用例的夹具，包括 `STORYBOARD_RENDER_RUNNER=0`、假 TTS、ffmpeg 检测）：
  - **还没合成**：`GET …/render/compose` 返回 `exportable == False`、`export_reason == "none"`；`GET …/render/export.zip` 返回 409。
  - **合成成功之后**（有 ffmpeg 时）：
    - `exportable == True`，`export_reason` 是 `None`。
    - `GET …/render/export.zip` 返回 200。
    - `content-type` 是 `application/zip`，`content-disposition` 里有 `filename*=UTF-8''`。
    - 响应体用 `zipfile` 能打开，里面有 `project.fcpxml`。
  - **删掉 `final/timeline.json` 后**：`export_reason == "no_timeline"`，导出返回 409，`detail` 里有「重新合成」。
  - **改动分镜使成片过期后**：`export_reason == "stale"`，导出返回 409。
  - **另一个用户请求**：返回 404。
  - **没有 ffmpeg**：现有夹具能模拟就测 503，不能就跳过并打印提示。
- [ ] **Step 2: 跑一下，确认失败**。
- [ ] **Step 3: 实现**：
  - **`_compose_preview`**：按实施裁定 6 往 `p` 里加 `exportable` 和 `export_reason`。合成在跑时为 `"busy"`，判断沿用现有表示合成中的字段。
  - **接口**：

```python
@app.get(_R + "/export.zip")
def render_export(nid: str, cid: str, vid: str, user: dict = Depends(novel_user)):
    """导出剪辑工程（FCPXML + 素材 + 字幕 + 说明）。只读本地文件、跑本地 ffmpeg，不花钱。"""
    root, doc, kfs, s, p = _compose_preview(user, nid, cid, vid, True)
    reason = p.get("export_reason")
    if reason:
        raise HTTPException(409, {"none": "还没有合成好的成片", "stale": "成片已过期，请先重新合成",
                                  "no_timeline": "这份成片是旧版合成的，重新合成一次即可导出（会复用已有配音与规整结果，不花钱）",
                                  "busy": "正在合成，完成后再导出"}[reason])
    tools = render_mix.tools()
    if not tools:
        raise HTTPException(503, "服务器没有安装 ffmpeg，无法导出")
    novel = _novel_call(novels.get_novel, user["id"], nid)
    chapter = next((c for c in novel["chapters"] if c["id"] == cid), {})
    title = f"{novel['title']}-{chapter.get('title', cid)}-{vid[:8]}"
    try:
        path = render_export_fcpxml.export(root, title=title, tools=tools)
    except render_export_fcpxml.ExportError as e:
        raise HTTPException(409, str(e))
    return FileResponse(path, media_type="application/zip", filename=path.name)
```

  - 接口返回的报错里不能出现服务器目录：沿用 `_hide_root` 的做法。
  - `FileResponse` 遇到非 ASCII 文件名会自动生成 `filename*=UTF-8''`。如果你的 FastAPI / Starlette 版本不会，就手动设置这个响应头。
  - 文件头的接口清单注释里加上这一行。
- [ ] **Step 4:** 后端各项检查通过。
- [ ] **Step 5: 提交**

```bash
git commit -m "导出剪辑工程接口：已合成且未过期时下载 zip；合成状态给出可否导出与原因（没有成片、已过期、旧成片需重新合成、合成中）"
```

---

### Task 5: 前端导出按钮

**Files:**
- Modify: `frontend/src/api.ts`、`types.ts`、`components/workflow/DownloadStep.tsx`、`i18n/zh.ts`、`en.ts`
- Test: `frontend/tests/workflow-ui.test.tsx`

- [ ] **Step 1: 先写失败测试**（沿用 `workflow-ui.test.tsx` 里渲染 `DownloadStep` 的夹具，`fetch` 打桩写法沿用该文件）：
  - `compose` 夹具 `exportable: true` 时，`[data-testid="export-fcpxml"]` 可点，文字是「导出剪辑工程（FCPXML）」，旁边有「可导入 Final Cut Pro、DaVinci Resolve」。点了之后请求 `…/render/export.zip`，并创建下载用的 `a` 元素（或调用 `URL.createObjectURL`，按现有下载写法断言）。
  - `exportable: false` 时按钮禁用，原因随 `export_reason` 变化：
    - `no_timeline`：「重新合成一次即可导出（会复用已有的配音与规整结果，不花钱）」。
    - `stale`：「成片已过期，请先重新合成」。
  - 主按钮（下载成片）不变，导出按钮是 `outline` 样式。
- [ ] **Step 2: 实现**：
  - **`types.ts`**：`ComposePreview` 加 `exportable?: boolean`、`export_reason?: 'none' | 'stale' | 'no_timeline' | 'busy' | null`。
  - **`api.ts`**：`exportFcpxml(nid, cid, vid)`：
    - 用带 token 的 `send(...)` 取回 `Response`。
    - 从 `content-disposition` 解析 `filename*`，`decodeURIComponent` 后得到文件名，取不到时用 `project.zip`。
    - 转成 blob URL，用临时 `a` 元素触发下载，下一帧 revoke。
    - 失败时抛出带后端 `detail` 的错误（沿用现有 `req` 的错误处理）。
  - **`DownloadStep`**：
    - 在成片下载那一块下面加一行：`Button variant="outline"`（`data-testid="export-fcpxml"`），加一行小字说明。
    - 导出中显示加载状态，并禁用按钮。
    - 失败时用 `notice.err`。
    - 不可导出时显示原因文案。
    - `compose` 数据从组件现有的属性取。现在拿不到的话，由 `ChapterWorkflow` 传入（它有 `input.compose`）。
  - **新增文案**：`flow.export.button`、`hint`、`busy`、`failed`，`flow.export.reason.none`、`stale`、`no_timeline`、`busy`。
- [ ] **Step 3:** 前端三项检查通过。
- [ ] **Step 4: 提交**

```bash
git commit -m "下载页加导出剪辑工程按钮：可导出时下载 FCPXML 工程包，不可导出时说明原因（旧成片需重新合成、成片已过期等）"
```

---

## 自查记录

- **规格覆盖**：
  - 第 2 节入口与文件名：Task 3、4、5。
  - 第 3 节 zip 内容与 fcpxml 结构：Task 2、3。
  - 4.1 时间轴记录：Task 1。
  - 4.2 导出与接口：Task 3、4。
  - 第 5 节前端：Task 5。
  - 第 6 节测试：分布在各任务。DTD 按实施裁定 1 改为结构校验。
- **类型一致**：
  - `timeline.json` 的结构由 Task 1 产生，Task 2、3 使用。
  - `speech[].duration` 在 Task 1 加上，Task 2 使用。
  - `media` 的形状在实施裁定 5 定义，Task 2、3 使用。
  - `ExportError` 在 Task 3 定义，Task 4 使用。
  - `exportable` 和 `export_reason` 在 Task 4 产生，Task 5 使用。
