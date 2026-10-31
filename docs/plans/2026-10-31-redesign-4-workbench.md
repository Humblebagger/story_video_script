# 前端改版 4：分镜视图、时间轴画布、出片与配音合成面板换装 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 分镜视图（总览、集、镜头卡、编辑控件、资产卡、原文溯源、渲染、完整性检查、JSON）、时间轴画布与侧栏、出片与配音合成面板换成新视觉；出片与合成的花钱确认换成全站统一的 `MoneyConfirm`；这些界面里的内部术语说人话。功能与交互不变。

**Architecture:** 按区域把 `src/index.css` 里对应的旧规则**搬出并重写**到新的样式文件（`src/styles/storyboard.css`、`views.css`、`canvas.css`、`film.css`），新文件只用新设计变量（shadcn 变量 + 本计划新增的 `--tone-*`），放在 `@layer components`；搬完从 `index.css` 删掉那一段。按钮、徽章、页签、提示用 shadcn 组件（`Button`、`Badge`、`Tabs` 外观、`Tooltip`）；画布的 SVG 泳道、镜头卡这类专门布局继续用类名 + 样式文件。测试依赖的类名一律保留（作为钩子）。子计划 5 删除 `index.css` 时，这几块已经不依赖它。

**Tech Stack:** React 19、TS 6、Tailwind v4、shadcn、motion、lucide-react、happy-dom。

**Spec:** `docs/specs/2026-10-31-frontend-redesign-design.md` 第 1 节（品牌色、字号三级）、第 4.3 节（说人话）、第 4.4 节（花钱确认）、第 5 节（分镜视图、时间轴画布）、第 6 节（动效）、第 8 节。

---

## 全局约束

- 提交只 `git add` 具体文件，不用 `git add -A` / `git commit -a`；提交信息中文，**不带任何 Claude 署名**。
- 命令在 `frontend/` 下执行。每个任务结束：`npm test`（全部 13 套 `ALL PASS`）、`npm run lint`（0 error，不新增 warning；现有 6 个）、`npx vite build`。
- **功能与交互不变**：不改 `edit.ts`、`resolve.ts`、`timeline.ts`、`timelineOps.ts`、`film.ts`、`useFilm.ts`、`useCompose.ts`、`useKeyframes.ts` 的行为；`compose.ts` / `film.ts` 只允许改返回给用户看的文字（第 4.3 节说人话）。SVG 绘制、拖动、缩放、快捷键、撤销逻辑不动。
- **测试钩子类名保留**：下列类名在测试里被选择器用到，组件上必须继续带着（可以同时加 Tailwind 类）：`tlc tlc__panel tlc__shot tlc__tabs tlc__rangeband tlc__frame tlc__pip tlc__clock tlc__thumb tlc__nodeedit tlc__link--lit tlc__labels tlc__vers tlc__unit tlc__svg tlc__prompt tlc__node tlc__music tlc__kfdot tlc__kf tlc__grip tlc__editbar tlc__clip tlc__char tlc__bar ed__at ed__attach ed--var acard tabs__btn shot unit--focus unit__id uref src rend__len rclip rclip__pick cpick cpick__wrap compose__run compose__play compose__table film__clip film__rows assets is-cur is-past is-on`。`grep -ohE "querySelector(All)?\('[^']+'\)" tests/*.tsx` 可复查。
- **样式文件规则**：新文件在 `src/styles/app.css` 里 `@import "./storyboard.css" layer(components);`（其余同理）放在 `@import "../index.css" layer(legacy);` 之后。新文件里**不许引用旧变量**（`--bg --panel --panel-2 --text --muted --faint --line --line-2 --accent --accent-soft --explicit --inferred --transition --danger --warn-bg --radius --mono`），只用：`--background --foreground --card --card-foreground --popover --primary --primary-foreground --secondary --ui-muted --muted-foreground --ui-accent --border --input --ring --destructive --success --warning --brand-from --brand-to --ui-radius`，以及 Task 1 新增的 `--tone-*`。字体等宽用 `var(--font-mono)`（在 app.css 的 `@theme` 里，没有就加 `--font-mono: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace;`）。
- **视觉基调**（全部任务通用）：卡片 `border` 1px `--border`、圆角 `calc(var(--ui-radius) + 2px)`、底 `--card`；悬停只抬描边色（`color-mix(in oklab, var(--foreground) 18%, var(--border))`）和极轻阴影，不位移超过 1px；字号只用三级（标题 15–16px 600、正文 14px、辅助 12px `--muted-foreground`）；标签（景别、运镜、时长等）用 `Badge variant="secondary"` 或 `.chip`（高 20px、圆角 999px、12px、`--secondary` 底）；ID 一律等宽 12px `--muted-foreground`；每屏最多一种强调色（品牌渐变只给「当前 / 选中」）。
- **说人话**（只改用户看到的文字；测试断言里的字面同步改）：「IR」→「分镜」；「验证门」「复验」→「完整性检查」；「指纹」「过期」（成片 / 段）→「内容改过，需要重新生成」（段横条上的「已过期 · 仍可播放旧版」→「内容改过 · 仍可播放旧版」）；「草稿合成」→「没出好的段先用图片代替」；画布「任务」页的「转换」→「生成」（「重新转换（新版本）」→「重新生成（新版本）」）。
- 动效：悬停、展开 150–240ms 缓出；减少动态效果时不位移。
- 测试固定用中文；本计划**不做英文翻译**（子计划 5 统一做），新写的少量文字可以先硬写中文。
- 不碰后端，不碰 `docs/specs/2026-10-27-commercialization-design-contract.md`，不读 `backend/.env`。

