"""流水线异常。单独成模块是为了让 graph.py 与 convert.py 都能用而不互相 import。"""
from server.messages import UserError


class ConversionError(UserError, RuntimeError):
    """转换失败。带代码的（ConversionError.of(code, report, **params)）str() 是中文兜底、不含服务器路径；
    report 是校验报告原文（不翻译），app 把它作为 job.failed_report 的 report 参数（spec 子计划 4 B）。"""

    def __init__(self, msg: str, report: str = ""):
        super().__init__(msg)
        self.report = report
