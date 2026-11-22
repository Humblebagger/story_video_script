# 内容限制设计

日期：2026-11-22　分支：langchain　状态：用户已确认方案；已按 Fable 设计审查（`.superpowers/sdd/design-review-2026-11-22-fable.md`）修订

## 1. 目标与范围

违法内容直接拒绝生成分镜脚本、视频与配音。只拦露骨与宣扬类，情节需要的一笔带过放行。

**拦截类别**（消息代码 `safety.category.<code>`，界面显示类别名）：

| code | 类别名（zh / en） | 拦 | 放 |
|---|---|---|---|
| `sexual` | 色情 / Sexual content | 露骨性描写 | 亲密戏一笔带过、暗场 |
| `minor_sexual` | 涉及未成年人的性内容 / Sexual content involving minors | 任何程度 | — |
| `drugs` | 毒品 / Drugs | 制毒贩毒的具体方法、美化吸毒 | 情节里的吸毒、贩毒及其后果 |
| `political` | 现实政治 / Real-world politics | 针对真实政治人物、现实政治事件的内容 | 架空世界的政治、宫廷斗争 |
| `extremism` | 恐怖与极端主义 / Terrorism and extremism | 宣传、招募、袭击方法 | 情节里的恐袭事件本身 |
| `unspecified` | 不符合使用规范 / Policy violation | 底层模型服务拒绝处理该文本（见 §2.3） | — |

不在范围：图片（产品不生成图片，关键帧由用户上传，`/render/keyframes` 只返回提示词文本）；助手对话本身（助手改出的分镜在出片与合成时把关，见 §3）。

## 2. 架构

新包 `backend/safety/`。

### 2.1 词表 `blocklist.py` + `blocklist.json`

明确违规词，每条带 category。只在服务端，不进前端、不进语言包。命中即 blocked，reason 固定为消息代码 `safety.reason.blocklist`，不调模型。

### 2.2 分类器 `classifier.py`

`classify(text) -> Verdict(blocked, category, reason)`。

- 专用 `ChatInvoker`：关 thinking、`temperature=0`、`max_tokens=200`、`transport_retries=0`；`pipeline/chat.build_chat_model` 新增请求超时参数，分类器传 15 秒。单段请求超时 15 秒（网络阶段），无重试；不支持 thinking 的错误不做兼容重试，直接按不可用处理。
- 系统提示写明 §1 尺度表；要求只输出 JSON `{"blocked":bool,"category":code|null,"reason":"≤80字，概括原因，不得引用原文"}`。
- 长文本按 6000 字切段（段落边界优先），逐段调用，任一段 blocked 即止。
- 解析失败、category 不在表内、超时、其他模型错误 → `SafetyUnavailable`。

### 2.3 底层模型拒答

分类调用收到 `llm.content_blocked`（`pipeline/chat.py` 现有映射）→ 判为 blocked，category=`unspecified`，reason=`safety.reason.model_refused`，照常写拦截记录。

转换过程中出现的 `llm.content_blocked`（已有行为）保持原样显示，同时写一条拦截记录（stage=convert，category=unspecified），让管理员可见；这类记录的「放行」只翻转缓存，不能让底层模型改变主意，后台在该记录旁显示「模型服务拒绝，放行无效」并禁用按钮。

### 2.4 结论缓存与拦截记录 `store.py`

- 模块级锁 + 原子写（临时文件后 rename）。
- `data/safety/verdicts.json`：`hash → {verdict: "pass"|"block", block_id?, policy, released?, at}`。
  - `hash = sha256(规范化文本)`，规范化 = 去首尾空白、统一换行。
  - `policy = 系统提示版本号 + 词表文件 hash`；policy 不等于当前值的条目视为不存在（词表或尺度更新后自动失效），`released: true` 的条目永不失效。
  - 上限 20000 条，超出按 `at` 最早淘汰（released 不淘汰）。
  - 缓存全站共享（只按文本 hash）：管理员为甲放行的文本，乙提交同样文本也通过。这是有意的。
