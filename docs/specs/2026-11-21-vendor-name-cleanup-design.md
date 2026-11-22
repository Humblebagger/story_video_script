# 普通用户界面与接口去掉服务商 / 模型名字 设计

日期：2026-11-21　分支：langchain　状态：待设计审查（同日修订：用户对四个待定问题作了裁定——档位命名接受；音色这次保留；**管理员在产品界面里要能看到厂商名**，见 §9.2；未知拒绝的原话只在后台看）

相关设计：`docs/specs/2026-11-21-film-task-visibility-design.md`（§10.1、§10.2、§10.8 把这件事列为「另开一件事」）、`docs/specs/2026-11-12-minimax-provider-design.md`（厂商接入）、`docs/specs/2026-11-13-backend-i18n-design.md`（消息登记、子计划 4 E「普通用户看不到底层模型」）、`docs/specs/2026-11-21-admin-console-redesign-design.md`（后台）。

起因：`.superpowers/sdd/2026-11-21-film-task-visibility/acceptance-fable.md` 的缺口 1、5、6。

实施计划：`docs/plans/2026-11-21-vendor-name-cleanup.md`。

## 1. 背景

用户的硬性要求：**普通用户绝不能看到模型名或服务商名**（MiniMax、海螺、Seedance、火山 / 方舟 / Volc / ARK、豆包、DeepSeek、Anthropic、Claude 等任何厂商或模型标识）；管理员可以看到。

上一轮（出片任务可见性）只保证了新增内容不带，既有内容仍然带。2026-11-21 对前端 `src`、两份语言包、构建产物、后端 `server` / `render` / `assistant` / `pipeline` 的对外响应全面排查，泄露点如下。

### 1.1 界面上看得见的

| # | 位置 | 现象 |
|---|---|---|
| A1 | 出片面板设置区（`FilmPanel.tsx` 的 `Settings`） | 「厂商」下拉直接列 `minimax` / `seedance`；「档位」下拉列 `MiniMax H3`、`Seedance 2.0 fast` 等；设置摘要一行带档位名；回落提示「MiniMax 还没有开通，新会话先用 Seedance…」 |
| A2 | 片段卡、侧栏、合成面板的失败原因（`itemError`） | 「视频服务（MiniMax）账户余额不足…」「方舟返回 HTTP 502」「豆包语音拒绝了请求…」等，共 44 条带厂商名的文案（`srv.film.ark.*`、`srv.film.minimax.*`、`srv.tts.volc.*`） |
| A3 | 厂商原话直通 | `film.provider.rejected` 的模板就是 `{detail}`，厂商返回的错误文字原样显示；`cause_of` 对没有代码的异常给原文，可能带厂商接口域名 |
| A4 | 花钱确认框、配音面板 | 费率说明「2026-11 MiniMax 官方刊例价（H3 768P 0.50…）」「火山引擎豆包语音合成 2.0…」；「请到方舟控制台 / MiniMax 开放平台核对」 |
| A5 | 配音面板标题 | 「音色 · volc」 |
| A6 | 落地页 FAQ「支持哪些模型？」 | 「出片目前接入字节跳动 Seedance，配音接入豆包语音」 |
| A7 | 渲染任务包页（`RenderView.tsx`，`POST /render/plan`） | 费率档位「Seedance 2.0（标准）」「Seedance 2.0 mini」；费用依据「公开报道的方舟资费」；下载的 Markdown 标题「Seedance 2.0 生产包」、正文「把代码块整段发给 Seedance」 |

### 1.2 界面不显示、但浏览器拿得到的

| # | 位置 | 现象 |
|---|---|---|
| B1 | 两份语言包（随首屏脚本下发给所有人） | 上面所有文案，加上语言包的键名本身（`ark`、`minimax`、`volc`、`volc_tts`） |
| B2 | 出片会话视图（`render.session.view`，十几个接口的响应都是它） | 顶层 `provider`、`model`；`options.providers`、`options.models`（含标签）、`options.default_note`、`options.rate_note`；每次尝试原样下发：`video_url` / `last_frame_url`（带签名的厂商下载地址）、`usage`、`billing`（含厂商与模型）、`known_cost_cny`、`task_id`（厂商任务号） |
| B3 | 错误码 | `film.ark.*`、`film.minimax.*`、`tts.volc.*`，以及参数里的 `{"t":"ref","code":"console.minimax"}` |
| B4 | `GET /render/tasks` | `error.code` 可能带厂商前缀；`late` 条目的 `id` 末尾是厂商任务号 |
| B5 | `GET …/render/voices` | `provider: "volc"`、`rate_note` |
| B6 | `POST /render/plan` | `estimate.model`、`model_label`、`rate.source`、`tiers[].id / label`、`packs[].markdown` |
| B7 | 片段文件名 | `clips/E01-C01.<厂商任务号>.mp4`（出现在尝试的 `file` 与 `/files/…` 地址里） |
| B8 | 助手工具 `film_status` | 把段的原始 `error` 文字交给大模型，大模型可能转述给用户 |

### 1.3 已经干净、本次只加守卫的

