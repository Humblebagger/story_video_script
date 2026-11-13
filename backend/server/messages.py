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


def msg(code: str, /, **params) -> dict:
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
    def of(cls, code: str, /, *args, **params):  # code 仅位置参数：参数里可以有名叫 code 的值
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


REF_SUFFIX_ZH = "（参考编号 {ref}）"     # 与前端 zh.common.refSuffix 一致


def with_ref(m: dict, ref: str) -> dict:
    """给消息对象加参考编号：顶层 ref（不进 params），中文兜底末尾附编号。已有编号时替换。"""
    base = m.get("message") or render_zh(m["code"], m.get("params") or {})
    old = m.get("ref")
    if old:
        base = base.replace(REF_SUFFIX_ZH.format(ref=old), "")
    return {**m, "message": base + REF_SUFFIX_ZH.format(ref=ref), "ref": ref}


def dump_codes() -> dict:
    return {c: {"params": list(p), "zh": z} for c, (p, z) in sorted(_REG.items())}


# ---------- 登记表（按域分组；改动后运行 python -m server.messages --write） ----------

register("common.unknown", "{message}")
register("common.internal", "服务器出了点问题，请稍后重试；仍失败请联系管理员")

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
register("film.provider.submit_cut", "网络中断")
register("film.provider.download_retry", "下载暂时失败（HTTP {status}）")
register("film.provider.download_failed", "下载失败（HTTP {status}）")
register("film.provider.download_connect", "下载视频时连接失败")
# 假厂商
register("film.fake.unknown_model", "所选的视频档位已不可用，请在出片设置里重新选择")
register("film.fake.throttled", "假的限流")
register("film.fake.no_task", "任务不存在：{id}")
# 方舟 Seedance
register("film.ark.no_key", "视频服务（方舟）还没有配置，请联系管理员")
register("film.ark.unknown_model", "所选的视频档位已不可用，请在出片设置里重新选择")
register("film.ark.connect_failed", "连接视频服务（方舟）失败")
register("film.ark.throttled", "视频服务（方舟）繁忙")
register("film.ark.http_ambiguous", "方舟返回 HTTP {status}")
register("film.ark.unavailable", "方舟暂时不可用（HTTP {status}）")
register("film.ark.not_json", "视频服务（方舟）返回了无法识别的响应")
register("film.ark.no_task_id", "视频服务（方舟）受理了请求却没有返回任务编号")
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
register("film.minimax.insufficient_balance", "视频服务（MiniMax）账户余额不足，暂时无法出片，请联系管理员")
register("film.minimax.invalid_key", "视频服务（MiniMax）鉴权失败，请联系管理员")
register("film.minimax.moderated", "这一段的画面描述或参考图没通过内容审核：改写描述或换参考图后重试")
register("film.minimax.url_expired", "结果地址已过期且重新查询失败；任务只能在 7 天内查询")
register("film.minimax.label_first", "首帧")
register("film.minimax.label_ref", "参考图 {id}")
register("film.minimax.bad_image", "{label} 不是可用的图片地址")
register("film.minimax.unsupported_format", "{label} 的格式 {mime} MiniMax 不支持（只收 JPG、PNG、WEBP、HEIC、HEIF）")
register("film.minimax.corrupt_image", "{label} 的图片数据损坏")
register("film.minimax.image_too_big", "{label} 有 {mb}MB，超过 MiniMax 单张 30MB 上限")
register("film.minimax.no_key", "视频服务（MiniMax）还没有配置，请联系管理员")
register("film.minimax.unknown_model", "所选的视频档位已不可用，请在出片设置里重新选择")
register("film.minimax.connect_failed", "连接视频服务（MiniMax）失败")
register("film.minimax.throttled", "MiniMax 限流或过载（HTTP {status}）")
register("film.minimax.http_ambiguous", "MiniMax 返回 HTTP {status}")
register("film.minimax.unavailable", "MiniMax 暂时不可用（HTTP {status}）")
register("film.minimax.not_json", "视频服务（MiniMax）返回了无法识别的响应")
register("film.minimax.bad_resolution", "这个档位不支持 {resolution}，可选：{options}")
register("film.minimax.prompt_too_long", "提示词超出 MiniMax 上限 {max} 字（当前 {len} 字）")
register("film.minimax.lite_needs_ratio", "MiniMax H3 Lite 的参考生视频必须明确画幅，不支持 adaptive")
register("film.minimax.bad_ratio", "MiniMax 不支持画幅 {ratio}，可选：{options}")
register("film.minimax.request_too_big", "请求体约 {mb}MB，超过 MiniMax 上限：减少参考图或换小一些的图")
register("film.minimax.no_task_id", "视频服务（MiniMax）受理了请求却没有返回任务编号")
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
register("film.settings.no_model", "所选的视频档位已不可用，请在出片设置里重新选择")
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
register("film.submit.crashed", "提交时出现意外错误，请重试；仍失败请联系管理员")
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

