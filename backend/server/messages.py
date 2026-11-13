"""后端对用户文字的消息对象（设计 docs/specs/2026-11-13-backend-i18n-design.md §3–§5）。

每个代码登记一条中文兜底模板，参数名取自模板里的 {name}。后端返回、持久化的都是
{code, params, message}：前端按代码与当前语言渲染（文案在 frontend/src/i18n 的 srv 节点），
message 是中文兜底，给旧前端、日志与测试阅读。登记表导出到 messages_codes.json，前端测试核对。

参数值允许：字符串、数字、列表、嵌套消息 {code, params}（内层原因）、
金额 {"t":"money","cny":…}、代码引用 {"t":"ref","code":…}、厂商原文 {"t":"vendor","text":…}。
"""
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

CODES_FILE = Path(__file__).with_name("messages_codes.json")
VENDOR_MAX = 300
_PH = re.compile(r"\{(\w+)\}")
_REG: dict = {}          # code → (参数名元组, 中文模板)


def register(code: str, zh: str) -> None:
    if code in _REG:
        raise ValueError(f"重复登记：{code}")  # i18n: internal
    for other in _REG:
        if other.startswith(code + ".") or code.startswith(other + "."):
            raise ValueError(f"{code} 与 {other} 一个是另一个的前缀")  # i18n: internal
    _REG[code] = (tuple(dict.fromkeys(_PH.findall(zh))), zh)


def money(cny: float) -> dict:
    return {"t": "money", "cny": round(float(cny), 2)}


def ref(code: str) -> dict:
    if code not in _REG:
        raise KeyError(code)
    return {"t": "ref", "code": code}


def vendor(text: Any) -> dict:
    """厂商或系统原文：原样显示、不翻译。调用方先脱敏（如 minimax.scrub），这里只截断。"""
    return {"t": "vendor", "text": str(text)[:VENDOR_MAX]}


def compact(m: dict) -> dict:
    """消息对象 → 只留 code、params（嵌进别的消息当原因时用）。"""
    return {"code": m["code"], "params": m.get("params") or {}}


def _zh_value(v: Any) -> str:
    if isinstance(v, list):
        return "、".join(_zh_value(x) for x in v)
    if isinstance(v, dict):
        t = v.get("t")
        if t == "money":
            return f"¥{float(v['cny']):.2f}"
        if t == "ref":
            return _REG[v["code"]][1]
        if t == "vendor":
            return str(v.get("text", ""))
        if "code" in v:
            return v.get("message") or render_zh(v["code"], v.get("params") or {})
        return ""
    return "" if v is None else str(v)


def render_zh(code: str, params: dict) -> str:
    tpl = _REG[code][1]
    return _PH.sub(lambda m: _zh_value(params[m.group(1)]) if m.group(1) in params else m.group(0), tpl)


def msg(code: str, **params) -> dict:
    if code not in _REG:
        raise KeyError(code)
    want = set(_REG[code][0])
    if set(params) != want:
        raise ValueError(f"{code} 的参数应为 {sorted(want)}，实际 {sorted(params)}")  # i18n: internal
    return {"code": code, "params": params, "message": render_zh(code, params)}


class UserError:
    """混入现有异常类：带代码与参数，str() 仍是中文兜底（原有 except 链、日志、测试不受影响）。"""
    code: Optional[str] = None

    @property
    def params(self) -> dict:
        """每个实例自己的参数字典（不共享类属性）。"""
        return self.__dict__.setdefault("_params", {})

    @params.setter
    def params(self, value: dict) -> None:
        self.__dict__["_params"] = value

    @classmethod
    def of(cls, code: str, *args, **params):
        m = msg(code, **params)
        e = cls(m["message"], *args)
        e.code, e.params = code, m["params"]
        return e

    def as_msg(self) -> Optional[dict]:
        if not self.code:
            return None
        text = self.args[0] if self.args else str(self)
        return {"code": self.code, "params": self.params, "message": text}


def _raw_text(e: BaseException) -> str:
    """无代码异常的原文：KeyError 的 str() 会加引号，args[0] 是 str 时取它，其余一律 str(e)。"""
    if isinstance(e, KeyError) and e.args and isinstance(e.args[0], str):
        return e.args[0]
    return str(e)


def cause_of(e: BaseException) -> dict:
    """异常 → 可嵌进外层消息的原因：带代码的给紧凑消息，其它给原文（截断）。"""
    m = e.as_msg() if isinstance(e, UserError) else None
    return compact(m) if m else vendor(_raw_text(e))


def to_detail(e: BaseException, **extra) -> Any:
    """HTTPException 的 detail：带代码 → 消息对象（附加字段同层）；不带代码 → 与现在一致。"""
    m = e.as_msg() if isinstance(e, UserError) else None
    if m:
        return {**m, **extra}
    text = _raw_text(e)
    return {"message": text, **extra} if extra else text


def dump_codes() -> dict:
    return {c: {"params": list(p), "zh": z} for c, (p, z) in sorted(_REG.items())}


# ---------- 登记表（按域分组；改动后运行 python -m server.messages --write） ----------

