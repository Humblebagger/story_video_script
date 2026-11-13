"""转换进度的两路输出（设计 docs/specs/2026-11-13-backend-i18n-design.md「子计划 4 范围补充」B）。

say(code, **params) 是给用户的进度事件的唯一出口：交给 on_event 一个消息对象（前端按语言渲染），
同时把它的中文兜底写进 log（调试日志；命令行打印的也是它）。给开发看的细节（校验报告逐行、
工作目录、工具输出）照旧直接 log(...)，不翻译、不进事件。
"""
from typing import Callable, Optional

from server.messages import msg


def make_say(log: Callable[[str], None], on_event: Optional[Callable[[dict], None]] = None):
    def say(code: str, /, **params) -> dict:
        m = msg(code, **params)
        log(m["message"])
        if on_event is not None:
            on_event(m)
        return m
    return say