# 配音厂商与音色
register("rate.volc_tts", "2026-10 火山引擎豆包语音合成 2.0 后付费刊例价（3 元/万字符），未经账单核对")
register("rate.fake_tts", "假配音：不联网、不花钱，金额只用于演示")
register("tts.unknown_provider", "未知的配音厂商：{name}")
register("tts.unknown_voice", "未知的音色：{voice}")
register("tts.unknown_voice_list", "没有这个音色：{voices}")
register("tts.concat_mismatch", "拼接的语音片段参数不一致")
register("tts.fake.failed", "{detail}")
register("tts.fake.throttled", "假的限流")
register("tts.volc.no_key", "配音服务还没有配置，请联系管理员")
register("tts.volc.unavailable", "豆包语音暂时不可用（HTTP {status}）")
register("tts.volc.rejected", "豆包语音拒绝了请求（{code}）：{detail}")
register("tts.volc.rejected_http", "豆包语音拒绝了请求（HTTP {status}）")
register("tts.volc.not_json", "豆包语音返回的不是 JSON")
register("tts.volc.not_object", "豆包语音返回的不是 JSON 对象")
register("tts.volc.failed", "豆包语音合成失败（{code}）")
register("tts.volc.failed_detail", "豆包语音合成失败（{code}）：{detail}")
register("tts.volc.bad_audio", "豆包语音返回的音频无法解码")
register("tts.volc.cut", "豆包语音中途断开")
register("tts.volc.connect_failed", "连接豆包语音失败")
register("tts.volc.incomplete", "豆包语音没有返回完整的音频")
register("voice.narrator", "旁白")
register("voice.unlabeled", "（未标说话人）")
register("compose.interrupted", "合成时服务中断，请重新合成（已合成的配音与已规整的片段会复用）")
register("compose.busy", "正在合成，等它结束再合成")
register("compose.voices_changed", "音色刚被改过，请重新确认金额")
register("compose.clips_busy", "有段在排队或生成中，等它们结束再合成")
register("compose.over_budget", "超出上限 {budget}：已花 {spent}，本次配音约 {cost}")
register("compose.step.start", "开始")
register("compose.step.voice", "配音 {n} 条")
register("compose.step.normalize", "规整 {id}")
register("compose.step.concat", "拼接 {id}")
register("compose.step.mix", "混音 {id}")
register("compose.step.done", "完成")
register("compose.ffmpeg_failed", "{what} 失败（ffmpeg 退出码 {rc}）")
register("compose.no_video", "{id} 还没有可用的视频；打开「草稿合成」可用关键帧补位")
register("compose.missing_voices", "还有说话人没选音色：{speakers}")
register("compose.line_failed", "{id}：{cause}")
register("compose.lines_failed", "有语音条合成失败，为免成片漏句已停止合成：{items}")
register("compose.voice_failed", "{cause}")
register("compose.alignment", "段内镜头切换时刻由视频模型决定，台词按计划镜头起点放置，属近似对齐")
register("compose.warning_native", "台词由视频模型生成，不保证逐字")
register("compose.confirm_cny", "本次配音约 {cost}，请确认金额后再合成")
register("compose.no_ffmpeg", "服务器缺少视频处理组件 ffmpeg，暂时无法合成，请联系管理员")
register("compose.no_video_count", "{n} 段还没有可用的视频；打开「草稿合成」可用关键帧补位")
register("compose.crashed", "合成时出现意外错误，请重试；仍失败请联系管理员")
register("compose.bgm.no_episode", "没有这一集：{episode}")
register("compose.bgm.bad_type", "BGM 只支持 mp3、wav、m4a、aac")
register("compose.bgm.too_big", "BGM 文件为空或超过 30MB")
register("export.none", "还没有合成好的成片")
register("export.stale", "成片已过期，请先重新合成")
register("export.no_timeline", "这份成片是旧版合成的，重新合成一次即可导出（会复用已有配音与规整结果，不花钱）")
register("export.voice_prerender", "预渲染配音 {line} 失败")
register("export.missing_file", "合成产物缺失（{file}），请重新合成")
register("export.busy", "正在合成，完成后再导出")
register("export.no_ffmpeg", "服务器缺少视频处理组件 ffmpeg，暂时无法导出，请联系管理员")

