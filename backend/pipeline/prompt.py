"""从 prompts/novel_to_storyboard.md 加载系统提示词，并按用户输入模板拼装 user message。

模板结构以 prompt 文件中的「用户输入模板」为准；此处的拼装格式与
tests/real_text_yao/input_batch*.txt 归档件逐字段一致。
"""
from functools import lru_cache

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


def build_user_message(params, novel_text: str,
                       existing_assets: str = "无",
                       continuation: str = "无") -> str:
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

【小说原文】
作品：{params.work_title}
章节：{params.chapter}

{novel_text}"""
