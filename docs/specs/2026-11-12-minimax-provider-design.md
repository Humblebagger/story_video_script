# 新增视频厂商 MiniMax H3（与 Seedance 并存）设计

日期：2026-11-12　状态：审查修订后（见文末修订记录）

## 1. 目标与范围

- 出片多一家厂商 MiniMax（海螺 H3 系列），与现有 Seedance 并存。用户在出片设置里切换，会话里各段照常按厂商记账、出片、接力。
- **系统缺省厂商改为 MiniMax**（`minimax-h3` + `768P`），只影响新建的出片会话；已有会话保持原厂商，不迁移（§3.1）。
- 档位：`MiniMax-H3`（默认）、`MiniMax-H3-Highspeed`、`MiniMax-H3-Lite`。`MiniMax-H3-Max` 这次不接，理由是参考图按每张 ¥0.50 收费，且自动扩写提示词会改掉分镜原意。
- 不在范围内：
  - 出片画布、节点图、自由节点、预算与确认、导出的流程不变；只有 §5 列出的厂商无关改动。
  - 不用 MiniMax 的参考视频、参考音频、尾帧（`last_frame`）、回调、再生成接口。
  - 不改 Seedance 的行为（它从缺省厂商变为可选厂商）。
  - 不改「生产包」（RenderView 的提示词包导出）里写死的 Seedance 档位：那是给外部工具用的提示词包，与出片会话的厂商无关。
- 依据：本文的接口与价格事实核对自 platform.minimax.cn 官方文档，核对日期 2026-11-12。核对过的页面是 `guides/video-generation`、`api-reference/video-generation-v2-create`、`api-reference/video-generation-v2-query`、`guides/pricing-paygo`。

## 2. 官方事实摘要（实现以此为准）

| 项 | 事实 |
|---|---|
| 创建 | `POST {base}/v2/video_generation` → `{"task_id"}`；body：`model`、`content[]`、`resolution`、`duration`（整数）、`ratio`、`aigc_watermark`、`response_format` |
| content | 元素 `{"type":"text","text":…}` / `{"type":"image_url","image_url":{"url":…},"role":…}`；role 用 `first_frame` / `reference_image` |
| 互斥 | 图生视频（first_frame/last_frame）与多模态参考（reference_image ≤ 9）不能同用 |
| ratio | `adaptive / 21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16`。图生时由图决定，传了也会被忽略。参考生默认 adaptive，Lite 不支持 adaptive，必须给比例 |
| 查询 | `GET {base}/v2/query/video_generation/{task_id}` → 缺省 `{"task":{status, content.url, usage, error}}`；状态 `queued/running/succeeded/failed/cancelled`；只能查 7 天内的任务；官方建议每 10 秒查一次 |
| 结果 | `content.url` 是限时下载地址，过期后重新查询可拿到新地址。不返回尾帧图 |
| 图片 | 公网 URL / `mm_file://` / `data:image/<小写格式>;base64,…`；格式 JPG/JPEG/PNG/WEBP/HEIC/HEIF；单张 ≤ 30MB；宽、高 ∈ [256, 5760]；宽/高 ∈ [0.4, 2.5]；请求体 ≤ 64MB；每个 text ≤ 7000 字 |
| 分辨率/时长 | H3：768P / 2K；Highspeed 与 Lite：480P / 768P。时长 4–15 秒 |
| 错误 | 400(2013)、401(1004)、402 余额不足(1008)、422 敏感内容(1026，提交时或任务失败时都可能出现)、429(1002)、500(1000)、529 过载 |
| 价格（元/秒，输出） | H3：2K 0.80、768P 0.50；Highspeed：768P 0.40、480P 0.26；Lite：768P 0.26、480P 0.16 |
| 图片输入费 | 每个任务前 5 张免费，超出部分每张 0.20（Lite 为 0.13） |
| 未说明 | 成片是否带声音、幂等或重复提交保护、限流数值、国际站差异、下载地址具体有效期、错误体的确切 JSON 结构、各分辨率的实际像素（尤其 2K 在 9:16 下的宽高） |

「未说明」各项都列入 §11 的真跑核对；实现时对这些项按保守方式处理（见各节）。

## 3. 厂商注册与配置

