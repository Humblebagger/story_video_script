# 两层偏好记忆设计

日期：2026-11-22　分支：langchain　状态：用户已确认方案；已按 Fable 设计审查（`.superpowers/sdd/design-review-2026-11-22-fable.md`）修订
依赖：`2026-11-22-content-safety-design.md`（被拦下的不计数；偏好文字保存时过内容检查）

## 1. 目标

在现有小说长期记忆（人物状态 / 主线剧情 / 创作限制，`pipeline/novel_memory.py`）之后新增两层：

1. **用户偏好**（跨作品）：使用习惯与镜头画面偏爱，注入后续章节转换提示词。
2. **本作品镜头偏好**：作品累计生成满 100 次时生成，注入后续分镜转换与视频生成提示词。

优先级（写进注入块说明）：原文 > 创作限制 > 本作品偏好 > 用户偏好。偏好只用于原文没写明的选择。

## 2. 线索（signals）

每部作品一份追加式日志 `novels/<nid>/preference/signals.jsonl`。以结构化字段为主，另存少量用户原话（`assistant_ask`）与 ≤40 字的自由文字字段截断；偏好弹窗里如实说明收集了什么。

| kind | 来源（唯一挂点） | 内容 |
|---|---|---|
| `shot_edit` | `server/app.py` `_save_version_doc`，新增参数 `source: "manual"|"assistant"|"undo"` | 按镜头 id 配对改前改后，逐镜记录变化字段：`duration_sec`、`shot_size`、`camera.*`、`time_of_day`、`weather`、`atmosphere`、`transition_out`；枚举原值，自由文字截断 ≤40 字。新增、删除、拆分的镜头不记 |
| `version_adopt` | `versions_adopt` 且 `changed=True`（人工采用；首个成功版本的自动采用不记） | 采用的版本 id、该章当时版本总数 |
| `take_chosen` | 段 `.../clips/{id}/chosen` 与自由节点 `.../free/{id}/chosen` 接口 | 该段成功尝试数、选中第几次；只在成功尝试数 ≥2 时记；失败、取消、自由节点交付来的副本不算尝试 |
| `assistant_ask` | 助手收到用户消息时 | 用户原话 ≤200 字；两层偏好都关闭时不记 |
| `adopted_stats` | 同 `version_adopt` 时计算 | 该版本景别占比、运镜占比、平均时长 |

- 撤销（`source="undo"`）不记线索，并删去它撤销的那一条 `shot_edit`。
- 同一镜头同一字段 10 分钟内的连续修改合并为一条（保留首个旧值与最后的新值）。
- 总结提示词说明：`adopted_stats` 是模型自己的输出，分量低于其他用户动作。

## 3. 计数与触发

- **+1 的时点**：
  - 章节转换任务通过内容检查、进入 `_execute`；
  - 视频段或自由节点 `sess.submitted` 成功写回后。由 `Runner` 注入的 `on_submitted` 回调执行（同 `request_builder` 的注入方式），包住异常，不影响 tick 与并发计数。
  - 被内容限制拦下、提交失败的不算。
- **阈值**（常量在 `backend/pipeline/preference.py`）：作品层首次 100、之后每 +100；用户层首次 30、之后每 +50。
- **最少线索**：用户动作（`shot_edit` + `take_chosen` + `assistant_ask`）合计 ≥5 条才生成；不够则不生成、不推进 `next_at`，界面进度处显示「线索还不够」。
- **触发**：`gen_count >= next_at` 且 enabled 且线索够 → 提交到偏好专用线程池（`ThreadPoolExecutor(max_workers=1)`，不复用 `app._executor`）。同一层同一对象同时只跑一个，用内存集合加锁实现。
- **推进**：总结**成功写入后**才 `next_at += 步长`。失败记 `last_error`（消息对象），至少再过 10 次生成才重试。
- **关闭期间**：计数照常增加，但不触发、不推进 `next_at`；重新打开后的下一次计数即触发（若已满）。

## 4. 总结

`backend/pipeline/preference.py`（纯函数 + 一次小调用，测试用 FakeChat）：

- **作品层**：
  - 输入：该作品 signals（超过 400 条取最近 400 条）+ 上一版偏好。
  - 输出 JSON `{"script": "≤300字，转换用", "video": "≤120字，视频画面短句"}`。
