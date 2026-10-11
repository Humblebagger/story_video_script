"""流水线异常。单独成模块是为了让 graph.py 与 convert.py 都能用而不互相 import。"""


class ConversionError(RuntimeError):
    def __init__(self, msg: str, report: str = ""):
        super().__init__(msg)
        self.report = report