- 新文件 `backend/render/providers/minimax.py`，类名 `MiniMax`，`name = "minimax"`。在 `providers/__init__.py` 用 `register("minimax", _minimax)` 注册，工厂调用 `MiniMax.from_env()`。
- 环境变量都写在 `backend/.env`，读取方式与 Seedance 相同（`_load_dotenv`）：
  - `MINIMAX_API_KEY`（必填）：只放进 `Authorization: Bearer` 请求头，不进日志、报错和 session.json。
  - `STORYBOARD_MINIMAX_BASE_URL`（可选，缺省 `https://api.minimax.cn`）：为国际站预留，换地址即可。
  - `STORYBOARD_MINIMAX_PRICE_SCALE`（可选，缺省 1.0）：所有单价乘以这个系数，用于按真实账单或折扣校准。解析失败时按 1.0 处理。
  - `STORYBOARD_MINIMAX_NATIVE_AUDIO`（可选，缺省关）：见 §6。
- 缺密钥时，`from_env` 抛 `ProviderError("没有配置 MiniMax 密钥：在 backend/.env 写 MINIMAX_API_KEY=…")`。现有链路已经能处理这种情况：`session._provider` 把它转成 `SessionError`，出片设置切到 minimax 时界面显示这句提示，原设置保持不变。`names()` 仍然列出 minimax，用户能看到选项，选了才提示缺密钥。
- `rate_note`：「2026-11 MiniMax 官方刊例价（H3 768P 0.50、2K 0.80 元/秒，Highspeed、Lite 见档位；每段前 5 张参考图免费，超出另计），未经账单核对」。
- `console_name = "MiniMax 开放平台"`（见 §8.2）。

### 3.1 缺省厂商改为 MiniMax

**落点**：只有一处，即 `providers/__init__.py` 的 `default_video_name()`。它在 `session.resolve_settings` 遇到 `cur["provider"]` 为空时用到，也就是新建出片会话、还没有任何厂商设置的时候；此外还被 `get_video(None)` 和 `names()` 用到。改后的取值规则如下：

1. 显式设置了 `STORYBOARD_VIDEO_PROVIDER`：照用，不做回落（测试里设成 `fake` 的写法照旧生效）。
2. 没设置时：
   - `_has_key("minimax")` 为真：取 `minimax`；
   - 否则 `_has_key("seedance")` 为真：回落到 `seedance`；
   - 都为假：取 `minimax`，让缺密钥的提示指向推荐厂商。
3. `providers._has_key(name)` 内部先加载 `backend/.env`（与各厂商 `from_env` 用同一个 `_load_dotenv`，只把值放进进程环境，不读出、不打印），再看对应环境变量（`MINIMAX_API_KEY` / `ARK_API_KEY`）是否非空。加载 `.env` 只在这个函数里发生，所以测试给 `_has_key` 打桩后不会碰真实 `.env`。

**界面提示**：
- 后端：`session.view` 的 `options` 增加 `default_note`。只在两个条件同时满足时给出文字：当前会话的厂商是 `seedance`，且 `default_video_name()` 发生了第 2 步的回落（没配 MiniMax 而配了方舟）。文字为「没有配置 MINIMAX_API_KEY，新会话先用 Seedance；配好后新建的会话会默认用 MiniMax」，其余情况为空串。
- 前端：`frontend/src/types.ts` 的会话 options 类型（约 805 行）加 `default_note?: string`；出片面板设置区在它非空时显示一行提示，样式同现有的 `providerNote`；`i18n` 不加文案（文字由后端给，与 `rate_note` 同样处理）。这是本设计唯一的前端改动（§10 的前端测试即针对它）。

**不受影响的部分**：
- 已有会话：`session.json` 里已经存了 `provider`、`model`、`resolution`，`resolve_settings` 以已存的为准。所以已有会话保持原厂商、原档位、原分辨率，不迁移、不重估，已出的片段、指纹、费用都不动。用户要换，在出片设置里手动切，走现有的换厂商流程。
- 小说参数（`novel.params`）：不存视频厂商，不受影响。
- 助手：报价（`_film_quote`）要求会话已存在，不建会话，读的是会话里的厂商与落盘的 `estimate_cny`，不受缺省变化影响。会话由界面建立时走新缺省。

**README**：出片一节改为「缺省 `minimax`（`MINIMAX_API_KEY`），没配 MiniMax 而配了 `ARK_API_KEY` 时回落到 `seedance`」。

## 4. Caps 映射

| 档位 id | 发给接口的 model | resolutions（第一个为默认） | 输出单价（元/秒） | 超出图价 |
|---|---|---|---|---|
| `minimax-h3` | MiniMax-H3 | `768P`、`2K` | 0.50 / 0.80 | 0.20 |
| `minimax-h3-highspeed` | MiniMax-H3-Highspeed | `768P`、`480P` | 0.40 / 0.26 | 0.20 |
| `minimax-h3-lite` | MiniMax-H3-Lite | `768P`、`480P` | 0.26 / 0.16 | 0.13 |

