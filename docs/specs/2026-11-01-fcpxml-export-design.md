# 导出剪辑工程（FCPXML）设计

日期：2026-11-01。

背景：工作台改版规格第 11 节第 4 条里的「导出剪映草稿」。经调研改为先做 FCPXML 工程包，见第 1 节。

## 0. 目标

把一章已合成的成片导出成可再剪辑的工程。成片里的每一段视频、每一句配音、BGM、字幕都是独立素材，按时间轴摆好，用户在专业剪辑软件里接着精修。

## 1. 为什么先做 FCPXML

- **剪映（国内版）**：自 6.0 起，`draft_content.json` 用 AES 加密，第三方工具连读都读不了。主流开源库（pyJianYingDraft、capcut-cli）都只检测、不解密。新版剪映还会在打开或关闭时，把明文草稿重新加密，所以写草稿不稳定。
- **CapCut（海外版）**：社区报告说没有加密，也有 pyCapCut，但格式没有官方文档、随版本变化。资料多来自 2026 年 5–10 月的社区测试。
- **FCPXML**：
  - 有公开规范，Final Cut Pro 和 DaVinci Resolve（免费）都能导入。
  - Premiere 不直接导入 FCPXML（它读的是 FCP7 XML），Premiere 用户可以经由 DaVinci 转。
  - CapCut 可以作为同一份时间轴数据的第二个导出器，以后再加（见第 7 节）。

## 2. 用户能看到的

- **入口**：⑥ 下载页，成片旁边加一个按钮「导出剪辑工程（FCPXML）」，旁边一行小字「可导入 Final Cut Pro、DaVinci Resolve」。
  - **可用条件**：这一章版本有已合成、且没过期的成片。「草稿合成」得到的成片也可以导出，用关键帧占位的段会写进 README。
  - **旧成片没有时间轴记录**（见第 4 节）时，按钮禁用，并提示「重新合成一次即可导出（会复用已有的配音与规整结果，不花钱）」。
  - **导出中**：按钮显示加载状态。完成后浏览器下载 zip。失败时用 `notice` 显示后端的报错。
- **zip 的名字**：`<小说>-<章节>-<版本>.zip`。文件名里的非法字符换成 `_`，最长 80 个字符。

## 3. zip 里有什么

```
<小说>-<章节>-<版本>/
  project.fcpxml
  media/clips/<集>-<段>.mp4        规整好的段（已是计划长度，含按设置压低的原声）
  media/voice/<语音条>.wav          每句配音；需要提速的已按倍速预渲染
  media/bgm/<集>.<扩展名>            本集 BGM（没有就不放）
  subtitles/<集>.srt                与成片同一份字幕
  README.txt                        中英双语：导入步骤、离线素材怎么重新链接、哪些段是占位、两件要用户自己做的事
```

### 3.1 project.fcpxml

- 格式版本是 FCPXML 1.10。结构：`resources` → `library` → 一个 `event` → 每集一个 `project`（导入后是一条时间轴）。
- **格式（format）**：
  - 尺寸取合成用的画面尺寸（`mix.frame_size`）。
  - 帧率 30（`mix.FPS`），`frameDuration="1/30s"`。
  - 所有时间都写成帧数对齐的有理数（`n/30s`），先四舍五入到整帧。
- **轨道**（每集一个 `spine`）：
  - **视频**：各段依次排列，是主故事线上的 `asset-clip`。时长取规整后的段长。
  - **配音**：每句是连接在主故事线上的音频 `asset-clip`，`lane="-1"`，`offset` 等于这句的计划起点。
  - **BGM**：一个连接的音频 `asset-clip`，`lane="-2"`，从 0 开始，长度截到本集总长，并写 `<adjust-volume amount="-14dB"/>`，与合成时的 `BGM_DB` 一致。
- **素材路径**：`asset` 的 `media-rep src` 写相对路径 `media/...`。
  - 剪辑软件不一定认相对路径。认不出时素材会显示离线，README 写明怎么把整个 `media/` 文件夹一次重新链接上。
  - 文件名在包内唯一，所以能自动匹配。

### 3.2 两件要用户自己做的事（README 写明）

- **字幕**：不进时间轴，把 `subtitles/` 里的 srt 拖进去。两款软件都支持导入 SRT。
- **响度**：成片最后的响度归一（−16 LUFS）不在工程里做，用户最终导出时自己处理。

## 4. 后端

### 4.1 时间轴记录 `final/timeline.json`

合成（`render/mix.py` 的 `compose`）在写成片的同时多写一个文件，和成片一样先写进 `final/.next`，全部成功后再挪进 `final/`：

