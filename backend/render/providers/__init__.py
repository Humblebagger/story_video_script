"""视频厂商注册表。STORYBOARD_VIDEO_PROVIDER 选默认厂商。

未显式设置时：配了 MiniMax 密钥用 minimax；没配 MiniMax 而配了方舟密钥回落 seedance；都没配仍取 minimax。
只影响新建的出片会话，已有会话不迁移。

新增厂商：写 providers/<name>.py，在文件末尾 register 一行。测试用 register 换成自己的实例。
"""
import os

from server.messages import UserError


class UnknownProvider(UserError, KeyError):
    """未注册的厂商名（继承 KeyError：原有 except KeyError 不变）。"""


_FACTORIES: dict = {}
_INSTANCES: dict = {}


def register(name: str, factory) -> None:
    _FACTORIES[name] = factory
    _INSTANCES.pop(name, None)


_KEY_ENV = {"minimax": "MINIMAX_API_KEY", "seedance": "ARK_API_KEY"}


def _has_key(name: str) -> bool:
    """这家厂商的密钥是否已配置。先把 backend/.env 读进进程环境（与各厂商 from_env 同一个加载函数，
    只放进环境、不读出不打印），再看变量是否非空。.env 只在这里加载：测试给它打桩就不会碰真实 .env。"""
    from pipeline.config import ROOT, _load_dotenv
    _load_dotenv(ROOT / ".env")
    _load_dotenv(ROOT.parent / ".env")
    return bool(os.environ.get(_KEY_ENV.get(name, ""), "").strip())


def _default_choice() -> tuple:
    """(缺省厂商, 是否发生了回落)。显式设置 STORYBOARD_VIDEO_PROVIDER 照用；否则有 MiniMax 密钥用 minimax，
    只有方舟密钥回落 seedance，都没有仍取 minimax（缺密钥的提示指向推荐厂商）。只影响新建的出片会话。"""
    explicit = os.environ.get("STORYBOARD_VIDEO_PROVIDER", "").strip()
    if explicit:
        return explicit, False
    if _has_key("minimax"):
        return "minimax", False
    if _has_key("seedance"):
        return "seedance", True
    return "minimax", False


def default_video_name() -> str:
    return _default_choice()[0]


def default_fell_back() -> bool:
    return _default_choice()[1]


def get_video(name=None):
    """按名字取厂商实例（同名只建一次）。未注册抛 KeyError；建不起来（如没配密钥）由工厂抛 ProviderError。"""
    name = name or default_video_name()
    if name not in _INSTANCES:
        factory = _FACTORIES.get(name)
        if factory is None:
            raise UnknownProvider.of("film.provider.unknown", name=name)
        _INSTANCES[name] = factory()
    return _INSTANCES[name]


def names() -> list:
    """界面可选的厂商。假厂商只在被显式设为默认（测试、本地演示）时出现。"""
    fake_on = os.environ.get("STORYBOARD_VIDEO_PROVIDER", "").strip() == "fake"
    return [n for n in sorted(_FACTORIES) if n != "fake" or fake_on]


def _fake():
    from render.providers.fake import FakeVideo
    return FakeVideo()


register("fake", _fake)


def _seedance():
    from render.providers.seedance import Seedance
    return Seedance.from_env()


register("seedance", _seedance)


def _minimax():
    from render.providers.minimax import MiniMax
    return MiniMax.from_env()


register("minimax", _minimax)


# ---------- TTS 厂商：STORYBOARD_TTS_PROVIDER 选默认（缺省 volc） ----------

_TTS_FACTORIES: dict = {}
_TTS_INSTANCES: dict = {}


def register_tts(name: str, factory) -> None:
    _TTS_FACTORIES[name] = factory
    _TTS_INSTANCES.pop(name, None)


def default_tts_name() -> str:
    return os.environ.get("STORYBOARD_TTS_PROVIDER", "").strip() or "volc"


def get_tts(name=None):
    """按名字取 TTS 厂商实例（同名只建一次）。未注册抛 KeyError；建不起来（没配密钥）由工厂抛 ProviderError。"""
    name = name or default_tts_name()
    if name not in _TTS_INSTANCES:
        factory = _TTS_FACTORIES.get(name)
        if factory is None:
            raise KeyError(f"未知的配音厂商：{name}")  # i18n: todo(2)
        _TTS_INSTANCES[name] = factory()
    return _TTS_INSTANCES[name]


def tts_names() -> list:
    """界面可选的配音厂商。假 TTS 只在被设为默认时出现。"""
    return [n for n in sorted(_TTS_FACTORIES) if n != "fake" or default_tts_name() == "fake"]


def _fake_tts():
    from render.providers.fake import FakeTts
    return FakeTts()


register_tts("fake", _fake_tts)


def _volc_tts():
    from render.providers.tts_volc import VolcTts
    return VolcTts.from_env()


register_tts("volc", _volc_tts)