共同取值：

- `min_clip_sec=4`，`max_clip_sec=15`，`max_refs=9`，`free_images=5`。
- `first_frame=True`，`last_frame=False`（本系统不发尾帧），`frame_with_refs=False`：与 Seedance 一样，首帧在 compose 里转为占第一个参考位（`frame_mode="ref"`）。
- `returns_last_frame=True`，**固定值**，不随本机有没有 ffmpeg 变化。它进入 compose 的接力判断和片段指纹（`relay:` 首帧来源），随环境变化会让指纹漂移、已出片段被误判过期。尾帧由 `download` 用 ffmpeg 从成片截取（§8.5）；截不到时现有链路已兜底：`request_for` 发现接力尾帧缺失就不带首帧提交，自由节点 `free.py` 遇到不存在的 `tail:` 来源会拒绝生成。
- `native_audio`：取 `STORYBOARD_MINIMAX_NATIVE_AUDIO`，缺省 False。处理见 §6。
- `short_side`：见 §5.1。
- 默认档位 `default_model = "minimax-h3"`。
- 档位 id 用小写短横线写法，与 Seedance 的 `seedance-2.0-fast` 一致；接口要的 model 名只在厂商模块里出现。

## 5. 厂商无关改动（分辨率、预估、图片张数、记账）

### 5.1 分辨率与合成画面尺寸

- **命名**：会话与界面直接用厂商原名 `768P` / `2K` / `480P`，不映射成 `720p` / `1080p`，避免误以为与 Seedance 的 720p 等价。
- **合成尺寸不是不透明的**：`render/mix.py:24` 的 `SHORT_SIDE` 只认 `480p/720p/1080p`，`frame_size()`（:41）查不到时回落 720；合成（:286）与导出 FCPXML（:356）都用它。不改的话，2K、768P 的片段会被规整成 720 短边，480P 会被放大。
- **改法**：`Caps` 增加 `short_side: dict = field(default_factory=dict)`（分辨率 → 短边像素）。`frame_size(resolution, aspect, short_side=None)` 先查传入的 `short_side`，再查 `SHORT_SIDE`，最后回落 720。合成与导出处从会话的厂商取 caps 传入。MiniMax 的取值：`{"480P": 480, "768P": 768, "2K": 1440}`。
- **2K 的实际像素未核实**：官方没有给 2K 在 9:16 下的宽高。先按短边 1440 处理，列入 §11 真跑核对（ffprobe 看实际宽高）；与实际不符时只改这张表。768P、480P 的短边同样由真跑确认。
- **默认分辨率**：`session.resolve_settings` 现在的规则是「有 `720p` 就用它，否则取第一个」。MiniMax 没有 `720p`，会取第一个；按 §4 表把默认分辨率排在第一位，这条规则不用改。

### 5.2 参考图张数与预估

- `Caps` 增加两个带缺省值的字段：`free_images: int = 0`、`cny_per_image: float = 0.0`。Seedance 和假厂商都取缺省值，行为不变。
- `base.estimate_cny(duration, caps, resolution, images: int = 0)` 增加一项：`max(0, images - caps.free_images) × caps.cny_per_image`。
- **统一张数函数** `compose.image_count(item) = len(item["refs"]) + (1 if item.get("first_frame") else 0)`：
  - 剧本段：落盘的 `clip["refs"]` 只含参考位和风格图，ref 模式下首帧（`__first__`）是在组装请求时才插到第一位的，所以不能只数 `refs`；frame 模式下首帧单独发。两种模式都是「refs + 有首帧时加 1」，统一用这个函数。
  - 自由节点：`refs` 加首帧，同一个函数。
  - 用在 `session.py:241/283` 与 `free.py:126/163` 四处预估调用。`queue_run` 与助手 `_film_quote` 读的是落盘的 `estimate_cny`，不需改。
- 这是预估：接力尾帧缺失时实际不发首帧，图会少一张，与时长取整一样属于已知误差，偏向多估。

### 5.3 实际记账