## 实施裁定

1. **画布与镜头卡继续用类名样式**（搬进新样式文件、改用新变量），不强行改成 Tailwind 工具类：SVG 泳道和多层镜头卡用工具类写会比样式文件难读得多。控件（按钮、徽章、页签、下拉、提示）换 shadcn 组件或与之同外观的类。
2. **`MoneyConfirm` 走 Radix portal**，渲染在 `document.body`：出片 / 合成测试里找确认框的选择器改为在 `document.body` 里找 `[data-testid="money-confirm"]`；`.film__rows` 明细表作为 `MoneyConfirm` 的 `children` 保留类名。
3. **语义色**：原文出处（explicit）、系统补充（inferred）、转场（transition）三种在 `app.css` 新增 `--tone-explicit --tone-inferred --tone-transition`（浅深两套），旧变量名不复用（foundation 测试会检查新旧变量名不重叠）。
4. **本计划不改** 小说页各页签、新建小说表单、分段选取、任务面板（`JobPanel`）与管理后台的样式——留给子计划 5。

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/styles/app.css` | 修改：`--tone-*`、`--font-mono`、引入四个新样式文件 |
| `src/styles/storyboard.css` | 新建：分镜总览、集、镜头卡、编辑控件、挂卡、阶段与负面约束 |
| `src/styles/views.css` | 新建：资产卡、原文溯源、JSON、渲染任务包、完整性检查 |
| `src/styles/canvas.css` | 新建：时间轴画布、侧栏、静帧、就地编辑、选区、预览窗 |
| `src/styles/film.css` | 新建：成片泳道、出片与合成侧栏页 |
| `src/index.css` | 修改：删掉已搬走的段（约 479–903、963–1083、1175–1376、1427–末尾） |
| `src/components/StoryboardView.tsx`、`EpisodeView.tsx`、`ShotCard.tsx` | 修改：标签、分层、分段控件 |
| `src/components/AssetsView.tsx`、`SourceView.tsx`、`RenderView.tsx`、`VerificationPanel.tsx` | 修改：按钮与徽章换 shadcn、说人话 |
| `src/components/TimelineCanvas.tsx`、`CanvasPanels.tsx` | 修改：工具条胶囊、侧栏页签外观、说人话 |
| `src/components/FilmPanel.tsx`、`ComposePanel.tsx` | 修改：确认换 `MoneyConfirm`、外观、说人话 |
| `src/compose.ts`、`src/film.ts` | 修改：只改给用户看的文字 |
| `tests/*.test.tsx` | 修改：随文字与确认框位置同步 |

---

### Task 1: 设计变量与样式文件骨架

**Files:** Modify `src/styles/app.css`；Create `src/styles/storyboard.css`、`views.css`、`canvas.css`、`film.css`（先只放一行注释）

- [ ] **Step 1:** 在 `app.css` 的浅色 `:root` 与深色块里各加：

```css
  /* 分镜语义色：原文出处 / 系统补充 / 转场 */
  --tone-explicit: oklch(0.58 0.11 155);
  --tone-inferred: oklch(0.68 0.13 75);
  --tone-transition: oklch(0.58 0.12 280);
