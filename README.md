# 小说 → AI 视频分镜脚本（忠实转换模式）

把一段/一章小说转换为 AI 视频制作可直接消费的结构化分镜文本。核心理念：**剧情属于小说，呈现属于系统**——每个镜头可溯源到原文句子，系统补的画面全部显式标记。

## 流水线

仓库分两个项目，各自独立开发与部署：

```
backend/    Python 转换流水线 + HTTP 服务（产出分镜 IR）
frontend/   React + TS 界面（提交转换任务 + 审阅分镜 IR）
```

```
小说原文
  │  backend/pipeline/                （一键编排：自动分批 → 调 LLM → 校验重试 → 合并终检）
  │    └─ prompts/novel_to_storyboard.md   （LLM 转换 prompt，忠实模式规则）
  ▼
分镜 JSON（backend/schema/storyboard.schema.json 定义的中间表示）
  │  backend/tools/lint_storyboard.py （结构 + 跨引用 + 覆盖率校验）
  ▼
  ├─ frontend/                        （审阅：分镜 / 资产卡 / 原文溯源 / 原始 JSON）
  ▼
下游消费（任意：AI 生视频 / 剪辑器 / 人工制作，不在项目范围内）
  │  backend/adapters/seedance.py     （参考实现：→ Seedance 2.0 生产包）
  ▼
素材出图清单 + 时间轴提示词(分clip) + 尾帧接力 + TTS旁白稿
```

## 快速开始

### 方式一：一键流水线（内置 LLM 调用，推荐）

配好密钥即可独立部署：文本进，通过三层校验的分镜 JSON 出。

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # 填入 ANTHROPIC_API_KEY

# CLI：自动分批 → LLM 转换 → 校验失败回喂重试 → 合并 → 整章终检
.venv/bin/python -m pipeline convert novel.txt -o storyboard.json --title 药 --chapter 第一章

# 或部署为 HTTP 服务（转换为分钟级任务，异步取结果）
.venv/bin/uvicorn server.app:app --host 0.0.0.0 --port 8000
curl -X POST localhost:8000/convert -H 'Content-Type: application/json' \
     -d '{"text": "……小说原文……", "work_title": "药"}'   # → {"job_id": "..."}
curl localhost:8000/jobs/<job_id>                            # → status / result / log

# 或 Docker 部署
docker build -t storyboard backend/
docker run -e ANTHROPIC_API_KEY=sk-ant-xxx -p 8000:8000 storyboard
```

离线回归（不调 LLM，用《药》归档回放编排逻辑）：`.venv/bin/python tests/pipeline/test_offline.py`

### 方式二：配套前端界面

```bash
cd frontend && npm install && npm run dev    # http://localhost:5173，/api 代理到 8000
```

粘贴原文 → 选制作参数 → 提交，日志实时回显；转换完成后按「分镜 / 资产卡 / 原文溯源 / JSON」
四个页签审阅。**原文溯源**页逐句标出被哪些镜头引用、是否念作旁白，未覆盖句标红——
IR 声称「每句可溯源」，这一页就是当场查证它。顶栏「打开本地 JSON」可离线审阅归档产物，不花 API 费用。
细节见 `frontend/README.md`。

### 方式三：手动流程（自备 LLM 会话）

```bash
cd backend
# 1. 转换：把 prompts/novel_to_storyboard.md 的系统提示词 + 填好变量的用户模板发给 LLM，
#    得到 storyboard.json（示例见 examples/）

# 2. 校验
pip install jsonschema
python3 tools/lint_storyboard.py examples/example_storyboard_suspense.json

