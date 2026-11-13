"""视频厂商注册表。STORYBOARD_VIDEO_PROVIDER 选默认厂商（缺省 seedance）。

新增厂商：写 providers/<name>.py，在文件末尾 register 一行。测试用 register 换成自己的实例。
"""
import os

_FACTORIES: dict = {}
_INSTANCES: dict = {}


def register(name: str, factory) -> None:
    _FACTORIES[name] = factory
    _INSTANCES.pop(name, None)


def default_video_name() -> str:
    return os.environ.get("STORYBOARD_VIDEO_PROVIDER", "").strip() or "seedance"


def get_video(name=None):
    """按名字取厂商实例（同名只建一次）。未注册抛 KeyError；建不起来（如没配密钥）由工厂抛 ProviderError。"""
    name = name or default_video_name()
    if name not in _INSTANCES:
        factory = _FACTORIES.get(name)
        if factory is None:
            raise KeyError(f"未知的视频厂商：{name}")
        _INSTANCES[name] = factory()
    return _INSTANCES[name]


def names() -> list:
    """界面可选的厂商。假厂商只在被设为默认（测试、本地演示）时出现。"""
    return [n for n in sorted(_FACTORIES) if n != "fake" or default_video_name() == "fake"]


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
            raise KeyError(f"未知的配音厂商：{name}")
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