- **用户层**：
  - 输入：该用户所有作品 `signals_since` 之后的最近 400 条 signals 合并，加上各作品现有偏好和上一版用户偏好。
  - 输出 `{"script": "≤300字"}`。
- **输出语言**：跟随存储的 `lang`。前端调偏好接口时都带 `lang`；助手消息已有 `lang` 字段，收到时也更新它；默认 `zh`。
- **输出处理**：超长截断，去掉 `{ref:X}`、`@图片N`、「参考图N」等占位符（复用 `compose.strip_placeholders`）。
  - 不做厂商名打码：偏好按用户内容处理，`public.redact` 会把「火山」等正常词改坏。
  - 总结提示词要求不写任何模型或服务商名。
- **内容检查**：输出过 `safety.check_sync`。被拦则丢弃本次结果，并记 `last_error = safety.blocked`。
- **记账**：用量记 `usage.record(purpose="preference")`，不计入用户月度上限。

## 5. 存储

- **作品层**：`novels/<nid>/preference/state.json`，与 `signals.jsonl` 同目录，不放进 `novel.json`。这样可以避免全局锁竞争、避免刷新 `updated_at`，也不会经 `GET /novels/{nid}` 漏出。
  - 删小说时，这个目录随 `rmtree` 一起清除。
- **用户层**：`users/<uid>/preference.json`。
- **加锁与写法**：
  - `pipeline/preference_store.py`（或 `server/preference.py`）用模块级锁统管读改写、追加和清空；
  - 状态文件原子写；
  - 追加写沿用 `usage.ensure_line_start` 的写法。

```json
{
  "enabled": true,
  "gen_count": 137,
  "next_at": 200,
  "script": "…",
  "video": "…",                // 仅作品层
  "source": "auto",            // auto | manual
  "suggestion": null,          // {script, video?, at}
  "updated_at": "…",
  "last_error": null,          // 消息对象，输出走 public.error_pair
  "last_error_at_count": null, // 失败时的 gen_count，用于「再过 10 次」
  "lang": "zh",
  "signals_since": null        // 仅用户层
}
```

**source 规则**：
- 手改（PUT）后 `source` 置为 manual，同时清空 `suggestion`。作品层的两段文字作为一个整体，只改其中一段也整体算 manual。
- `source=manual` 时，自动总结只写 `suggestion`。
- 采纳建议（accept）后，用建议覆盖正文，`source` 回到 auto，清空 `suggestion`。
- 忽略建议（dismiss）只清空 `suggestion`。

## 6. 注入

### 6.1 转换

- `NovelContext` 新增 `user_pref`、`novel_pref` 两个字段，由 `novels.novel_context` 填充。
- `empty()` 把这两个字段算进去，避免作品没有其他记忆时偏好被吞掉。
- 在 `memory_blocks` 现有三块之后追加以下内容；enabled=false 或文字为空时不注入：
  - 块首一句：「以下是用户偏好，只在原文和创作限制没有规定时参考。」
  - `【本作品镜头偏好】{novel_pref.script}`
  - `【用户偏好】{user_pref.script}`
- 带入偏好时，进度事件另发一条 `job.event.preference`。

### 6.2 视频

**唯一出片路径**：`_render_request` → `compose.request_for`（段）或 `compose.request_for_free`（自由节点）。`render/plan.clip_prompt` 不改，它只服务于渲染任务包和人读版生产包。

**传入与追加**：
- `_render_request` 读作品层偏好，enabled 且 `video` 非空时，作为新参数 `pref_video` 传给两个组装函数。
- 追加的文字是 `\n画面偏好（镜头自身已写明的设定优先）：{video}`。
  - 段：在 `request_for` 的过期判断之后、构造 `ClipRequest` 时，追加到 `c["prompt"]` 末尾；
  - 自由节点：在 `request_for_free` 里追加到正文之后、交给 `rewrite` 之前。

**不影响已出片段**：
- 偏好短句**不计入指纹**，偏好更新不会让已出片段变成过期。
- 内容检查用的 hash 也不包含它，见内容限制 spec §3.2。

**提示词与界面一致**：
- 该次尝试上记 `pref_video_hash`，并加进 `ATTEMPT_KEYS` 白名单。
- 界面在这次尝试的提示词下方显示「已附加画面偏好」，保持「看到的提示词就是发出去的」这一约定。

