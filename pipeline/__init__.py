"""小说 → 分镜 IR 一键流水线。

把仓库里原本人肉执行的转换流程编排成代码：
自动分批 → 调用 LLM（prompts/novel_to_storyboard.md）→ 三层校验（失败回喂重试）
→ 分批合并 → 整章终检 → 输出通过校验的分镜 JSON。

入口：
  CLI   python3 -m pipeline convert novel.txt -o storyboard.json
  服务  uvicorn server.app:app（见 server/app.py）
"""

__version__ = "0.4.0"