- 提交成功时，`sess.submitted` 在 attempt 里多记一个 `images = len(req.refs) + (1 if req.first_frame else 0)`，按实际发出的请求计数（接力缺尾帧没发首帧时就不算）。
- `cost(st, req)`：
  - 成功：`request_seconds × 单价 × scale`，加图片费。张数优先用查询返回的 `usage.input_image_count`，没有就用 attempt 的 `images`。
  - 为让 `cost` 拿到 `images`，runner 的 `_stub` 读 attempt 的 `images` 放进一个计费用的小结构；为此 `ClipRequest` 增加 `images: Optional[int] = None`（只用于计费，submit 不读）。
  - 失败：记 0。官方未写明失败任务是否计费，按「失败不计费」处理，列为 §11 核对项。
- `usage` 在 poll 阶段原样存进 attempt，Seedance 已经是这样做的。

### 5.4 runner 去掉写死的厂商字样

- `VideoProvider` 增加可选属性 `console_name`（Seedance 为「方舟控制台」，MiniMax 为「MiniMax 开放平台」）。runner 的 AmbiguousSubmit 提示（`runner.py:245`）改为用 `getattr(provider, "console_name", "厂商控制台")` 拼接。
- 「结果地址 24 小时有效」的注释和下载失败文案改为不写具体时长。

### 5.5 占位符清洗

`compose.py:26` 的 `_PLACEHOLDER` 用来清掉用户正文、资产名里冒出的占位符写法，防止参考编号错位。现在只认 `{ref:…}` 和 `@图片\d+`。加上 `参考图\d+`，否则用户写的「参考图2」会和改写出来的编号混在一起。补用例：正文和资产名里含「参考图3」时被清掉，改写后编号仍从 1 连续。

## 6. 声音

官方没有说明 H3 成片是否带声音，也没有声音参数。

- **缺省 `native_audio=False`**（保守做法）：
  - `session.view` 的 `options.audio_modes` 按能力过滤。厂商不支持原生声音时，只给 `tts_all`、`silent`。
  - `resolve_settings` 遇到不支持的模式：
    - patch 明确指定了该模式：报 SessionError「这家厂商不出原声，可选：全部配音、静音」；
    - patch 换了厂商或档位、而继承下来的旧模式不支持：回落到 `tts_all`；
    - 其它情况（例如只读刷新、build 时 patch 为空）：**不改写**，保持原样，避免把 session.json 改写成和已出片段不一致、触发过期。compose 侧已有 `audio = audio_mode != "silent" and caps.native_audio`，不支持时本就不请求原声。
  - 合成（mix）已经会用 `has_audio` 探测片段是否带音轨，再决定是否混原声，这里不用改。
- **真跑确认 H3 带声音、并能念出台词后**：用户设置 `STORYBOARD_MINIMAX_NATIVE_AUDIO=1`，`dialogue_native` 与 `all_native` 才会出现。代码不变。
- 即使成片自带环境音、而模式选了 `tts_all`，mix 现有的原声策略（`native_audio_policy`）也照常处理，不额外改。

## 7. 请求组装（submit）

### 7.1 提示词改写 `rewrite_prompt`

- compose 产出的是厂商无关的中间格式：`【首帧】{ref:__first__} …`、`【参考】{ref:ID} 文字`，参考位顺序与 `ClipRequest.refs` 一致。
- 改写规则：按出现顺序把每个 `{ref:…}` 换成「参考图N」，N 从 1 开始。与 Seedance 一样按次序编号，不按 ID：同一资产出现两次也各占一张图。
- `submit` 按同一顺序把 `refs` 写成 `role="reference_image"` 的 `image_url` 元素，所以第 N 张图对应文字里的「参考图N」。示例：`【参考】参考图1 主角林冲，黑衣…`。
- 首帧走 `frame_mode="frame"`（本段没有参考图）时，提示词里没有占位符；`first_frame` 作为唯一一张 `role="first_frame"` 的图发出。
- 超过 7000 字时 `ProviderError("提示词超出 MiniMax 上限 7000 字（当前 N 字）")`，不截断，因为截断会悄悄丢掉镜头。正常一段远小于这个上限。

### 7.2 ratio

- 参考生（有 refs）或纯文生：显式传 `req.aspect`（分镜 `meta.video.aspect_ratio`，缺省 `9:16`）。不在枚举里的值报 ProviderError。
- 图生（只有 first_frame）：不传 ratio（官方恒为 adaptive，由图决定）。
- 首帧来源有两种：关键帧图，或用户选用的首帧。目前关键帧图按分镜画幅出，尾帧接力来自同画幅的成片，所以画幅一致。比例合法但与分镜画幅不同的情况列入 §12 风险。

### 7.3 图片检查与规范化

图片来源分两类，处理不同：