- 转换任务与版本记录：`_public_manifest` 已去掉 `model`、`review_model`；调试日志只给管理员；模型服务错误已映射成 `llm.*`（文案只说「AI 服务」），原文只进日志。
- `GET /healthz`、`GET /auth/me` 不带模型名。账号菜单里的「当前模型」只在管理员登录时由 `/admin/service` 取值，值不在打包产物里。
- 运营后台（`frontend/src/components/admin/*`、`/admin/*` 接口）：允许保留，且已经在按需加载的块里（`tests/admin-bundle.check.mjs` 在查）。

## 2. 目标与非目标

目标：

1. 普通用户能拿到的一切里不出现厂商或模型标识。「能拿到的一切」指：**首屏下发的打包产物（含两份语言包的文案与键名）**，以及**所有非 `/admin` 接口的响应**（包括界面不显示的字段、错误响应的 `detail`、流式事件）。
2. 普通用户仍然能选出片档位：用中性名字，映射表在后端。
3. 已有的 `session.json`、已有的错误记录不迁移，照样能读、能显示。
4. 管理员仍然查得到厂商、模型与厂商原话，但只在后台。
5. 有自动守卫防回归：语言包、首屏打包产物、后端非管理接口响应三处都扫词表。

非目标（本次不做）：

- 让管理员在后台**改**档位映射（映射表是后端代码里的常量；后台只读展示）。
- 把音色 id 与音色名称（如 `zh_male_…_bigtts`、「云舟 2.0」）换成中性的（见 §9.3，用户已裁定这次保留）。
- 迁移或改写磁盘上的 `session.json`、历史片段文件名。
- 改后台（`/admin/*`、`components/admin/*`）里的厂商名。
- 改日志、代码注释、测试名、内部模块名（`render/providers/minimax.py` 等）、环境变量名。
- 后端命令行工具（`adapters/seedance.py` 的命令行入口、`render/smoke*.py`）的输出文件名。

## 3. 裁定总览

| # | 问题 | 裁定 |
|---|---|---|
| R1 | 管理员在产品界面里看到什么 | 中性名**后面附厂商名**（如「引擎 A · 标准（MiniMax H3）」）。首屏脚本对所有人是同一份，厂商名不能在里面；厂商文字只来自管理员专用接口 `/admin/service` 的数据，角色确认为管理员后才请求，普通用户永远不发这个请求（§9.2） |
| R2 | 词表放哪 | 一份 `backend/server/vendor_words.json`，后端出口、后端守卫、前端守卫共用（前端测试已有读 `../backend/server/messages_codes.json` 的先例） |
| R3 | 「厂商」「服务商」「provider」「大模型」这类通用词 | 允许。禁的是具体名字。凡是指向「厂商控制台」的文案改成「联系管理员」（普通用户没有控制台） |
| R4 | 档位怎么选 | 一个下拉，中性档位 id：`a-standard / a-fast / a-lite / b-standard / b-fast / b-lite`（测试与演示另有 `demo`），显示名「引擎 A · 标准」等。映射表在 `backend/render/tiers.py`。接口只收 `tier`，不再收 `provider`、`model` |
| R5 | 错误码命名空间 | 新代码一律中性：`film.vendor.*`（生成服务侧的失败）、`film.input.*`（提交前的输入检查）、`tts.vendor.*`。旧代码从登记表删除，另有一张「旧 → 新」对照表，出口处归一 |
| R6 | 厂商原话 | 不再给普通用户。改成中性文案加参考编号；原话（脱敏后）进错误记录，管理员在后台「错误」页按编号查 |
| R7 | 没有代码的旧错误文字 | 不外放，换成通用失败文案（白名单思路，同时关掉验收缺口 5） |
| R8 | 会话视图 | 出口过滤，不动存储：去掉 `provider`、`model`、`options.providers / models / default_note`；尝试按字段白名单下发；厂商任务号换成不可逆的短键；新增 `tier` 与 `options.tiers` |
| R9 | 费率说明、控制台名 | 费率说明改成一条中性文案（视频、配音各一条）；`console.*` 代码删除；厂商对象上的 `rate_note`、`console_name` 属性删除 |
| R10 | 渲染任务包 | 档位 id 改 `standard` / `lite`（请求里仍接受旧 id），标签、费用依据、Markdown 标题与正文都改中性说法 |
| R11 | 新出的片段文件名 | 用短键命名（`clips/<段>.<短键>.mp4`）；已有文件不改名 |
| R12 | 对用户内容要不要打码 | 不要。「方舟」「火山」「海螺」「豆包」都是小说里的常用词。打码只作用于错误文字（`error`、`detail`、消息参数里的原文）；分镜、提示词、小说正文、助手对话一概不碰 |
| R13 | 管理员从哪看 | `/admin/service` 增加出片线路表（档位 → 厂商、厂商内档位、厂商自己的档位名、密钥是否已配）与配音厂商；产品界面里按这张表给管理员附加显示（§9.2）；后台概览加一张只读卡片；厂商原话只在 `/admin/errors` |
| R14 | 守卫 | 三个：前端语言包测试（进 `npm test`）、首屏打包产物检查（构建后跑，同 `admin-bundle.check.mjs`）、后端非管理接口响应测试（投毒会话 + 路由清单） |

