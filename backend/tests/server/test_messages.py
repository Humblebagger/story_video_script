#!/usr/bin/env python3
"""后端消息登记：代码、参数、中文兜底、带类型参数、异常 mixin、to_detail。用法: python3 tests/server/test_messages.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

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


# 固定的旧码 → 新码清单（逐项照 spec §6.3），与 messages._legacy() 独立书写
EXPECTED_LEGACY = {
    "film.ark.access_denied": "film.vendor.access_denied",
    "film.ark.auth": "film.vendor.auth",
    "film.ark.connect_failed": "film.vendor.connect_failed",
    "film.ark.copyright": "film.vendor.copyright",
    "film.ark.download_failed": "film.provider.download_failed",
    "film.ark.http_ambiguous": "film.vendor.http_ambiguous",
    "film.ark.input_moderated": "film.vendor.input_moderated",
    "film.ark.limit_paused": "film.vendor.limit_paused",
    "film.ark.model_unavailable": "film.vendor.tier_unavailable",
    "film.ark.no_key": "film.vendor.no_key",
    "film.ark.no_result_url": "film.vendor.no_result_url",
    "film.ark.no_task_id": "film.vendor.no_task_id",
    "film.ark.not_json": "film.vendor.not_json",
    "film.ark.output_copyright": "film.vendor.output_copyright",
    "film.ark.output_moderated": "film.vendor.output_moderated",
    "film.ark.overdue": "film.vendor.balance",
    "film.ark.quota": "film.vendor.quota",
    "film.ark.task_expired": "film.vendor.task_expired",
    "film.ark.throttled": "film.vendor.throttled",
    "film.ark.unavailable": "film.vendor.unavailable",
    "film.ark.unknown_model": "film.settings.no_model",
    "film.fake.unknown_model": "film.settings.no_model",
    "film.minimax.bad_image": "film.input.bad_image",
    "film.minimax.bad_ratio": "film.input.bad_ratio",
    "film.minimax.bad_resolution": "film.settings.bad_resolution",
    "film.minimax.connect_failed": "film.vendor.connect_failed",
    "film.minimax.corrupt_image": "film.input.corrupt_image",
    "film.minimax.http_ambiguous": "film.vendor.http_ambiguous",
    "film.minimax.image_too_big": "film.input.image_too_big",
    "film.minimax.insufficient_balance": "film.vendor.balance",
    "film.minimax.invalid_key": "film.vendor.auth",
    "film.minimax.label_first": "film.input.label_first",
    "film.minimax.label_ref": "film.input.label_ref",
    "film.minimax.lite_needs_ratio": "film.input.needs_ratio",
    "film.minimax.moderated": "film.vendor.input_moderated",
    "film.minimax.no_key": "film.vendor.no_key",
    "film.minimax.no_result_url": "film.vendor.no_result_url",
    "film.minimax.no_task_id": "film.vendor.no_task_id",
    "film.minimax.not_json": "film.vendor.not_json",
    "film.minimax.prompt_too_long": "film.input.prompt_too_long",
    "film.minimax.request_too_big": "film.input.request_too_big",
    "film.minimax.throttled": "film.vendor.throttled",
    "film.minimax.unavailable": "film.vendor.unavailable",
    "film.minimax.unknown_model": "film.settings.no_model",
    "film.minimax.unsupported_format": "film.input.unsupported_format",
    "film.minimax.url_expired": "film.vendor.result_expired",
    "film.provider.http_rejected": "film.vendor.rejected",
    "film.provider.rejected": "film.vendor.rejected",
    "film.provider.unknown": "film.settings.no_model",
    "rate.ark": "rate.video",
    "rate.fake": "rate.video",
    "rate.fake_tts": "rate.tts",
    "rate.minimax": "rate.video",
    "rate.volc_tts": "rate.tts",
    "tts.unknown_provider": "tts.vendor.misconfigured",
    "tts.volc.bad_audio": "tts.vendor.bad_audio",
    "tts.volc.connect_failed": "tts.vendor.connect_failed",
    "tts.volc.cut": "tts.vendor.cut",
    "tts.volc.failed": "tts.vendor.failed",
    "tts.volc.failed_detail": "tts.vendor.failed",
    "tts.volc.incomplete": "tts.vendor.incomplete",
    "tts.volc.no_key": "tts.vendor.no_key",
    "tts.volc.not_json": "tts.vendor.not_json",
    "tts.volc.not_object": "tts.vendor.not_json",
    "tts.volc.rejected": "tts.vendor.rejected",
    "tts.volc.rejected_http": "tts.vendor.rejected_http",
    "tts.volc.unavailable": "tts.vendor.unavailable",
}


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
    for c in ("film.vendor.no_key", "film.vendor.auth", "film.vendor.balance", "film.vendor.input_moderated",
              "film.settings.no_model", "film.vendor.connect_failed", "film.provider.submit_cut",
              "film.provider.download_connect", "film.submit.crashed", "film.vendor.not_json",
              "film.vendor.no_task_id", "film.vendor.throttled", "film.vendor.rejected", "tts.vendor.rejected"):
        assert codes[c]["params"] == [], (c, codes[c])
    assert codes["film.settings.bad_resolution"]["params"] == ["resolution", "options"]
    assert codes["novel.unknown_params"]["params"] == ["keys"]
    assert codes["chapter.version.not_adoptable"]["params"] == []
    assert M.render_zh("film.provider.submit_cut", {}) == "网络中断"
    assert M.render_zh("film.submit.crashed", {}) == "提交时出现意外错误，请重试；仍失败请联系管理员"

    # 对照表：旧代码不在登记表、新代码在、新参数 ⊆ 旧参数（旧数据总能渲染）；全表没有厂商词
    from server import public as P
    from render.providers.base import ProviderError as _PE3
    OLD_PARAMS = {  # 删除前各旧代码的参数（只列有参数的；其余为空）
        "film.ark.http_ambiguous": ["status"], "film.ark.unavailable": ["status"], "film.ark.download_failed": ["status"],
        "film.minimax.http_ambiguous": ["status"], "film.minimax.unavailable": ["status"], "film.minimax.throttled": ["status"],
        "film.minimax.label_ref": ["id"], "film.minimax.bad_image": ["label"], "film.minimax.corrupt_image": ["label"],
        "film.minimax.unsupported_format": ["label", "mime"], "film.minimax.image_too_big": ["label", "mb"],
        "film.minimax.prompt_too_long": ["max", "len"], "film.minimax.bad_ratio": ["ratio", "options"],
        "film.minimax.request_too_big": ["mb"], "film.minimax.bad_resolution": ["resolution", "options"],
        "film.provider.rejected": ["detail"], "film.provider.http_rejected": ["status", "detail"],
        "film.provider.unknown": ["name"], "tts.unknown_provider": ["name"],
        "tts.volc.unavailable": ["status"], "tts.volc.rejected": ["code", "detail"], "tts.volc.rejected_http": ["status"],
        "tts.volc.failed": ["code"], "tts.volc.failed_detail": ["code", "detail"],
    }
    assert M.LEGACY == EXPECTED_LEGACY, "对照表与固定清单不一致：" + str(set(M.LEGACY.items()) ^ set(EXPECTED_LEGACY.items()))
    for old, new in M.LEGACY.items():
        assert not M.registered(old), f"{old} 应已删除"
        assert M.registered(new), f"{new} 没登记"
        assert set(M.params_of(new)) <= set(OLD_PARAMS.get(old, [])), (old, new)
    assert not [c for c in codes if c.startswith(("film.ark.", "film.minimax.", "tts.volc.", "console."))]
    hits = {c: P.find_vendor_words([c, v["zh"]]) for c, v in M.dump_codes().items()}
    assert not {c: h for c, h in hits.items() if h}, "登记表里不得有厂商词"
    # public_cause：有代码给紧凑消息；没有代码不带原文
    e = _PE3.of("film.vendor.throttled")
    assert M.public_cause(e) == {"code": "film.vendor.throttled", "params": {}}
    assert M.public_cause(RuntimeError("POST https://api.minimax.cn 502")) == {"code": "film.vendor.unknown_cause", "params": {}}
    print("对照表 / public_cause ✓")

    # 10. with_ref：顶层 ref，已有编号时替换、不重复附加
    r1 = M.with_ref(M.msg("common.internal"), "K7Q2M9XD")
    r2 = M.with_ref(r1, "AB12CD34")
    assert r2["ref"] == "AB12CD34" and r2["message"].count("参考编号") == 1 and r2["message"].endswith("（参考编号 AB12CD34）"), r2
    assert "K7Q2M9XD" not in r2["message"] and "ref" not in r2["params"]

    from render.providers.base import ProviderError
    e = ProviderError.of("tts.vendor.failed", code="401")
    assert e.params["code"] == "401" and str(e) == "配音合成失败（401）", "参数可以叫 code"

    # 子计划 4：长报告参数、换异常类型保留代码
    long = "行\n" * 5000
    assert len(M.vendor(long)["text"]) == M.VENDOR_MAX
    assert len(M.vendor(long, limit=M.REPORT_MAX)["text"]) == M.REPORT_MAX == 6000
    m = M.msg("chapter.version.not_found")

    class E1(M.UserError, ValueError):
        pass

    class E2(M.UserError, Exception):
        pass

    e = E2.from_msg({**m, "ref": "K7Q2M9XD"})
    assert isinstance(e, E2) and e.code == "chapter.version.not_found" and e.params == {} and str(e) == "版本不存在"
    e = M.recast(E2, E1.of("novel.bad_id", id="../x"))
    assert e.code == "novel.bad_id" and e.params == {"id": "../x"} and str(e) == "非法的 ID：../x"
    e = M.recast(E2, KeyError("raw"))
    assert e.code is None and str(e) == "raw", "无代码的保留原文（KeyError 不加引号）"
    e = E2.from_msg(M.with_ref(M.msg("common.internal"), "K7Q2M9XD"))
    assert e.as_msg()["ref"] == "K7Q2M9XD" and "参考编号 K7Q2M9XD" in str(e)
    print("子计划 4：vendor 上限 / from_msg / recast ✓")
    # 子计划 5：逐条报告参数 lines（spec 子计划 5 C）
    L = M.lines_of([M.msg("common.unknown", message="a"), M.vendor("b"), "c"])
    assert L == {"t": "lines", "items": [{"code": "common.unknown", "params": {"message": "a"}},
                                         {"t": "vendor", "text": "b"}, "c"]}, "消息对象压成紧凑形，其余原样"
    assert M.render_zh("common.unknown", {"message": L}) == "a\nb\nc", "中文兜底换行连接"
    big = M.lines_of([M.msg("common.unknown", message=str(i)) for i in range(M.LINES_MAX + 7)])
    assert len(big["items"]) == M.LINES_MAX + 1 == 101
    assert big["items"][-1] == {"code": "common.more_lines", "params": {"n": 7}}
    assert M.render_zh("common.more_lines", {"n": 7}) == "…还有 7 行未显示"
    # 总长预算：按中文兜底累计，超过 REPORT_MAX 就截止（防止落盘的报告与中文兜底无界变大，设计审查 I3）
    long = M.lines_of([M.msg("common.unknown", message="字" * 300)] * 30)
    assert len(long["items"]) == 20 and long["items"][-1] == {"code": "common.more_lines", "params": {"n": 11}}, "每项 301 字（含换行），19 项后超预算"
    assert len(M.render_zh("common.unknown", {"message": long})) <= M.REPORT_MAX + 100
    print("子计划 5：lines_of / 条数与总长截断 / 中文兜底 ✓")
    # 内容限制的消息：类别走代码引用，拦截消息带参考编号
    from server import messages as _m, public as _p
    for c in ("sexual", "minor_sexual", "drugs", "political", "extremism", "unspecified"):
        assert _m.registered(f"safety.category.{c}"), c
    assert not _m.registered("safety.category") and not _m.registered("safety.reason")
    blocked = _m.with_ref(_m.msg("safety.blocked", category=_m.ref("safety.category.sexual")), "AB12CD34")
    assert blocked["message"] == "内容不符合使用规范，已拒绝生成（类别：色情）（参考编号 AB12CD34）", blocked["message"]
    out = _p.public_msg(blocked)
    assert out["code"] == "safety.blocked" and out["ref"] == "AB12CD34"
    assert out["params"]["category"] == {"t": "ref", "code": "safety.category.sexual"}
    assert _m.msg("safety.unavailable")["message"] == "暂时无法完成内容检查，请稍后再试"
    for code in ("safety.reason.blocklist", "safety.reason.model_refused", "job.event.safety_check",
                 "film.safety_checking", "admin.safety.not_releasable"):
        assert _m.registered(code), code
    assert _m.params_of("admin.safety.not_found") == ("ref",)
    print("内容限制消息登记 ✓")
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