# 3. 生成 Seedance 生产包
python3 adapters/seedance.py examples/example_storyboard_suspense.json --out out/
```

## 目录

| 路径 | 内容 |
|---|---|
| `backend/pipeline/` | 一键流水线（分批/LLM 调用/校验重试/合并编排 + 质量层），CLI 入口 `python3 -m pipeline` |
| `backend/server/app.py` | HTTP 服务（FastAPI，异步任务模型），配合 `backend/Dockerfile` 独立部署 |
| `backend/schema/storyboard.schema.json` | NovelStoryboard v0.5 分镜 JSON Schema（严格模式：拒绝未知字段；v0.4 产物仍合法） |
| `backend/docs/schema-design.md` | schema 设计决策说明 |
| `backend/prompts/novel_to_storyboard.md` | 小说→分镜 转换 prompt（系统提示词+用户模板） |
| `backend/tools/lint_storyboard.py` | 校验器（schema 校验 + 跨引用 + 忠实性检查） |
| `backend/tools/check_fidelity.py` | 原文保真度检查（unit 拼接与原文逐字比对） |
| `backend/tools/merge_storyboard.py` | 分批转换结果合并器（资产按 ID 合并 + 一致性检查 + coverage 重算） |
| `backend/adapters/seedance.py` | Seedance 2.0 适配器（镜头自动打包 ≤15s clip） |
| `backend/examples/` | 武侠、悬疑两个完整示例及其适配器输出（`out/`） |
| `backend/tests/genre_stability/` | 多题材稳定性测试的输入与输出（言情/玄幻/古典） |
| `backend/tests/long_chapter/` | 长章节分批转换 + 资产库续传测试（81 句 / 2 批 / 4 集） |
| `backend/tests/real_text_yao/` | 真实公版文本端到端测试：鲁迅《药》全文（132 句 / 2 批 / 4 集） |
| `backend/tests/pipeline/` | 流水线离线回归测试（mock LLM 回放《药》归档，不产生 API 费用） |
| `backend/docs/genre-stability-report.md` | 稳定性测试报告与规则修订记录 |
| `frontend/src/types.ts` | 分镜 IR 的 TS 镜像（对齐 schema），前端所有渲染的类型地基 |
| `frontend/src/resolve.ts` | 溯源索引：资产 ID→名称、原文句→引用它的镜头、覆盖率/旁白占比统计 |
| `frontend/src/components/` | 转换表单 / 任务面板 / 分镜·资产·溯源·JSON 四页签视图 |

## 三个核心设计

1. **溯源锚点**：原文切成带 ID 的句子，每个镜头声明 `source.unit_refs`，覆盖率机器可查
2. **推导标记**：`derivation: explicit / inferred / transition`，系统补的画面必须写推导依据
3. **资产引用制**：外貌只存在于 C/S/P 资产卡，镜头层只写引用，从根上防角色漂移

## Roadmap

- [x] 多题材 prompt 稳定性测试（言情/玄幻/古典白话 3/3 通过，报告见 `docs/genre-stability-report.md`）
- [x] 长章节（>60 句）分批转换 + 资产库续传测试（81 句 2 批全链路通过，含 `tools/merge_storyboard.py`）
- [x] schema v0.2：收紧 `additionalProperties`（严格模式，未知字段即校验失败）；群像卡 outfit 默认值矛盾已理顺（变更记录见 `docs/schema-design.md`）
- [x] 规则 5 衣物指称专项测试（古装宫廷篇一次通过；核心裁决修入规则：原文动作句字面颜色词保留、构件名视同中性指称）
- [x] schema v0.3：episode 级 BGM 情绪标注（mood 主基调 + 情绪曲线分段 + 配器提示，段可挂 unit_refs 溯源；《玉佩》4 集验证通过）
- [x] 真实公版文本端到端测试（鲁迅《药》全文 4584 字 2 批全链路通过；暴露 25 处真实文本特有情形，16 处修入 prompt、4 处结构性缺口记入 v0.4 方向，详见报告）
- [x] schema v0.4：道具状态机（props.states + prop_refs[].state）、生物资产类别（assets.creatures，A 卡）、镜头内旁白/台词顺序（narration.order）；mood 词表评估后维持不变。《药》归档改造为实战验证件，负例测试 4/4 拦截（变更记录见 `docs/schema-design.md`）
- [x] 一键流水线与独立部署：`pipeline/`（自动分批 → 内置 LLM 调用 → 校验失败回喂重试 → 合并终检）+ CLI + HTTP 服务 + Docker；离线回归用《药》归档回放，结果与人肉实测逐字一致
- [x] 弱模型质量层：meta 确定性覆写（参数即标准答案）、selective 旁白密度质量门（占比超阈值回喂可拍句清单）、可选 LLM 评审阶段（评分卡+issues 回喂，`STORYBOARD_REVIEW=1` 开启）。实测 DeepSeek 旁白占比 100% → 三轮收敛到 27%（人工基准 18%–36%），保留句恰为心理+点题句
- [x] 失败分档处理：硬校验（schema/lint/保真）失败即产物合同破坏，重试耗尽直接报错（工作目录保留已通过批次与失败报告）；软质量门（旁白密度/评审分）失败产物仍合法可用，重试耗尽默认**择优降级交付**历次尝试中最接近达标的一版并附质量报告（CLI 落 `*.quality-report.txt`，HTTP 返回 `completed_with_warnings` + `quality_report`），`--strict`/`STORYBOARD_STRICT=1` 改为直接失败
- [x] schema v0.5：镜头内阶段 `shot.beats[]`（一镜到底里情绪/灯光逐级推进，各拍时长之和须等于镜头时长）+ 镜头级负面约束 `shot.constraints[]`。两字段皆可选，v0.4 产物原样合法；生成器暂不产出，定位为人工在编辑器里给高潮戏加拍子（变更记录见 `docs/schema-design.md`）
- [x] 时长自洽与预算控制：新增语音时长质量门（镜头时长必须够念完自己的旁白+台词，`STORYBOARD_SPEECH_OVERFLOW_MAX` 默认 0.25、`STORYBOARD_SPEECH_CPS` 默认 4.5 字/秒）。归档实测暴露系统性问题：selective 模式 13%–26% 的镜头念不完、original_text 高达 55%–64%，《药》标称 678s 实为 762s（差 12%）。渲染估算据此改为**按可播时长计价**，并支持按 clip/按集勾选只渲染选中范围——预算失真靠可见性与选范围解决，不靠回喂重试硬顶
- [x] 渲染任务包（下游接入一期）：产物页新增「渲染」页签，把分镜切成视频模型可直接消费的 clip，附出图清单与费用估算（可切 Seedance 标准/mini 档，或用真实账单标定 `STORYBOARD_RENDER_CNY_PER_SECOND`）。机器可读清单与人读版 Markdown 生产包共用 `render/plan.py` 的提示词组装——两套分叉的话，人眼核对过的提示词就不是真正发出去的那句
- [x] 设定图归属变体：`reference_images[]` 标注 `outfit`/`state`（垫图必须垫对那套衣服，lint 交叉校验）、`view` 补 `close_up`、资产卡级负面约束 `constraints`。同时修正前端 TS 镜像与 schema 的三处字段错配（此前编辑服装描述会产出 schema 非法的产物）
- [x] 分镜编辑器「@ 挂卡」：画面描述里打 @ 或点＋挂卡即可给镜头挂上角色/生物/道具/场景引用，按 lint 规则自动补齐服装与形态（生物不带 outfit、无状态道具不填 state），并可维护垫图列表 `prompts.reference_assets`。形象锁定走结构化引用，正文只留自然语句
- [x] 入口归一化：剔除原文中的零宽空格/BOM/词连接符等排版噪声后再进流水线（实测弱模型无法在 JSON 输出里逐字复制不可见字符，反复保真失败），`STORYBOARD_NORMALIZE_INPUT=0` 关闭
- [x] LLM 传输层重试：断连/超时/5xx/限流指数退避重试（实测 DeepSeek 流式响应中途被服务端掐断），`max_tokens` 截断等确定性错误不重试直接抛（`STORYBOARD_TRANSPORT_RETRIES`，默认 3）
- [x] **弱模型全链路实跑验证**：DeepSeek 跑通《药》全文（4642 字，`STORYBOARD_BATCH_CHARS=1400` 切 4 批），4 批全部真正通过校验，整章 lint + 保真终检 PASS——136 句 / 4 集 / 98 镜，**旁白占比 16%**（人工基准 18%），inferred 4%（人工 6%）。旁白密度门在批 2/批 3 触发，回喂可拍句清单后模型均自行收敛：**弱模型不会主动做「能拍出来的不念」的取舍，但给它清单让它逐句重新裁决，它改得对**。代价是重试成本（4 批共 9 次生成，约 35 分钟），要更快更稳把 `STORYBOARD_MODEL` 换强档即可

- [x] 前后端分仓：`backend/`（Python 流水线 + 服务）与 `frontend/`（React + TS 界面）各自独立部署。前端定位是 IR 的**审阅器**而非剪辑器——分镜按集折叠并铺出 BGM 情绪曲线、资产卡集中展示外貌（镜头层只写引用）、原文溯源页逐句标注引用镜头与旁白归属且未覆盖句标红，把「每句可溯源」这个核心主张变成可当场查证的界面。服务端补 CORS（`STORYBOARD_CORS_ORIGINS` 收紧白名单）

- [x] 转换历史落盘与跨章资产复用：完成的转换写入 `backend/runs/*.json`（进程重启不丢，`GET /history` 等接口取用），转换慢又花钱，产物不该只活在内存里；`convert_text(seed_assets=...)` 让**首批**即带【已有资产库】，续写同一部小说的下一章时沿用已有 C/S/P/A 卡的 ID 与描述——把资产引用制的防漂移能力从批间延伸到章间
- [x] 分镜与资产卡人工编辑：呈现层字段（分镜的景别/运镜/时长/画面描述/氛围/音效/转场/角色表演/台词情绪，资产卡的名称/别名/外貌/服装/状态/描述）可改；原文 units 文本、`source.unit_refs`、`derivation`、台词与旁白文本、以及被跨引用的各级 ID（资产 ID、`outfits[].id`、`states[].id`）锁死。边界即产品主张——编辑权只开在「呈现属于系统」那一侧。前端测试对《药》全文施加编辑后交由**真实的 lint + 保真校验器**复核，确保改完仍是合法可溯源的 IR

- [x] 失败可诊断：每次生成未通过时，把校验/质量门报告**逐行打进日志流**（超 60 行截断并给出完整报告落盘路径）。此前日志只说「未通过校验」，报告仅存在于用户看不到的工作目录里——等于没说
- [x] 任务可离开与桌面通知：`GET /jobs` 列出在跑任务，前端重开页面自动接上（转换本就在后台线程池里跑，关页面不中断），完成/失败弹桌面通知；侧栏常驻显示在跑任务与最新一行日志
- [x] 章节自动识别与分段选取：支持 `第N章/回/节/卷`、`Chapter N`、`1. 标题`、独占一行的汉字序号（《药》即此形态）四类标题模式，取命中数 ≥2 且优先级最高的一套——宁可识别不出（回退全文/自定义），也不把正文句子误判成标题。可按章节多选、切前/后半章（切点落在段落边界）、或按自然段自定义范围

### 弱模型实跑的三类故障与防线

真实长文四次实跑，每次失败换来一条防线，现无已知缺口：

| 死因 | 防线 |
|---|---|
| 输出膨胀撞 32k token 上限被截断 | 调小 `STORYBOARD_BATCH_CHARS`（弱模型话多，宁可多切几批） |
| 模型丢失原文中的 U+200B，保真反复失败 | 入口归一化（剔除零宽噪声后再进流水线） |
| 服务端流式响应中途断连，任务崩溃 | LLM 传输层指数退避重试 |

**产品边界**：本项目的交付物是分镜 JSON 这份中间表示本身——信息完整（资产/镜头/台词/旁白/溯源）、结构合法、机器可校验。下游用剪辑器还是 AI 生视频应用消费它，不在本项目范围内；`backend/adapters/seedance.py` 仅作为"IR 可被下游直接消费"的参考实现保留，不再扩展适配器矩阵。`frontend/` 是这份 IR 的转换台与审阅器，同样不越界做剪辑功能。
