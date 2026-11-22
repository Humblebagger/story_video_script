#!/usr/bin/env python3
"""出片：厂商统一接口的公共函数、假厂商、注册表。用法: python3 tests/render/test_providers.py"""
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

from render import providers  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FAKE_MP4, FakeVideo  # noqa: E402

# 测试不读真实的 .env：各处 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pc  # noqa: E402
import render.providers.minimax as _mm  # noqa: E402
import render.providers.seedance as _sd  # noqa: E402
_pc._load_dotenv = _mm._load_dotenv = _sd._load_dotenv = lambda *_a, **_k: None


class _LogGrab(logging.Handler):
    """挂在某个 logger 上收日志文字与记录（测试不读真实日志配置）。"""
    def __init__(self, name):
        super().__init__(logging.DEBUG)
        self.lines, self.records = [], []
        self._lg = logging.getLogger(name)

    def emit(self, rec):
        self.records.append(rec)
        self.lines.append(rec.getMessage())

    def __enter__(self):
        self._lg.addHandler(self)
        return self

    def __exit__(self, *a):
        self._lg.removeHandler(self)


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def main() -> int:
    fake = FakeVideo()
    caps = fake.caps("fake-1")

    # 1. 整数秒：向上取整，夹在上下限之间；预估 = 秒数 × 单价
    assert base.request_seconds(4.2, caps) == 5
    assert base.request_seconds(1.0, caps) == 2 and base.request_seconds(30, caps) == 10
    assert base.request_seconds(6.0, caps) == 6, "整数不多算一秒"
    assert base.estimate_cny(4.2, caps, "720p") == 5.0
    assert base.estimate_cny(4.2, caps, "480p") == 2.5
    print("1. 整数秒与预估 ✓")

    # 1b. 图片费：缺省字段为 0 时与旧版相同；超出免费张数的部分按张计
    assert base.estimate_cny(4.2, caps, "720p", images=9) == 5.0, "缺省不收图片费"
    priced = base.Caps(max_clip_sec=15, min_clip_sec=4, max_refs=9, first_frame=True, last_frame=False,
                       returns_last_frame=True, native_audio=False, frame_with_refs=False,
                       resolutions=["768P"], cny_per_sec={"768P": 0.5},
                       short_side={"768P": 768}, free_images=5, cny_per_image=0.2)
    assert base.estimate_cny(4, priced, "768P") == 2.0
    assert base.estimate_cny(4, priced, "768P", images=5) == 2.0, "前 5 张免费"
    assert base.estimate_cny(4, priced, "768P", images=7) == 2.4, "超出 2 张"
    assert base.ClipRequest(prompt="", model="m", duration=1, resolution="r").images is None
    print("1b. 图片费 ✓")

    # 2. 可播放校验：MP4 容器头，不依赖 ffmpeg
    with tempfile.TemporaryDirectory() as d:
        good, bad = Path(d) / "a.mp4", Path(d) / "b.mp4"
        good.write_bytes(FAKE_MP4)
        bad.write_bytes(b"<html>expired</html>")
        assert base.is_playable_mp4(good) and not base.is_playable_mp4(bad)
        assert not base.is_playable_mp4(Path(d) / "missing.mp4")
    print("2. 可播放校验 ✓")

    # 3. 假厂商：提交 → 轮询 → 成功 → 下载 → 计费；失败、瞬时错误
    slow = FakeVideo(polls_to_finish=2)
    req = base.ClipRequest(prompt="p", model="fake-1", duration=4.2, resolution="720p")
    tid = slow.submit(req)
    assert slow.poll(tid).status == "running"
    st = slow.poll(tid)
    assert st.status == "succeeded" and st.usage == {"seconds": 5}
    with tempfile.TemporaryDirectory() as d:
        files = slow.download(st, Path(d) / "clips" / "E01-C01.v1.mp4")
        assert base.is_playable_mp4(files["video"])
        assert files["last_frame"].name == "E01-C01.v1.last.jpg" and files["last_frame"].exists()
    assert slow.cost(st, req) == 5.0
    assert slow.cost(base.TaskState("x", "failed"), req) == 0.0, "失败不计费"
    must_raise(base.ProviderError, slow.poll, "nope")
    bad = FakeVideo(fail_with="审核未通过")
    st = bad.poll(bad.submit(req))
    assert st.status == "failed" and st.error == "审核未通过"
    flaky = FakeVideo(transient_submits=1)
    must_raise(base.TransientError, flaky.submit, req)
    assert flaky.submit(req) == "fake-1", "瞬时错误不占任务号"
    assert fake.rewrite_prompt("看 {ref:C01} 和 {ref:S03}") == "看 [参考C01] 和 [参考S03]"
    must_raise(base.ProviderError, fake.caps, "nope")
    print("3. 假厂商全流程 ✓")

    # 4. 注册表：同名只建一次；未注册抛 KeyError
    mine = FakeVideo()
    providers.register("fake", lambda: mine)
    assert providers.get_video("fake") is mine and providers.get_video("fake") is mine
    must_raise(KeyError, providers.get_video, "nope")
    os.environ["MINIMAX_API_KEY"] = ""          # 先置空串：.env 不会覆盖已有变量
    with _LogGrab("render.providers.minimax") as g:
        e = must_raise(base.ProviderError, providers.get_video, "minimax")
    assert e.code == "film.vendor.no_key" and "MINIMAX_API_KEY" not in str(e)
    assert any("MINIMAX_API_KEY" in x for x in g.lines), g.lines
    with _LogGrab("render.providers.fake") as g:
        e = must_raise(base.ProviderError, FakeVideo().caps, "nope-tier")
    assert e.code == "film.settings.no_model" and e.params == {} and "nope-tier" not in str(e)
    assert any("nope-tier" in x for x in g.lines), g.lines
    print("4. 注册表 ✓")

    # 5. 缺省厂商：显式设置照用；只有 MiniMax 密钥 → minimax；只有方舟 → 回落 seedance；都没有 → minimax
    saved_env = os.environ.pop("STORYBOARD_VIDEO_PROVIDER", None)
    real_has = providers._has_key
    try:
        for keys, want, fell in (({"minimax"}, "minimax", False), ({"minimax", "seedance"}, "minimax", False),
                                 ({"seedance"}, "seedance", True), (set(), "minimax", False)):
            providers._has_key = lambda n, ks=keys: n in ks
            assert providers.default_video_name() == want, (keys, want)
            assert providers.default_fell_back() is fell, (keys, fell)
        os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
        providers._has_key = lambda n: (_ for _ in ()).throw(AssertionError("显式设置时不该查密钥"))
        assert providers.default_video_name() == "fake" and providers.default_fell_back() is False
        assert "fake" in providers.names()
        os.environ.pop("STORYBOARD_VIDEO_PROVIDER")
        providers._has_key = lambda n: False
        assert "fake" not in providers.names() and {"minimax", "seedance"} <= set(providers.names())
    finally:
        providers._has_key = real_has
        if saved_env is None:
            os.environ.pop("STORYBOARD_VIDEO_PROVIDER", None)
        else:
            os.environ["STORYBOARD_VIDEO_PROVIDER"] = saved_env
    print("5. 缺省厂商与回落 ✓")

    # 6. 错误带代码
    e = must_raise(KeyError, providers.get_video, "nope")
    assert e.code == "film.settings.no_model" and e.params == {} and "nope" not in e.args[0]
    print("6. 错误带代码 ✓")

    # 脱敏：模型密钥、签名密钥、x-api-key 头
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-fake-0123456789"
    os.environ["STORYBOARD_SECRET"] = "fake-signing-secret-0123"
    try:
        out = base.scrub_secrets("k=sk-ant-fake-0123456789 s=fake-signing-secret-0123")
        assert "sk-ant-fake-0123456789" not in out and "fake-signing-secret-0123" not in out, out
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("STORYBOARD_SECRET", None)
    for raw in ("x-api-key: abc", '{"x-api-key": "abc"}', "X-Api-Key=abc"):
        assert "abc" not in base.scrub(raw), (raw, base.scrub(raw))
    print("脱敏：模型密钥 / 签名密钥 / x-api-key ✓")

    # 脱敏：含反斜杠 / 引号 / 非 ASCII 的密钥经转义后也要抹掉（验收 G1）
    import ast
    import json as _json
    for secret in ("abc123\\secret_token", 'abc"123secret', "abc密钥123secret", "sk-test-plainkey123"):
        os.environ["STORYBOARD_SECRET"] = secret
        try:
            k = secret
            forms = {k, repr(k)[1:-1], _json.dumps(k)[1:-1], _json.dumps(k, ensure_ascii=False)[1:-1],
                     repr(repr(k))[1:-1], _json.dumps(_json.dumps(k))[1:-1]}
            samples = [k, repr(k), str({"v": k}), str({k: 1}), _json.dumps(k), _json.dumps({"v": k}),
                       _json.dumps(k, ensure_ascii=False), repr(repr(k)), _json.dumps(_json.dumps(k)),
                       str({"v": repr(k)}), "msg: " + repr([k])]
            for sm in samples:
                for out in (base.scrub_secrets(sm), base.scrub(sm, k)):
                    for form in forms:
                        assert form not in out, (k, sm, out)
                    assert k not in out, (k, sm, out)
                    assert "***" in out, (k, sm, out)
            for sm, load in ((repr(k), ast.literal_eval), (str({"v": k}), ast.literal_eval),
                             (str({k: 1}), ast.literal_eval), (_json.dumps(k), _json.loads),
                             (_json.dumps({"v": k}), _json.loads), (repr(repr(k)), ast.literal_eval)):
                try:
                    back = load(base.scrub_secrets(sm))
                except (ValueError, SyntaxError):
                    continue
                assert k not in str(back), (k, sm, back)
            normal = "普通文本 plain text, path C:\\dir, quote \" and 'x'"
            assert base.scrub_secrets(normal) == normal and base.scrub(normal) == normal, normal
        finally:
            os.environ.pop("STORYBOARD_SECRET", None)
    print("脱敏：反斜杠 / 引号 / 非 ASCII 密钥的转义形态 ✓")

    # 第 3 轮：容器 x 序列化 x 1~4 层嵌套穷举；逐层解码到底，沿途所有字符串都不含 k 及其长度 >= 8 的子串
    import ast
    import itertools
    import json as _json
    import time
    sers = (("repr", repr, ast.literal_eval), ("json", _json.dumps, _json.loads),
            ("json_u", lambda x: _json.dumps(x, ensure_ascii=False), _json.loads))
    conts = (("value", lambda x: {"value": x}, lambda v: v["value"]), ("list", lambda x: [x], lambda v: v[0]),
             ("key", lambda x: {x: 1}, lambda v: next(iter(v))), ("xy", lambda x: "x" + x + "y", lambda v: v[1:-1]))
    combos = [(c, f) for c in conts for f in sers]

    def pieces(k):
        return {k[i:i + 8] for i in range(max(1, len(k) - 7))} | {k}

    def roundtrip(k, plan):
        text = k
        for c, f in plan:
            text = f[1](c[1](text))
        out = base.scrub_secrets(text)
        assert not any(p in out for p in pieces(k)), (k, plan, out)
        for c, f in reversed(plan):                 # 解码失败即失败，不跳过
            v = f[2](out)
            out = c[2](v)
            assert not any(p in out for p in pieces(k)), (k, [(x[0], y[0]) for x, y in plan], out)

    keys3 = ("abc'123secret", 'abc"123secret', "ab'c\"123secret", "abc123\\sec'ret", "abc\\'123secret",
             "abc密钥'123secret", "abc😀123secret", "sk-test-plainkey123")
    t0 = time.perf_counter()
    nplans = 0
    for k in keys3:
        os.environ["ANTHROPIC_API_KEY"] = k
        try:
            for depth in (1, 2, 3, 4):
                for plan in itertools.product(combos, repeat=depth):
                    roundtrip(k, plan)
                    nplans += 1
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
    print(f"  嵌套穷举 {nplans} 组 {time.perf_counter() - t0:.1f}s")
    # 误伤：带引号的密钥不得抹掉不带引号的正常文本；中英文长文本不变
    os.environ["ANTHROPIC_API_KEY"] = "'not-a-secret'"
    try:
        assert base.scrub_secrets("normal not-a-secret text") == "normal not-a-secret text"
        long_txt = "普通的中文句子，English sentence with quotes 'a' \"b\" and back\\slash. " * 200
        assert base.scrub_secrets(long_txt) == long_txt
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    # 性能：10 万字 + 6 个混合字符密钥
    names = ("ARK_API_KEY", "MINIMAX_API_KEY", "VOLC_TTS_API_KEY", "VOLC_TTS_ACCESS_KEY", "ANTHROPIC_API_KEY", "STORYBOARD_SECRET")
    for i, n in enumerate(names):
        os.environ[n] = f"k{i}密钥😀a\\b'c\"d{i}"
    try:
        big = ("普通中文文本 plain english text 一二三 " * 4000)[:100000]
        base.scrub_secrets(big)
        t0 = time.perf_counter()
        base.scrub_secrets(big)
        ms = (time.perf_counter() - t0) * 1000
        print(f"  10 万字 x 6 密钥脱敏 {ms:.1f}ms")
        assert ms < 30, ms
    finally:
        for n in names:
            os.environ.pop(n, None)
    # 多密钥互相重叠：一个密钥的转义形态不得吞掉另一个密钥的前缀
    k1, k2 = "abc密钥123secret", "abc密钥123secret-sensitiveTAIL987"
    os.environ["ARK_API_KEY"], os.environ["STORYBOARD_SECRET"] = k1, k2
    try:
        for sm in (k2, repr(k2), _json.dumps(k2), str({"v": k2}), k1 + " " + k2):
            out = base.scrub_secrets(sm)
            assert "TAIL987" not in out and "sensitive" not in out, (sm, out)
        assert base.scrub_secrets(k2) == "***", base.scrub_secrets(k2)
    finally:
        os.environ.pop("ARK_API_KEY", None)
        os.environ.pop("STORYBOARD_SECRET", None)
    print("脱敏：逐层嵌套与多密钥重叠 ✓")

    # 第 4 轮：规范化 N + 位置映射。各轮复审（codex-accept-fix*-result.txt）的复现逐条在此
    # 4a. 控制字符密钥：repr / json / 混合序列化，容器嵌套 1~4 层，逐层解码都不含 k 及其长度 >= 8 的子串
    keys4 = ("abc\n123secret", "abc\t\x01secret", "headTOKEN\atailTOKEN", "headTOKEN\btailTOKEN",
             "headTOKEN\vtailTOKEN", "headTOKEN\ftailTOKEN")
    t0 = time.perf_counter()
    nplans = 0
    for k in keys4:
        os.environ["ANTHROPIC_API_KEY"] = k
        try:
            for depth in (1, 2, 3, 4):
                for plan in itertools.product(combos, repeat=depth):
                    roundtrip(k, plan)
                    nplans += 1
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
    print(f"  控制字符嵌套穷举 {nplans} 组 {time.perf_counter() - t0:.1f}s")
    # 4b. 原文直接写成 \u000A、\x0A、\n（十六进制大小写都算），以及复审给的 \a \b \v \f 的 repr / json 形态
    direct = {
        "abc\n123secret": ("abc\\u000A123secret", "abc\\u000a123secret", "abc\\x0A123secret", "abc\\x0a123secret",
                           "abc\\n123secret", "abc\\\\\\n123secret", "abc\\U0000000A123secret"),
        "abc\t\x01secret": ("abc\\t\\x01secret", "abc\\u0009\\u0001secret", "abc\\x09\\\\u0001secret"),
        "headTOKEN\atailTOKEN": ("headTOKEN\\x07tailTOKEN", "headTOKEN\\u0007tailTOKEN", "headTOKEN\\atailTOKEN"),
    }
    for ch in "\a\b\v\f":
        k = "headTOKEN" + ch + "tailTOKEN"
        direct.setdefault(k, ())
        direct[k] += (repr(k), _json.dumps(k), repr(repr(k)), _json.dumps(_json.dumps(k)))
    for k, texts in direct.items():
        for sm in texts:
            for out in (base.scrub_secrets(sm, extra=[k]), base.scrub(sm, k)):
                assert out.replace("'", "").replace('"', "").replace("\\", "") == "***", (k, sm, out)
    print("脱敏：控制字符密钥的各种转义写法 ✓")

    # 4c. 凭据与密钥交叠：Bearer / x-api-key 只收集区间、与密钥区间取并集，不得留下 ***'123secret
    kq = "abc'123secret"
    os.environ["STORYBOARD_SECRET"] = kq
    try:
        for raw in ("Bearer abc'123secret", "x-api-key: abc'123secret", "authorization: bearer abc'123secret;",
                    '{"x-api-key": "abc\'123secret"}'):
            for sm in (raw, repr(raw), _json.dumps(raw), repr(repr(raw)), _json.dumps(_json.dumps(raw)),
                       str({"h": raw}), _json.dumps({"h": raw})):
                for out in (base.scrub_secrets(sm), base.scrub(sm, kq)):
                    assert "123secret" not in out and "abc" not in out and "***" in out, (sm, out)
        assert base.scrub_secrets("Bearer abc'123secret") == "Bearer ***"
        assert base.scrub("x-api-key: abc'123secret", kq) == "x-api-key: ***"
        # scrub 只管传进来的密钥与凭据，环境密钥不归它；limit 截断在脱敏之后
        assert base.scrub("plain abc'123secret") == "plain abc'123secret"
        assert base.scrub("abc'123secret tail", kq, limit=5) == "*** t"
        assert base.scrub("Bearer tok123 rest", limit=10) == "Bearer ***"
    finally:
        os.environ.pop("STORYBOARD_SECRET", None)
    print("脱敏：凭据与密钥交叠 ✓")

    # 4d. 前几轮复审的原始复现
    os.environ["STORYBOARD_SECRET"] = kq
    try:
        for sm in (repr(repr(kq)), repr(repr(repr({"value": kq})))):                # 第 1、2 轮
            out = base.scrub_secrets(sm)
            assert "123secret" not in out and out == base.scrub(sm, kq), (sm, out)
            back = out
            while isinstance(back, str) and back not in ("***",):
                try:
                    back = ast.literal_eval(back)
                except (ValueError, SyntaxError):
                    raise AssertionError(("解码失败", sm, out))
                if isinstance(back, dict):
                    back = back["value"]
            assert back == "***", (sm, out, back)
    finally:
        os.environ.pop("STORYBOARD_SECRET", None)
    k1, k2raw = "abc密钥123secret", r"abc\u5bc6\u94a5123secret-sensitiveTAIL987"     # 第 1 轮：跨密钥交叠
    os.environ["ARK_API_KEY"], os.environ["STORYBOARD_SECRET"] = k1, k2raw
    try:
        assert base.scrub_secrets(k2raw) == "***", base.scrub_secrets(k2raw)
        assert base.scrub_secrets("abc密钥123secret-sensitiveTAIL987") == "***"
        for sm in (repr(k2raw), _json.dumps(k2raw), _json.dumps({"v": k2raw}), k1 + " " + k2raw):
            out = base.scrub_secrets(sm)
            assert "TAIL987" not in out and "sensitive" not in out and "123secret" not in out, (sm, out)
    finally:
        os.environ.pop("ARK_API_KEY", None)
        os.environ.pop("STORYBOARD_SECRET", None)
    assert base.scrub_secrets("normal not-a-secret text", extra=["'not-a-secret'"]) == "normal not-a-secret text"
    # 可接受的误伤：原文解码后恰好就是密钥（反斜杠加普通字符解码为该字符）
    assert base.scrub_secrets("x ab\\c y", extra=["abc"]) == "x *** y"
    assert base.scrub_secrets("x a\\bc y", extra=["abc"]) == "x a\\bc y", "\\b 是退格，解码后不等于密钥"
    print("脱敏：前几轮复审复现 ✓")

    # 4e. 接缝：文本里紧挨密钥的残缺转义会吞掉密钥开头、或补齐密钥结尾的残缺转义（报告里的边界判定）
    for k, sm in (("abc123secretXY", "dir\\abc123secretXY"),                    # 孤立反斜杠 + 短转义字母 a
                  ("abc123secretXY", repr("C:\\dir\\" + "abc123secretXY")),
                  ("ntoken-secret-1", repr("C:\\keys\\" + "ntoken-secret-1")),   # \n
                  ("41secretsecret", "x\\u0041secretsecret"),                      # \u00 + 密钥开头的十六进制
                  ("ude00secretsecret".join(["\\", ""]), "\\ud83d\\ude00secretsecret"),   # 高代理 + 密钥开头的低代理
                  ("mysecretkey\\u12", "mysecretkey\\u1234"),                     # 密钥结尾残缺的 \u
                  ("mysecretkey\\u12", repr("mysecretkey\\u1234z")),
                  ("mysecretkey\\ud83d", "mysecretkey\\ud83d\\ude00"),             # 密钥结尾的高代理与后文合成
                  ("mysecretkey\\", repr({"v": "mysecretkey\\"})),                 # 密钥结尾是反斜杠
                  ("mysecretkey\\", _json.dumps(["mysecretkey\\"]))):
        for out in (base.scrub_secrets(sm, extra=[k]), base.scrub(sm, k)):
            assert "secret" not in out and "***" in out, (k, sm, out)
    assert ast.literal_eval(base.scrub_secrets(repr({"v": "mysecretkey\\"}), extra=["mysecretkey\\"]))["v"] == "***\\"
    assert _json.loads(base.scrub_secrets(_json.dumps(["mysecretkey\\"]), extra=["mysecretkey\\"])) == ["***\\"]
    print("脱敏：转义接缝 ✓")

    # 4f. 性能：严格线性，不回溯（每项取 3 次最好成绩）
    def best_ms(text, keys):
        base.scrub_secrets(text[:200], extra=keys)
        best = None
        for _ in range(3):
            t0 = time.perf_counter()
            out = base.scrub_secrets(text, extra=keys)
            ms = (time.perf_counter() - t0) * 1000
            best = ms if best is None else min(best, ms)
        return best, out

    mixed6 = [f"k{i}密钥😀a\\b'c\"d{i}" for i in range(6)]
    plain = "sk-test-plainkey123"
    perf = (
        ("10 万个反斜杠", "\\" * 100000, [plain, "head" + "\\" * 6 + "tail"], 50, None),
        ("head+96 个反斜杠+FAIL", "head" + "\\" * 96 + "FAIL", ["head" + "\\" * 6 + "tail"], 5, None),
        ("5 万个反斜杠+完整密钥", "\\" * 50000 + plain, [plain], 50, "***"),
        ("5 万个反斜杠+a 开头的密钥", "\\" * 50000 + "abc'123secret", ["abc'123secret"], 50, "***"),
        ("10 万字常见文本 x 6 个混合密钥", ("普通中文文本 plain english text 一二三 " * 4000)[:100000], mixed6, 30, None),
        ("10 万个重复字符（未命中）", "a" * 100000, [plain] + mixed6, 50, None),
        ("10 万个重复字符（逐位重叠命中）", "a" * 100000, ["aaaaaaaa", "a"], 50, "***"),
    )
    for label, text, keys, limit_ms, want in perf:
        ms, out = best_ms(text, keys)
        print(f"  {label}：{ms:.3f}ms（上限 {limit_ms}ms）")
        assert ms < limit_ms, (label, ms)
        if want is not None:
            assert out == want, (label, out[:80])
        elif label.startswith("10 万字") or "未命中" in label:
            assert out == text, label
    print("脱敏：性能 ✓")

    # 第 5 轮（codex-accept-fix4-result.txt）
    # 5a. 拼接边界吞字：文本里的字面 \ud8 / \u00 经 repr / json 序列化后，N0 不看奇偶会把它和密钥开头一起解码
    for k, payload in ((r"3d\ude00SECRETTAIL", r"C:\ud8" + r"3d\ude00SECRETTAIL"), ("41", r"C:\u00" + "41"),
                       ("abcdef", r"\U00" + "abcdef"), ("0041SECRETTAIL", r"\u" + "0041SECRETTAIL")):
        for ser, load in ((repr, ast.literal_eval), (_json.dumps, _json.loads),
                          (lambda x: _json.dumps(x, ensure_ascii=False), _json.loads)):
            for depth in (1, 2, 3):
                text = payload
                for _ in range(depth):
                    text = ser({"value": text})
                for out in (base.scrub(text, k), base.scrub_secrets(text, extra=[k])):
                    cur = out
                    for _ in range(depth):
                        cur = load(cur)["value"]          # 解码失败即失败
                    assert k not in cur and "SECRETTAIL" not in cur, (k, depth, text, out, cur)
    print("脱敏：拼接边界吞字 ✓")

    # 5b. 随机接缝 fuzz：转义前缀 x 随机密钥（含十六进制开头的、短的） x 1~3 层 repr / json；泄露 0、误伤 0
    import random
    rnd = random.Random(20261114)
    prefixes = ("\\u", "\\u0", "\\u00", "\\u000", "\\ud83d", "\\ud8", "\\x", "\\x4", "\\U0001", "\\U000",
                "\\", "\\\\", "\\\\\\", "C:\\", "")
    hexd = "0123456789abcdefABCDEF"
    pool = list(hexd) + list("uxUntrbfvSECRT-'\"密😀") + ["\\ude00", "\\udc00", "\\u12", "\\", "\n", "\x01"]
    sers5 = ((repr, ast.literal_eval), (_json.dumps, _json.loads),
             (lambda x: _json.dumps(x, ensure_ascii=False), _json.loads))

    def wrap(v, plan):
        for f in plan:
            v = f[0]({"_Z": v})
        return v

    def unwrap(v, plan):
        layers = []
        for f in reversed(plan):
            v = f[1](v)["_Z"]
            layers.append(v)
        return layers

    t0 = time.perf_counter()
    ntrial = leaks = fps = 0
    while ntrial < 6000:
        r = rnd.random()
        if r < 0.3:
            k = "".join(rnd.choice(hexd) for _ in range(rnd.randint(2, 4)))
        elif r < 0.6:
            k = ("".join(rnd.choice(hexd) for _ in range(rnd.randint(1, 3)))
                 + "".join(rnd.choice(pool) for _ in range(rnd.randint(0, 4))) + "SECRETTAIL")
        else:
            k = "".join(rnd.choice(pool) for _ in range(rnd.randint(1, 6))) + rnd.choice(["", "SECRETTAIL"])
        k = k.strip()
        # 退化密钥（单字符、只有引号或反斜杠）会与容器语法本身撞车，不是脱敏问题
        if len(k) < 2 or sum(c.isalnum() for c in k) < (3 if ("'" in k or '"' in k) else 1):
            continue
        ntrial += 1
        pre, suf = rnd.choice(prefixes), rnd.choice(prefixes + ("x", "'"))
        plan = [rnd.choice(sers5) for _ in range(rnd.randint(1, 3))]
        text = wrap(pre + k + suf, plan)
        out = base.scrub(text, k)
        if k in unwrap(out, plan)[-1]:
            leaks += 1
        other = "".join("Z" if c.isalnum() else c for c in k) + "Q"   # 同样的前后缀与转义结构，换成不含密钥的串
        t2 = wrap(pre + other + suf, plan)
        if k not in t2 and not any(k in x for x in unwrap(t2, plan)) and base.scrub(t2, k) != t2:
            fps += 1
    print(f"  接缝 fuzz {ntrial} 组 {time.perf_counter() - t0:.1f}s：泄露 {leaks}，误伤 {fps}")
    assert leaks == 0 and fps == 0, (leaks, fps)

    # 5c. 密钥里是原始代理对，文本里是解码后的 astral 字符（或转义写法）
    kp = "headTOKEN\ud83d\ude00tailTOKEN"
    for sm in (repr({"value": kp}), _json.dumps({"value": kp}), "headTOKEN😀tailTOKEN", repr("headTOKEN😀tailTOKEN"),
               _json.dumps("headTOKEN😀tailTOKEN"), _json.dumps("headTOKEN😀tailTOKEN", ensure_ascii=False)):
        for out in (base.scrub(sm, kp), base.scrub_secrets(sm, extra=[kp])):
            assert "tailTOKEN" not in out and "headTOKEN" not in out, (sm, out)
    assert base.scrub("x headTOKEN😀tailTOKEN y", "headTOKEN😀tailTOKEN") == "x *** y"
    assert base.scrub("x headTOKEN\ud83d\ude00tailTOKEN y", "headTOKEN😀tailTOKEN") == "x *** y"
    print("脱敏：原始代理对与 astral 字符 ✓")

    # 5d. 超长自重叠密钥：全部出现位置的查找是线性的（最小周期顺延 + 倍增），n = 16 万时小于 100ms
    for text, k, want in (("a" * 160000, "a" * 80000, "***"), ("ab" * 80000, "ab" * 40000, "***"),
                          ("a" * 160000, "a" * 79999 + "b", None), ("\\a" * 80000, "\a" * 40000, "***")):
        base._needles.cache_clear()                    # 含查找串的生成（冷启动）
        t0 = time.perf_counter()
        out = base.scrub(text, k)
        ms = (time.perf_counter() - t0) * 1000
        print(f"  自重叠 文本 {len(text)} 密钥 {len(k)}：{ms:.1f}ms（上限 100ms）")
        assert ms < 100, (len(text), len(k), ms)
        assert out == (text if want is None else want), out[:20]
    print("脱敏：自重叠密钥线性查找 ✓")

    # 6. 通常时长：厂商给了用厂商的，没给用保守缺省；只是界面提示用的数字
    assert base.typical_sec(fake) == [60, 180]
    assert base.typical_sec(object()) == [60, 600]
    print("通常时长 ✓")

    # 7. 取消：厂商没有 cancel、cancel 抛异常都当「没取消成」，不往外抛，日志里没有密钥
    assert base.try_cancel(object(), "t") is False

    class Boom:
        _key = "k-secret"

        def cancel(self, task_id):
            raise RuntimeError("k-secret 炸了")

    with _LogGrab("render.providers.base") as g:
        assert base.try_cancel(Boom(), "t") is False
    assert g.lines and all("k-secret" not in x for x in g.lines), g.lines
    # 假厂商：缺省取消不了（任务照常跑）；cancel_ok 时确认取消，之后查询是「任务已取消」
    f2 = FakeVideo(polls_to_finish=3)
    tid = f2.submit(base.ClipRequest(prompt="p", model="fake-1", duration=4, resolution="720p"))
    assert base.try_cancel(f2, tid) is False and f2.poll(tid).status == "running"
    f2.cancel_ok = True
    assert base.try_cancel(f2, tid) is True
    st = f2.poll(tid)
    assert st.status == "failed" and st.error_msg["code"] == "film.provider.task_cancelled"
    assert f2.cancel_calls == [tid, tid]
    assert base.try_cancel(f2, "nope") is False
    print("取消 ✓")

    # vendor_reject：消息不带原话；没装钩子没有编号；装了钩子带编号，钩子收到脱敏后的原话与厂商名
    base.record_reject = None
    with _LogGrab("render.providers.base") as g:
        m = base.vendor_reject("film.vendor.rejected", "bad prompt k-secret", who="minimax", secrets=("k-secret",))
    assert m["code"] == "film.vendor.rejected" and m["params"] == {} and "ref" not in m and "bad prompt" not in m["message"]
    assert any("bad prompt" in x and "minimax" in x for x in g.lines) and all("k-secret" not in x for x in g.lines)
    seen = []
    base.record_reject = lambda code, detail: (seen.append((code, detail)), "AB12CD34")[1]
    m = base.vendor_reject("film.vendor.rejected", "bad prompt k-secret", who="minimax", secrets=("k-secret",))
    assert m["ref"] == "AB12CD34" and "AB12CD34" in m["message"]
    assert seen == [("film.vendor.rejected", "minimax: bad prompt ***")]
    base.record_reject = lambda *_a: (_ for _ in ()).throw(OSError("disk"))     # 钩子出错不能挡住报错
    assert "ref" not in base.vendor_reject("film.vendor.rejected", "x", who="minimax")
    base.record_reject = None
    print("vendor_reject ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
