# 小说 → AI 视频分镜脚本（忠实转换模式）

把一段/一章小说转换为 AI 视频制作可直接消费的结构化分镜文本。核心理念：**剧情属于小说，呈现属于系统**——每个镜头可溯源到原文句子，系统补的画面全部显式标记。

## 流水线

```
小说原文
  │  pipeline/                        （一键编排：自动分批 → 调 LLM → 校验重试 → 合并终检）
  │    └─ prompts/novel_to_storyboard.md   （LLM 转换 prompt，忠实模式规则）
  ▼
分镜 JSON（schema/storyboard.schema.json 定义的中间表示）
  │  tools/lint_storyboard.py         （结构 + 跨引用 + 覆盖率校验）
  ▼
下游消费（任意：AI 生视频 / 剪辑器 / 人工制作，不在项目范围内）
  │  adapters/seedance.py             （参考实现：→ Seedance 2.0 生产包）
  ▼
素材出图清单 + 时间轴提示词(分clip) + 尾帧接力 + TTS旁白稿
```

## 快速开始

### 方式一：一键流水线（内置 LLM 调用，推荐）

配好密钥即可独立部署：文本进，通过三层校验的分镜 JSON 出。

```bash
pip install -r requirements.txt
cp .env.example .env        # 填入 ANTHROPIC_API_KEY

# CLI：自动分批 → LLM 转换 → 校验失败回喂重试 → 合并 → 整章终检
python3 -m pipeline convert novel.txt -o storyboard.json --title 药 --chapter 第一章

# 或部署为 HTTP 服务（转换为分钟级任务，异步取结果）
uvicorn server.app:app --host 0.0.0.0 --port 8000
curl -X POST localhost:8000/convert -H 'Content-Type: application/json' \
     -d '{"text": "……小说原文……", "work_title": "药"}'   # → {"job_id": "..."}
curl localhost:8000/jobs/<job_id>                            # → status / result / log

# 或 Docker 部署
docker build -t storyboard .
docker run -e ANTHROPIC_API_KEY=sk-ant-xxx -p 8000:8000 storyboard
```

离线回归（不调 LLM，用《药》归档回放编排逻辑）：`python3 tests/pipeline/test_offline.py`

### 方式二：手动流程（自备 LLM 会话）

```bash
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
| `pipeline/` | 一键流水线（分批/LLM 调用/校验重试/合并编排 + 质量层），CLI 入口 `python3 -m pipeline` |
| `server/app.py` | HTTP 服务（FastAPI，异步任务模型），配合 `Dockerfile` 独立部署 |
| `schema/storyboard.schema.json` | NovelStoryboard v0.4 分镜 JSON Schema（严格模式：拒绝未知字段） |
| `docs/schema-design.md` | schema 设计决策说明 |
| `prompts/novel_to_storyboard.md` | 小说→分镜 转换 prompt（系统提示词+用户模板） |
| `tools/lint_storyboard.py` | 校验器（schema 校验 + 跨引用 + 忠实性检查） |
| `tools/check_fidelity.py` | 原文保真度检查（unit 拼接与原文逐字比对） |
| `tools/merge_storyboard.py` | 分批转换结果合并器（资产按 ID 合并 + 一致性检查 + coverage 重算） |
| `adapters/seedance.py` | Seedance 2.0 适配器（镜头自动打包 ≤15s clip） |
| `examples/` | 武侠、悬疑两个完整示例及其适配器输出（`out/`） |
| `tests/genre_stability/` | 多题材稳定性测试的输入与输出（言情/玄幻/古典） |
| `tests/long_chapter/` | 长章节分批转换 + 资产库续传测试（81 句 / 2 批 / 4 集） |
| `tests/real_text_yao/` | 真实公版文本端到端测试：鲁迅《药》全文（132 句 / 2 批 / 4 集） |
| `tests/pipeline/` | 流水线离线回归测试（mock LLM 回放《药》归档，不产生 API 费用） |
| `docs/genre-stability-report.md` | 稳定性测试报告与规则修订记录 |

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
- [x] 入口归一化：剔除原文中的零宽空格/BOM/词连接符等排版噪声后再进流水线（实测弱模型无法在 JSON 输出里逐字复制不可见字符，反复保真失败），`STORYBOARD_NORMALIZE_INPUT=0` 关闭

**产品边界**：本项目的交付物是分镜 JSON 这份中间表示本身——信息完整（资产/镜头/台词/旁白/溯源）、结构合法、机器可校验。下游用剪辑器还是 AI 生视频应用消费它，不在本项目范围内；`adapters/seedance.py` 仅作为"IR 可被下游直接消费"的参考实现保留，不再扩展适配器矩阵。
