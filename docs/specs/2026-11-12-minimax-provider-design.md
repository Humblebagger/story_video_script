# 新增视频厂商 MiniMax H3（与 Seedance 并存）设计

日期：2026-11-12　状态：待审查

## 1. 目标与范围

- 出片多一家厂商 MiniMax（海螺 H3 系列），与现有 Seedance 并存。用户在出片设置里切换，会话里各段照常按厂商记账、出片、接力。
- 档位：`MiniMax-H3`（默认）、`MiniMax-H3-Highspeed`、`MiniMax-H3-Lite`。`MiniMax-H3-Max` 这次不接，理由是参考图按每张 ¥0.50 收费，且自动扩写提示词会改掉分镜原意。
- 不在范围内：
  - 出片画布、节点图、自由节点、预算与确认、合成、导出的流程不变。它们只经 `Caps` 与 `VideoProvider` 接口跟厂商打交道。
  - 不用 MiniMax 的参考视频、参考音频、尾帧（`last_frame`）、回调、再生成接口。
  - 不改 Seedance 的行为。
- 依据：本文的接口与价格事实核对自 platform.minimax.cn 官方文档，核对日期 2026-11-12。核对过的页面是 `guides/video-generation`、`api-reference/video-generation-v2-create`、`api-reference/video-generation-v2-query`、`guides/pricing-paygo`。

## 2. 官方事实摘要（实现以此为准）

| 项 | 事实 |
|---|---|
| 创建 | `POST {base}/v2/video_generation` → `{"task_id"}`；body：`model`、`content[]`、`resolution`、`duration`（整数）、`ratio`、`aigc_watermark`、`response_format` |
| content | 元素 `{"type":"text","text":…}` / `{"type":"image_url","image_url":{"url":…},"role":…}`；role 用 `first_frame` / `reference_image` |
| 互斥 | 图生视频（first_frame/last_frame）与多模态参考（reference_image ≤ 9）不能同用 |
| ratio | `adaptive / 21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16`。图生时由图决定，传了也会被忽略。参考生默认 adaptive，Lite 不支持 adaptive，必须给比例 |
| 查询 | `GET {base}/v2/query/video_generation/{task_id}` → `{"task":{status, content.url, usage, error}}`；状态 `queued/running/succeeded/failed/cancelled`；只能查 7 天内的任务；官方建议每 10 秒查一次 |
| 结果 | `content.url` 是限时下载地址，过期后重新查询可拿到新地址。不返回尾帧图 |
| 图片 | 公网 URL / `mm_file://` / `data:image/<小写格式>;base64,…`；格式 JPG/JPEG/PNG/WEBP/HEIC/HEIF；单张 ≤ 30MB；宽、高 ∈ [256, 5760]；宽/高 ∈ [0.4, 2.5]；请求体 ≤ 64MB；每个 text ≤ 7000 字 |
| 分辨率/时长 | H3：768P / 2K；Highspeed 与 Lite：480P / 768P。时长 4–15 秒 |
| 错误 | 400(2013)、401(1004)、402 余额不足(1008)、422 敏感内容(1026，提交时或任务失败时都可能出现)、429(1002)、500(1000)、529 过载 |
| 价格（元/秒，输出） | H3：2K 0.80、768P 0.50；Highspeed：768P 0.40、480P 0.26；Lite：768P 0.26、480P 0.16 |
| 图片输入费 | 每个任务前 5 张免费，超出部分每张 0.20（Lite 为 0.13） |
| 未说明 | 成片是否带声音、幂等或重复提交保护、限流数值、国际站差异、下载地址具体有效期 |

## 3. 厂商注册与配置

- 新文件 `backend/render/providers/minimax.py`，类名 `MiniMax`，`name = "minimax"`。在 `providers/__init__.py` 用 `register("minimax", _minimax)` 注册，工厂调用 `MiniMax.from_env()`。
- 环境变量都写在 `backend/.env`，读取方式与 Seedance 相同（`_load_dotenv`）：
  - `MINIMAX_API_KEY`（必填）：只放进 `Authorization: Bearer` 请求头，不进日志、报错和 session.json。
  - `STORYBOARD_MINIMAX_BASE_URL`（可选，缺省 `https://api.minimax.cn`）：为国际站预留，换地址即可。
  - `STORYBOARD_MINIMAX_PRICE_SCALE`（可选，缺省 1.0）：所有单价乘以这个系数，用于按真实账单或折扣校准。解析失败时按 1.0 处理。
