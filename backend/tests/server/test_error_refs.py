#!/usr/bin/env python3
"""错误参考编号：编号格式、记录脱敏与截断、裁剪、查找、接口 500 兜底。用法: python3 tests/server/test_error_refs.py"""
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name          # 必须在导入 server.* 之前

# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None
KEY = "sk-ark-test-0123456789"
os.environ["ARK_API_KEY"] = KEY                         # 只为验证脱敏；测试不联网
LLM_KEY = "sk-ant-test-llm-0123456789"
SIGN = "test-signing-secret-0123456789"
os.environ["ANTHROPIC_API_KEY"] = LLM_KEY               # 章后整理、转换用的模型密钥（x-api-key）
os.environ["STORYBOARD_SECRET"] = SIGN                  # token 签名密钥

from server import auth, error_refs, messages as M  # noqa: E402


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, rec):
        self.lines.append(rec.getMessage())


def part_ref():
    r = error_refs.new_ref()
    assert len(r) == 8 and set(r) <= set(error_refs.ALPHABET), r
    assert not set("ILOU") & set(error_refs.ALPHABET)
    assert error_refs.normalize(" k7q2-m9xd ") == "K7Q2M9XD"
    assert error_refs.normalize("k7q2-m9xo") == "K7Q2M9X0" and error_refs.normalize("il") == "11", "Crockford：O→0，I/L→1"
    assert error_refs.normalize("编号K7") == "K7", "只留 0-9A-Z"
    assert error_refs.user_of_root(auth.DATA_DIR / "users" / "a1b2c3d4e5f6" / "novels" / "n1") == "a1b2c3d4e5f6"
    assert error_refs.user_of_root("/tmp/elsewhere") is None
    assert error_refs.user_of_root("/srv/users/a1b2c3d4e5f6/x") is None, "不在 DATA_DIR/users 下的路径不认"
    # with_ref：顶层 ref，中文兜底附编号；compact 不带 ref
    m = M.with_ref(M.msg("common.internal"), "K7Q2M9XD")
    assert m["ref"] == "K7Q2M9XD" and m["message"].endswith("（参考编号 K7Q2M9XD）"), m
    assert "ref" not in M.compact(m)
    print("1. 编号格式 / normalize / user_of_root / with_ref ✓")


