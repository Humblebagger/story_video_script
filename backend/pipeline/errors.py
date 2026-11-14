"""流水线异常。单独成模块是为了让 graph.py 与 convert.py 都能用而不互相 import。"""
from server.messages import UserError


class ConversionError(UserError, RuntimeError):
    """转换失败。带代码的（ConversionError.of(code, report, lines, **params)）str() 是中文兜底、不含服务器路径。
    report 是校验报告原文（回喂模型的那份，不翻译；调试日志与命令行用）；
    lines 是同一份报告给用户看的逐条消息（spec 子计划 5 C），app 用它作 job.failed_report 的 report 参数，
    没有逐条时退回 report 原文。"""

    def __init__(self, msg: str, report: str = "", lines=None):
        super().__init__(msg)
        self.report = report
        self.lines = list(lines or [])
