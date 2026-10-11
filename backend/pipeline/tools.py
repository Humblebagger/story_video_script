"""修复阶段的工具声明。

工具实现一律复用 repair.py——那里的约束（只允许 add/remove/replace、
/coverage 与 /meta 前缀锁定、模型拿不到文件系统或任意代码执行）是审计过的，
本模块只负责把它们包成 LangChain 工具。

关键设计点：doc 有 36KB，绝不能让模型当参数传。用 InjectedState 让运行时把
状态塞进来，模型只看得见 unit_ids / asset_ids / patch 这几个小参数。
"""
import copy
from typing import Annotated, Any

from langchain_core.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from . import repair


@tool
def source_read(unit_ids: list[str],
                state: Annotated[dict, InjectedState]) -> list[dict]:
    """按句子编号读取冻结的原文句单元，确认画面有没有原文依据。例：["u0001"]。"""
    return repair.source_read(state["doc"], unit_ids)


@tool
def asset_get(asset_ids: list[str],
              state: Annotated[dict, InjectedState]) -> list[dict]:
    """按资产编号读取资产卡（角色 C / 场景 S / 道具 P / 设定图 A）。例：["C01"]。"""
    return repair.asset_get(state["doc"], asset_ids)


@tool
def validation_list(state: Annotated[dict, InjectedState]) -> list[dict]:
    """列出当前产物的全部校验失败条目，每条含位置与原因。"""
    return repair.validation_list(state["structured"])


@tool
def coverage_query(state: Annotated[dict, InjectedState]) -> dict:
    """查询原文覆盖率统计：哪些句单元还没有镜头覆盖。"""
    return repair.coverage_query(state["structured"])


@tool
def json_patch(patch: list[dict],
               tool_call_id: Annotated[str, InjectedToolCallId],
               state: Annotated[dict, InjectedState]) -> Command:
    """提交受限 JSON Patch 修正产物。只允许 add/remove/replace；
    /coverage 与 /meta 前缀锁定（它们是程序重算的结果，不接受模型改写）。"""
    doc = repair.apply_tool_call(copy.deepcopy(state["doc"]),
                                 {"tool": "json_patch", "patch": patch})
    return Command(update={
        "doc": doc,
        "patch_applied": True,
        "messages": [ToolMessage(f"补丁已应用（{len(patch)} 项），即将重新校验",
                                 tool_call_id=tool_call_id)],
    })


@tool
def task_done(tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """声明本轮修复完成，交回程序重新校验。"""
    return Command(update={
        "task_done": True,
        "messages": [ToolMessage("本轮修复结束，重新校验",
                                 tool_call_id=tool_call_id)],
    })


REPAIR_TOOLS = [source_read, asset_get, validation_list, coverage_query,
                json_patch, task_done]