## 4. 词表与判定规则

`backend/server/vendor_words.json`：

```json
{
  "substr": ["minimax", "hailuo", "seedance", "doubao", "volcengine", "volces", "volc",
             "bytedance", "deepseek", "anthropic", "claude", "openai", "kling", "jimeng"],
  "word": ["ark", "gpt"],
  "cjk": ["海螺", "豆包", "方舟", "火山", "字节跳动", "即梦", "可灵", "深度求索"]
}
```

- `substr`：不分大小写，出现即命中。
- `word`：太短，只在前后都不是字母或数字时命中（`dark`、`park` 不算；`film.ark.x`、`ark:` 算）。
- `cjk`：出现即命中。
- 新接厂商或换模型时，把名字加进这份文件，三处守卫与出口打码同时生效。

`backend/server/public.py` 由它编出一个正则 `VENDOR_RE`，并提供 `redact(text)`（命中处换成 `***`）与 `find_vendor_words(json 值)`（守卫用）。

**适用边界**（R12）：`find_vendor_words` 只在守卫测试里对「不含用户内容的响应」或「用无关词汇造的夹具」使用；`redact` 只作用于错误文字。两者都不对分镜、小说、对话等用户内容使用。

## 5. 出片档位

### 5.1 映射表

`backend/render/tiers.py`（新）：

| 档位 id | 显示名（中 / 英） | 厂商 | 厂商内档位 |
|---|---|---|---|
| `a-standard` | 引擎 A · 标准 / Engine A · Standard | minimax | `minimax-h3` |
| `a-fast` | 引擎 A · 快速 / Engine A · Fast | minimax | `minimax-h3-highspeed` |
| `a-lite` | 引擎 A · 经济 / Engine A · Economy | minimax | `minimax-h3-lite` |
| `b-standard` | 引擎 B · 标准 / Engine B · Standard | seedance | `seedance-2.0` |
| `b-fast` | 引擎 B · 快速 / Engine B · Fast | seedance | `seedance-2.0-fast` |
| `b-lite` | 引擎 B · 经济 / Engine B · Economy | seedance | `seedance-2.0-mini` |
| `demo` | 演示（不联网、不花钱）/ Demo (offline, free) | fake | `fake-1` |

为什么保留两条「引擎」而不是只给「标准 / 快速 / 经济」三档：两家的能力不同（能否出原声、参考图上限、首帧与参考图能否同用、可选分辨率、价格），现在用户就在两家之间选，合并成三档等于替用户做了选择并砍掉一半能力。字母不透露是谁。

显示名是登记过的消息代码（`tier.a_standard` 等），前端按语言渲染，与现有后端文案机制一致。

函数：

- `resolve(tier_id) -> (provider, model)`，不认识抛 `KeyError`；
- `tier_of(provider, model) -> Optional[str]`，表里没有返回 `None`；
- `options() -> list`：界面可选的档位。只列「厂商在 `providers.names()` 里、且厂商对象建得起来（密钥已配）」的；每项 `{id, label, resolutions, default_resolution, cny_per_sec, audio_modes}`。`default_resolution` 的规则与 `resolve_settings` 一致（有 `720p` 用它，否则第一个）；
- `admin_table() -> list`：给管理员接口，每项 `{id, provider, model, vendor_label, key_configured}`。`vendor_label` 是厂商自己的档位名（取各厂商模块静态档位表里的 `label`，如 `MiniMax H3`、`Seedance 2.0 fast`；不需要密钥）。

### 5.2 存储与兼容

`session.json` 里仍然存 `provider`、`model`，**不改、不迁移**。`session.resolve_settings`、`SETTING_KEYS`、出片线程、计费都不动。换算只发生在接口层：

- 入：`RenderSettingsBody` 去掉 `provider`、`model` 两个字段，新增 `tier`，并禁止多余字段（带 `provider` / `model` 的请求得 422）。`tier` 经 `tiers.resolve` 变成 `{provider, model}` 再交给 `session.build`；不认识的档位 → 422 `film.settings.no_model`（「所选的视频档位已不可用，请在出片设置里重新选择」）。
- 出：视图里 `tier = tiers.tier_of(provider, model)`。旧会话的组合不在表里（例如以后下线了某个档位）时为 `null`，界面显示「原档位已不可用，请重选」，其余功能照常。

新建会话的缺省厂商与档位逻辑不变（`default_video_name()` 与厂商的 `default_model`）。

### 5.3 界面

设置区只剩一个「档位」下拉（原来的「厂商」下拉、换厂商提示、回落提示都删掉），选项来自 `options.tiers`。草稿里换了档位时，分辨率、每秒价格、声音模式的可选项取自那一档的 `resolutions / cny_per_sec / audio_modes`（原来换厂商后要先应用才能细调，现在一次选完）：

- 换档后当前分辨率不在新档里 → 草稿分辨率置为那一档的 `default_resolution`；
- 换档后当前声音模式不在新档里 → 草稿声音模式置为「全部配音」。

设置摘要：「设置 · 引擎 A · 标准 · 768P · 全部配音 · 上限 ¥200」。