# 账号
register("auth.unauthenticated", "未登录或登录已过期")
register("auth.admin_only", "需要管理员权限")
register("auth.bad_username", "用户名需为 2–32 位的中英文、数字、下划线、点或连字符")
register("auth.password_short", "密码至少 {min} 位")
register("auth.username_taken", "用户名已被占用")
register("auth.disabled", "账号已停用")
register("auth.bad_credentials", "用户名或密码不正确")
register("auth.user_not_found", "用户不存在")

register("common.image_too_big", "图片为空或超过 {mb}MB")
# 小说与长期记忆
register("novel.bad_id", "非法的 ID：{id}")
register("novel.not_found", "小说不存在")
register("novel.empty_title", "小说标题不能为空")
register("novel.title_taken", "《{title}》已存在")
register("novel.unknown_params", "未知的制作参数：{keys}")
register("novel.asset.unknown_kind", "未知的资产类别：{kind}")
register("novel.asset.no_id", "资产卡必须带 id")
register("novel.asset.no_name", "资产卡必须有名称")
register("novel.asset.not_found", "资产卡不存在")
register("novel.asset.id_mismatch", "卡片 id 与路径不一致：{got} != {want}")
register("novel.lifecycle.unknown_character", "资产库里没有角色 {id}")
register("novel.lifecycle.unknown_type", "未知的状态类型：{type}（可选 {options}）")
register("novel.lifecycle.unknown_status", "未知的状态：{status}")
register("novel.lifecycle.not_found", "生命周期记录不存在")
register("novel.constraint.no_text", "限制必须写明规则（text）")
register("novel.constraint.not_found", "限制不存在")
register("novel.style.bad_type", "风格参考图只收 PNG / JPEG / WebP 图片")
register("novel.style.not_found", "这部小说还没有风格参考图")
# 章节、版本、关键帧
register("chapter.not_found", "章节不存在")
register("chapter.empty_title", "章节标题不能为空")
register("chapter.text_locked", "本章已有采用版，原文已锁定；要改原文请新建章节")
register("chapter.no_text", "本章还没有原文")
register("chapter.no_adopted", "本章还没有采用版")
register("chapter.synopsis_too_long", "每章摘要不超过 {max} 字（现在 {len} 字）")
register("chapter.version.not_found", "版本不存在")
register("chapter.version.adopted_delete", "这是本章的采用版，先采用别的版本再删")
register("chapter.version.busy", "这个版本还有片段在出，等出完或失败后再删")
register("chapter.version.not_adoptable", "这个版本还不能采用：只有转换成功、且人工编辑后仍通过复验的版本可以")
register("chapter.version.later_adopted", "后面的章节（{names}）已经接着本章的编号转换过，"
                                          "本章不能再换采用版；要换，先删掉或重转后面的章节")
register("chapter.digest.off", "章后整理功能没有开启，请联系管理员")
register("chapter.digest.failed", "没有完成，可以稍后重跑；仍失败请联系管理员")
register("chapter.keyframe.bad_type", "关键帧只收 PNG / JPEG / WebP 图片")
register("chapter.keyframe.no_shot", "这个版本里没有镜头 {shot}")
register("chapter.keyframe.not_found", "这个镜头还没有关键帧")
# 用量
register("usage.monthly_cap", "本月用量已达上限，请联系管理员")
# 管理后台
register("admin.one_field", "一次只能修改一项")
register("admin.bad_disabled", "disabled 必须是 true 或 false")
register("admin.self_disable", "不能停用自己")
register("admin.last_admin", "至少保留一个管理员")
register("admin.bad_role", "角色只能是 admin 或 user")
register("admin.self_role", "不能修改自己的角色")
register("admin.bad_cap", "月上限必须是非负数，或留空表示不限")
register("admin.bad_field", "不支持修改 {field}")
register("admin.bad_days", "days 只能是 7、30、90")
register("admin.pricing.empty", "价格表必须包含至少一个模型")
register("admin.pricing.bad_row", "模型 {name} 的单价格式不对")
register("admin.pricing.bad_price", "模型 {name} 的 {key} 单价必须是非负数")
register("admin.error_ref.not_found", "没有这个参考编号：{ref}")
register("usage.bad_group", "不支持的分组：{group}")
# 旧资产库
register("library.empty_title", "作品名不能为空")


if __name__ == "__main__":
    if "--write" in sys.argv:
        CODES_FILE.write_text(json.dumps(dump_codes(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {CODES_FILE}")