def part_record():
    grab = _Grab()
    lg = logging.getLogger("server.errors")
    lg.addHandler(grab)
    try:
        try:
            raise RuntimeError(f"boom {KEY} Authorization: Bearer abc.def")
        except RuntimeError as e:
            m = error_refs.unexpected(e, user_id="a1b2c3d4e5f6", where="GET /novels")
    finally:
        lg.removeHandler(grab)
    assert m["code"] == "common.internal" and m["params"] == {} and len(m["ref"]) == 8
    row = error_refs.find(m["ref"].lower())
    assert row and row["user_id"] == "a1b2c3d4e5f6" and row["where"] == "GET /novels"
    assert row["code"] == "common.internal" and "RuntimeError" in row["detail"] and "Traceback" in row["detail"]
    dump = json.dumps(row) + "\n".join(grab.lines)
    assert KEY not in dump and "abc.def" not in dump, "记录与日志不得含密钥或 Bearer 凭据"
    # 模型密钥、签名密钥、x-api-key 头
    ref = error_refs.record("common.internal", f"headers={{'x-api-key': '{LLM_KEY}'}} x-api-key: zz9 sign={SIGN}")
    d2 = json.dumps(error_refs.find(ref))
    assert LLM_KEY not in d2 and SIGN not in d2 and "zz9" not in d2, d2
    # 数据目录换成 <data>：位置与堆栈里都不留服务器的绝对路径
    ref = error_refs.record("common.internal", f"open {auth.DATA_DIR}/users/x failed",
                            where=f"submit {auth.DATA_DIR}/users/a1b2c3d4e5f6/novels/n1")
    r2 = error_refs.find(ref)
    assert r2["where"] == "submit <data>/users/a1b2c3d4e5f6/novels/n1" and str(auth.DATA_DIR) not in r2["detail"], r2
    assert any(m["ref"] in x for x in grab.lines)
    # 堆栈里的后端代码目录、Python 环境目录也换成占位，不留主机路径
    app_root = str(Path(error_refs.__file__).resolve().parents[1])
    assert app_root not in row["detail"] and "<app>/" in row["detail"], row["detail"]
    ref = error_refs.record("common.internal", f'File "{sys.prefix}/lib/x.py", line 1 / {app_root}/server/app.py')
    d3 = error_refs.find(ref)["detail"]
    assert sys.prefix not in d3 and app_root not in d3 and "<lib>/lib/x.py" in d3 and "<app>/server/app.py" in d3, d3
    # 截断：保留头尾（链式异常的最后一行在末尾，最有用）
    ref = error_refs.record("common.internal", "HEAD" + "x" * (error_refs.DETAIL_MAX + 500) + "TAIL")
    d = error_refs.find(ref)["detail"]
    assert len(d) <= error_refs.DETAIL_MAX and d.startswith("HEAD") and d.endswith("TAIL"), len(d)
    # 额外密钥（厂商对象持有的）
    ref = error_refs.record("common.internal", "key=zz-extra-secret", secrets_extra=["zz-extra-secret"])
    assert "zz-extra-secret" not in error_refs.find(ref)["detail"]
    # 指定 logger：写到调用方的 logger（runner、app 现有的日志断言依赖这一点）
    g2 = _Grab()
    other = logging.getLogger("render.runner")
    other.addHandler(g2)
    try:
        ref = error_refs.record("common.internal", "提交异常 root=R clip=E01", logger=other)
    finally:
        other.removeHandler(g2)
    assert any(ref in x and "clip=E01" in x for x in g2.lines)
    print("2. 记录：脱敏 / 截断 / 额外密钥 / 指定 logger / 查找不分大小写 ✓")


def part_write_fail():
    """写盘失败：日志不带 exc_info 链（链里有正在处理的业务异常和密钥），编号照常返回。"""
    grab = _Grab()
    fmt = logging.Formatter("%(message)s")
    grab.emit = lambda rec: grab.lines.append(fmt.format(rec))   # 完整格式化，含 exc 文字
    lg = logging.getLogger("server.errors")
    lg.addHandler(grab)
    orig = error_refs._file

    def bad():
        raise OSError(f"disk full {KEY} {auth.DATA_DIR}")
    try:
        try:
            raise RuntimeError(f"business failure {KEY}")
        except RuntimeError:
            error_refs._file = bad
            ref = error_refs.record("common.internal", "detail")
    finally:
        error_refs._file = orig
        lg.removeHandler(grab)
    assert len(ref) == 8
    text = "\n".join(grab.lines)
    assert "写盘失败" in text and KEY not in text, text
    assert "business failure" not in text and "Traceback" not in text and str(auth.DATA_DIR) not in text, text
    print("2b. 写盘失败：日志不带异常链、不含密钥，编号照常返回 ✓")


def part_trim():
    old_max = error_refs.MAX_ROWS
    error_refs.MAX_ROWS = 5
    try:
        refs = [error_refs.record("common.internal", f"n{i}") for i in range(12)]
        rows = error_refs.recent(100)
        assert len(rows) <= 2 * error_refs.MAX_ROWS, len(rows)
        assert rows[0]["ref"] == refs[-1], "最新在前"
        assert error_refs.find(refs[-1]) and error_refs.find(refs[0]) is None, "超过上限后最旧的被裁掉"
    finally:
        error_refs.MAX_ROWS = old_max
    # 坏行容忍
    with open(error_refs._file(), "a", encoding="utf-8") as f:
        f.write("{坏行\n")
    assert error_refs.recent(1)
    print("3. 裁剪到上限 / 最新在前 / 坏行跳过 ✓")