回落提示（`default_note`）整个删除：它说的是「哪家没开通」，普通用户不需要知道；管理员在后台线路表里看密钥状态。

## 6. 错误码与文案

### 6.1 新代码

**生成服务侧（`film.vendor.*`）**

| 代码 | 参数 | 中文 |
|---|---|---|
| `film.vendor.no_key` | — | 视频生成服务还没有配置，请联系管理员 |
| `film.vendor.auth` | — | 视频生成服务鉴权失败，请联系管理员 |
| `film.vendor.balance` | — | 视频生成服务账户余额不足，暂时无法出片，请联系管理员 |
| `film.vendor.access_denied` | — | 视频生成服务拒绝访问，请联系管理员 |
| `film.vendor.limit_paused` | — | 视频生成服务已达到用量上限并暂停，请联系管理员 |
| `film.vendor.quota` | — | 额度不足或排队已满，持续失败请联系管理员 |
| `film.vendor.tier_unavailable` | — | 所选的视频档位暂时不可用，请换一个档位或联系管理员 |
| `film.vendor.connect_failed` | — | 连接视频生成服务失败 |
| `film.vendor.throttled` | — | 视频生成服务繁忙 |
| `film.vendor.http_ambiguous` | `status` | 视频生成服务返回 HTTP {status} |
| `film.vendor.unavailable` | `status` | 视频生成服务暂时不可用（HTTP {status}） |
| `film.vendor.not_json` | — | 视频生成服务返回了无法识别的响应 |
| `film.vendor.no_task_id` | — | 视频生成服务受理了请求却没有返回任务编号 |
| `film.vendor.no_result_url` | — | 视频生成服务没有返回结果地址 |
| `film.vendor.task_expired` | — | 任务超时 |
| `film.vendor.result_expired` | — | 结果地址已过期且重新查询失败 |
| `film.vendor.input_moderated` | — | 这一段的画面描述或参考图没通过内容审核：改写描述或换参考图后重试 |
| `film.vendor.copyright` | — | 这一段的描述可能涉及版权限制：改写后重试 |
| `film.vendor.output_moderated` | — | 生成的视频没通过内容审核：调整这一段的描述后重试 |
| `film.vendor.output_copyright` | — | 生成的视频可能涉及版权限制：调整这一段的描述后重试 |
| `film.vendor.rejected` | — | 视频生成服务拒绝了这次请求，请重试；仍失败请联系管理员（带参考编号） |
| `film.vendor.unknown_cause` | — | 未知原因 |

**输入检查（`film.input.*`）**：`label_first`（首帧）、`label_ref {id}`（参考图 {id}）、`bad_image {label}`、`unsupported_format {label, mime}`（「{label} 的格式 {mime} 不支持（只收 JPG、PNG、WEBP、HEIC、HEIF）」）、`corrupt_image {label}`、`image_too_big {label, mb}`（「{label} 有 {mb}MB，超过单张图片的大小上限」）、`prompt_too_long {max, len}`（「提示词超出上限 {max} 字（当前 {len} 字）」）、`needs_ratio`（「这个档位的参考生视频必须明确画幅，不支持自适应」）、`bad_ratio {ratio, options}`（「这个档位不支持画幅 {ratio}，可选：{options}」）、`request_too_big {mb}`（「请求体约 {mb}MB，超过上限：减少参考图或换小一些的图」）。

**配音（`tts.vendor.*`）**：`no_key`（配音服务还没有配置，请联系管理员）、`misconfigured`（配音服务配置有误，请联系管理员）、`unavailable {status}`、`rejected`（配音服务拒绝了这次请求，请重试；仍失败请联系管理员，带参考编号）、`rejected_http {status}`、`not_json`（配音服务返回了无法识别的响应）、`failed {code}`（配音合成失败（{code}））、`bad_audio`、`cut`、`connect_failed`、`incomplete`。文案统一说「配音服务」。

**其它**：

- `common.failed_generic`：「没有成功，请重试；仍失败请联系管理员」（没有代码的旧文字、认不出的代码用它）。
- `rate.video`：「按公开刊例价估算，未经账单核对」；`rate.tts`：「配音按字符计费，按公开刊例价估算，未经账单核对」。
- `tier.a_standard` … `tier.demo`：档位显示名。
- `film.fake.failed {detail}`：假厂商（测试、演示）的失败，文字是测试自己给的，不是厂商原话。

### 6.2 改字不改码的

| 代码 | 新中文 | 参数变化 |
|---|---|---|
| `film.submit.ambiguous` | 提交时连接中断，不确定生成服务是否已受理：这一段可能已计费，请联系管理员核对后再重做（{cause}） | 去掉 `console` |
| `film.submit.interrupted` | 提交时服务中断，不确定生成服务是否已受理；请联系管理员核对后再重做 | — |
| `film.poll.gave_up` | 多次查询都失败，已放弃；请联系管理员核对这个任务：{cause} | — |
| `film.session.none_pick` | 还没有出片会话：先到出片那一步选好档位 | — |
| `film.settings.no_native_audio` | 这个档位不出原声，可选：全部配音、静音 | — |
| `film.free.over_refs` | 参考超出当前档位上限（{need} / {max}） | — |
| `film.free.no_first_frame` | 当前档位不支持指定首帧 | — |