- **http(s) 地址**（`compose._usable` 允许资产图直接给公网地址）：原样透传，不检查、不规范化，由厂商判定。
- **data URI**（本机文件，包括资产 data URI，它们不一定经过 `_MIME`）：
  1. **格式**：把 MIME 部分统一转小写；在 `image/jpeg|jpg|png|webp|heic|heif` 之内才发，否则报 ProviderError，写明是哪张图、什么格式。
  2. **尺寸与比例**：后端没有 Pillow，不新增依赖。每次提交时，在 `tempfile.TemporaryDirectory()` 里把图片字节写成临时文件，用 ffprobe 读宽高（`ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0`）。规则：
     - 宽高都在 [256, 5760]、且宽/高在 [0.4, 2.5] 之内：原样发出；
     - 否则用 ffmpeg 规范化成 JPEG：太小时等比放大到短边 256；太大时等比缩小到长边 5760；比例超界时用中性灰补边，把比例拉回 0.4 或 2.5。参考图不裁剪，避免裁掉人物。
     - 规范化结果在内存里转成新的 data URI；临时目录在 submit 结束时删除，不在会话目录留任何文件。`submit(req)` 拿不到会话目录，会话目录也刻意不在下载外重建，所以不做落盘缓存，每次提交重做一次。ffprobe 与 ffmpeg 对单张图只需几十毫秒。
     - 没装 ffmpeg 时不做规范化、原样发出；厂商若因尺寸拒绝，按 400 原文展示。
  3. **体积**：单张解码后 > 30MB，或整个请求体估算 > 60MB（留余量）时，报 ProviderError，说明是哪张图、多大。不自动压缩。

### 7.4 请求体

```
{"model": <接口 model>, "content": [text, image_url…], "resolution": req.resolution,
 "duration": request_seconds(req.duration, caps), ["ratio": …], "aigc_watermark": false}
```

不传 `callback_url`，本系统轮询；不传 `response_format`，用缺省的 `task` 结构，查询按 `{"task": {...}}` 解析。

## 8. 提交、轮询、下载与错误映射

### 8.1 HTTP 调用

**错误信息的取法**（官方没有给出错误体的完整结构，按两种可能都兼容）：
1. 顶层 `error`：`{"error": {"code"|"type", "message"}}`；
2. `base_resp`：`{"base_resp": {"status_code", "status_msg"}}`。

有任一处给出非 0 / 非空错误码，就取 `code：message` 作为原文；都没有时用 `HTTP 状态码` 加响应体前 300 字。错误码（如 1008、1026）从这两处的 code 里取，用于下表的专门提示。

**判定顺序**（自上而下，先命中先返回）：

| # | 情况 | 提交（submit=True） | 查询 / 下载 |
|---|---|---|---|
| 1 | 连不上、连接超时、连接池超时（请求没发出） | TransientError（可重试） | TransientError |
| 2 | 发出后断连或读超时 | **AmbiguousSubmit**（不重试） | TransientError |
| 3 | 429 或 529（529 必须在一般 5xx 之前判定） | TransientError | TransientError |
| 4 | 其它 5xx | **AmbiguousSubmit** | TransientError |
| 5 | 402 或错误码 1008 | ProviderError「MiniMax 账户余额不足（1008），充值后重新出这一段」 | 同左 |
| 6 | 401 或错误码 1004 | ProviderError「MiniMax 密钥无效（1004），检查 MINIMAX_API_KEY」 | 同左 |
| 7 | 422 或错误码 1026 | ProviderError「内容被 MiniMax 审核拦下（1026）：改写这一段的画面描述或换参考图后重试」 | 同左 |
| 8 | 其它 4xx | ProviderError（原文） | 同左 |
| 9 | 2xx，但 `base_resp.status_code` 非 0 或有顶层 `error` | **ProviderError**（厂商明确拒绝，没建任务，按 5–8 的专门提示归类） | 同左 |
| 10 | 2xx 但不是 JSON，或提交时没有 `task_id` | **AmbiguousSubmit** | TransientError |

第 9 行与第 10 行的区别：前者是厂商明确说了失败，不会有付费任务；后者无法判断是否已受理，只能不重试、标待核对。

### 8.2 轮询状态映射

| 厂商状态 | 本系统状态 |
|---|---|
| queued | pending |
| running | running |
| succeeded | succeeded |
| failed | failed，error = `code：message`（1026 用 §8.1 第 7 行的提示） |
| cancelled | failed，error =「任务已取消」 |
| 其它 | running |

