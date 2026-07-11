# 分镜 JSON Schema 设计说明（v0.4 · 忠实转换模式）

> Schema: `schema/storyboard.schema.json` · 示例: `examples/example_storyboard.json`

## 定位

本 schema 是"小说 → AI 视频"流水线的**中间表示（IR）**，也是本项目的最终交付物：上游是 LLM 对小说的理解与镜头翻译，下游是任意视频制作方式（AI 生视频应用、剪辑器、人工制作）——用什么工具消费不在项目范围内。它平台无关，只承载决策，不绑定任何模型；`adapters/seedance.py` 仅为"IR 可被下游直接消费"的参考实现。

## 五层结构

```
meta       项目级全局设定（风格前缀、画幅、旁白策略）
source     原文切分层：小说被切成带 ID 的句子（忠实模式的溯源 backbone）
assets     资产库：C 角色 / S 场景 / P 道具，一次定义全片引用
episodes   分集 → 镜头（shot 是原子单元）
coverage   覆盖率质检报告（工具生成，非人工维护）
```

## 三个核心设计决策

### 1. 溯源锚点（source.unit_refs）——忠实性的机器可验证保证

小说先被切成句子单元（`u0001`...），每个镜头必须声明它依据哪些句子（`shot.source.unit_refs`）。由此可以自动做**覆盖率检查**：任何没被镜头引用、又没标 `skipped` 的句子，就是转换遗漏。"剧情由小说固定"从一句口号变成可校验的约束。

### 2. 推导标记（derivation）——区分"原文写的"和"系统补的"

- `explicit`：画面为原文明确描写，可直接成像
- `inferred`：原文不可拍（心理描写/抽象叙述），画面是转换器推导的，**必须写 `inference_note` 说明推导依据**，供人工重点审核
- `transition`：纯转场空镜

`coverage.inferred_shot_ratio` 过高即说明偏离忠实模式。这是本 schema 相对 Seedance 项目（Markdown 输出、无溯源概念）的核心差异化。

### 3. 资产引用制——文本层的一致性根

镜头里**只允许写 `C01`/`S01`/`P01` 引用，禁止重写外貌**。外貌只存在于资产卡一处，改一处全片生效，从根上杜绝描述漂移。借鉴自 Seedance 的编号规范：

- 角色卡：结构化外貌字段 + **outfits 服装状态集**（角色跨章换装，镜头用 `outfit` 指定）+ 参考图槽位（供 IP-Adapter/垫图）
- 道具卡：**states 状态集**（外观随剧情演变的道具，镜头用 `prop_refs[].state` 指定形态）；生物卡（A 卡）收非人视觉主体
- 场景卡：**正打/反打/侧面机位版本**（对话戏正反打必需），镜头用 `location_angle` 指定
- 最终提示词由适配器确定性拼装：`style_prefix + 资产 visual_prompt + shot.action + atmosphere`

## 其他要点

- **旁白与忠实性解耦**：句子有三种承载方式——旁白朗读、角色台词、画面呈现。`meta.narration.mode = selective`（推荐默认）下"能拍出来的不念"，只朗读画面承载不了的信息（时间跳跃/事实交代/心理核心/点题句）；`original_text` 则逐句朗读（经典小说推文形态）。两种模式下忠实性都由 `source.unit_refs` 溯源保证，覆盖率校验口径随模式切换（见 lint）
- **对白 `verbatim` 标记**：忠实模式下台词应为原文原句，改写过的必须标 `false`
- **`tail_frame_description`**：每集尾帧描述，用于跨集抽帧接力（借鉴 Seedance）
- **枚举受控**：景别 8 档、运镜 11 种、机位角度 7 种，中文映射写在 description 里——受控词表让下游适配器可以做"镜头类型 → 生成参数"的映射（借鉴 ComfyUI 按镜头类型分流的思路）
- **`prompts` 为产物字段**：由生成器拼装、人工可覆写，不属于人工编辑面

## 校验

```bash
pip install jsonschema
python -c "
import json, jsonschema
jsonschema.validate(json.load(open('examples/example_storyboard.json')),
                    json.load(open('schema/storyboard.schema.json')))"
```

## v0.2 变更（2026-07-11）