- `data/safety/blocks.json`（整份 JSON，原子写）：`{id, at, last_at, hits, user_id, novel_id, chapter_id, version_id?, clip_id?, stage: "convert"|"video"|"tts", category, reason, excerpt(≤300字), hash, status: "blocked"|"released", released_by?, released_at?}`。
  - `id` 用 `error_refs.new_ref()` 生成（符合出口的 `[0-9A-Z]{1,16}`）。
  - 同一 hash 再次被拦 → 返回同一个 `block_id`，`hits += 1`、`last_at` 更新，不新增记录、不再调模型。
- 清理：启动时 + 每天一次，`at` 早于 90 天的记录清空 `excerpt` 与 `reason`（记录保留供统计）。用户删除作品或账号时，对应记录的 `excerpt`、`reason` 同时清空。

### 2.5 判定入口 `gate.py`

统一顺序：**结论缓存（含放行）→ 词表 → 模型分类**。

- `check_sync(text, ctx) -> None`：用于转换任务、合成任务、保存偏好文字（都已在后台或允许几秒）。拦截抛 `SafetyBlocked(category, block_id)`，不可用抛 `SafetyUnavailable`。
- `lookup(text) -> "pass"|("block", block_id, category)|None` + `classify_async(text, ctx)`：用于出片 runner，见 §3.2。

两种异常均为带代码的 `UserError`：

- `safety.blocked`：「内容不符合使用规范，已拒绝生成（类别：{category}）」。`category` 参数传 `ref("safety.category.<code>")`，前端按现有 `t === 'ref'` 渲染；消息带 `ref = block_id`。
- `safety.unavailable`：「暂时无法完成内容检查，请稍后再试」。

登记步骤：`server/messages.py` 登记全部代码（`safety.blocked`、`safety.unavailable`、`safety.category.*`、`safety.reason.*`、`job.event.safety_check`、`film.safety_checking`；不登记 `safety.category` 本身，避免前缀冲突）→ `python -m server.messages --write` 更新 `messages_codes.json` → 前端 zh/en 的 srv 节点。

## 3. 检查点

### 3.1 转换前（stage=convert）

位置：`server/app.py` `_run_version_job`，在 `_execute` 之前（接口与助手都经 `_start_version` → 这里，唯一路径）。

- 检查文本两份，分别 `check_sync`：
  1. 章节原文（按段）；
  2. 用户手写的注入文本拼接：资产卡描述、创作限制、全书梗概、章节摘要、人物生命周期备注、`style_prefix`、两层偏好文字。平时命中缓存，零成本。
- 检查前发进度事件 `job.event.safety_check`。
- 拦截或不可用 → 现有 `except` 分支（`app.py:719-732`）收尾为 failed 并保留消息与编号；不进入转换，不计生成次数。

### 3.2 视频提交前（stage=video）

位置：`render/runner.py` 提交循环，在 `begin_submit` **之前**。文本用会话里存的 `c["prompt"]`（段）或自由节点的 `node["prompt"]`，不含偏好短句（偏好短句保存时单独检查，见偏好 spec §6）。

- 所有段与自由节点一律按「缓存 → 词表 → 分类」，不区分版本是否编辑过。
- `Runner` 新增注入的 `safety_check` 回调（与 `request_builder` 同样方式，测试可替换），tick 线程里只做 `lookup`（缓存 + 词表，毫秒级）：
  - pass → 继续 `_submit`；
  - block → `sess.submit_failed(root, c["id"], SafetyBlocked(...))`（无 pending 尝试时也能正确置失败），不付费；
  - 未知 → 调 `classify_async` 把分类交给**专用线程池**（`safety` 模块自己的 `ThreadPoolExecutor(max_workers=2)`，不复用 `app._executor`），本轮跳过这一段（写法同 `sess.waiting_on_relay`），下一轮再 `lookup`。同一 hash 同时只排一个分类任务。
  - 分类不可用 → 结论表记 `unavailable`（不缓存为结论，只记最近失败时间）；该段 `submit_failed(SafetyUnavailable)`。
