# 拉片表与片段卡镜头标签设计

日期：2026-11-17　分支：langchain　状态：待设计审查

## 1. 背景与目标

产品把小说转成分镜再出视频。对比竞品后发现：我们的界面上看不到「镜号 / 景别 / 运镜」这类专业说明，用户没法像看拉片表那样一眼扫完整章的镜头设计。

调查结论是**数据已经齐全，缺口只在展示**：

- 每个镜头（`backend/schema/storyboard.schema.json` 的 shot，前端类型 `frontend/src/types.ts` 的 `Shot`）已有 `id`（如 `E01-SH003`）、`duration_sec`、`shot_size`、`camera.movement`、`camera.angle`、`action`、`atmosphere`、`dialogue`、`narration`。
- 视频提示词由 `backend/render/plan.py` 拼装，已含景别、角度、运镜；前端在出片会话 `FilmSession.clips[].prompt` 里能拿到。
- 出片画布的片段卡（`NodeCards.tsx` 的 `ClipCard`）只显示片段号、时长、状态、提示词，看不出这一段由哪几镜组成、各是什么景别。
- 没有「每镜一行」的总表。

目标：

1. 分镜视图新增「拉片表」页签：每镜一行、按集分组的只读总表。
2. 出片画布节点图的片段卡上，逐镜列出小标签（镜号、景别、运镜）。

## 2. 范围与非目标

范围：**纯前端**。不改后端、不改 schema、不改任何模型调用，不新增接口。

非目标（本次不做）：

- 每镜的图片提示词列。
- 导出 CSV 或其他格式。
- 在拉片表里编辑。表是只读的，编辑仍在「镜头」「卡片」页签。
- 时间轴视图的片段条、侧栏「出片」页不加标签。
- 搜索、筛选、列排序、列显隐。

另有一条贯穿约束：普通用户界面不得出现模型名或供应商名。拉片表与标签只读 `clip.id`、`clip.duration`、`clip.prompt`、`clip.shots`，不读 `FilmSession.provider`、`model`、`options`。

## 3. 拉片表

### 3.1 入口与地址

- `StoryboardView` 的页签顺序改为：镜头 `focus`、卡片 `cards`、**拉片表 `sheet`**、资产 `assets`、原文 `source`、渲染 `render`、JSON `json`。
- 页签文案：中文「拉片表」，英文「Breakdown」。
- 地址 `?tab=sheet`。`frontend/src/paths.ts` 的 `TABS` 加入 `'sheet'` 后，`parseLocation` 与 `chapterPath` 自动支持，规则不变：只在 review / render / compose 三步有意义，刷新、前进后退、直接打开链接都停在拉片表。
- 分批预览（`preview` 非空）时拉片表照常可见，因为它本来就只读。

### 3.2 列

每个镜头一行，七列：

| 列 | 内容 | 缺省 |
|---|---|---|
| 镜号 | 完整镜头 id（如 `E01-SH003`），下方小字时长 `5s`（取 `duration_sec`，最多一位小数） | — |
| 关键帧 | 已上传关键帧的缩略图，画幅按 `meta.video.aspect_ratio` | 灰底占位，文字「无图」 |
| 景别 | `SHOT_SIZE` 标签 | 「—」 |
| 运镜 / 角度 | `CAMERA_MOVEMENT` 与 `CAMERA_ANGLE` 标签，用「 / 」连接，如「推 / 仰拍」；只有其一就只显示其一 | 「—」 |
| 画面 | `action`，下方小字 `atmosphere` | 没有 atmosphere 就不显示小字 |
| 台词 / 旁白 | 台词逐条：说话人（资产卡名）加粗、非普通台词时加类型小标签（内心独白、画外音）、正文；旁白一条，前缀「旁白」 | 都没有显示「—」 |
| 视频提示词 | 该镜所属片段的 `prompt`，上方小字「片段号 · 时长」 | 「未规划」 |

枚举值找不到标签时原样显示英文枚举（`label()` 的既有行为），不留空白。

### 3.3 分组

- 按集分组。每集一个 `<tbody>`，第一行是集标题行（跨七列）：集 id、集标题（有才显示）、镜头数（复用文案 `board.ep.count`）。
- 没有任何集时只显示表头。

### 3.4 视频提示词列的合并

- 一个镜头属于哪个片段：出片会话里第一个 `shots` 含该镜头 id 的片段（与 `shotFocus.ts` 的 `clipForShot` 同一规则）。
- **同一集内相邻**且属于同一片段的镜头，提示词格用 `rowSpan` 合并成一格。
- 同一集内相邻的「不属于任何片段」的镜头同样合并成一格，显示「未规划」。没有出片会话（`film` 为 null）时每集恰好一格「未规划」。
- 同一片段的镜头如果不相邻（中间夹了别的片段），各自成格，不跨行合并。
- 合并不跨集。