前端自己的文案（不是 `srv` 节点）里凡是「请到厂商控制台核对」的，同样改成「请联系管理员核对」；「厂商」下拉相关的键删除。清单在计划里。

### 6.3 删除的代码与对照表

从登记表删除：全部 `film.ark.*`、`film.minimax.*`、`tts.volc.*`，`film.provider.rejected`、`film.provider.http_rejected`、`film.provider.unknown`、`film.fake.unknown_model`、`tts.unknown_provider`、`console.*`、`rate.ark / minimax / fake / volc_tts / fake_tts`。

`server/messages.py` 新增 `LEGACY`（旧代码 → 新代码）与 `canonical(code)`。对照规则：

| 旧 | 新 |
|---|---|
| `film.ark.no_key`、`film.minimax.no_key` | `film.vendor.no_key` |
| `film.ark.auth`、`film.minimax.invalid_key` | `film.vendor.auth` |
| `film.ark.overdue`、`film.minimax.insufficient_balance` | `film.vendor.balance` |
| `film.ark.access_denied` / `limit_paused` / `quota` | `film.vendor.` 同名 |
| `film.ark.model_unavailable` | `film.vendor.tier_unavailable` |
| `film.ark.unknown_model`、`film.minimax.unknown_model`、`film.fake.unknown_model`、`film.provider.unknown` | `film.settings.no_model` |
| `film.{ark,minimax}.connect_failed` / `throttled` / `http_ambiguous` / `unavailable` / `not_json` / `no_task_id` / `no_result_url` | `film.vendor.` 同名 |
| `film.ark.task_expired` | `film.vendor.task_expired` |
| `film.minimax.url_expired` | `film.vendor.result_expired` |
| `film.ark.download_failed` | `film.provider.download_failed` |
| `film.ark.input_moderated`、`film.minimax.moderated` | `film.vendor.input_moderated` |
| `film.ark.copyright` / `output_moderated` / `output_copyright` | `film.vendor.` 同名 |
| `film.provider.rejected`、`film.provider.http_rejected` | `film.vendor.rejected` |
| `film.minimax.label_first` / `label_ref` / `bad_image` / `unsupported_format` / `corrupt_image` / `image_too_big` / `prompt_too_long` / `bad_ratio` / `request_too_big` | `film.input.` 同名 |
| `film.minimax.lite_needs_ratio` | `film.input.needs_ratio` |
| `film.minimax.bad_resolution` | `film.settings.bad_resolution` |
| `tts.volc.no_key` / `unavailable` / `rejected` / `rejected_http` / `not_json` / `failed` / `bad_audio` / `cut` / `connect_failed` / `incomplete` | `tts.vendor.` 同名 |
| `tts.volc.not_object` | `tts.vendor.not_json` |
| `tts.volc.failed_detail` | `tts.vendor.failed` |
| `tts.unknown_provider` | `tts.vendor.misconfigured` |
| `rate.ark`、`rate.minimax`、`rate.fake` | `rate.video` |
| `rate.volc_tts`、`rate.fake_tts` | `rate.tts` |

对照表的不变式（有测试）：每个旧代码都不在登记表里；每个新代码都在；新代码的参数集是旧代码参数集的子集（所以旧数据总能渲染）。`console.*` 没有对应的新代码：引用它的参数在出口处被丢掉（新模板不再有 `console`）。

### 6.4 厂商原话的去向（R6）

`render/providers/base.py` 新增 `vendor_reject(code, raw, *, who, secrets=())`：

1. 把 `who`（厂商名）与原话拼起来、脱敏、截断，写一条 WARNING 日志；
2. 如果装了记录钩子 `base.record_reject`（`server/app.py` 启动时装上，指向 `error_refs.record`），记一条错误记录，拿到参考编号；
3. 返回消息对象（带编号时附 `ref`）。

厂商模块里原来给 `film.provider.rejected {detail: 厂商原话}`、`tts.volc.rejected {code, detail}`、`tts.volc.failed_detail` 的地方都改走它。钩子缺省为空：厂商模块的单元测试不设数据目录，不会往真实的错误记录里写。

出片线程（`render/runner.py`）、合成（`render/mix.py`、`render/voice.py`）里 `cause_of(e)` 对没有代码的异常会给原文（可能带厂商接口地址）。这三处改用新函数 `messages.public_cause(e)`：有代码给紧凑消息，没有代码给 `film.vendor.unknown_cause`，原文由调用方写日志。`messages.cause_of` 本身不动（转换管线还在用，那里的原文是校验报告，不是厂商文字）。

「请联系管理员」类的已知错误（没配置、鉴权、余额、拒绝访问、用量上限）不记编号：原因从代码就清楚，管理员在后台线路表看是哪一家；厂商模块的日志里照旧有厂商名与原始错误码。

## 7. 出口过滤

### 7.1 消息对象

`server/public.py` 的 `public_msg(m)`：

