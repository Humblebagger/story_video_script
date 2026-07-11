"""配置：环境变量（支持仓库根目录 .env 文件）→ Settings。"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 解析：KEY=VALUE 逐行读取，已有环境变量优先。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


@dataclass
class Settings:
    api_key: Optional[str] = None
    base_url: Optional[str] = None          # 走网关/代理时设置 ANTHROPIC_BASE_URL
    model: str = "claude-sonnet-5"
    max_tokens: int = 32000
    temperature: float = 0.2
    batch_target_chars: int = 2500          # 分批目标字符数（在段落边界切）
    single_batch_max_chars: int = 3200      # 不超过此长度不分批
    max_retries: int = 2                    # 校验失败后的回喂重试次数


def load_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    env = os.environ.get
    return Settings(
        api_key=env("ANTHROPIC_API_KEY"),
        base_url=env("ANTHROPIC_BASE_URL"),
        model=env("STORYBOARD_MODEL", "claude-sonnet-5"),
        max_tokens=int(env("STORYBOARD_MAX_TOKENS", "32000")),
        temperature=float(env("STORYBOARD_TEMPERATURE", "0.2")),
        batch_target_chars=int(env("STORYBOARD_BATCH_CHARS", "2500")),
        single_batch_max_chars=int(env("STORYBOARD_SINGLE_BATCH_MAX", "3200")),
        max_retries=int(env("STORYBOARD_MAX_RETRIES", "2")),
    )
