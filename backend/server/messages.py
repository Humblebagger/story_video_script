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
register("film.ark.auth", "视频服务（方舟）鉴权失败，请联系管理员")
register("film.ark.overdue", "视频服务（方舟）账户欠费，暂时无法出片，请联系管理员")
register("film.ark.access_denied", "视频服务（方舟）拒绝访问，请联系管理员")
register("film.ark.model_unavailable", "所选的视频档位暂时不可用（模型未开通），请换一个档位或联系管理员")
register("film.ark.limit_paused", "视频服务（方舟）已达到用量上限并暂停，请联系管理员")
register("film.ark.quota", "额度不足或排队已满，持续失败请联系管理员")
register("film.ark.input_moderated", "这一段的画面描述或参考图没通过内容审核：改写描述或换参考图后重试")
register("film.ark.copyright", "这一段的描述可能涉及版权限制：改写后重试")
register("film.ark.output_moderated", "生成的视频没通过内容审核：调整这一段的描述后重试")
register("film.ark.output_copyright", "生成的视频可能涉及版权限制：调整这一段的描述后重试")
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

# 出片会话
register("film.session.corrupt", "出片会话文件损坏：{path}，已保留原文件，请检查后再操作")
register("film.session.corrupt_admin", "出片记录文件已损坏，原文件已备份，请联系管理员处理")
register("film.session.dir_gone", "出片会话目录已不存在（版本可能已删除）")
register("film.session.none", "还没有出片会话")
register("film.session.none_pick", "还没有出片会话：先到出片那一步选好厂商与档位")
register("film.session.no_storyboard", "这个版本还没有分镜产物")
register("film.file.not_found", "文件不存在")
register("film.clip.not_found", "没有这一段：{id}")
register("film.settings.unknown", "未知的出片设置：{keys}")
register("film.settings.no_model", "{provider} 没有档位 {model}")
register("film.settings.bad_resolution", "这个档位不支持 {resolution}，可选：{options}")
register("film.settings.bad_audio", "未知的声音模式：{mode}")
register("film.settings.no_native_audio", "这家厂商不出原声，可选：全部配音、静音")
register("film.build.no_shots", "这个版本的分镜没有镜头，无法切段")
register("film.build.in_flight", "有段在排队或生成中，等它们结束再改设置")
register("film.build.incomplete", "分镜结构不完整，无法切段：{detail}")
register("film.run.composing", "正在合成，等它结束再出片")
register("film.run.busy", "{id} 已在排队或生成中")
register("film.run.nothing", "没有要出的段")
register("film.run.confirm", "本次约 {amount}，请确认金额后再出片")
register("film.run.changed", "预估金额已变为 {amount}，请重新确认")
register("film.budget.exceeded", "超出单章上限 ¥{budget}：已花 {spent}，在跑预留 {reserved}，本次约 {total}")
register("film.choose.busy", "这一段正在生成，等它结束再换")
register("film.choose.not_success", "只能采用成功的那几次")
register("film.submit.interrupted", "提交时服务中断，不确定厂商是否已受理；请到厂商控制台核对后再重做")
register("film.submit.over_budget", "超出单章上限，没有提交")
register("film.submit.stale", "分镜或关键帧已改动，没有提交；请确认后重新出这一段")
register("film.submit.build_failed", "组装请求失败：{cause}")
register("film.submit.ambiguous", "提交时连接中断，不确定厂商是否已受理：请到{console}核对，确认没有生成再重做（{cause}）")
register("film.submit.unavailable", "厂商暂时不可用（已重试 {retries} 次）：{cause}")
register("film.submit.crashed", "提交异常：{kind}: {cause}")
register("film.provider.retrying", "厂商暂时不可达，正在重试：{cause}")
register("film.poll.gave_up", "多次查询都失败，已放弃；请到厂商控制台核对这个任务：{cause}")
register("film.download.keeps_failing", "下载一直失败，结果地址即将过期：{cause}")
register("film.download.not_playable", "下载到的文件不是可播放的视频")
# 自由节点
register("film.free.not_found", "没有这个自由节点：{id}")
register("film.free.dup_ref", "参考里有重复的资产")
register("film.free.no_style", "这部小说还没有风格图")
register("film.free.unknown_asset", "分镜里没有这个资产：{id}")
register("film.free.no_ref_image", "{name}（{id}）没有可用的参考图")
register("film.free.over_refs", "参考超出当前厂商上限（{need} / {max}）")
register("film.free.no_first_frame", "当前厂商不支持指定首帧")
register("film.free.no_keyframe", "镜头 {shot} 还没有关键帧")
register("film.free.self_tail", "不能用自己的尾帧作首帧")
register("film.free.no_tail", "{id} 还没有可用的尾帧")
register("film.free.bad_first_frame", "看不懂的首帧来源：{src}")
register("film.free.bad_duration", "时长要在 1 到 {max} 秒之间")
register("film.free.prompt_too_long", "提示词不能超过 {max} 字")
register("film.free.empty_prompt", "先写提示词再生成")
register("film.free.bad_fields", "不能改这些字段：{keys}")
register("film.free.busy_edit", "这个节点正在生成，等它结束再改")
register("film.free.target_duration", "挂靠某一段的节点时长跟随那一段，不能单独改")
register("film.free.busy_delete", "这个节点正在生成，等它结束再删")
register("film.free.tail_in_use", "{id} 用它的尾帧作首帧，先改掉那边")
register("film.free.composing", "正在合成，等它结束再生成")
register("film.free.confirm", "本次约 {amount}，请确认金额后再生成")
register("film.free.busy_choose", "这个节点正在生成，等它结束再换")
register("film.free_invalid.empty_prompt", "提示词是空的")
register("film.free_invalid.style_gone", "风格图已删除，请从参考里去掉它")
register("film.free_invalid.no_ref_image", "{id} 没有可用的参考图了")
register("film.free_invalid.keyframe_gone", "首帧用的关键帧没了：{shot}")
register("film.free_invalid.tail_gone", "首帧用的尾帧找不到了：{id}")


if __name__ == "__main__":
    if "--write" in sys.argv:
        CODES_FILE.write_text(json.dumps(dump_codes(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {CODES_FILE}")