- 缺密钥时，`from_env` 抛 `ProviderError("没有配置 MiniMax 密钥：在 backend/.env 写 MINIMAX_API_KEY=…")`。现有链路已经能处理这种情况：`session._provider` 把它转成 `SessionError`，出片设置切到 minimax 时界面显示这句提示，原设置保持不变。`names()` 仍然列出 minimax，用户能看到选项，选了才提示缺密钥。
- `rate_note`：「2026-11 MiniMax 官方刊例价（H3 768P 0.50、2K 0.80 元/秒，Highspeed、Lite 见档位；每段前 5 张参考图免费，超出另计），未经账单核对」。

## 4. Caps 映射

| 档位 id | 发给接口的 model | resolutions（第一个为默认） | 输出单价（元/秒） | 超出图价 |
|---|---|---|---|---|
| `minimax-h3` | MiniMax-H3 | `768P`、`2K` | 0.50 / 0.80 | 0.20 |
| `minimax-h3-highspeed` | MiniMax-H3-Highspeed | `768P`、`480P` | 0.40 / 0.26 | 0.20 |
| `minimax-h3-lite` | MiniMax-H3-Lite | `768P`、`480P` | 0.26 / 0.16 | 0.13 |

共同取值：

- `min_clip_sec=4`，`max_clip_sec=15`，`max_refs=9`。
- `first_frame=True`，`last_frame=False`（本系统不发尾帧），`frame_with_refs=False`：与 Seedance 一样，首帧在 compose 里转为占第一个参考位（`frame_mode="ref"`）。
- `returns_last_frame`：厂商不给尾帧，由 `download` 用 ffmpeg 从成片截取（见 §8）。构造时如果 `mix.tools()` 找到了 ffmpeg，取 True，否则取 False。取 False 时 compose 不安排上一段尾帧的接力，现有逻辑已支持。
- `native_audio`：取环境变量 `STORYBOARD_MINIMAX_NATIVE_AUDIO`，缺省 False。处理见 §6。
- 默认档位 `default_model = "minimax-h3"`。
- 档位 id 用小写短横线写法，与 Seedance 的 `seedance-2.0-fast` 一致；接口要的 model 名只在厂商模块里出现。

## 5. 分辨率命名、预估与参考图收费

- **分辨率命名**：会话与界面直接用厂商原名 `768P` / `2K` / `480P`，不映射成 `720p` / `1080p`。理由：
  - 分辨率在系统里本来就是厂商内的不透明字符串，界面下拉照原样显示，预估按 `caps.cny_per_sec[r]` 查。
  - 映射会让用户误以为与 Seedance 的 720p 等价。
- **默认分辨率**：`session.resolve_settings` 现在的规则是「有 `720p` 就用它，否则取第一个」。MiniMax 没有 `720p`，会取第一个；按上表把默认分辨率排在第一位，这条规则不用改。
- **参考图收费进预估**：
  - `Caps` 增加两个带缺省值的字段：`free_images: int = 0`、`cny_per_image: float = 0.0`。Seedance 和假厂商都取缺省值，行为不变。
  - `base.estimate_cny(duration, caps, resolution, images: int = 0)` 增加一项：`max(0, images - caps.free_images) × caps.cny_per_image`。
  - `images` 的取值：剧本段为 `len(clip["refs"])` 加上「首帧单独作为图片发出时」的 1。也就是 frame_mode 为 `"frame"` 时加 1；为 `"ref"` 时首帧已在 refs 里，不再加。自由节点为 `len(refs)` 加上首帧的 1。
  - `session.py:241/283` 与 `free.py:126/163` 的四处调用传入 `images`。
  - 这是预估：段的参考在出片时还会按当时的图片情况变化，与时长取整一样，属于已知误差。
