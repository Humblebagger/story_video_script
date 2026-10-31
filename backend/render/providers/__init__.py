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
