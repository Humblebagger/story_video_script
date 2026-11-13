#!/usr/bin/env python3
"""后端消息登记：代码、参数、中文兜底、带类型参数、异常 mixin、to_detail。用法: python3 tests/server/test_messages.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from server import messages as M  # noqa: E402


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


class Boom(M.UserError, ValueError):
    pass


class Conf(M.UserError, ValueError):
    def __init__(self, message, expected_cny=None):
        super().__init__(message)
        self.expected_cny = expected_cny


def main() -> int:
    reg = M._REG.copy()
    try:
        # 1. 登记：参数取自模板占位符；重复、叶子与前缀冲突都拒绝
        M.register("t.a.leaf", "第 {n} 段：{why}")
        assert M._REG["t.a.leaf"] == (("n", "why"), "第 {n} 段：{why}")
        must_raise(ValueError, M.register, "t.a.leaf", "x")
        must_raise(ValueError, M.register, "t.a", "x")            # t.a 是 t.a.leaf 的前缀
        must_raise(ValueError, M.register, "t.a.leaf.more", "x")  # t.a.leaf 已是叶子

        # 2. msg：未登记、缺参数、多参数都抛；渲染中文兜底
        must_raise(KeyError, M.msg, "t.nope")
        must_raise(ValueError, M.msg, "t.a.leaf", n=1)
        must_raise(ValueError, M.msg, "t.a.leaf", n=1, why="x", extra=2)
        m = M.msg("t.a.leaf", n=3, why="断网")
        assert m == {"code": "t.a.leaf", "params": {"n": 3, "why": "断网"}, "message": "第 3 段：断网"}

        # 3. 带类型的值：金额、代码引用、厂商原文、列表、嵌套原因
        M.register("t.money", "本次约 {amount}")
        assert M.msg("t.money", amount=M.money(12.3))["message"] == "本次约 ¥12.30"
        M.register("t.place", "控制台")
        M.register("t.go", "请到{where}核对")
        assert M.msg("t.go", where=M.ref("t.place"))["message"] == "请到控制台核对"
        must_raise(KeyError, M.ref, "t.nope")
        v = M.vendor("x" * 500)
        assert v == {"t": "vendor", "text": "x" * 300}
        M.register("t.list", "可选：{options}")
        assert M.msg("t.list", options=["720p", "1080p"])["message"] == "可选：720p、1080p"
        inner = M.msg("t.money", amount=M.money(1))
        outer = M.msg("t.a.leaf", n=1, why=M.compact(inner))
        assert outer["params"]["why"] == {"code": "t.money", "params": {"amount": {"t": "money", "cny": 1.0}}}
        assert outer["message"] == "第 1 段：本次约 ¥1.00"

        # 4. UserError：.of() 构造带代码的异常，str() 是中文兜底，额外位置参数照传
        e = Boom.of("t.a.leaf", n=2, why="限流")
        assert isinstance(e, ValueError) and str(e) == "第 2 段：限流" and e.code == "t.a.leaf"
        assert e.as_msg() == {"code": "t.a.leaf", "params": {"n": 2, "why": "限流"}, "message": "第 2 段：限流"}
        c = Conf.of("t.money", 7.5, amount=M.money(7.5))
        assert c.expected_cny == 7.5 and str(c) == "本次约 ¥7.50"
        assert Boom("旧写法").as_msg() is None                    # 没带代码

        # 5. cause_of：带代码 → 紧凑消息；不带 → 厂商原文
        assert M.cause_of(e) == {"code": "t.a.leaf", "params": {"n": 2, "why": "限流"}}
        assert M.cause_of(RuntimeError("raw")) == {"t": "vendor", "text": "raw"}

        # 6. to_detail：带代码 → 消息对象（附加字段同层）；不带代码 → 字符串（与现在一致）
        assert M.to_detail(e) == e.as_msg()
        assert M.to_detail(c, expected_cny=7.5)["expected_cny"] == 7.5
        assert M.to_detail(Boom("旧写法")) == "旧写法"
        assert M.to_detail(Conf("旧写法"), expected_cny=None) == {"message": "旧写法", "expected_cny": None}

        # 6b. 无代码时一定是字符串；KeyError 只在 args[0] 是 str 时取它
        assert M.to_detail(KeyError("raw")) == "raw"
        d = M.to_detail(KeyError(404))
        assert isinstance(d, str) and d == str(KeyError(404))
        assert M.cause_of(KeyError(404)) == {"t": "vendor", "text": "404"}

        # 6c. params 是每个实例自己的，不共享类属性
        b1, b2 = Boom("a"), Boom("b")
        b1.params["k"] = 1
        assert b2.params == {} and Boom("c").params == {}

        # 7. common.unknown 的模板只是 {message}
        assert M._REG["common.unknown"][1] == "{message}"
    finally:
        M._REG.clear()
        M._REG.update(reg)

    # 8. 导出的 JSON 与登记表一致（改了登记要跑 python -m server.messages --write）
    on_disk = json.loads(M.CODES_FILE.read_text(encoding="utf-8"))
    assert on_disk == M.dump_codes(), "messages_codes.json 过期：cd backend && .venv/bin/python -m server.messages --write"

    # 9. 面向最终用户的出片文案：不再带异常类名、档位 id、环境变量名等内部参数
    codes = M.dump_codes()
    for c in ("film.ark.no_key", "film.minimax.no_key", "film.minimax.invalid_key",
              "film.minimax.insufficient_balance", "film.minimax.moderated", "film.ark.unknown_model",
              "film.minimax.unknown_model", "film.fake.unknown_model", "film.settings.no_model",
              "film.ark.connect_failed", "film.minimax.connect_failed", "film.provider.submit_cut",
              "film.provider.download_connect", "film.submit.crashed", "film.ark.not_json",
              "film.minimax.not_json", "film.ark.no_task_id", "film.minimax.no_task_id", "film.ark.throttled"):
        assert codes[c]["params"] == [], (c, codes[c])
    assert codes["film.minimax.bad_resolution"]["params"] == ["resolution", "options"]
    assert codes["novel.unknown_params"]["params"] == ["keys"]
    assert codes["chapter.version.not_adoptable"]["params"] == []
    assert M.render_zh("film.provider.submit_cut", {}) == "网络中断"
    assert M.render_zh("film.submit.crashed", {}) == "提交时出现意外错误，请重试；仍失败请联系管理员"

    # 10. with_ref：顶层 ref，已有编号时替换、不重复附加
    r1 = M.with_ref(M.msg("common.internal"), "K7Q2M9XD")
    r2 = M.with_ref(r1, "AB12CD34")
    assert r2["ref"] == "AB12CD34" and r2["message"].count("参考编号") == 1 and r2["message"].endswith("（参考编号 AB12CD34）"), r2
    assert "K7Q2M9XD" not in r2["message"] and "ref" not in r2["params"]

    from render.providers.base import ProviderError
    e = ProviderError.of("tts.volc.rejected", code="401", detail=M.vendor("x"))
    assert e.params["code"] == "401" and str(e) == "豆包语音拒绝了请求（401）：x", "参数可以叫 code"
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
