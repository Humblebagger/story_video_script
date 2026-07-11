# 小说 → AI 视频分镜脚本（忠实转换模式）

把一段/一章小说转换为 AI 视频制作可直接消费的结构化分镜文本。核心理念：**剧情属于小说，呈现属于系统**——每个镜头可溯源到原文句子，系统补的画面全部显式标记。

## 流水线

```
小说原文
  │  prompts/novel_to_storyboard.md   （LLM 转换 prompt，忠实模式规则）
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

**产品边界**：本项目的交付物是分镜 JSON 这份中间表示本身——信息完整（资产/镜头/台词/旁白/溯源）、结构合法、机器可校验。下游用剪辑器还是 AI 生视频应用消费它，不在本项目范围内；`adapters/seedance.py` 仅作为"IR 可被下游直接消费"的参考实现保留，不再扩展适配器矩阵。