1. 代码过 `canonical`；不在登记表里 → 整条换成 `common.failed_generic`；
2. 参数只留新代码登记的那几个（多余的丢掉，例如 `console`）；缺参数 → 整条换成通用文案；
3. 参数值：字符串打码；嵌套消息递归；`{"t":"ref"}` 的代码归一，认不出就置空；`{"t":"vendor"}` 的文字打码；金额原样；
4. 中文兜底 `message` 按归一后的代码与参数重写（存盘的旧兜底里有厂商名，不能原样带出）；
5. 参考编号保留（格式校验过的）。

`error_pair(obj)` 把一对 `error` / `error_msg` 换成净化后的；**只有文字、没有代码的 → 通用文案**（R7）。`scrub_errors(v)` 递归处理任意结构里的 `error` / `error_msg`、`step` / `step_msg`（步骤没有代码时置空而不是换成失败文案）与字符串型的 `detail`（打码）。

### 7.2 出片会话视图

`public.film_view(view, tier=…, tiers=…, rate_note=…)`：

| 位置 | 处理 |
|---|---|
| 顶层 `provider`、`model` | 去掉；新增 `tier` |
| `options.providers`、`options.models`、`options.default_note` | 去掉 |
| `options.rate_note` | 换成 `rate.video` |
| `options.tiers` | 新增（§5.1） |
| `options` 其余（当前档位的分辨率、价格、上限、声音模式、通常时长） | 原样 |
| 段、自由节点、失效段的 `attempts[]` | **白名单**：`state, cost_cny, file, last_frame, at, fingerprint, first_frame_used, style_ref, free_id, late, cancelled_at, settled_at, images`，加净化后的 `error / error_msg`，加 `task_id`（短键）。`video_url`、`last_frame_url`、`usage`、`billing`、`known_cost_cny` 以及将来新增的任何字段默认不下发 |
| 段、自由节点、`final` 的错误与步骤 | `scrub_errors` |

短键：`task_key(task_id) = "t" + sha256(task_id) 的前 16 位十六进制`；没有任务号时为 `null`。前端对 `task_id` 只做三件事——判空（能不能取消）、相等比较（自由节点的尝试对应目标段的哪一次；任务面板点名播哪一次）——同一个任务号在视图与任务列表里算出同一个短键，所以都不受影响。

`server/app.py` 里所有返回会话视图的地方（建会话、读、改设置、出片、取消、采用、静音、自由节点的增删改、发起合成）统一走一个 `_film_view(s, lenient=False)`；`render.session.view` 本身不改（后台、测试、助手内部仍可用完整视图）。

### 7.3 其它接口

| 接口 | 处理 |
|---|---|
| `GET /render/tasks` | `late` 条目的 `id` 用短键；`error`、`step` 用 `public_msg`。因为新错误码本身中性，失败原因现在**总能给出**（原来带厂商名的一律 `null`），只有段上没有任何错误信息时才是 `null`。每行新增 `tier`（这条任务所在会话的中性档位 id，可为 `null`）：管理员提示要靠它对上厂商（§9.2） |
| `GET /jobs` | 行为不变（带原文参数的仍为 `null`），词表改用共用的 `VENDOR_RE` |
| `GET …/render/voices` | 去掉 `provider`；`rate_note` 换成 `rate.tts` |
| `GET …/render/compose`（预览） | `final`、`report`、失败的语音条过 `scrub_errors` |
| `POST /render/plan` | §8 |
| 助手工具 `film_status` | 段的 `error` 换成净化后的中文兜底 |
| 错误响应（4xx 的 `detail`） | 源头已经中性（§6）；出片相关的 `_render_call`、`_tts` 再过一遍 `public_msg` 兜底 |

### 7.4 文件名

`session.clip_dest` 新文件用短键命名。已有文件不改名（旧文件名里的厂商任务号是一串不带厂商词的不透明字符，守卫也查这一点）。升级瞬间正在下载的那一段会按新名字重新下载一次，无害。

## 8. 渲染任务包（`POST /render/plan` 与 `RenderView`）

- `render/plan.py` 的 `TIERS` 键改成 `standard`、`lite`，标签「标准档」「轻量档」；`DEFAULT_TIER = "standard"`；另有 `LEGACY_TIERS = {"seedance-2.0": "standard", "seedance-2.0-mini": "lite"}`，请求里的旧 id 照样接受，响应里只出新 id。
- `RATE_SOURCE` 改成「2026-03 公开报道的资费，非官方定价页，未经账单核对」。
- `adapters/seedance.py` 的 `render_episode`（Markdown 生产包正文）：标题「视频生成生产包」，「发给视频生成模型」，小节名「时间轴提示词」。命令行入口与输出文件名不动。
- 前端：`RenderView` 的缺省档位 `standard`；`renderPack.tierDefault` 改「标准档」。
- 金样文件 `backend/tests/render/golden_plan_yao.json` 按同样的替换更新（只有这几处字面变化）。

## 9. 管理员可见（R1、R13）

### 9.1 管理员专用接口与后台

- `GET /admin/service` 增加：

  ```json
  "film": {
    "default_provider": "minimax",
    "fell_back": false,
    "tiers": [
      { "id": "a-standard", "provider": "minimax", "model": "minimax-h3", "vendor_label": "MiniMax H3", "key_configured": true }
    ],
    "tts": { "provider": "volc", "key_configured": true }
  }
  ```

  不新开接口：账号菜单本来就在角色确认为管理员后请求一次 `/admin/service`，线路表搭这一次请求。