```

深色：

```css
  --tone-explicit: oklch(0.74 0.12 155);
  --tone-inferred: oklch(0.8 0.13 80);
  --tone-transition: oklch(0.74 0.11 280);
```

`@theme inline` 里加 `--color-tone-explicit: var(--tone-explicit);`（另两个同理），`--font-mono` 没有就加上。

- [ ] **Step 2:** 四个新样式文件各写一行文件头注释（职责见文件结构表），在 `app.css` 里 `@import "../index.css" layer(legacy);` 之后加：

```css
@import "./storyboard.css" layer(components);
@import "./views.css" layer(components);
@import "./canvas.css" layer(components);
@import "./film.css" layer(components);
```

- [ ] **Step 3:** 验证（foundation 测试的新旧变量名不重叠检查要过）并提交：

```bash
git add src/styles/app.css src/styles/storyboard.css src/styles/views.css src/styles/canvas.css src/styles/film.css
git commit -m "工作台换装底座：分镜语义色（原文出处、系统补充、转场）浅深两套、等宽字体变量、分镜 / 视图 / 画布 / 出片四个样式文件挂进组件层"
```

---

### Task 2: 分镜视图（总览、集、镜头卡、编辑控件）

**Files:** Modify `StoryboardView.tsx`、`EpisodeView.tsx`、`ShotCard.tsx`、`src/styles/storyboard.css`、`src/index.css`；测试按需

把 `index.css` 中「分镜总览」到「镜头内阶段与负面约束」几段（约 479–778 行：`.sb* .stats .stat* .tabs* .eps .ep* .curve* .shot* .ed* .cpick* .uref* .stage* .neg*` 等，以实际为准）搬进 `storyboard.css` 并按全局约束重写；搬完从 `index.css` 删除。具体视觉：

- [ ] **Step 1: 总览头部（`StoryboardView`）**
  - 标题 `h2` 16px 600；章节名辅助色；`schema` / 保真模式 / 旁白模式 / 画幅四个标签改 `Badge variant="secondary"`（`schema` 那个用等宽字）。
  - 右侧动作改 `Button size="sm"`：「编辑分镜 / 完成编辑」`variant={editing ? 'default' : 'outline'}`；「保存修改」`default`（保留 `id="storyboard-save"`）；「时间轴画布」「下载 JSON」`ghost`，加 lucide 图标（`Clapperboard`、`Download`）。
  - 统计行改成一排小卡（`grid grid-cols-3 md:grid-cols-6 gap-2`），数字 20px 600 `tabular-nums`、标签 12px 辅助色；覆盖率不足 100% 的那张数字用 `--warning`。
  - 预览提示、编辑说明改成带左侧 3px 色条的提示块（预览用 `--warning`、编辑说明用 `--border`）。
  - **视图切换做成分段控件**：外层 `inline-flex rounded-lg bg-muted p-1`，每个按钮 `rounded-md px-3 py-1.5 text-sm`，选中的 `bg-background shadow-sm font-medium`；保留 `tabs__btn` 与 `is-on` 类名。
- [ ] **Step 2: 集（`EpisodeView`）** — 集头一行：折叠箭头换 lucide `ChevronRight`（展开时旋转 90°，200ms）、集号等宽、标题 15px 600、镜数 `Badge`；摘要、配器、尾帧为辅助色正文；BGM 曲线条保持结构，颜色换新变量。
- [ ] **Step 3: 镜头卡（`ShotCard`）** — 结构保持，排版改为三层：
  1. **顶行**：镜号（等宽）、景别 / 运镜 / 机位 / 时长做成一排 `.chip`，推导标记（原文出处 / 系统补充）用 `--tone-explicit` / `--tone-inferred` 的小圆点 + 文字；
  2. **画面层**：画面描述正文 14px；氛围、音效、转场为辅助行（转场用 `--tone-transition`）；
  3. **声音层**：旁白与台词放进底部一块 `bg-muted/50 rounded-lg p-3`，旁白前加 lucide `Mic` 小图标、台词前显示说话人名（600）+ 类型 chip；台词与旁白文字用正文色，引用的原文句号用 `.uref` 链接样式（下划线虚线、悬停品牌色）。
  - 选中 / 跳转高亮（`is-flash`）改为 `box-shadow: 0 0 0 2px var(--brand-to)` 渐隐 1.6s。
  - 编辑态控件（`.ed`、`.ed--sel`、`.ed--area`、`.ed--var`、`@` 挂卡浮层 `.cpick`）：输入框与 shadcn `Input` 同外观（高 32px、`--input` 描边、聚焦 `--ring` 2px 外环）；浮层用 `--popover` 底、`shadow-lg`、圆角。
  - 锁定的字段前的 🔒 换 lucide `Lock`（12px、辅助色）。
- [ ] **Step 4: 验证与提交** — 13 套 ALL PASS（如有断言依赖被改掉的文字，同步改测试并在提交信息里说明）、lint、build；`grep -n "\.shot\b\|\.ep__\|\.sb__" src/index.css` 应无结果。

```bash
git add src/components/StoryboardView.tsx src/components/EpisodeView.tsx src/components/ShotCard.tsx src/styles/storyboard.css src/index.css
git commit -m "分镜视图换装：总览头部标签与动作按钮、统计小卡、分段控件切视图；集头折叠动效；镜头卡分三层（景别运镜时长小标签、画面、旁白与台词）、跳转高亮、编辑控件与挂卡浮层新外观"
```

（测试有改动时一并 `git add` 对应测试文件。）

---

### Task 3: 资产卡、原文溯源、渲染任务包、完整性检查、JSON

**Files:** Modify `AssetsView.tsx`、`SourceView.tsx`、`RenderView.tsx`、`VerificationPanel.tsx`、`src/styles/views.css`、`src/index.css`；测试按需

搬 `index.css` 中「资产卡」「原文溯源」「原始 JSON」「渲染任务包」「服务端验证报告」几段（约 779–903、963–1083）进 `views.css` 并重写，删原段。

- [ ] **Step 1: 资产卡** — 卡片网格 `grid gap-3 sm:grid-cols-2 xl:grid-cols-3`；卡头：类别图标（角色 `User`、场景 `MapPin`、道具 `Package`、生物 `PawPrint`）+ 名称 600 + ID 等宽；别名、外貌、服装、状态分行，标签用辅助色 12px；变体（服装 / 形态）做成 `.chip`。编辑态输入同 Task 2。
- [ ] **Step 2: 原文溯源** — 每句一行：左侧句号（`.unit__id` 等宽辅助色）、正文；被引用的句子左侧 2px `--tone-explicit` 竖条，未覆盖的句子 `--warning` 竖条；`unit--focus` 用 `bg-brand/10` 底 + 品牌色竖条，滚动定位保持。
- [ ] **Step 3: 渲染任务包（`RenderView`）** — 费用卡：合计 24px 600 `tabular-nums`，依据与保留意见折叠在「费用怎么算」里（`<details>` 换成同外观的折叠：标题行可点、`ChevronRight` 旋转）；clip 列表每行一张小卡（`.rclip`），勾选框与 `.rclip__pick` 保留；按钮换 `Button`。
- [ ] **Step 4: 完整性检查（`VerificationPanel`）** — 通过：一行 `--success` 小圆点 +「完整性检查通过」；不通过：卡片左侧 3px `--destructive` 条，标题「完整性检查没通过」，每条发现一行（严重度 `Badge`：硬性 `destructive`、提示 `secondary`），「显示 N 条提示」开关换 `Button variant="ghost" size="sm"`。所有「复验」「验证门」字样改「完整性检查」。
- [ ] **Step 5: JSON** — `pre` 用等宽 12.5px、`bg-muted/50`、圆角、`max-h-[70vh] overflow-auto`。
- [ ] **Step 6: 验证与提交**

```bash
git add src/components/AssetsView.tsx src/components/SourceView.tsx src/components/RenderView.tsx src/components/VerificationPanel.tsx src/styles/views.css src/index.css
git commit -m "分镜各页签换装：资产卡分类图标与变体标签、原文溯源出处与未覆盖竖条、渲染任务包费用卡与可折叠依据、完整性检查结果卡（说人话）、JSON 等宽代码块"
```

---

### Task 4: 时间轴画布与侧栏

**Files:** Modify `TimelineCanvas.tsx`、`CanvasPanels.tsx`、`src/styles/canvas.css`、`src/index.css`；测试按需

搬「时间轴画布」到「播放时的预览窗」几段（约 1175–1376）进 `canvas.css` 并重写，删原段。**只换配色、描边、悬停与工具条/侧栏外观，SVG 的几何与交互不改。**

- [ ] **Step 1: 画布底与泳道** — 画布底 `--background`，泳道交替行 `color-mix(in oklab, var(--foreground) 2.5%, transparent)`；泳道名一栏 `--card` 底、右侧 1px `--border`；刻度与网格线 `--border`、刻度文字 11px 等宽辅助色。
- [ ] **Step 2: 泳道配色统一** — 每类元素一个色相、填充用 18% 透明度、描边用实色 50%：集 `--secondary`、场景 `--ui-muted`、镜头 `--card` 加 `--border` 描边（原文出处镜头左边 3px `--tone-explicit`、系统补充 `--tone-inferred`）、旁白 / 台词 `--tone-transition`、BGM 情绪 `--brand-from`。
- [ ] **Step 3: 选中与悬停** — 悬停镜头描边加深；**选中镜头发光描边**：`stroke: var(--brand-to); stroke-width: 2; filter: drop-shadow(0 0 6px color-mix(in oklab, var(--brand-to) 55%, transparent));`；连线高亮 `.tlc__link--lit` 用 `--brand-to`。
- [ ] **Step 4: 播放头更醒目** — 竖线 2px 品牌渐变（SVG 里用 `linearGradient` 定义 `id="tlc-head"`，从 `--brand-from` 到 `--brand-to`；若当前播放头是 HTML 元素则用 `bg-brand`），顶部一个 10px 圆头带 2px `--background` 描边与阴影；`.tlc__clock` 时间读数等宽、`tabular-nums`。
- [ ] **Step 5: 底部工具条做成悬浮胶囊** — `.tlc__bar` 改为距底 16px 水平居中的胶囊：`rounded-full border bg-card/80 backdrop-blur-md shadow-xl px-2 py-1.5`，内部按钮换 `Button variant="ghost" size="sm"`（图标按钮 `size="icon"`），播放 / 暂停换 lucide `Play` / `Pause`，倍速做成小分段控件；编辑按钮组与播放组之间 1px 竖分隔线（`.tlc__editbar` 保留）。
- [ ] **Step 6: 侧栏** — `.tlc__panel` `--card` 底、左侧 1px `--border`；页签 `.tlc__tabs` 做成分段控件外观（同 Task 2 Step 1，按钮文字不变——测试按文字找页签）；关闭按钮 `✕` 换 lucide `X` 图标按钮（`aria-label="关闭画布（Esc）"`，`title` 保留）。侧栏内复用的原文 / 资产卡按窄宽排（保持原有收窄规则的意图）。
- [ ] **Step 7: 静帧、就地编辑、选区、预览窗** — 静帧缩略图圆角 6px、无图时虚线框 + `ImageOff` 图标；选区 `.tlc__rangeband` `bg-brand/12` 加两侧 1px 品牌色；预览窗 `.tlc__pip` 圆角 12px、`shadow-2xl`、字幕白字加 `text-shadow`。
- [ ] **Step 8: 「任务」「剧情」页（`CanvasPanels.tsx`）说人话与按钮** — 「转换」小节标题 →「生成」，「重新转换（新版本）」→「重新生成（新版本）」，说明里的「转换」→「生成」、「复验」→「完整性检查」；按钮换 `Button size="sm"`；版本按钮（`.tlc__vers` 里的 `vchip`）同章节页版本条外观；「主线剧情 / 创作限制」二段切换做成分段控件。
- [ ] **Step 9: 验证与提交** — 测试里按「重新转换」文字找按钮的地方同步改。

```bash
git add src/components/TimelineCanvas.tsx src/components/CanvasPanels.tsx src/styles/canvas.css src/index.css
git commit -m "时间轴画布换装：泳道统一配色与语义色、选中镜头发光描边、渐变播放头、悬浮胶囊工具条、侧栏分段页签与图标关闭；静帧、选区与预览窗新外观；任务页说人话（生成、完整性检查）"
```

（改到的测试文件一并 `git add`。）

---

### Task 5: 出片与配音合成面板、统一花钱确认

**Files:** Modify `FilmPanel.tsx`、`ComposePanel.tsx`、`src/compose.ts`、`src/film.ts`（只改文字）、`src/styles/film.css`、`src/index.css`、`tests/film.test.tsx`、`tests/compose.test.tsx`、`tests/flow.test.tsx`（若受影响）

搬「画布出片」一段（约 1427–末尾）进 `film.css` 并重写，删原段。

- [ ] **Step 1: 出片确认换 `MoneyConfirm`** — `FilmPanel` 里删掉 `ConfirmBox` 的自绘框，改为：

```tsx
<MoneyConfirm
  open={!!film.confirm && !!s}
  title={cf.kind === 'rest' ? `出剩余 ${rows.length} 段` : `出 ${cf.clipId}`}
  cny={cf.cny} spent={s.spent_cny} reserved={s.reserved_cny} budget={s.budget_cny}
  changed={cf.changed} rateNote={s.options.rate_note} action="确认出片"
  blocked={!!blocked} busy={film.busy}
  onConfirm={() => void film.confirmNow()} onCancel={film.cancelConfirm}>
  {cf.kind === 'clip' && cf.uncertain && <p className="text-destructive">这一段结果不明：厂商那边可能还有任务在跑或已扣费，请到厂商控制台核对，确认没有生成再重做。</p>}
  {!!rows.length && (
    <table className="film__rows w-full text-xs tabular-nums">
      <tbody>{rows.map((r) => <tr key={r.id}><td className="font-mono">{r.id}</td><td>{r.duration}s</td><td className="text-right">{yuan(r.cny)}</td></tr>)}</tbody>
    </table>
  )}