```json
{ "version": 1, "fps": 30, "size": [1080, 1920], "draft": false, "bgm_db": -14,
  "episodes": [
    { "episode": "E01", "total": 63.4,
      "segments": [ { "clip": "K01", "file": "final/work/K01.<key>.mp4", "start": 0.0, "duration": 6.2,
                      "placeholder": false } ],
      "speech": [ { "line": "L001", "file": "audio/cache/...wav", "start": 0.4, "speed": 1.0 } ],
      "bgm": "bgm/E01.mp3" } ] }
```

- 路径都相对于出片会话目录。
- `segments`、`speech` 直接取 `plan_episode` 的结果，加上规整后文件的路径。
- `speech.start` 与字幕起点一致。
- 合成的指纹不变，这个文件不进指纹。旧成片没有这个文件。
- `compose` 返回的 `files` 仍只列 mp4 和 srt，这个文件不出现在界面的成片列表里。

### 4.2 导出

- **新模块 `render/export_fcpxml.py`**：
  - **纯函数** `build_fcpxml(timeline: dict, names: dict) -> str`。`names` 是包内素材的相对路径映射。
  - **执行函数** `export(root, *, title: str, tools) -> Path`：
    1. 读 `final/timeline.json`。
    2. 需要提速的配音用 ffmpeg 的 `atempo` 预渲染到 `final/export/voice/`。按「源文件、倍速」命名缓存，已有的不重做。
    3. 组装 zip，写到 `final/export/<…>.zip`，返回路径。
- **新接口** `GET /novels/{nid}/chapters/{cid}/versions/{vid}/render/export.zip`：
  - 鉴权和读成片文件一样，依赖 `novel_user`。
  - 有已合成的成片，且 `final/timeline.json` 存在，才导出。否则返回 409，并附说明：没有成片，或「重新合成一次即可导出」。
  - 成片过期（合成指纹与当前不一致）时也返回 409：「成片已过期，请先重新合成」。
  - 返回 zip 文件，带 `Content-Disposition: attachment; filename*=UTF-8''…`。
  - 生成过程不花钱、不调厂商。没有 ffmpeg 时返回 503，与合成一致。
- **报错文字**：沿用中文，与现有接口一致。

## 5. 前端

- **`api.ts`**：`exportFcpxml(nid, cid, vid)`。带 token 取回 blob，从 `Content-Disposition` 取文件名，触发下载，用完 revoke。
- **`DownloadStep`**：
  - 加「导出剪辑工程（FCPXML）」按钮，用 `outline` 样式。每屏一个主按钮，主按钮仍是下载成片。
  - 是否可点：取合成状态里新增的 `exportable: boolean`。成片存在、不过期且有时间轴记录时为真。
  - 不可点时，在按钮下方写原因。
- **合成状态接口**（`getCompose` 的返回）加 `exportable` 和 `export_reason`，前端只读这两个字段。
- 所有新文字进 `zh.ts` 和 `en.ts`。

## 6. 测试

- **纯函数**：用手写的两集 timeline 生成 FCPXML。
  - 能被 `xml.etree` 解析。
  - 每集一个 `project`，帧率和尺寸正确。
  - 视频段的 `offset` / `duration` 连续，并且等于记录里的值（按帧取整）。
  - 配音的 `offset` 等于计划起点，`lane="-1"`。
  - BGM 带 `-14dB`，长度等于本集总长。
  - 所有 `asset` 的 `src` 都在 `names` 里，没有绝对路径。
- **DTD 校验**：仓库放一份 FCPXML 1.10 的公开 DTD，测试里用 `xmllint --dtdvalid` 校验生成结果。没有 `xmllint` 时跳过并打印提示。
- **合成**：现有的 `test_mix_e2e`（真跑 ffmpeg）在合成后断言 `final/timeline.json` 存在，且内容与 `plan_episode` 一致、引用的文件都存在。中途失败时 `final/` 里不出现新的 timeline。
- **导出端到端**：在 `test_mix_e2e` 合成之后调 `export`。
  - zip 里有 `project.fcpxml`、README、每个被引用的文件。
  - 提速的配音时长约等于原时长除以倍速，用 ffprobe 测，误差 ≤ 0.05 秒。
- **接口**：
  - 没有成片返回 409；有成片但没有 timeline 返回 409，且带「重新合成」提示；别人的版本返回 404。
  - 合成状态里 `exportable` 的三种取值。
- **前端**：
  - `DownloadStep`：`exportable` 为真时按钮可点，点了调导出。
  - 为假时按钮禁用，并显示原因。

## 7. 不做

- 剪映 / CapCut 草稿（以后可以作为第二个导出器，读同一份 `timeline.json`）。
- FCP7 XML（Premiere 直接导入）。
- 字幕进时间轴（标题、字幕轨）。
- 在时间轴里用变速表示提速：改为预渲染。
- 导出时的响度归一。
- 后台异步导出、进度条：按需生成，一章通常几十 MB，同步返回即可。