- **实际记账 `cost(st, req)`**：
  - 成功时：`request_seconds × 单价 × scale`，加上图片费。图片费优先用查询返回的 `usage.input_image_count`，没有就用请求里的张数。
  - 失败时：记 0。官方未写明失败任务是否计费，按「失败不计费」处理，列为手动冒烟核对项（§11）。
  - 为此 `ClipRequest` 不加字段。`cost` 收到的 `_stub` 没有 refs，所以 runner 的 `_stub` 需要把 `refs`、`first_frame` 也带上（只用于计数）。在 poll 阶段把 `usage` 存进 attempt，Seedance 已经是这样做的。

## 6. 声音

官方没有说明 H3 成片是否带声音，也没有声音参数。

- **缺省 `native_audio=False`**（保守做法）：
  - `session.view` 的 `options.audio_modes` 改为按能力过滤。厂商不支持原生声音时，只给 `tts_all`、`silent`。
  - `resolve_settings` 遇到不支持的模式：如果是 patch 明确指定的，报 SessionError「这家厂商不出原声，可选：全部配音、静音」；如果是从旧设置继承来的，回落到 `tts_all`。
  - compose 现有逻辑 `audio = audio_mode != "silent" and caps.native_audio` 不变。
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
- 首帧来源有两种：关键帧图，或用户上传 / 选用的首帧。目前关键帧图按分镜画幅出，尾帧接力来自同画幅的成片，所以画幅一致。
- 画幅不一致的风险由 §7.3 的比例检查兜底：它只拦截超出 [0.4, 2.5] 的极端比例；比例合法但与分镜画幅不同的，出片后由用户在预览里发现。这一点写进 §12 风险。

### 7.3 图片规范化

所有图片都以 data URI 形式发出，沿用 `compose.data_uri`。提交前在厂商模块里检查：

1. **格式**：MIME 在 `image/jpeg|png|webp` 之内。现有 `_MIME` 只产这三种，其它情况报 ProviderError。
2. **尺寸与比例**：后端没有 Pillow，不新增依赖。用 ffprobe 读宽高（`ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0`），图片字节写入临时文件后再读。处理规则：
   - 宽高都在 [256, 5760]、且宽/高在 [0.4, 2.5] 之内：原样发出。
   - 否则用 ffmpeg 规范化成 JPEG，结果按图片内容哈希缓存在会话目录的 `.mm_norm/` 下，供下次复用：
     - 太小：等比放大到短边 256。
     - 太大：等比缩小到长边 5760。
     - 比例超界：用中性灰补边，把比例拉回 0.4 或 2.5。参考图不裁剪，避免裁掉人物。
   - 没装 ffmpeg 时不做规范化、原样发出；厂商若因尺寸拒绝，按 400 原文展示。
3. **体积**：单张解码后 > 30MB，或整个请求体估算 > 60MB（留余量）时，报 ProviderError，说明是哪张图、多大。不自动压缩。现有资产图远小于这个上限。

### 7.4 请求体

```
{"model": <接口 model>, "content": [text, image_url…], "resolution": req.resolution,
 "duration": request_seconds(req.duration, caps), ["ratio": …],
 "aigc_watermark": false, "response_format": "task"}
```

不传 `callback_url`；本系统轮询。

## 8. 提交、轮询、下载与错误映射

### 8.1 HTTP 调用

`_call` 复刻 Seedance 的规则：

| 情况 | 提交（submit=True） | 查询 / 下载 |
|---|---|---|
| 连不上、连接超时、连接池超时（请求没发出） | TransientError（可重试） | TransientError |
| 发出后断连或读超时 | **AmbiguousSubmit**（不重试） | TransientError |
| 429 / 529 | TransientError | TransientError |
| 5xx | **AmbiguousSubmit** | TransientError |
| 2xx 但不是 JSON，或没有 `task_id` | **AmbiguousSubmit** | TransientError |
| 402（1008） | ProviderError「MiniMax 账户余额不足（1008），充值后重新出这一段」 | 同左 |
| 401（1004） | ProviderError「MiniMax 密钥无效（1004），检查 MINIMAX_API_KEY」 | 同左 |
| 422（1026） | ProviderError「内容被 MiniMax 审核拦下（1026）：改写这一段的画面描述或换参考图后重试」 | 同左 |
| 其它 4xx | ProviderError（`code：message` 原文） | 同左 |