- `video_url` 取 `task.content.url`；`usage` 原样存入 attempt，用于记账；`last_frame_url` 恒为 None。
- 轮询间隔：沿用全局 `STORYBOARD_RENDER_POLL_SEC`（缺省 10 秒），与官方建议一致。

### 8.3 下载

- 下载地址是限时签名直链，不带密钥，复用 Seedance 的 `_fetch` 写法：先写 `.part` 再改名，不建上级目录。
- 地址过期（403、404、410）时，在 `download` 内用 `st.task_id` 重新 `poll` 一次拿新地址，再下一次；仍失败报 ProviderError「结果地址已过期且重新查询失败；任务只能在 7 天内查询」。
- 重查拿到的新地址**不写回** attempt：provider 接口拿不到会话，attempt 里的旧地址只用于下一次下载尝试，过期了还会再重查，不影响结果。

### 8.4 尾帧截取

下载成功后执行：

```
ffmpeg -y -v error -sseof -0.1 -i <video> -frames:v 1 -q:v 2 <last_frame_path(video)>
```

- 失败（没装 ffmpeg、退出码非 0、文件为空）时 `last_frame=None`，只影响下一段接力，不让本段失败；后续链路见 §4 `returns_last_frame`。
- 截出的尾帧在下一段作首帧时，同样经过 §7.3 的检查。

## 9. 冒烟脚本

`render/smoke.py`：

- 增加 `--provider {seedance,minimax}`，缺省取 `default_video_name()`（与新会话一致），先打印选中的厂商，再询问是否提交。
- `--model`、`--resolution` 的缺省改为 None，按厂商补：seedance 为 `seedance-2.0-mini` + `480p`（与现在相同）；minimax 为 `minimax-h3-lite` + `480P`（最便宜）。
- `--out` 缺省路径名去掉 seedance，改为 `/tmp/video-smoke`。
- 描述文字改为「视频厂商真实冒烟（花钱）」；会话与 `build_clips` 的 `provider` 用所选厂商，不再写死 `"seedance"`。
- 预估加上图片费；冒烟上限 `LIMIT_CNY` 不变。
- 输出：视频是否可播放、**是否带音轨**（ffprobe 判定）、**实际宽高**（ffprobe，用来核对 §5.1 的短边表）、尾帧路径、usage 与折算金额。
- 冒烟由用户自己跑；实现与测试过程中不运行它。

## 10. 测试策略（不联网、不花钱）

后端测试按 README 的约定放在 `backend/tests/**/test_*.py`，由 glob 自动收集，不需要维护清单。

- **厂商无关部分**（用 `FakeVideo` 测，不依赖 minimax.py）：
  - `test_providers.py`：`estimate_cny` 的 `images` 参数（缺省 0 时结果与旧版相同；`free_images`、`cny_per_image` 生效）；注册表里能取到 minimax（没配密钥时得到 ProviderError，不是 KeyError）。缺密钥用例照 `test_seedance.py:159` 的写法，先把 `MINIMAX_API_KEY` 置为空串，防止 `_load_dotenv` 的 setdefault 灌入真实值。
  - `test_providers.py`，缺省厂商四种情况：给 `_has_key` 打桩（`.env` 只在它里面加载，桩替换后不会读真实 `.env`），暂时清掉 `STORYBOARD_VIDEO_PROVIDER`，结束后恢复。覆盖：显式设置照用；只有 MiniMax 密钥取 minimax；只有方舟密钥回落 seedance；都没有取 minimax。
  - `test_mix.py`：`frame_size` 传入 `short_side` 时用它（`768P` → 768×1366 一类的偶数尺寸），不传时旧行为不变，未知分辨率仍回落 720。
  - `test_compose.py`：`image_count` 对 ref 模式、frame 模式、无首帧三种段的结果；`_PLACEHOLDER` 清掉正文和资产名里的「参考图N」。
  - `test_session.py`：
    - 不支持原生声音的厂商，`options.audio_modes` 只剩两项；
    - 换厂商时继承来的旧模式回落到 `tts_all`，只读刷新时不改写 session.json；
    - 切到 minimax 后默认分辨率为 `768P`；
    - 回落且会话为 seedance 时 `options.default_note` 非空，其余情况为空；
    - 已有会话（存的是 seedance）在缺省改为 minimax 后再读取，厂商、档位、分辨率都不变；
    - 提交后 attempt 记录 `images`。
  - `test_runner.py`：AmbiguousSubmit 的提示用 `console_name`；`cost` 无 usage 时用 attempt 的 `images`。