def part_api():
    from fastapi.testclient import TestClient
    from server import app as app_mod, novels

    u = auth.register("erruser", "secret1")
    tok = auth.issue_token(u["id"])
    orig = novels.list_novels

    def boom(user_id):
        raise RuntimeError(f"disk on fire {KEY}")

    novels.list_novels = boom
    grab_api = _Grab()
    logging.getLogger("server.errors").addHandler(grab_api)
    try:
        c = TestClient(app_mod.app)
        r = c.get("/novels", headers={"Authorization": f"Bearer {tok}", "Origin": "http://localhost:5173"})
    finally:
        novels.list_novels = orig
        logging.getLogger("server.errors").removeHandler(grab_api)
    assert r.status_code == 500, r.text
    d = r.json()["detail"]
    assert d["code"] == "common.internal" and d["params"] == {} and len(d["ref"]) == 8, d
    assert d["ref"] in d["message"] and KEY not in r.text and "RuntimeError" not in r.text
    assert r.headers.get("access-control-allow-origin"), "500 也要带 CORS 头，跨源前端才读得到 detail"
    row = error_refs.find(d["ref"])
    assert row["user_id"] == u["id"] and row["where"] == "GET /novels" and KEY not in row["detail"]
    assert any(d["ref"] in x for x in grab_api.lines), "接口 500 的记录写进 server.errors 日志"
    # HTTPException 不经过中间件：照旧
    assert c.get("/novels").status_code == 401
    print("4. 接口 500：消息对象带编号 / CORS 头 / 记录带用户与位置 / 不含密钥 ✓")


def part_expected():
    class Coded(M.UserError, RuntimeError):
        needs_ref = False
    assert error_refs.expected(Coded.of("common.internal"))
    e = Coded.of("common.internal")
    e.needs_ref = True
    assert not error_refs.expected(e), "needs_ref 的要记编号"
    assert not error_refs.expected(Coded("没有代码"))
    assert not error_refs.expected(RuntimeError("x"))
    print("5. expected：带代码且不需要编号才算可预期 ✓")


def part_scrub_deep():
    raw = f"{auth.DATA_DIR}/users/x key={LLM_KEY}"
    m = M.compact(M.msg("job.failed_report", reason=M.compact(M.msg("job.batch_failed", batch=1, retries=0)),
                        report=M.lines_of([M.msg("common.unknown", message=M.vendor(raw))])))
    out = error_refs.scrub_deep(m)
    blob = json.dumps(out, ensure_ascii=False)
    assert str(auth.DATA_DIR) not in blob and LLM_KEY not in blob and "<data>" in blob, blob
    assert out["code"] == "job.failed_report" and out["params"]["report"]["t"] == "lines"
    assert out["params"]["report"]["items"][0]["code"] == "common.unknown", "code 与 t 不动"
    assert m["params"]["report"]["items"][0]["params"]["message"]["text"] == raw, "不改调用方的对象"
    print("6. scrub_deep：字符串逐个脱敏，code 与 t 不动 ✓")


def part_rel():
    """只换整段路径前缀：Docker 里后端目录是 /app，/assets/…/appearance 不能变成 <app>earance（设计审查 Minor 4）。"""
    app = str(error_refs._APP_ROOT)
    assert error_refs.scrub_text(f"{app}/server/app.py:12") == "<app>/server/app.py:12"
    assert error_refs.scrub_text(f"{app}earance/face") == f"{app}earance/face", "不是这个目录的前缀不替换"
    assert error_refs.scrub_text(f"'{auth.DATA_DIR}'") == "'<data>'"
    assert error_refs.scrub_text(f"at {auth.DATA_DIR}") == "at <data>"
    print("7. _rel 只换整段路径前缀 ✓")


def main() -> int:
    part_ref()
    part_record()
    part_write_fail()
    part_trim()
    part_api()
    part_expected()
    part_scrub_deep()
    part_rel()
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
