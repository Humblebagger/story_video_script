# 两层偏好记忆设计

日期：2026-11-22　分支：langchain　状态：用户已确认方案（2026-11-22）
依赖：`2026-11-22-content-safety-design.md`（被拦下的不计数）

## 1. 目标

在现有小说长期记忆（人物状态 / 主线剧情 / 创作限制，`pipeline/novel_memory.py`）之后新增两层：

1. **用户偏好**（跨作品）：使用习惯与镜头画面偏爱，注入后续章节转换提示词。
2. **本作品镜头偏好**：作品累计生成满 100 次时生成，注入后续分镜转换与视频生成提示词。

优先级（写进注入块说明里）：原文 > 创作限制 > 本作品偏好 > 用户偏好。偏好只用于原文没写明的选择。

## 2. 线索（signals）

每部作品一份追加式日志 `novels/<nid>/preference/signals.jsonl`，只存结构化字段，不存正文。

| kind | 来源（唯一挂点） | 内容 |
|---|---|---|
| `shot_edit` | `server/app.py` `_save_version_doc`（手改与助手改共用） | 对比改前改后，逐镜记录变化字段：`duration_sec`、`shot_size`、`camera.*`、`time_of_day`、`weather`、`atmosphere.*`、`transition_out`；值为枚举或 ≤40 字截断 |
| `version_adopt` | `versions_adopt` | 采用的版本 id、该章当时版本总数 |
| `take_chosen` | 片段与自由节点 `.../chosen` 接口 | 该段尝试数、选中第几次（只在尝试数 ≥2 时记） |
| `assistant_ask` | 助手收到用户消息时 | 用户原话 ≤200 字 |
| `adopted_stats` | 采用版本时计算 | 该版本景别占比、运镜占比、平均时长 |

总结时提示模型：`adopted_stats` 是模型自己的输出，分量低于其他用户动作。

## 3. 计数

- 作品计数 `novel.preference.gen_count`；用户计数 `users/<uid>/preference.json` 的 `gen_count`。
- +1 的时点：章节转换任务进入 `_execute`（即已通过内容检查）；视频片段/自由节点 `sess.submitted` 成功写回后。被内容限制拦下、提交失败的不算。
- 作品层：首次在 100 触发，之后每 +100 触发（`gen_count >= next_at` 时触发并 `next_at += 100`）。
- 用户层：首次 30，之后每 +50。阈值放 `backend/pipeline/preference.py` 常量。
- 触发 = 提交后台总结任务（`_executor`），不阻塞当次生成。失败只记 `last_error`，等下次满数再试；同一层同时只跑一个。

## 4. 总结

`backend/pipeline/preference.py`（纯函数 + 一次小调用，测试用 FakeChat）：

- 作品层输入：该作品全部 signals（超过 400 条取最近 400 条）+ 上一版偏好文字。输出 JSON：`{"script": "≤300字，转换用", "video": "≤120字，视频画面短句"}`。
- 用户层输入：该用户所有作品最近 400 条 signals 合并 + 各作品现有偏好 + 上一版。输出 `{"text": "≤300字"}`。
- 超长截断；输出过 `public.redact`（不含厂商名）。
- 用量 `usage.record(purpose="preference")`，不计入用户月度上限（同 safety spec §3.3）。

## 5. 存储形状

```json
// novel.json 的 preference 键；users/<uid>/preference.json 同形（无 video 字段）
{
  "enabled": true,
  "gen_count": 137,
  "next_at": 200,
  "text": "…",            // 作品层为 script
  "video": "…",           // 仅作品层
  "source": "auto|manual",
  "suggestion": null,     // source=manual 时自动更新只写这里：{text, video?, at}
  "updated_at": "…",
  "last_error": null,
  "signals_since": null   // 仅用户层
}
```

## 6. 注入

- 转换：`pipeline/novel_memory.memory_blocks` 之后追加两块（`NovelContext` 加 `user_pref`、`novel_pref` 字段，由 `novels.novel_context` 填充，enabled=false 或为空不注入）：
  - `【本作品镜头偏好】…`
  - `【用户偏好】…`
  - 块首说明一句：「以下是用户偏好，只在原文和创作限制没有规定时参考。」
- 视频：`render/plan.clip_prompt`（分镜段）与自由节点提示词组装处，作品层 `video` 非空且 enabled 时追加 `\n画面偏好：{video}`；用户层不进视频。镜头自身已写明的设定优先（短句里说明）。
- 偏好短句**不计入**提示词指纹，只在提交时追加：偏好自动更新不会让已出片段变 stale。

## 7. 接口

用户本人：

- `GET/PUT /me/preference`：查看、手改（PUT 置 `source=manual`、清空 suggestion）。
- `POST /me/preference/clear`：清空用户层文字与 suggestion、计数归零，并记 `signals_since=now`；之后的用户层总结只读这个时间之后的线索（作品线索文件属于各作品，不在这里删）。
- `PATCH /me/preference {enabled}`、`POST /me/preference/suggestion/{accept|dismiss}`。
- 关闭（enabled=false）只停止注入，线索照常收集、计数照常增加，但不触发总结。
- 作品层同形：`/novels/{nid}/preference`（GET/PUT/PATCH/clear/suggestion），clear 同时删除 `signals.jsonl` 并归零计数。

响应过 `public` 出口；新接口登记进 `test_vendor_guard.py`。

## 8. 前端

- 设置入口：用户菜单新增「我的偏好」弹窗：文字框（可编辑保存）、开关、清空（二次确认）、建议更新卡（采纳/忽略）、进度「已生成 N 次，下次整理于 M 次」。
- 小说记忆面板新增「本作品偏好」区：两段文字（转换用 / 视频画面短句）、同样的操作、进度「已生成 37/100」。
- 语言包 zh/en；不含厂商名。

## 9. 测试（全部假模型）

- signals：手改与助手改各记 `shot_edit` 且只含变化字段；采用、选尝试（≥2 才记）、助手原话截断。
- 计数：转换与提交成功各 +1；拦截、提交失败不 +1；100/200 与 30/80 触发；触发不阻塞；并发只一个。
- 总结：输出截断、redact、非法 JSON 记 last_error。
- 手改后自动更新只写 suggestion；accept/dismiss。
- 注入：块顺序在现有三块之后、enabled=false 不注入、视频短句只在提交时追加且不改指纹。
- clear：作品层删 signals 归零；用户层归零且之后总结不读 signals_since 之前的线索。
- enabled=false：不注入、不触发总结、线索与计数照常。
- 月度上限排除 preference 用量。