- **`backend/tests/render/test_minimax.py`**（新增，`httpx.MockTransport` 模拟接口，写法同 `test_seedance.py`）：
  1. caps：三档的分辨率顺序、单价（含 scale）、图片费字段、`short_side`；`returns_last_frame` 恒为 True；缺密钥抛 ProviderError，报错里不含密钥。
  2. rewrite 与 submit：多参考图按序编号「参考图1…N」，content 顺序对应；首帧模式只有一张 first_frame、不带 ratio；参考模式显式带 `9:16`；Lite 也显式带比例；不带 `response_format`；超过 7000 字报错。
  3. 图片：http(s) 原样透传；大写 MIME 被转成小写；不支持的格式报错；用 ffmpeg 生成的过小（100×100）、过宽（3000×800）图规范化后都在限制之内，且临时目录在提交后不存在。机器上没有 ffmpeg 时跳过这几条并打印提示，与 mix 测试一致。
  4. `_call` 错误映射：§8.1 每一行至少一个用例。重点覆盖：529 走可重试；2xx 带 `base_resp.status_code` 非 0 时为 ProviderError，不是 AmbiguousSubmit；两种错误体结构都能取到 1008、1026 的专门提示。
  5. poll：五种状态映射，`task` 结构解析，usage 原样保留。
  6. download：正常下载；地址过期后重新查询再下成功；重查仍失败报错；尾帧截取成功与失败（打桩 ffmpeg 不存在）。
  7. cost：失败为 0；≤ 5 张不加钱；7 张加 2 张的钱；优先用 `usage.input_image_count`，没有时用 `req.images`。
- **前端**：只有 `default_note` 一处改动，`film.test` 加一条：options 带 `default_note` 时出片设置区显示这行提示，为空时不显示。声音模式下拉本来就读 `options.audio_modes`，不需改代码；确认 `film.test` 没有写死四种声音模式，写死了就改为读 options。

## 11. 用户手动冒烟清单（花钱，由用户执行）

1. 在 `backend/.env` 写入 `MINIMAX_API_KEY`，执行 `.venv/bin/python -m render.smoke --provider minimax`（Lite 480P 4 秒，约 ¥0.64），确认能提交、查询、下载，视频可播放。
2. 看冒烟输出的「是否带音轨」。如果带，再用 H3 768P 出一段有台词的，听声音是否念出台词、口型是否大致对得上。都满足就在 `.env` 加 `STORYBOARD_MINIMAX_NATIVE_AUDIO=1`。
3. 看冒烟输出的实际宽高，各分辨率都至少出一次（480P、768P；2K 选做），与 §5.1 的短边表核对，不符就改表。
4. 用带 2 个以上角色参考图的一段，看「参考图N」的写法是否让人物对上了参考图：人脸和服装是否沿用，是否把 1、2 号张冠李戴。
5. 连续出同一集的两段，看第二段开场是否接上了第一段的尾帧。
6. 与 MiniMax 开放平台账单核对两项：一段的实际扣费是否等于 `秒数 × 单价 + 超出图片费`；失败任务是否扣费。
7. 用一张宽比很大的场景图（例如 3:1）作参考出一段，确认补边后的图被接受、画面没有灰边进入成片。
8. 故意用一个错误的密钥提交一次（不扣费），记下错误体的实际结构，核对 §8.1 的两种取法是否覆盖。
9. 出片设置切到 minimax、没配密钥时，确认界面提示缺密钥，原设置不变。

## 12. 风险与未决项

- **声音未知**：缺省按不带原声处理，保守但安全。代价是确认带原声之前用不了原生台词模式。
- **参考图语法无官方规范**：「参考图N」只照官方示例的自然语言写法，效果要靠清单第 4 项验证。不行再调改写规则，只改厂商模块。
- **无幂等**：提交中断时可能重复建任务。沿用 AmbiguousSubmit：不重试、标待核对、提示到 MiniMax 开放平台核对。
- **失败任务是否计费未写明**：按不计费记账，靠清单第 6 项核对。
- **分辨率实际像素未写明**：先按 §5.1 的表，靠清单第 3 项核对。
- **错误体结构未写明**：两种取法都兼容，靠清单第 8 项核对。
- **首帧图与分镜画幅不一致**：图生由图决定画幅。当前首帧来源都与分镜同画幅；以后若允许任意上传首帧，需要再加画幅检查。
- **国际站**：只预留了 base URL。国际站价格是美元、接口可能不同，海外上线前要单独核对，届时在 `rate_note` 与单价里区分站点。
- **参考图收费**：9 张参考图比 5 张每段多 ¥0.80（Lite 多 ¥0.52）。按 §13 的决定用满 9 张，费用如实进预估。