### 3.5 截断与展开

- 提示词默认截到 3 行（CSS `line-clamp`）。
- 提示词较长时格子底部显示「展开」按钮，点开显示全文，按钮变「收起」。展开状态按片段记在组件内，不进地址，切走页签即丢。
- 「较长」的判定是纯函数 `needsFold`：超过 60 个字符，或超过 3 行（按换行符数）。不量 DOM——测试环境（happy-dom）没有布局，量不出来；60 字在最窄的提示词列宽下不足 3 行中文，所以被截断的提示词一定带按钮。

### 3.6 交互

- 只读。
- 点一行（提示词格除外）跳到「镜头」页签并选中这一镜：直接复用 `StoryboardView` 现有的 `jumpShot(shotId)`。
  - 受控时（章节工作流里）它调用上层的 `onJumpShot()`，由 `App` 一次 `replace` 到不带 `?tab=` 的地址；
  - 非受控时 `setTab('focus')`。
  - 两种情况下 `focusShot` 都先记下，`ShotFocusView` 挂载时选中这一镜。
- 镜号是一个真正的 `<button>`，键盘可聚焦，回车等同点行。
- 提示词格不参与跳转（它可能跨多镜，点它跳哪一镜有歧义），格内点击不冒泡。

### 3.7 布局

- 表格放在 `.sheet__wrap` 容器里，容器 `overflow: auto`、限高 `calc(100vh - 96px)`，表头吸顶。
- 表格 `min-width: 1080px`。窄屏时在容器内横向滚动，**页面本身不出现横向滚动条**。
- 关键帧缩略图：横画幅宽 96px，竖画幅宽 54px，高度由画幅比例决定。

## 4. 片段卡镜头标签

位置：出片画布的节点图视图（`NodeGraph.tsx`），剧本段卡片（`ClipCard`）标题行下面。

- 每个镜头一个小标签：`短镜号 景别·运镜`，如 `SH003 特写·推`。
  - 短镜号 = 镜头 id 最后一个 `-` 之后的部分（`E01-SH003` → `SH003`）；id 里没有 `-` 就用整个 id。
  - 没有运镜时只有景别（`SH003 中景`）。
  - 片段里的镜头 id 在分镜里找不到时（重新转换后的旧会话），只显示短镜号。
- 最多显示 3 个；超出的折叠成一个 `+N` 标签。
- 整行的 `title` 是全部标签，一行一个，悬停可见。
- 片段没有镜头时不渲染这一行。
- 标签行最多占两行高度（英文标签较长时会折到第二行），超出部分隐藏；为此剧本段卡片高度 `CARD_H` 由 208 调到 252。自由节点卡不变。

## 5. 组件与数据流

### 5.1 新增文件

| 文件 | 职责 |
|---|---|
| `frontend/src/shotSheet.ts` | 纯函数：`sheetGroups`（分组与 rowSpan）、`cameraText`、`shortShotId`、`shotTag`、`shotsById`、`clipShotTags`、`foldTags`、`needsFold`。不依赖 React |
| `frontend/src/components/ShotSheet.tsx` | 拉片表组件 |
| `frontend/tests/shot-sheet.test.ts` | 纯函数单测 |
| `frontend/tests/sheet-view.test.tsx` | 拉片表界面测试 |

### 5.2 改动文件

| 文件 | 改动 |
|---|---|
| `frontend/src/components/StoryboardView.tsx` | `Tab` 与 `TABS` 加 `'sheet'`；`tab === 'sheet'` 时渲染 `<ShotSheet>` |
| `frontend/src/paths.ts` | `TABS` 加 `'sheet'` |
| `frontend/src/i18n/zh.ts`、`en.ts` | `board.tabs.sheet`、`board.sheet.*` |
| `frontend/src/styles/storyboard.css` | `.sheet*` 样式 |
| `frontend/src/components/NodeGraph.tsx` | 用 `doc` 建镜头索引，把标签传给 `ClipCard` |
| `frontend/src/components/NodeCards.tsx` | `ClipCard` 新增 `tags` 属性并渲染 |
| `frontend/src/nodeGraph.ts` | `CARD_H` 208 → 252 |
| `frontend/src/styles/nodegraph.css` | `.ngv__shots`、`.ngv__shot` |
| `frontend/package.json` | `test` 脚本串加两个新测试 |
| `frontend/tests/paths.test.ts`、`chapter.test.tsx`、`real-doc.test.tsx`、`graph-view.test.tsx` | 页签清单断言更新、新用例 |

### 5.3 数据从哪来

**拉片表**所需的数据 `StoryboardView` 都已经有，`App.tsx` 不用改：