### 8.2 去掉 runner 里写死的方舟字样

现在 runner 里有两处写死了方舟：AmbiguousSubmit 的提示「请到方舟控制台核对」（`runner.py:245`），以及「结果地址 24 小时有效」的注释和文案。

- `VideoProvider` 增加可选属性 `console_name: str`（Seedance 为「方舟控制台」，MiniMax 为「MiniMax 开放平台」）。runner 改为用 `getattr(provider, "console_name", "厂商控制台")` 拼提示。
- 下载过期的文案改为不写具体时长。

### 8.3 轮询状态映射

| 厂商状态 | 本系统状态 |
|---|---|
| queued | pending |
| running | running |
| succeeded | succeeded |
| failed | failed，error = `code：message` |
| cancelled | failed，error =「任务已取消」 |
| 其它 | running |

- 查询返回 1026 失败时，error 同样用 §8.1 的审核提示。
- `video_url` 取 `content.url`。`usage` 原样存入 attempt，用于记账。
- `last_frame_url` 恒为 None。
- 轮询间隔：沿用全局 `STORYBOARD_RENDER_POLL_SEC`（缺省 10 秒），与官方建议一致。

### 8.4 下载

- 下载地址是限时签名直链，不带密钥，复用 Seedance 的 `_fetch` 写法：先写 `.part` 再改名，不建上级目录。
- 地址过期（403、404、410）时，在 `download` 内用 `st.task_id` 重新 `poll` 一次拿新地址，再下一次。仍失败报 ProviderError「结果地址已过期且重新查询失败；任务只能在 7 天内查询」。

### 8.5 尾帧截取

下载成功后执行：

```
ffmpeg -y -v error -sseof -0.1 -i <video> -frames:v 1 -q:v 2 <last_frame_path(video)>
```

- 失败（没装 ffmpeg、退出码非 0、文件为空）时 `last_frame=None`，只影响下一段接力，不让本段失败。这与 Seedance 拿不到尾帧时的处理一致。
- 截出的尾帧在下一段作首帧时，同样经过 §7.3 的规范化。

## 9. 冒烟脚本

`render/smoke.py` 增加 `--provider {seedance,minimax}`，缺省 seedance。

- 按厂商取实例和缺省档位、分辨率：minimax 缺省 `minimax-h3-lite` 加 `480P`，最便宜。
- 描述文字改为「视频厂商真实冒烟（花钱）」。
- 预估加上图片费；冒烟上限 `LIMIT_CNY` 不变。
- 输出：视频是否可播放、**是否带音轨**（ffprobe 判定）、尾帧路径、usage 与折算金额。
- 冒烟由用户自己跑；实现与测试过程中不运行它。

## 10. 测试策略（不联网、不花钱）

- 新增 `backend/tests/render/test_minimax.py`，用 `httpx.MockTransport` 模拟接口，写法同 `test_seedance.py`。覆盖：
  1. caps：三档的分辨率顺序、单价（含 scale）、图片费字段；缺密钥抛 ProviderError，报错里不含密钥。
  2. rewrite 与 submit：多参考图按序编号「参考图1…N」，content 顺序对应；首帧模式只有一张 first_frame、不带 ratio；参考模式显式带 `9:16`；Lite 也显式带比例；超过 7000 字报错。
  3. `_call` 错误映射：§8.1 表中每一行至少一个用例，重点是 AmbiguousSubmit 的三种情况、402、1026 的提示文字。
  4. poll：五种状态映射；cancelled 的提示；usage 原样保留。
  5. download：正常下载；地址过期后重新查询再下成功；重查仍失败报错；尾帧截取成功与失败（打桩 ffmpeg 不存在的情况）。
  6. cost：失败为 0；图片 ≤ 5 张不加钱；7 张加 2 张的钱；优先用 `usage.input_image_count`。
  7. 图片规范化：用 ffmpeg 生成过小（100×100）、过宽（3000×800）的测试图，规范化后都在限制之内，缓存命中时不重复处理。机器上没有 ffmpeg 时跳过并打印提示，与 mix 测试一致。
