# 内容限制设计

日期：2026-11-22　分支：langchain　状态：用户已确认方案（2026-11-22）

## 1. 目标与范围

违法内容直接拒绝生成分镜脚本和视频。只拦露骨与宣扬类，情节需要的一笔带过放行。

**拦截类别**（code 固定，界面显示中性类别名）：

| code | 类别名（zh / en） | 拦 | 放 |
|---|---|---|---|
| `sexual` | 色情 / Sexual content | 露骨性描写 | 亲密戏一笔带过、暗场 |
| `minor_sexual` | 涉及未成年人的性内容 / Sexual content involving minors | 任何程度 | — |
| `drugs` | 毒品 / Drugs | 制毒贩毒的具体方法、美化吸毒 | 情节里的吸毒、贩毒及其后果 |
| `political` | 现实政治 / Real-world politics | 针对真实政治人物、现实政治事件的内容 | 架空世界的政治、宫廷斗争 |
| `extremism` | 恐怖与极端主义 / Terrorism and extremism | 宣传、招募、袭击方法 | 情节里的恐袭事件本身 |

不在范围：图片审核（产品不生成图片，关键帧由用户上传；`/render/keyframes` 只返回提示词文本）、助手对话本身、音色与配音文本（配音文本来自已通过的分镜）。

## 2. 架构

新模块 `backend/safety/`：

- `categories.py`：上表 code 列表。
- `classifier.py`：`classify(text, *, chat) -> Verdict(blocked: bool, category: str|None, reason: str)`。用底层模型单独调用，系统提示写明 §1 尺度表，要求只输出 JSON `{"blocked":bool,"category":code|null,"reason":"≤80字"}`。解析失败或 category 不在表内 → 视为 `SafetyUnavailable`（不放行）。长文本按 6000 字切段（段落边界优先），逐段调用，任一段 blocked 即止。
- `blocklist.py` + `blocklist.json`：明确违规词表（每条带 category）。只在服务端，不进前端、不进语言包。命中即判 blocked，reason 为「命中词表」，不调模型。
- `store.py`：
  - 通过缓存 `data/safety/passed.json`：`sha256(规范化文本) → {at}`，上限 20000 条，超出按最早淘汰。
  - 拦截记录 `data/safety/blocks.jsonl`：`{id, at, user_id, novel_id, chapter_id, version_id?, clip_id?, stage: "convert"|"video", category, reason, excerpt(≤300字), hash, status: "blocked"|"released", released_by?, released_at?}`。
  - 放行表：被管理员放行的 hash 直接写入通过缓存（标 `released: true`，不被淘汰）。
  - 90 天保留：启动时与每次写入时清理 `at` 早于 90 天的拦截记录的 `excerpt`（记录本身留着供统计，摘录置空）。
- `gate.py`：两个入口，见 §3。返回 None（放行）或抛 `SafetyBlocked(category, block_id)` / `SafetyUnavailable`。

`SafetyBlocked` / `SafetyUnavailable` 均为 `UserError` 体系（走 `public_msg` 出口，不带厂商名）：

- `safety.blocked`：「内容不符合使用规范，已拒绝生成（类别：{category}）」，category 参数是类别 code，前端按 code 翻译；带 ref = block_id。
- `safety.unavailable`：「暂时无法完成内容检查，请稍后再试」。

## 3. 检查点

### 3.1 转换前（stage=convert）

位置：`server/app.py` `_run_version_job` 里，在 `_execute` 之前（任务已排队后台执行，不阻塞接口）。

- 文本 = 章节原文。规范化（去首尾空白、统一换行）后算 hash；hash 在通过缓存 → 放行。
- 先过词表，再过模型分类（按段）。通过 → 写缓存。
- 拦下 → 任务与版本状态 `failed`，`error_msg = safety.blocked`；写拦截记录；不进入转换，不计生成次数（见偏好记忆 spec 计数口径）。
- 分类不可用（模型错误、超时 30 秒、输出不合法）→ `safety.unavailable`，版本 `failed`。

### 3.2 视频提交前（stage=video）

位置：`render/runner.py` `_submit`，在 `request_builder` 组装出 `req` 之后、`provider.submit` 之前。失败走 `sess.submit_failed(root, clip_id, err)`，不付费。

- 一律过词表（检查 `req.prompt`）。
- 需要模型分类的情形：
  - 自由节点（用户手写提示词）；
  - 分镜段落，且所属版本 `edited_at` 非空（人工或助手改过）。
  未改过的分镜段落只过词表——其文字由已通过的章节转换而来。
- 分类按最终提示词 hash 走通过缓存。
- runner 的 tick 是单线程循环：分类调用超时 20 秒；不可用 → `safety.unavailable` 段失败，不卡住其他会话太久。

### 3.3 不扣费

- 被拦下时不发生生成，不产生生成费用。
- 分类调用的用量记账 `usage.record(purpose="safety", ...)`，计入后台成本统计，但 `usage.month_spent` 排除 `purpose in {"safety","preference"}`，不占用户月度上限。

## 4. 后台

- 新接口（仅管理员）：
  - `GET /admin/safety/blocks?status=&days=`：拦截列表（时间、用户名、作品、章节或片段、阶段、类别、理由、摘录、状态）。
  - `POST /admin/safety/blocks/{id}/release`：放行 → 记录状态改 released，hash 写入通过缓存，写审计日志 `safety.release`。
- 前端后台新增「内容拦截」页（`AdminNav` 加一项，带待处理计数），列表 + 放行按钮（二次确认）。
- 审计页能看到放行记录。

## 5. 前端

- 语言包新增 `safety.blocked`、`safety.unavailable`、五个类别名（zh/en）。不得含厂商名（现有守卫会查）。
- 版本失败、片段失败的现有显示位置照常显示这条消息，无需新组件。

## 6. 测试

全部用假分类器（`FakeChat` 返回指定 JSON），不调真实模型、不跑 smoke 脚本。

- 分类器：正常通过、拦截、输出非法 JSON、类别不在表内、超时 → 不可用；长文本切段任一段拦截即止。
- 词表命中不调模型。
- 转换：拦截时版本 failed + 消息 + 记录 + 未调用转换；通过写缓存，第二次同文本不再调用分类器；不可用 → failed。
- 视频：未改分镜只过词表；改过的版本与自由节点调用分类器；拦截时 `provider.submit` 未被调用。
- 放行：放行后同文本通过；改一个字重新检查；审计记录存在；非管理员 403。
- 90 天清理摘录。
- `month_spent` 排除 safety 用量。
- 厂商名守卫：新接口登记进 `test_vendor_guard.py`。