- `doc`、`idx`（`buildIndex(doc)`，说话人名字用 `idx.assetName`）；
- `film`：`App.tsx` 已传 `film={flow.film}`（`FilmSession | null`）；
- `version`、`imagesKey`：关键帧图走 `useShotImages(version, imagesKey)`，与 `ShotFocusView` 同一个 hook——只列出并读取已上传的图，不请求出图提示词，读失败静默。拉片表与镜头视图不同时挂载，不会重复取图；
- 跳转：`jumpShot`。

```
StoryboardView ── doc, idx, film, version, imagesKey, onJump=jumpShot ──▶ ShotSheet
                                                                          ├─ sheetGroups(doc, film)   分组 + rowSpan
                                                                          └─ useShotImages(version, imagesKey)
```

**片段卡标签**：`NodeGraph` 已有 `doc` 属性（由 `TimelineCanvas` 传入），`ClipCard` 目前拿不到镜头数据。最小改动是 `NodeGraph` 用 `shotsById(doc)` 建一次索引（`useMemo`），渲染每张剧本段卡时算 `clipShotTags(clip.shots, 索引)`，以新属性 `tags: string[]` 传给 `ClipCard`。`nodeGraph.ts` 的布局函数不需要知道镜头。

标签文字在渲染时计算而不是缓存，因为 `labels.ts` 的枚举表按当前语言取值，切语言后要跟着变。

## 6. 边界情况

| 情况 | 表现 |
|---|---|
| 没有出片会话 | 每集一格「未规划」 |
| 会话里某镜不属于任何片段 | 该镜（及相邻的同类镜）「未规划」 |
| 同一镜出现在两个片段里 | 取第一个片段 |
| 片段引用了分镜里不存在的镜头 | 拉片表不受影响（按分镜的镜头出行）；片段卡标签只显示短镜号 |
| 没上传关键帧、没有版本（本地打开的 JSON） | 缩略图位显示「无图」 |
| 关键帧读取失败 | 同上，静默 |
| 镜头没有 `camera`、`atmosphere`、台词、旁白 | 对应位置显示「—」或不显示 |
| 枚举值不认识（模型写了表外的值） | 原样显示该值 |
| `duration_sec` 不是数字（脏数据） | 时长留空，不报错 |
| 提示词很短 | 不显示「展开」 |
| 片段 `shots` 为空 | 片段卡不显示标签行 |
| 切换语言 | 表头、枚举标签、占位文字、片段卡标签都跟着切；镜头正文与提示词原样 |
| 分镜没有任何集 | 只显示表头 |

## 7. 测试

测试沿用仓库现有做法：`vite build --ssr` 构建测试文件，再交给 node 跑；界面测试用 happy-dom 加 `react-dom/client`，断言用文件内的 `must` / `eq`（仓库没有 vitest 与 testing-library，本次不引入）。

纯函数（`tests/shot-sheet.test.ts`）：

- `sheetGroups`：无会话、有会话、同片段不相邻、一镜两片段、无集；
- `shortShotId`、`cameraText`、`shotTag`、`clipShotTags`（含找不到的镜头）、`shotsById`；
- `foldTags`（3 个不折叠、5 个折叠成 +2、空）；
- `needsFold`（60 / 61 字、3 / 4 行）；
- 英文标签。

拉片表界面（`tests/sheet-view.test.tsx`）：

- 行数、集标题行与镜头数；
- 各列文字（镜号、时长、景别、运镜 / 角度、画面与氛围、说话人、旁白）；
- `rowSpan`：同片段相邻两镜合并、被合并的行没有提示词格、未规划占位、无会话时每集一格；
- 关键帧：有图的显示 `<img>`，其余显示「无图」；
- 展开 / 收起，且不触发跳转；
- 点行跳转：非受控时切到镜头页签并选中该镜；受控时只调用 `onJumpShot`；
- 英文：页签、表头、枚举、占位全部英文；
- 界面文字里不出现会话的模型名与供应商名。

路由（`tests/paths.test.ts`）：`?tab=sheet` 解析与拼地址。

页签清单（`tests/chapter.test.tsx`、`tests/real-doc.test.tsx`）：七个页签的中英文顺序。

片段卡（`tests/graph-view.test.tsx`）：标签文字、恰好 3 个不出 `+N`、5 个时显示 3 个加 `+2`、`title` 含全部、找不到的镜头只显示短镜号、空片段不渲染、英文标签。

验收命令（在 `frontend/` 下）：

- `npm test`
- `npm run lint`（基线 5 条警告，不得增加）
- `npm run build`

布局类要求（窄屏只在容器内横向滚动、表头吸顶、片段卡高度够用）在 happy-dom 里测不出来，留给功能验收时在浏览器里目视确认。