- 改 `test_providers.py`：`estimate_cny` 的 images 参数（缺省 0 时结果与旧版相同）；注册表里能取到 minimax（没配密钥时得到 ProviderError，不是 KeyError）。
- 改 `test_session.py`：不支持原生声音的厂商，`options.audio_modes` 只剩两项，继承下来的旧模式回落到 `tts_all`；切到 minimax 后默认分辨率为 `768P`。
- 改 `test_runner.py`：AmbiguousSubmit 的提示用 `console_name`。
- 新测试文件加入后端测试脚本清单，跟现有的 `test_seedance.py` 放在同一处。
- 前端只做一处有行为的改动：声音模式下拉的选项来自 options，已经是动态的。所以不改前端代码，只确认 `film.test` 里没有写死四种声音模式；如果写死了，改成读 options。

## 11. 用户手动冒烟清单（花钱，由用户执行）

1. 在 `backend/.env` 写入 `MINIMAX_API_KEY`，执行 `.venv/bin/python -m render.smoke --provider minimax`（Lite 480P 4 秒，约 ¥0.64），确认能提交、查询、下载，视频可播放。
2. 看冒烟输出的「是否带音轨」。如果带，再用 H3 768P 出一段有台词的，听声音是否念出台词、口型是否大致对得上。都满足就在 `.env` 加 `STORYBOARD_MINIMAX_NATIVE_AUDIO=1`。
3. 用带 2 个以上角色参考图的一段，看「参考图N」的写法是否让人物对上了参考图：人脸和服装是否沿用，是否把 1、2 号张冠李戴。
4. 连续出同一集的两段，看第二段开场是否接上了第一段的尾帧。
5. 与 MiniMax 开放平台账单核对两项：一段的实际扣费是否等于 `秒数 × 单价 + 超出图片费`；失败任务是否扣费。
6. 用一张宽比很大的场景图（例如 3:1）作参考出一段，确认补边后的图被接受、画面没有灰边进入成片。
7. 出片设置切到 minimax、没配密钥时，确认界面提示缺密钥，原设置不变。

## 12. 风险与未决项

- **声音未知**：缺省按不带原声处理，保守但安全。代价是确认带原声之前用不了原生台词模式。
- **参考图语法无官方规范**：「参考图N」只照官方示例的自然语言写法，效果要靠清单第 3 项验证。不行再调改写规则，只改厂商模块。
- **无幂等**：提交中断时可能重复建任务。沿用 AmbiguousSubmit：不重试、标待核对、提示到 MiniMax 开放平台核对。
- **失败任务是否计费未写明**：按不计费记账，靠清单第 5 项核对。
- **首帧图与分镜画幅不一致**：图生由图决定画幅。当前首帧来源都与分镜同画幅；以后若允许任意上传首帧，需要再加画幅检查。
- **国际站**：只预留了 base URL。国际站价格是美元、接口可能不同，海外上线前要单独核对，届时在 `rate_note` 与单价里区分站点。
- **参考图收费**：9 张参考图比 5 张每段多 ¥0.80（Lite 多 ¥0.52）。缺省仍按 `max_refs=9`，费用会如实进预估。是否默认少带几张，见开放问题。

## 13. 开放问题（需用户拍板）

1. **参考图上限**：缺省按 9 张（效果优先，超出部分如实计费），还是限到 5 张（不额外收费）？本设计按 9 张写。
2. **原生声音**：在真跑确认之前，缺省关闭（只给「全部配音」和「静音」两种模式）是否接受？
3. **系统缺省厂商**：仍用 Seedance，用户在出片设置里手动切换；还是把 `STORYBOARD_VIDEO_PROVIDER` 缺省改成 minimax？本设计保持 Seedance。