- 等待分类期间段状态保持 queued，界面显示 `film.safety_checking`「内容检查中」（会话视图按 runner 暴露的待检查集合标注）。
- `_submit` 内部不加检查，避免 `begin_submit` 之后的长窗口被 `recover` 误标为「待核对」。

### 3.3 合成配音前（stage=tts）

位置：`server/app.py` `_compose_start`（合成在后台线程，可同步检查）。

- 版本 `edited_at` 非空时，对配音全文（台词 + 旁白拼接）`check_sync`；未编辑版本的配音文字来自已通过检查的原文转换，跳过。
- 拦截 → 合成失败并显示 `safety.blocked`；不调用配音厂商。

### 3.4 不扣费

- 被拦下时不发生生成，不产生生成费用。
- 分类调用记账 `usage.record(purpose="safety", ...)`，计入后台成本统计；`usage.month_spent` 排除 `purpose in {"safety","preference"}`，不占用户月度上限。被拦结论有缓存，重复提交不再产生分类费用。

## 4. 后台

- 接口（仅管理员；`test_vendor_guard.py` 中进 `EXEMPT` 并写理由「管理接口」）：
  - `GET /admin/safety/blocks?status=&days=&ref=`：拦截列表（时间、用户名、作品、章节或片段、阶段、类别、理由、摘录、次数、状态），支持按编号查。查看记审计 `view_safety_blocks`。
  - `POST /admin/safety/blocks/{id}/release`：放行 → 状态 released，结论缓存该 hash 改为 pass 且 `released: true`；审计 `release_safety_block`。category=unspecified 且来自模型拒答的记录不可放行（409）。
- 后台错误页按编号查询时，若 `/admin/errors/{ref}` 无此编号，前端再查拦截列表（`?ref=`），找到则跳到「内容拦截」页对应行。
- 前端后台新增「内容拦截」页（`AdminNav` 加一项，带未放行计数）：列表、放行按钮（二次确认），按钮旁说明「放行后需用户重新发起转换或出片」。

## 5. 前端（用户侧）

- 语言包 zh/en 新增 §2.5 列出的代码；不得含厂商名（现有守卫会查）。
- 版本失败、片段失败、合成失败的现有显示位置照常显示；排队段显示「内容检查中」。

## 6. 使用条款（用户待办）

上架前在使用条款里告知：被拦截内容的摘录会保留 90 天，可由管理员查看，用于误拦复核。本计划不改条款页面。

## 7. 测试

全部用假分类器（`FakeChat` 返回指定 JSON 或抛指定错误），不调真实模型、不跑 smoke 脚本。

- 分类器：通过、拦截、非法 JSON、类别不在表内、超时 → 不可用；`llm.content_blocked` → unspecified 拦截；长文本切段任一段拦截即止。
- 顺序：放行条目先于词表；词表命中不调模型；policy 变化使旧结论失效、released 不失效；被拦结论缓存，重复提交返回同一 block_id 且 hits+1、不再调模型。
- 转换：原文拦截、注入文本（资产卡）拦截都使版本 failed + 消息 + 编号，且未调用转换；通过写缓存，同文本第二次不调分类器；不可用 → failed。
- 视频：tick 中不调用分类器（只 lookup）；未知结论排进专用池、本轮跳过且段仍 queued、未调用 `begin_submit`；下一轮按结论提交或失败；拦截时 `provider.submit` 未被调用；同一 hash 只排一个任务。
- 合成：编辑过的版本配音文字拦截时不调配音；未编辑版本跳过检查。
- 放行：放行后同文本通过；改一个字重新检查；审计记录存在；模型拒答记录放行 409；非管理员 403。
- 90 天清理摘录与理由；删除作品时清空对应摘录。
- `month_spent` 排除 safety 用量。
- 并发：两个线程同时写结论缓存不丢条目。