**验收点**：不传 `pref_video` 时，`tests/render/golden_clips.py` 的黄金文件保持不变。

### 6.3 视频短句的保存约束

无论是手改还是自动生成，`video` 字段保存时都要：
- 截断到 ≤120 字；
- 去掉占位符；
- 过 `safety.check_sync`。

被拦下时拒绝保存，接口返回 422 和 `safety.blocked`。`script` 字段同样过内容检查。

## 7. 接口

用户本人；请求体都可带 `lang`。

| 方法与路径 | 作用 |
|---|---|
| `GET /me/preference` | 返回状态（不含内部字段 `last_error_at_count`）、线索条数、是否够数 |
| `PUT /me/preference {script}` | 手改 |
| `PATCH /me/preference {enabled}` | 开关 |
| `POST /me/preference/suggestion/accept`、`POST …/dismiss` | 采纳或忽略建议 |
| `POST /me/preference/clear` | 清空，见下 |

**用户层清空**：
- 清空 `script` 与 `suggestion`，`gen_count` 归 0，`next_at` 重置为 30，`signals_since=now`；
- 把该用户各作品线索里 `assistant_ask` 的原话字段抹掉，其余结构化字段保留。

**作品层**：`/novels/{nid}/preference`，提供同样的 GET / PUT `{script, video}` / PATCH / suggestion / clear。
- 作品层清空会删除 `signals.jsonl`，`gen_count` 归 0，`next_at` 重置为 100。

**出口与守卫**：
- 响应过 `public` 出口：`last_error` 用 `public.error_pair`，`script`、`video`、`suggestion.*` 是用户内容，不打码。
- `test_vendor_guard.py` 登记这些接口，并把上述字段登记为用户内容字段。

## 8. 前端

**我的偏好**：用户菜单新增「我的偏好」弹窗，包含：
- 文字框，可编辑保存；
- 开关；
- 清空按钮，二次确认；
- 建议更新卡，可采纳或忽略；
- 进度「已生成 N 次，下次整理于 M 次」，线索不够时显示「线索还不够」；
- 一段收集说明：记录哪些镜头修改、选片和助手原话，以及关闭和清空分别会怎样。

**本作品偏好**：小说记忆面板新增「本作品偏好」区，显示两段文字（转换用 / 视频画面短句），提供同样的操作，进度显示为「已生成 37/100」。

**出片尝试**：附加过偏好的那次尝试，在提示词下方显示「已附加画面偏好」。

**语言包**：zh/en 两份都加，不得含厂商名。

## 9. 测试（全部假模型）

**线索**
- 手改与助手改各记一条 `shot_edit`，且只含变化字段；
- 撤销不记，并删去被撤销的那一条；
- 10 分钟内的连续修改合并为一条；
- 人工采用才记，自动采用不记；
- 选片只在成功尝试 ≥2 时记；
- 助手原话截断；两层都关闭时不记。

**计数**
- 转换与提交成功各 +1，拦截和提交失败不加；
- `on_submitted` 抛错不影响 tick；
- 在 100/200 与 30/80 触发；线索不够不触发；
- 成功写入后才推进；失败后 10 次内不重试；
- 关闭期间不触发，打开后的下一次计数触发；
- 同一对象只跑一个总结任务。

**总结**
- 输出截断、去占位符，不做厂商打码（「火山」原样保留）；
- 内容检查拦截时丢弃结果；非法 JSON 时记 `last_error`；
- 输出语言跟随 `lang`。

**手改与建议**
- 手改后自动更新只写 suggestion；
- accept 回到 auto，dismiss 只清空建议。

**注入**
- 只有偏好、没有其他记忆时也注入；
- 块顺序在现有三块之后；enabled=false 时不注入；
- 视频短句只在 `request_for` / `request_for_free` 追加，不改指纹，尝试上记了 `pref_video_hash`；
- 不传偏好时黄金文件不变；
- `video` 超长截断、占位符被去掉、违规时 422。

**清空**
- 作品层：删除 signals，计数归 0，`next_at` 回到 100；
- 用户层：计数归 0，`next_at` 回到 30，之后的总结不读 `signals_since` 之前的线索，且各作品 `assistant_ask` 的原话被抹掉。

**其他**
- 并发：追加写与清空同时进行不出错；
- 月度上限排除 preference 用量；
- 删除小说时偏好目录一并删除。