- **严格模式**：全部 27 个 object 节点加 `additionalProperties: false`，未知字段直接校验失败。动机是实测漂移：LLM 曾在 appearance 写出 `build`/`distinguishing`（正确为 `body`/`distinguishing_marks`）、在 voice 混入 `age`/`gender`——这类漂移下游适配器读不到，等于信息静默丢失；现在会在 lint 层立刻报错
- **群像卡矛盾修复**：`shot.characters[].outfit` 移除 `default: "default"` 标注——引用省略 outfits 的卡（群像卡）时 outfit 字段同样省略，有 outfits 的卡必须显式填写；语义裁决在 lint 中实现
- `schema_version` 常量升至 `"0.2"`；全部归档示例/测试输出已迁移并通过严格校验

## v0.3 变更（2026-07-11）

- **BGM 情绪标注**：新增 `episodes[].music`（可选）——`mood` 主基调（10 值受控词表：calm/warm/playful/tense/ominous/eerie/sorrow/melancholy/triumph/epic）+ `curve` 情绪曲线（连续无缝隙的镜头区间段，每段 mood/intensity/note，段边界即 BGM 切换点）+ `style_hint` 配器提示。与忠实模式兼容：情绪判定必须有原文依据，每段可挂 `unit_refs` 溯源
- lint 新增 curve 校验（区间存在性/顺序/连续性/溯源句存在性）；Seedance 适配器新增「BGM 提示」段（按镜头时长换算出精确到秒的分段）
- 功能验证：《玉佩》4 集标注一次通过（含爆发-死寂-揭示的六段曲线），3 处裁决口径修入 prompt（主基调按戏剧主导性、镜头中段转折归入转折后段、跨批依据写 note）

## v0.4 变更（2026-07-11）

真实文本端到端测试（鲁迅《药》，见 `tests/real_text_yao/`）暴露的 4 处结构性缺口的裁决结果——3 项实装、1 项评估后维持现状：

- **道具状态机**：`props[].states[]`（对应角色的 outfits），外观随剧情持续演变的道具按状态建条目、`visual_prompt` 写基准态；`shot.prop_refs` 从字符串数组升级为 `[{ref, state}]` 对象数组，卡有 states 则 state 必填（口径同 outfit：镜头进行中变化取关键帧结果态）。动机：人血馒头五态（鲜红滴血→纸罩裹→荷叶包→焦黑→拗开）此前只能塞 visual_prompt 括号备注，下游无法按镜头取对形态的参考图
- **生物资产类别**：新增 `assets.creatures`（A01 起编号：species/visual_prompt/notes），收作为剧情视觉主体、需资产出图的非人生物（《药》的乌鸦）；镜头层在 `characters` 数组引用（ref 放宽为 `^[CA]\d{2}$`），不填 outfit，生物叫声走 sfx。一闪而过的背景动物仍写 action 不建卡
- **镜头内旁白/台词顺序**：`narration.order`（可选，before_dialogue / after_dialogue），缺省=按原文语序；解决"台词先出、旁白随后交代身份"（'好香！'→"这是驼背五少爷到了"）无处声明成片顺序的问题
- **mood 词表扩充**：评估后**维持 10 值不变**——"板滞死寂"类复杂情绪本轮仅出现一次，按"取最近值 + note 说明差异"口径处理（已写入 prompt），高频出现再扩
- lint 新增 state 交叉校验（必填/存在性/无 states 不得填）与生物引用校验（存在性/不得填 outfit）；合并器 states 并入可增列表、资产循环加 creatures；适配器渲染道具状态清单与"生物参考"垫图行、TTS 稿按 order 排序
- 全部归档件已迁移并通过校验；《药》归档同步改造为 v0.4 特性实战验证件（P01 五态精确到镜头、乌鸦 A01、E02-SH011 挂 order），负例测试 4/4 拦截

## 后续版本方向（v0.5+）

- ~~剪映草稿 JSON 适配器~~ 移出范围：产品边界收在 IR 本身，下游消费方式不做承诺
- 暂无排期项——真实文本驱动的结构性需求已清空，建议由下一轮真实网文（句式混乱度更高的连载文）实测驱动
