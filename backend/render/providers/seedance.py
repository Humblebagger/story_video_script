"""火山方舟 Seedance：提示词语法（@图片n），以及提交、查询、下载、计费。

接口与价格核实于 2026-10-31 的官方文档：首帧模式与参考图模式互斥；结果地址 24 小时有效；
失败任务不计费。
"""
import itertools
import re

_REF = re.compile(r"\{ref:([^{}]+)\}")


def rewrite_refs(text: str) -> str:
    """厂商无关占位符 {ref:ID} → Seedance 的 @图片n，按出现顺序编号。

    同一资产出现两次也各占一张图（同一场景的两个机位是两张图），所以按次序而不是按 ID
    编号；请求里的参考图按同一顺序排列。
    """
    n = itertools.count(1)
    return _REF.sub(lambda m: f"@图片{next(n)}", text)