- 后台概览页加一张「出片线路」卡片（在按需加载的后台块里）：档位 id → 厂商 → 厂商内档位 → 密钥是否已配。
- 厂商原话：后台「错误」页按参考编号查（已有页面，不改）。**产品界面里不显示原话**，对管理员也一样。
- 账号菜单里的「当前模型」不变。

### 9.2 产品界面里给管理员附加显示厂商名

用户裁定：管理员在产品界面里要直接看到是哪家，不用去对后台的表。

**硬约束（守卫不放松）**：首屏打包产物、两份语言包、所有非 `/admin` 接口的响应仍然不含厂商词。厂商文字**只能来自 `/admin/service` 的响应数据**；前端代码里不出现任何厂商字面量，不按档位 id 写死对应关系。

**拉取与缓存**

- 时机：沿用 `App.tsx` 现有的那次请求——`roleConfirmed`（`me()` 已返回）且角色是管理员时请求一次 `/admin/service`。角色未确认、或确认为普通用户时不请求（现有测试 `routing.test.tsx` 已在查，本次补「线路表」同样成立）。
- 存放：只在内存里（`App.tsx` 的 `svcInfo` 状态，带 `uid`）。不写 `localStorage` / `sessionStorage`。
- 失效：退出登录、换账号时清空（`svcInfo` 置空；另外读取处要求 `svcInfo.uid === user.id` 且 `user.role === 'admin'`，所以哪怕清空晚一拍也不会给错人看）。刷新页面后重新请求。
- 下发：新文件 `frontend/src/adminHints.tsx` 提供一个 React context。`App.tsx` 在满足上面条件时把 `svcInfo.info.film` 放进去，否则放 `null`。组件用两个钩子取：`useTierHint()` 返回 `(tier) => vendor_label | null`，`useTtsHint()` 返回配音厂商名或 `null`。普通用户、请求失败、旧后端没有 `film` 字段时都是 `null`，界面与普通用户完全一样。

**显示形式**：中性文字后面加括号，括号用现有的 `common.paren`（「（{text}）」），括号里的文字是接口给的原样字符串，不翻译。

**显示位置**

| # | 位置 | 管理员看到的 | 依据 |
|---|---|---|---|
| H1 | 出片面板设置区的档位下拉每个选项 | 引擎 A · 标准（MiniMax H3） | 选项的档位 id |
| H2 | 出片面板设置摘要一行 | 设置 · 引擎 A · 标准（MiniMax H3）· 768P · … | 会话的 `tier` |
| H3 | 片段卡、自由节点卡上的失败原因 | 视频生成服务账户余额不足…（MiniMax H3） | 会话的 `tier`；只在错误码以 `film.vendor.` 开头时加 |
| H4 | 出片面板选中段 / 自由节点详情里的失败原因、尝试表里每次失败的原因 | 同 H3 | 同 H3 |
| H5 | 任务面板「已结束」里出片条目的失败原因 | 同 H3 | 任务行的 `tier`（§7.3 新增） |
| H6 | 配音面板标题 | 音色（volc） | 配音厂商名 |
| H7 | 合成失败原因（合成面板、任务面板里的合成条目） | 配音服务暂时不可用…（volc） | 配音厂商名；只在错误码以 `tts.vendor.` 开头时加 |

不加的地方：通知与页内提示（文字一闪而过，且通知内容会进系统通知中心）、花钱确认框（紧挨着的设置摘要里已有）、渲染任务包页（那里的档位只是估价口径，不对应真实线路）。

已知的不精确：H3–H5 用的是会话**现在**的档位。失败之后管理员又改了档位，括号里显示的是新档位的厂商；取消后才出结果的那次按取消时的设置计费，括号里同样是现在的。要精确得把每次尝试的档位 id 下发，这次不做。

### 9.3 遗留项：音色（用户已裁定这次保留）

`GET …/render/voices` 的音色表是配音厂商的原始目录：id 形如 `zh_female_…_bigtts`，名称形如「云舟 2.0」「Vivi 2.0」。它们不含词表里的任何词，但内行能认出是哪家。本次保留；以后要换，需要做一层「公开 id ↔ 厂商 id」的双向映射（`PUT …/voices` 也要翻译回去），并给每个音色起中性名。

## 10. 守卫

| 守卫 | 文件 | 查什么 | 何时跑 |
|---|---|---|---|
| 语言包 | `frontend/tests/vendor-words.test.ts` | 两份语言包（文案与键名）里没有词表命中；反向对照：后台语言包（`components/admin/messages.*.ts`）与 `components/admin/pricing.ts` 里有命中（证明扫描有效） | `npm test` |
| 首屏打包产物 | `frontend/tests/vendor-bundle.check.mjs` | `index.html` 引用的脚本、样式及其静态依赖里没有词表命中；按需加载的块里有命中（后台） | `npm run build` 之后，与 `admin-bundle.check.mjs` 并列 |
| 后端响应 | `backend/tests/server/test_vendor_guard.py` | 往会话文件里投毒（真实厂商名、旧错误码、厂商原话、带签名地址、计费快照、无代码的原始文字），再以普通用户身份调用每一个非 `/admin` 的出片相关接口与任务接口，响应里没有词表命中，也没有 `video_url`、`billing`、`provider`、`"model"` 这些键；`/admin/service` 里有命中（反向对照）；**路由清单**：`app.routes` 里每条非 `/admin` 路由必须出现在测试的「已覆盖」或「豁免（返回用户内容或二进制）」名单里，新增接口不登记就红 | 后端全套 |
| 登记表 | `backend/tests/server/test_messages.py`（补） | 登记表所有代码名与中文兜底没有词表命中；对照表的不变式（§6.3） | 后端全套 |

