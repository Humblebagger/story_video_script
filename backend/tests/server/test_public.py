#!/usr/bin/env python3
"""给普通用户的出口：词表、短键、消息净化、会话视图过滤。用法: python3 tests/server/test_public.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

from server import messages as M, public as P  # noqa: E402


def main() -> int:
    # 1. 词表：大小写、短词边界、中文
    assert P.redact("MiniMax says ARK; dark park; volces.com; 火山方舟") == "*** says ***; dark park; ***.com; ******"
    assert P.find_vendor_words({"a": "film.ark.x", "b": ["Doubao"]}) == ["ark", "doubao"]
    assert P.find_vendor_words({"a": "引擎 A · 标准", "b": "dark"}) == []
    print("词表 ✓")

    # 2. 短键
    assert P.task_key(None) is None and P.task_key("") is None
    assert P.task_key("cgt-1") == P.task_key("cgt-1") != P.task_key("cgt-2")
    assert len(P.task_key("x")) == 17 and P.task_key("x").startswith("t") and "cgt" not in P.task_key("cgt-1")
    print("短键 ✓")

    # 3. public_msg
    g = P.public_msg({"code": "nope.x", "params": {}, "ref": "AB12CD"})
    assert g["code"] == "common.failed_generic" and g["ref"] == "AB12CD" and "AB12CD" in g["message"]
    assert P.public_msg({"code": "film.submit.unavailable", "params": {"retries": 3}})["code"] == "common.failed_generic"
    m = P.public_msg({"code": "film.submit.unavailable", "message": "MiniMax 挂了",
                      "params": {"retries": 3, "extra": "Seedance",
                                 "cause": {"t": "vendor", "text": "POST https://api.minimax.cn 502"}}})
    assert m["code"] == "film.submit.unavailable" and set(m["params"]) == {"retries", "cause"}
    assert m["params"]["cause"] == {"t": "vendor", "text": "POST https://api.***.cn 502"} and not P.find_vendor_words(m)
    assert P.public_msg(None)["code"] == "common.failed_generic"
    print("public_msg ✓")

    # 4. error_pair
    assert P.error_pair({"error": None, "error_msg": None}) == (None, None)
    text, em = P.error_pair({"error": "KeyError: 'video_url' sk-live-1 https://cdn/x?X-Tos-Signature=zz", "error_msg": None})
    assert em == {"code": "common.failed_generic", "params": {}} and "sk-live" not in text
    print("error_pair ✓")

    # 5. scrub_errors
    out = P.scrub_errors({"state": "failed", "step": "配音", "step_msg": None, "error": "x", "error_msg": None,
                          "detail": "ffmpeg … doubao", "files": ["a.mp4"]})
    assert out["step"] is None and out["step_msg"] is None and out["error_msg"]["code"] == "common.failed_generic"
    assert out["detail"] == "ffmpeg … ***" and out["files"] == ["a.mp4"]
    print("scrub_errors ✓")

    # 6. film_view
    view = {"provider": "minimax", "model": "minimax-h3", "resolution": "768P",
            "clips": [{"id": "E01-C01", "state": "failed", "error": "x", "error_msg": None, "attempts": [
                {"task_id": "cgt-1", "state": "abandoned", "cost_cny": 0, "file": None, "last_frame": None, "error": None,
                 "error_msg": None, "at": "t", "fingerprint": "f", "first_frame_used": None,
                 "video_url": "https://x.volces.com/v.mp4?sig=1", "last_frame_url": "u", "usage": {"n": 1},
                 "billing": {"provider": "minimax", "model": "minimax-h3"}, "known_cost_cny": 2, "future_field": "MiniMax"}]}],
            "free": [], "orphaned": [{"id": "o", "shots": [], "attempts": [], "chosen": None}], "final": None,
            "options": {"providers": ["minimax"], "models": {"minimax-h3": {"label": "MiniMax H3"}}, "resolutions": ["768P"],
                        "default_note": "minimax_key_missing", "rate_note": {"code": "x", "params": {}}}}
    v = P.film_view(view, tier="a-standard", tiers=[{"id": "a-standard"}], rate_note={"code": "common.internal", "params": {}})
    assert "provider" not in v and "model" not in v and v["tier"] == "a-standard"
    a = v["clips"][0]["attempts"][0]
    assert set(a) == set(P.ATTEMPT_KEYS) & set(a) | {"task_id", "error", "error_msg"} and a["task_id"] == P.task_key("cgt-1")
    assert not {"video_url", "last_frame_url", "usage", "billing", "known_cost_cny", "future_field"} & set(a)
    assert set(v["options"]) == {"resolutions", "rate_note", "tiers"} and not P.find_vendor_words(v)
    assert view["provider"] == "minimax" and "video_url" in view["clips"][0]["attempts"][0], "不改入参"
    print("film_view ✓")

    # 7. 旧数据经出口后的样子
    m = P.public_msg({"code": "film.minimax.insufficient_balance", "params": {}, "message": "视频服务（MiniMax）账户余额不足…"})
    assert m["code"] == "film.vendor.balance" and m["message"] == M.render_zh("film.vendor.balance", {})
    m = P.public_msg({"code": "film.provider.rejected", "params": {"detail": {"t": "vendor", "text": "MiniMax: bad"}}})
    assert m == M.msg("film.vendor.rejected")
    m = P.public_msg({"code": "film.submit.ambiguous", "params": {
        "console": {"t": "ref", "code": "console.minimax"}, "cause": {"code": "film.ark.connect_failed", "params": {"kind": "ConnectError"}}}})
    assert m["params"] == {"cause": {"code": "film.vendor.connect_failed", "params": {}}} and not P.find_vendor_words(m)
    m = P.public_msg({"code": "tts.volc.failed_detail", "params": {"code": "45000", "detail": {"t": "vendor", "text": "豆包…"}}})
    assert m["code"] == "tts.vendor.failed" and m["params"] == {"code": "45000"}
    print("旧代码归一 ✓")

    # 8. 参考编号：嵌套原因里的编号提升到外层；公开原因（public_cause）带着编号
    from server.messages import with_ref
    from render.providers.base import ProviderError
    inner = {"code": "tts.vendor.rejected", "params": {}, "ref": "AB12CD34"}
    m = P.public_msg({"code": "film.poll.gave_up", "params": {"cause": inner}})
    assert m["ref"] == "AB12CD34" and "AB12CD34" in m["message"] and "ref" not in m["params"]["cause"], m
    m = P.public_msg({"code": "film.poll.gave_up", "ref": "ZZ99ZZ99", "params": {"cause": inner}})
    assert m["ref"] == "ZZ99ZZ99", "外层自己有编号时不覆盖"
    e = ProviderError.from_msg(with_ref(M.msg("tts.vendor.rejected"), "AB12CD34"))
    assert M.public_cause(e) == inner, M.public_cause(e)
    assert M.public_cause(RuntimeError("x")) == {"code": "film.vendor.unknown_cause", "params": {}}
    print("参考编号提升 ✓")

    # 9. 金额与原文参数只留允许字段；形状不合法整条回落通用消息并保留有效编号
    ok = P.public_msg({"code": "film.run.confirm", "params": {"amount": {"t": "money", "cny": 1.236, "detail": "MiniMax"}}})
    assert ok["params"]["amount"] == {"t": "money", "cny": 1.24} and not P.find_vendor_words(ok)
    for bad in ({"t": "money"}, {"t": "money", "cny": "bad"}, {"t": "money", "cny": float("nan")},
                {"t": "money", "cny": float("inf")}, {"t": "money", "cny": True}):
        g = P.public_msg({"code": "film.run.confirm", "ref": "AB12CD34", "params": {"amount": bad}})
        assert g["code"] == "common.failed_generic" and g["ref"] == "AB12CD34", (bad, g)
    v = P.public_msg({"code": "film.fake.failed", "params": {"detail": {"t": "vendor", "text": "x MiniMax", "extra": "Seedance"}}})
    assert v["params"]["detail"] == {"t": "vendor", "text": "x ***"}, v
    print("money / vendor 参数 ✓")

    # 10. 配音错误码只放行整数或纯数字串（最长 12 位）；历史 failed_detail 同样
    for good in (45000000, "45000"):
        assert P.public_msg({"code": "tts.volc.failed_detail", "params": {"code": good, "detail": {"t": "vendor", "text": "x"}}})["code"] == "tts.vendor.failed"
    for bad in ("Doubao.InvalidSpeaker", "1234567890123", ["1"], True, 1.5, -3):
        g = P.public_msg({"code": "tts.vendor.failed", "ref": "AB12CD34", "params": {"code": bad}})
        assert g["code"] == "common.failed_generic" and g["ref"] == "AB12CD34", (bad, g)
    print("配音 code 白名单 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