</MoneyConfirm>
```

（`cf`、`rows` 在 `film.confirm` 为空时不能解引用：先算 `const cf = film.confirm`，`open` 为假时传占位值，或只在 `cf && s` 时渲染组件——两种都可，**确认框关闭时要有退出动画**就选前者。）`MoneyConfirm` 自己算执行后累计与超上限，原 `ConfirmBox` 里的同类计算删掉。

- [ ] **Step 2: 合成确认换 `MoneyConfirm`** — `ComposePanel` 的 `ComposeConfirm` 同理：`title="合成整章"`、`cny={cf.cny}`、`spent={s.spent_cny}`、`budget={s.budget_cny}`、`rateNote={c.voices?.rate_note}`、`action="确认合成"`、`blocked={blockers.length > 0}`、`busy={c.busy}`；`children` 放一行「配音费用对应未缓存的 {c.preview.tts_chars} 字；合成本身不花钱。」

- [ ] **Step 3: 面板外观** — 出片页分区（设置、前置检查、主按钮、段列表、成片泳道说明）每区一张卡；设置表单控件同 shadcn 外观；主按钮（先试一段 / 出剩余各段）`Button` 默认样式并写金额；段列表每段一行（`.film__clip`）：状态点（未出 `--ui-muted`、排队/生成中 `--warning` 带 `animate-pulse motion-reduce:animate-none`、完成 `--success`、失败 `--destructive`、内容改过 `--tone-inferred`）+ 段号等宽 + 时长 + 金额 + 操作按钮；「原声静音」勾选保留。合成区（`.compose__run`、`.compose__table`、`.compose__play`）：音色表每行说话人名 + 下拉（`aria-label` 保持）；BGM 上传按钮换 `Button variant="outline"`；成片播放器圆角 12px；下载链接做成按钮外观（`a` 保留 `download` 属性）。成片泳道颜色进 `film.css` 用新变量。
- [ ] **Step 4: 说人话** — `compose.ts`：`composeBlockers` 里「打开「草稿合成」可用关键帧补位」→「打开「没出好的段先用图片代替」」，`finalText` 里「成片已过期：分镜、音色、BGM 或采用的视频改过，重新合成才会更新」→「内容改过，需要重新合成：分镜、音色、BGM 或采用的视频有变化」，`o.gate` 那条的「先在分镜页修好再合成」前缀文字若含「验证」改为「完整性检查没通过」；`film.ts`：`laneText` 的「已过期 · 仍可播放旧版」→「内容改过 · 仍可播放旧版」。`ComposePanel` 里「草稿合成」勾选的文字 →「没出好的段先用图片代替」。`FilmPanel` / `useFilm` 给用户看的「分镜未通过独立验证」→「分镜没通过完整性检查」（`useFilm.ts` 只改这一个字符串）。
- [ ] **Step 5: 测试同步** — `tests/film.test.tsx`、`tests/compose.test.tsx`：
  - 确认框断言改在 `document.body` 里找 `[data-testid="money-confirm"]`（`.film__rows tr` 也在 `document.body` 里找）；确认按钮按文字「确认出片」「确认合成」在 `document.body` 的按钮里找；取消按「取消」。
  - happy-dom 跑 Radix AlertDialog 若缺全局（`PointerEvent`、`DOMRect`、`ResizeObserver` 已在全局列表里），按 `tests/foundation.test.tsx` 测 `MoneyConfirm` 的方式补。
  - 被改文字的断言同步改字面（「已过期」→「内容改过」、「草稿合成」→新文字等），每处保留原意图。
- [ ] **Step 6: 验证与提交**

```bash
git add src/components/FilmPanel.tsx src/components/ComposePanel.tsx src/compose.ts src/film.ts src/useFilm.ts src/styles/film.css src/index.css tests/film.test.tsx tests/compose.test.tsx
git commit -m "出片与配音合成换装：花钱确认换成全站统一对话框（明细、合计、累计、上限、费率依据）；分区卡片、段状态点、音色与 BGM、成片播放与下载新外观；说人话（内容改过需要重新生成、没出好的段先用图片代替、完整性检查）"
```

---

### Task 6: 回归与验收准备（控制者做）

- [ ] `npm test`（13 个 ALL PASS）、`npm run lint`（0 error、6 warning）、`npx vite build`；`grep -nE "\.(tlc|film|compose|shot|ep|sb|acard|rend|rclip|vrf|src)__?" src/index.css` 只剩本计划不负责的部分。
- [ ] 请用户在浏览器（假出片、假配音）里看：分镜视图浅深两套、镜头卡三层排版、分段控件；资产卡、原文溯源、完整性检查；画布泳道配色、选中发光、渐变播放头、悬浮工具条、侧栏页签；出片页与确认对话框、配音合成区。
