"""从 prompts/novel_to_storyboard.md 加载系统提示词，并按用户输入模板拼装 user message。

模板结构以 prompt 文件中的「用户输入模板」为准；此处的拼装格式与
tests/real_text_yao/input_batch*.txt 归档件逐字段一致。
"""
from functools import lru_cache
import json
import math

from .config import ROOT

PROMPT_PATH = ROOT / "prompts" / "novel_to_storyboard.md"


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    try:
        body = text.split("\n## 系统提示词\n", 1)[1]
        return body.split("\n---\n", 1)[0].strip()
    except IndexError:
        raise RuntimeError(f"无法从 {PROMPT_PATH} 提取「## 系统提示词」段落，请检查文件结构")


# 人工基准的旁白占比（《药》0.18、《玉佩》0.36），见 quality.narration_density_gate
NARRATION_BENCHMARK = (0.18, 0.36)


def narration_budget(n_units: int, max_ratio: float) -> str:
    """selective 模式的旁白预算：把比例换算成本批的具体句数。

    弱模型对「只念画面承载不了的」这类原则几乎不执行，实测首次生成旁白占比
    97%–100%；给出具体句数和打回线，放在消息末尾离生成最近的位置。
    """
    lo, hi = (round(n_units * r) for r in NARRATION_BENCHMARK)
    cap = math.floor(n_units * max_ratio + 1e-9)
    return (f"\n\n【旁白预算】\n"
            f"本批共 {n_units} 个句单元。selective 模式下人工基准的旁白约占 "
            f"{NARRATION_BENCHMARK[0]:.0%}–{NARRATION_BENCHMARK[1]:.0%}，即本批"
            f"约 {lo}–{hi} 句进 narration.unit_refs；超过 {cap} 句会被自动打回重做。\n"
            f"逐句自问「删掉这句旁白，只看画面的观众会损失信息吗」，输出前数一遍"
            f"全部 narration.unit_refs 的总数。\n"
            f"不进旁白的句子必须由画面或台词承载：被某个镜头的 source.unit_refs "
            f"引用，否则算未覆盖。")


def build_user_message(params, novel_text: str,
                       existing_assets: str = "无",
                       continuation: str = "无",
                       frozen_units=None,
                       narration_density_max=None) -> str:
    units_block = (json.dumps(frozen_units, ensure_ascii=False, indent=2)
                   if frozen_units is not None else "无（兼容模式：由模型切分）")
    budget = (narration_budget(len(frozen_units), narration_density_max)
              if params.narration_mode == "selective" and frozen_units
              and narration_density_max is not None and narration_density_max < 1
              else "")
    return f"""【制作参数】
风格前缀：{params.style_prefix}
风格分类：{params.art_style}
色调：{params.color_tone}
画幅：{params.aspect_ratio}
目标平台：{params.target_platform}
旁白模式：{params.narration_mode}
旁白音色：{params.tts_voice}

【已有资产库】
{existing_assets}

【续批参数】
{continuation}

【冻结源单元】
{units_block}

【小说原文】
作品：{params.work_title}
章节：{params.chapter}

{novel_text}{budget}"""