## 13. 已决事项（用户 2026-11-12 拍板）

1. **参考图上限**：用满 9 张，超出 5 张的部分如实计费并计入预估（§5.2）。
2. **原生声音**：真跑确认之前缺省当作不带，只给「全部配音」和「静音」两种模式（§6）。
3. **系统缺省厂商**：改为 MiniMax（`minimax-h3` + `768P`）。没配 MiniMax 密钥而配了方舟密钥时，回落到 Seedance 并在界面提示；已有会话不迁移（§3.1）。

## 14. 实施顺序

每步可独立通过后端全部测试与前端 `npm test`、lint、build。

1. **厂商无关部分**：
   - `Caps` 新字段（`short_side`、`free_images`、`cny_per_image`）、`estimate_cny` 的 `images` 参数；
   - `compose.image_count` 与四处预估调用、`_PLACEHOLDER` 加「参考图N」；
   - `sess.submitted` 记 `images`、`ClipRequest.images` 与 runner `_stub`；
   - `mix.frame_size` 接受 `short_side`，合成与导出传入；
   - `console_name` 与 runner 文案。
   用 `FakeVideo` 测，行为对 Seedance 不变。
2. **`providers/minimax.py` 及 `test_minimax.py`**：注册、caps、改写、图片检查与规范化、`_call` 错误映射、poll、download（重查与截尾帧）、cost。
3. **缺省厂商与界面**：`default_video_name` 与 `_has_key`、`options.default_note`、声音模式过滤与 `resolve_settings` 回落规则、前端 `types.ts` 与出片设置提示、对应测试。
4. **冒烟与文档**：`smoke.py` 的 `--provider` 及按厂商的缺省值、音轨与宽高输出，README 出片一节。

## 审查修订记录（Opus 设计审查，2026-11-12）

- **C1 分辨率并非不透明**：新增 §5.1。`Caps.short_side` 由厂商给，`frame_size` 先查它；2K 等实际像素列入 §2「未说明」与 §11 第 3 项；补 `frame_size` 用例。
- **C2 规范化缓存放会话目录不可行**：§7.3 改为每次提交在临时目录规范化、用完即删，不落盘；删去「缓存命中」用例，改为「临时目录提交后不存在」。
- **I1 ref 模式首帧少算**：§5.2 统一用 `image_count(item)=len(refs)+(1 if first_frame else 0)`，用于四处预估；注明 `queue_run` 与 `_film_quote` 读落盘值，不改。
- **I2 `_stub` 带 refs 计费不可行**：§5.3 改为 `sess.submitted` 在 attempt 记 `images`（按实际发出的请求），`cost` 无 usage 时读它。
- **I3 `returns_last_frame` 随 ffmpeg 漂移**：§4 改为固定 True，并写明截不到尾帧时现有链路如何兜底。
- **I4 图片来源不全是 data URI**：§7.3 改为 http(s) 原样透传；data URI 的 MIME 统一小写，不在允许集合则报错。
- **I5 占位符清洗不认「参考图N」**：新增 §5.5，正则加 `参考图\d+` 并补用例。
- **I6 错误体路径与 2xx 业务错误**：§8.1 写明两种错误体取法；2xx 内 `base_resp.status_code` 非 0 按 ProviderError；529 先于 5xx 判定，表格按判定顺序编号。
- **I7 测试会读真实 `.env`**：§3.1 把加载 `.env` 移进 `_has_key`，打桩一并绕过；§10 缺密钥用例照 `test_seedance.py:159` 先置空串。
- **Minor**：
  - 只读刷新不改写声音模式，只在 patch 换厂商或档位时回落（§6）。
  - 前端改动范围统一为只有 `default_note`，并写明 `types.ts` 加字段（§3.1、§10）。
  - 助手不建会话，§3.1 改正描述。
  - 后端测试由 glob 自动收集，删去「加入测试清单」（§10）。
  - §12 末条改指 §13。
  - `smoke.py` 的 `--model`、`--resolution` 缺省改为按厂商补，`--out` 去掉 seedance（§9）。
  - 不传 `response_format`（§7.4）。
  - 下载过期重查的新地址不写回 attempt，写明原因（§8.3）。
  - `default_note` 只在当前会话为 seedance 且发生回落时显示（§3.1）。
- **实施拆分**：采纳审查建议，写入 §14。