register("common.unknown", "{message}")

# 控制台名与费率说明（厂商属性，前端按代码渲染）
register("console.generic", "厂商控制台")
register("console.ark", "方舟控制台")
register("console.minimax", "MiniMax 开放平台")
register("rate.fake", "假厂商：不联网、不花钱，金额只用于演示")
register("rate.ark", "2026-10 方舟官方刊例价（2.0 为 46、fast 为 37、mini 为 23 元/百万 token，"
                     "token ≈ 秒 × 宽 × 高 × 24 / 1024），未经账单核对")
register("rate.minimax", "2026-11 MiniMax 官方刊例价（H3 768P 0.50、2K 0.80 元/秒，Highspeed、Lite 见档位；"
                         "每段前 5 张参考图免费，超出另计），未经账单核对")
# 厂商通用
register("film.provider.unknown", "未知的视频厂商：{name}")
register("film.provider.failed", "厂商返回失败")
register("film.provider.generation_failed", "生成失败")
register("film.provider.task_cancelled", "任务已取消")
register("film.provider.rejected", "{detail}")
register("film.provider.http_rejected", "HTTP {status}：{detail}")
register("film.provider.submit_cut", "提交时连接中断：{kind}")
register("film.provider.download_retry", "下载暂时失败（HTTP {status}）")
register("film.provider.download_failed", "下载失败（HTTP {status}）")
register("film.provider.download_connect", "下载连接失败：{kind}")
# 假厂商
register("film.fake.unknown_model", "未知的档位：{model}")
register("film.fake.throttled", "假的限流")
register("film.fake.no_task", "任务不存在：{id}")
# 方舟 Seedance
register("film.ark.no_key", "没有配置方舟密钥：在 backend/.env 写 ARK_API_KEY=…")
register("film.ark.unknown_model", "未知的 Seedance 档位：{model}")
register("film.ark.connect_failed", "连接方舟失败：{kind}")
register("film.ark.throttled", "方舟限流（HTTP 429）")
register("film.ark.http_ambiguous", "方舟返回 HTTP {status}")
register("film.ark.unavailable", "方舟暂时不可用（HTTP {status}）")
register("film.ark.not_json", "方舟返回的不是 JSON")
register("film.ark.no_task_id", "方舟受理了请求却没有返回任务 id")
register("film.ark.task_expired", "任务超时")
register("film.ark.no_result_url", "方舟没有返回结果地址")
register("film.ark.download_failed", "下载失败（HTTP {status}）：结果地址 24 小时内有效")
# MiniMax
register("film.minimax.insufficient_balance", "MiniMax 账户余额不足（1008），充值后重新出这一段")
register("film.minimax.invalid_key", "MiniMax 密钥无效（1004），检查 MINIMAX_API_KEY")
register("film.minimax.moderated", "内容被 MiniMax 审核拦下（1026）：改写这一段的画面描述或换参考图后重试")
register("film.minimax.url_expired", "结果地址已过期且重新查询失败；任务只能在 7 天内查询")
register("film.minimax.label_first", "首帧")
register("film.minimax.label_ref", "参考图 {id}")
register("film.minimax.bad_image", "{label} 不是可用的图片地址")
register("film.minimax.unsupported_format", "{label} 的格式 {mime} MiniMax 不支持（只收 JPG、PNG、WEBP、HEIC、HEIF）")
register("film.minimax.corrupt_image", "{label} 的图片数据损坏")
register("film.minimax.image_too_big", "{label} 有 {mb}MB，超过 MiniMax 单张 30MB 上限")
register("film.minimax.no_key", "没有配置 MiniMax 密钥：在 backend/.env 写 MINIMAX_API_KEY=…")
register("film.minimax.unknown_model", "未知的 MiniMax 档位：{model}")
register("film.minimax.connect_failed", "连接 MiniMax 失败：{kind}")
register("film.minimax.throttled", "MiniMax 限流或过载（HTTP {status}）")
register("film.minimax.http_ambiguous", "MiniMax 返回 HTTP {status}")
register("film.minimax.unavailable", "MiniMax 暂时不可用（HTTP {status}）")
register("film.minimax.not_json", "MiniMax 返回的不是 JSON")
register("film.minimax.bad_resolution", "{model} 不支持 {resolution}，可选：{options}")
register("film.minimax.prompt_too_long", "提示词超出 MiniMax 上限 {max} 字（当前 {len} 字）")
register("film.minimax.lite_needs_ratio", "MiniMax H3 Lite 的参考生视频必须明确画幅，不支持 adaptive")
register("film.minimax.bad_ratio", "MiniMax 不支持画幅 {ratio}，可选：{options}")
register("film.minimax.request_too_big", "请求体约 {mb}MB，超过 MiniMax 上限：减少参考图或换小一些的图")
register("film.minimax.no_task_id", "MiniMax 受理了请求却没有返回任务 id")
register("film.minimax.no_result_url", "MiniMax 没有返回结果地址")


if __name__ == "__main__":
    if "--write" in sys.argv:
        CODES_FILE.write_text(json.dumps(dump_codes(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {CODES_FILE}")