现有 `frontend/tests/film-tasks.test.tsx` 里「文案扫厂商名」的自带词表改成读共用词表。

## 11. 已知限制

1. **未知拒绝看不到原因**：厂商拒绝但不在已知错误码里时，用户只看到「请重试 / 联系管理员（参考编号）」。原来能看到厂商原话（有时有用，例如指出提示词里的哪个词）。这是「绝不出现厂商名」的代价；常见的审核、版权、余额类都有专门文案。
2. **档位映射是常量**：换厂商、加档位要改代码并发版。
3. **旧文件名不改**：见 §7.4。
4. **音色**：见 §9.3。
5. **词表是人工维护的**：新接厂商时要记得加词。守卫的反向对照能发现「扫描失效」，发现不了「词表漏词」。
6. **管理员提示按会话现在的档位**：见 §9.2 末尾。失败原因的厂商原话对管理员也只在后台「错误」页。

## 12. 测试

| 层 | 文件 | 覆盖 |
|---|---|---|
| 出口函数 | `tests/server/test_public.py`（新） | 词表正则（大小写、短词边界、中文）；打码；短键稳定且不可逆推；`public_msg`（旧代码归一、丢多余参数、缺参数换通用、嵌套、原文打码、编号保留）；`error_pair`（无代码文字换通用）；`scrub_errors`；`film_view`（去字段、尝试白名单、新增字段默认不下发） |
| 登记表 | `tests/server/test_messages.py` | 新代码在、旧代码不在；对照表不变式；全表无厂商词；`public_cause` |
| 厂商 | `test_minimax.py`、`test_seedance.py`、`test_tts_volc.py`、`test_providers.py` | 错误映射到新代码；未知拒绝走 `vendor_reject`：消息不带原话，装了钩子时带编号且钩子收到原话；没有 `rate_note`、`console_name` |
| 档位 | `tests/render/test_tiers.py`（新） | 双向换算；表里每个组合在对应厂商模块的档位表里存在；`options()` 只列可用的；`admin_table()` |
| 出片线程、合成 | `test_runner.py`、`test_cancel_runner.py`、`test_mix.py`、`test_voice.py` | 提交不明、查询放弃的新文案与参数；无代码异常的原因是「未知原因」，原文在日志里 |
| 接口 | `test_render.py`、`test_render_free.py`、`test_film_tasks.py`、`test_compose.py` | 设置用 `tier`；带 `provider` 的请求 422；视图字段；任务列表的短键与失败原因；音色接口 |
| 守卫 | `tests/server/test_vendor_guard.py`（新） | §10 |
| 渲染任务包 | `tests/pipeline/test_offline.py`、`tests/render/test_compose.py` | 新档位 id、旧 id 兼容、金样 |
| 后台 | `tests/server/test_admin.py` | `/admin/service` 的线路表（含 `vendor_label`）；非管理员 403 |
| 管理员提示 | `tests/film.test.tsx`、`tests/film-tasks.test.tsx`、`tests/compose.test.tsx`、`tests/routing.test.tsx` | 给了提示数据时 H1–H7 各处出现接口给的厂商字样；没给时与普通用户一字不差；普通用户全程不请求 `/admin/service`；管理员登录后看得到，退出再以普通用户登录后看不到；首屏产物守卫照常通过 |
| 前端语言包 | `tests/srv-codes.test.ts`（不改，自动跟随）、`tests/vendor-words.test.ts`（新） | 语言包与登记表一致；无厂商词 |
| 前端界面 | `tests/film.test.tsx`、`graph-view.test.tsx`、`compose.test.tsx`、`routing.test.tsx`、`flow.test.tsx`、`server-msg.test.ts`、`film-lane.test.ts` 等 | 档位下拉（选项、换档带出分辨率与声音模式、原档位不可用）；夹具换成新视图形状；旧代码相关断言换成新代码 |
| 后台前端 | `tests/admin.test.tsx` | 线路卡片 |
| 构建产物 | `tests/vendor-bundle.check.mjs`（新）、`tests/admin-bundle.check.mjs` | §10 |

所有测试都不发真实网络请求，不读 `backend/.env`，不读真实 `session.json`。

验收：后端 `tests/pipeline`、`tests/server`、`tests/render`、`tests/assistant` 全部脚本无失败；前端 `npm test`、`npm run lint`（仍是基线 5 条警告）、`npm run build`、`node tests/admin-bundle.check.mjs`、`node tests/vendor-bundle.check.mjs`。
