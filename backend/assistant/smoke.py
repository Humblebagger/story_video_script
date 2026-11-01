"""助手真实模型冒烟（花几分钱；用户手动运行，开发与测试中不运行）。

用法（backend/ 下）: .venv/bin/python -m assistant.smoke <用户名> <小说标题> "<问题>"
"""
import sys

from assistant import events, graph, store
from pipeline.chat import UsageCallback, build_chat_model, replace_thinking
from pipeline.config import load_settings
from server import auth, novels


def main(argv: list) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    user = next((u for u in auth.list_users_safe() if u["username"] == argv[0]), None)
    if not user:
        print("找不到用户")
        return 1
    novel = next((n for n in novels.list_novels(user["id"]) if n["title"] == argv[1]), None)
    if not novel:
        print("找不到小说")
        return 1
    cb = UsageCallback()
    model = build_chat_model(replace_thinking(load_settings()))
    with store.saver(user["id"], novel["id"]) as cp:
        agent = graph.build_agent(model, cp)
        for ev in events.stream(agent, graph.run_config(user["id"], novel["id"], {}, "zh", [cb]), argv[2]):
            if ev["event"] == "token":
                print(ev["data"]["text"], end="", flush=True)
            else:
                print(f"\n[{ev['event']}] {ev['data']}")
    print("用量：", cb.usage_totals())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
