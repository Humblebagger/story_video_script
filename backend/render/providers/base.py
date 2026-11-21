"""出片：视频厂商统一接口。

主流程只用 caps / rewrite_prompt / submit / poll / download / cost。新增厂商 = 新文件 +
在 providers/__init__.py 注册一行。厂商的提示词语法（如 Seedance 的 @图片n）只在厂商模块里。
"""
import logging
import math
import os
import re
from functools import lru_cache
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from server.messages import UserError

log = logging.getLogger("render.providers.base")

REF_ROLES = ("character", "creature", "location", "prop", "first_frame", "style")
DEFAULT_TYPICAL_SEC = (60, 600)     # 厂商没给「通常时长」时的保守区间（秒）


class ProviderError(UserError, Exception):
    """厂商明确失败（审核、参数、密钥）：原因原样展示，不自动重试。"""


class TransientError(UserError, Exception):
    """断连、5xx、限流：调用方自动重试，不算新尝试。"""


class AmbiguousSubmit(UserError, Exception):
    """提交请求可能已被厂商受理（请求发出后断连、超时、5xx、2xx 却没拿到任务 id）：
    不能重试（重试可能再建一个付费任务），记失败并提示用户到厂商控制台核对。"""


@dataclass
class Caps:
    max_clip_sec: float
    min_clip_sec: float
    max_refs: int
    first_frame: bool               # 可指定首帧
    last_frame: bool                # 可指定结束帧
    returns_last_frame: bool        # 能返回成片尾帧，用于接力（拿不到时下一段不带首帧，链路自带兜底）
    native_audio: bool
    frame_with_refs: bool           # 首帧与参考图能否同用（方舟、MiniMax 都不能：两种模式互斥）
    resolutions: list
    cny_per_sec: dict               # 分辨率 → 元/秒，只用于预估
    short_side: dict = field(default_factory=dict)   # 分辨率 → 成片短边像素；空表时合成按 mix.SHORT_SIDE
    free_images: int = 0            # 每个任务免费的输入图片张数
    cny_per_image: float = 0.0      # 超出免费张数后每张的价格（元）


@dataclass
class RefImage:
    asset_id: str
    role: str                       # REF_ROLES 之一
    source: str                     # http(s) 地址或 data:image/...;base64,...


@dataclass
class ClipRequest:
    prompt: str                     # 已改写为该厂商语法
    model: str
    duration: float
    resolution: str
    aspect: str = "9:16"
    audio: bool = True
    refs: list = field(default_factory=list)   # list[RefImage]，已按 max_refs 裁剪
    first_frame: Optional[str] = None          # 首帧图，格式同 RefImage.source
    style_ref: Optional[str] = None            # 带上的风格图哈希（没带为 None）
    images: Optional[int] = None               # 只用于计费：提交时实际发出的图片张数（submit 不读）


@dataclass
class TaskState:
    task_id: str
    status: str                     # pending / running / succeeded / failed
    video_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    error: Optional[str] = None     # 中文兜底（含厂商原文）
    error_msg: Optional[dict] = None  # {code, params}：前端按代码渲染
    usage: dict = field(default_factory=dict)


class VideoProvider(Protocol):
    name: str
    default_model: str
    models: dict                    # 档位 id → {"label": ...}
    rate_note: dict     # 费率依据（消息对象 {code, params}）：如实写出处、是否经账单核对；出片确认框照抄
    console_name: str   # 厂商控制台名的代码，如 console.ark
    typical_sec: tuple  # 一段通常要等多久（秒，下限与上限）：只给界面显示「通常 x–y 分钟」，不参与判定

    def caps(self, model: str) -> Caps: ...
    def rewrite_prompt(self, text: str) -> str: ...
    def submit(self, req: ClipRequest) -> str: ...
    def poll(self, task_id: str) -> TaskState: ...
    def download(self, st: TaskState, dest: Path) -> dict: ...   # {"video": Path, "last_frame": Path | None}
    def cost(self, st: TaskState, req: ClipRequest) -> float: ...
    def cancel(self, task_id: str) -> bool: ...                  # True = 厂商确认已取消且不计费；取消不了返回 False


# ---- 密钥脱敏：三道规范化扫描 + 位置映射（验收 G1 第 4、5 轮）----
# 不用正则匹配密钥。文本过三种单遍规范化，每个输出字符记下它在原文里的区间：
#   N0（不看奇偶）：一串反斜杠 R 连同其后的转义解码成一个字符，R 的个数不计，repr / json 任意嵌套层都归到同一结果；
#   NP（遵守奇偶）：R 里成对的反斜杠是字面反斜杠，只有落单的那个才开始转义，即如实解一层；
#   NC（只压缩）：一串反斜杠压成一个，不做任何解码，从不吞反斜杠以外的字符，兜住拼接边界的吞字。
# 每种扫描在其文本里用 str.find（自重叠时按最小周期顺延，线性）找对应的密钥串，命中经映射换回原文区间；
# 三种扫描的区间与 Bearer / x-api-key 的区间取并集后一次替换成 ***。全程不回溯，耗时与文本长度成线性。

_BS_RUN = re.compile(r"\\+")                    # 只做 match：贪婪吃满一串反斜杠，不回溯
_BS_RUN2 = re.compile(r"\\{2,}")                # 两个以上的连续反斜杠（单一字符类的贪婪重复，无回溯）
_SPECIAL = re.compile("\\\\|[\ud800-\udbff][\udc00-\udfff]")   # 反斜杠，或原始的高低代理对
_HEXSET = frozenset("0123456789abcdefABCDEF")
_SHORT = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "a": "\a", "0": "\0", "/": "/"}
_HEXLEN = {"u": 4, "U": 8, "x": 2}
_ESC_BODY = _HEXSET | frozenset("uxUntrbfva")   # 转义体里可能出现的字符：被拼接边界吞掉的只能是这些


def _hex_at(s: str, p: int, n: int):
    """s[p:p+n] 恰好是 n 位十六进制时返回其值，否则 None（只看定长，不回溯）。"""
    h = s[p:p + n]
    if len(h) == n and all(c in _HEXSET for c in h):
        return int(h, 16)
    return None


def _decode_at(s: str, q: int, parity: bool):
    """q 处紧跟在（起转义作用的）反斜杠之后：返回 (输出字符, 原文结束位置)，构不成转义时返回 None。"""
    n = len(s)
    if q >= n:
        return None
    c = s[q]
    if c in _HEXLEN:
        cp = _hex_at(s, q + 1, _HEXLEN[c])
        if cp is None or cp > 0x10FFFF:
            return None
        e = q + 1 + _HEXLEN[c]
        if c == "u" and 0xD800 <= cp <= 0xDBFF and e < n and s[e] == "\\":
            q2 = _BS_RUN.match(s, e).end()              # 这串反斜杠若不成对，主循环还会再扫一次：至多两次
            if (not parity or q2 - e == 1) and q2 < n and s[q2] == "u":   # 遵守奇偶时只认紧挨着的单个反斜杠
                lo = _hex_at(s, q2 + 1, 4)
                if lo is not None and 0xDC00 <= lo <= 0xDFFF:
                    return chr(0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)), q2 + 5
        return chr(cp), e
    if c in _SHORT:
        return _SHORT[c], q + 1
    return c, q + 1                                     # 其他字符（含引号）：丢掉反斜杠，输出该字符


class _Norm:
    """一种规范化（mode 为 "n0" / "np" / "nc"）的结果与位置映射。原文没有反斜杠与原始代理对时 text == s、映射是恒等。
    marks 只记特殊位置产生的输出字符（输出下标、原文起止）；输出字符的原文区间首尾相连、恰好铺满原文，
    所以第一次需要换算时一次性展开成 st（st[o] 为第 o 个输出字符的起点，st[o + 1] 即其终点），之后 O(1)。"""
    __slots__ = ("src", "text", "mo", "ms", "me", "_st")

    def __init__(self, s: str, mode: str = "n0"):
        self.src = s
        self.mo, self.ms, self.me, self._st = [], [], [], None
        parts, olen, pos = [], 0, 0
        mo, ms, me = self.mo, self.ms, self.me
        if mode == "nc":                                # 只压缩：两个以上的连续反斜杠变成一个，单个的原样
            for m in _BS_RUN2.finditer(s):
                j, q = m.span()
                parts.append(s[pos:j])
                olen += j - pos
                parts.append("\\")
                mo.append(olen), ms.append(j), me.append(q)
                olen, pos = olen + 1, q
            self.text = "".join(parts) + s[pos:] if mo else s
            return
        while True:
            m = _SPECIAL.search(s, pos)
            if m is None:
                break
            j = m.start()
            parts.append(s[pos:j])
            olen += j - pos
            if s[j] != "\\":                            # 原始的高低代理对：合成一个字符，与解码出来的一致
                parts.append(chr(0x10000 + ((ord(s[j]) - 0xD800) << 10) + (ord(s[j + 1]) - 0xDC00)))
                mo.append(olen), ms.append(j), me.append(j + 2)
                olen, pos = olen + 1, j + 2
                continue
            q = _BS_RUN.match(s, j).end()
            if mode == "np":
                h = (q - j) // 2                        # 成对的反斜杠：每对是一个字面反斜杠
                if h:
                    parts.append("\\" * h)
                    mo.extend(range(olen, olen + h))
                    ms.extend(range(j, j + 2 * h, 2))
                    me.extend(range(j + 2, j + 2 * h + 2, 2))
                    olen += h
                if (q - j) % 2 == 0:
                    pos = q
                    continue
                j = q - 1                               # 落单的那个反斜杠开始转义
            d = _decode_at(s, q, mode == "np")
            if d is None:                               # R 在末尾或构不成转义：一个反斜杠，后面的字符留给下一步原样输出
                ch, e = "\\", q
            else:
                ch, e = d
            parts.append(ch)
            mo.append(olen), ms.append(j), me.append(e)
            olen, pos = olen + 1, e
        if not mo:
            self.text = s
            return
        parts.append(s[pos:])
        self.text = "".join(parts)

    def _table(self) -> list:
        if self._st is None:
            st, po, ps = [], 0, 0
            for o, a, b in zip(self.mo, self.ms, self.me):
                st.extend(range(ps, ps + (o - po)))     # 两个特殊位置之间的原样字符：逐一对应
                st.append(a)
                po, ps = o + 1, b
            st.extend(range(ps, ps + (len(self.text) - po)))
            st.append(len(self.src))
            self._st = st
        return self._st

    def start(self, o: int) -> int:
        """第 o 个输出字符在原文里的起点。"""
        return self._table()[o] if self.mo else o

    def end(self, o: int) -> int:
        """第 o 个输出字符在原文里的终点（不含）。"""
        return self._table()[o + 1] if self.mo else o + 1


def _bare(s: str) -> str:
    return s.replace("\\", "")


def _absorbable_heads(k: str) -> list:
    """文本里紧挨密钥前面的残缺转义（孤立的反斜杠、\\u00、\\ud8 等）会把密钥开头的若干字符一起解成一个字符。
    被吞的只能是转义体里的字符（十六进制、u x U、短转义字母，及密钥自带的反斜杠），去掉反斜杠后不超过 10 个
    （最长的转义体是代理对 uXXXXuXXXX）。返回所有可能的开头长度 m（不含整个密钥：整个被吞由 NC 兜住）。"""
    out = []
    for m in range(1, len(k)):
        c = k[m - 1]
        if c != "\\" and c not in _ESC_BODY:
            break
        if len(_bare(k[:m])) > 10:
            break
        if c != "\\":
            out.append(m)
    return out


def _unstable_tails(k: str) -> list:
    """密钥结尾若是一段以反斜杠开始、其后只含转义体字符（去掉反斜杠不超过 10 个）的尾巴，后面的文本可能把它
    补成别的字符（如残缺的 \\u12、结尾的高代理与后文的低代理合成）。返回这些尾巴在 k 里的起点。"""
    out, t = [], len(k)
    while t > 0:
        j = k.rfind("\\", 0, t)
        if j < 0:
            break
        s = j
        while s > 0 and k[s - 1] == "\\":
            s -= 1
        tail = _bare(k[s:])
        if len(tail) > 10 or any(c not in _ESC_BODY for c in tail):
            break
        if s > 0:
            out.append(s)
        t = s
    return out


_PAIR = re.compile("[\ud800-\udbff][\udc00-\udfff]")


def _pairs(s: str) -> str:
    """只把原始的高低代理对合成一个字符，其余不动。"""
    return _PAIR.sub(lambda m: chr(0x10000 + ((ord(m[0][0]) - 0xD800) << 10) + (ord(m[0][1]) - 0xDC00)), s)


@lru_cache(maxsize=64)
def _needles(keys: tuple) -> tuple:
    """返回 (N0 查找串, NP 查找串, NC 查找串)，每项为 (串, 开头被吞的字面, 结尾残缺的字面, 须以反斜杠开头)：
    - 开头/结尾字面为 None 表示无附加条件；否则命中时要求原文相邻处确有对应的转义，并把它一并抹掉；
      结尾字面为空串表示密钥以反斜杠结尾：命中处后面须紧跟反斜杠，只抹前面的部分。
    - 须以反斜杠开头：密钥以反斜杠开头时，N0 会丢掉这串反斜杠，命中处在原文里也须以反斜杠开始，免得误伤。
    NP 找原样的密钥（原始代理对已合成），NC 找压缩反斜杠后的密钥。"""
    n0, np_, nc = {}, {}, {}
    for k in keys:
        heads = [(0, None)] + [(m, _bare(k[:m])) for m in _absorbable_heads(k)]
        tails = [(len(k), None)] + [(t, _bare(k[t:])) for t in _unstable_tails(k)]
        for m, hl in heads:
            for e, tl in tails:
                if e <= m:
                    continue
                nd = _Norm(k[m:e]).text
                if nd:
                    n0.setdefault((nd, hl, tl, m == 0 and k.startswith("\\")), None)
        # 结尾的反斜杠不进 NP / NC 的查找串：序列化后那串反斜杠还转义着外层引号，抹掉会破坏结构，它本身也不含密钥内容
        core = k.rstrip("\\")
        if core:
            cut = "" if core != k else None
            np_.setdefault((_pairs(core), None, cut, False), None)
            nc.setdefault((_Norm(core, "nc").text, None, cut, False), None)
    return tuple(n0), tuple(np_), tuple(nc)


@lru_cache(maxsize=256)
def _period(nd: str) -> int:
    """查找串的最小周期（KMP 前缀函数，O(len)）：自重叠的出现只能间隔它的整数倍顺延。"""
    L, f, k = len(nd), [0] * len(nd), 0
    for i in range(1, L):
        while k and nd[i] != nd[k]:
            k = f[k - 1]
        if nd[i] == nd[k]:
            k += 1
        f[i] = k
    return L - f[-1]


def _occurrences(s: str, nd: str):
    """s 里 nd 的全部出现（含重叠），线性：命中后先按最小周期 p 顺延（每步只比较新增的 p 个字符），
    顺延断了再用 str.find 从下一位接着找。由 Fine–Wilf 定理，断开后下一次重叠出现距上次超过 len/2，
    所以 find 的调用次数是 O(n / len)，每次 O(len + 间隔)，总计 O(n + len)。"""
    L, n = len(nd), len(s)
    i = s.find(nd)
    if i == -1:
        return
    p = _period(nd)
    tail = nd[L - p:]
    while i != -1:
        yield i
        while i + L + p <= n and s.startswith(tail, i + L):
            i += p
            yield i
        i = s.find(nd, i + 1)


def _runs(s: str, nd: str):
    """s 里 nd 的各次出现（含重叠）的并集，按段给出 [起, 止)。与 _occurrences 同理，但周期顺延按倍增
    一次比较一大块（块总是周期尾巴的重复），不必逐个出现走一遍；总比较量仍是 O(n)。"""
    L, n = len(nd), len(s)
    i = s.find(nd)
    if i == -1:
        return
    p = _period(nd)
    tail = nd[L - p:]
    while i != -1:
        first, end = i, i + L
        while True:
            chunk = tail
            while end + p <= n:                         # 倍增顺延：成功就把块加倍，失败就减半，直到一个周期也接不上
                if s.startswith(chunk, end):
                    end += len(chunk)
                    if len(chunk) * 2 <= n - end:
                        chunk += chunk
                elif len(chunk) > p:
                    chunk = chunk[:len(chunk) // 2 // p * p] or tail
                else:
                    break
            j = s.find(nd, end - L + 1)
            if j != -1 and j <= end:                    # 不按周期的重叠或首尾相接：并入同一段
                end = j + L
                continue
            break
        yield first, end
        i = j


def _key_spans(nt: _Norm, needles) -> list:
    """规范化文本里每个查找串的全部出现（含重叠），换回原文区间。"""
    src, s, spans = nt.src, nt.text, []
    ident = not nt.mo
    no_bs = "\\" not in src
    for nd, hl, tl, lb in needles:
        if no_bs and (hl is not None or tl is not None or lb):
            continue                                    # 原文没有反斜杠：附加条件不可能成立
        L = len(nd)
        if hl is None and tl is None and not lb:
            # 无附加条件：相互重叠或首尾相接的一串出现只换算首尾两端（输出区间在原文里首尾相连，并集不变）
            for a, b in _runs(s, nd):
                spans.append((a, b) if ident else (nt.start(a), nt.end(b - 1)))
            continue
        for i in _occurrences(s, nd):
            a, b = nt.start(i), nt.end(i + L - 1)
            ok = not lb or src[a] == "\\"
            if ok and hl is not None:                          # 前一个输出字符须是吞掉密钥开头的那个转义
                ok = i > 0 and src[nt.start(i - 1)] == "\\" and _bare(src[nt.start(i - 1):a]).endswith(hl)
                if ok:
                    a = nt.start(i - 1)
            if ok and tl is not None:                   # 后一个输出字符须是补齐密钥结尾的那个转义
                ok = i + L < len(s) and b < len(src) and src[b] == "\\"
                if ok and tl:
                    # 结尾是残缺转义：连同补齐它的那个转义一起抹掉。结尾只是一串反斜杠（tl 为空）时只抹前面的部分：
                    # 这串反斜杠在序列化后还承担着转义后面引号的职责，抹掉会破坏外层结构，而它本身不含密钥内容
                    nb = nt.end(i + L)
                    ok = _bare(src[b:nb]).startswith(tl)
                    b = nb
            if ok:
                spans.append((a, b))
    return spans


_BEARER = re.compile(r"(?i)bearer\s+([^\s\"',;]+)")
_XAPIKEY = re.compile(r"(?i)x-api-key[\"']?\s*[:=]\s*[\"']?([^\s\"',;}]+)")


def _cred_spans(t: str) -> list:
    """Bearer 凭据与 x-api-key 头：在原文上只收集要抹掉的那一组的区间，不在这一步替换。"""
    return [m.span(1) for pat in (_BEARER, _XAPIKEY) for m in pat.finditer(t)]


def _mask(text: str, keys) -> str:
    """区间并集：三种扫描的密钥区间与凭据区间，重叠或相邻的合成一段，每段整体换成 ***，一次完成。"""
    ks = tuple(sorted({k.strip() for k in keys if isinstance(k, str) and k.strip()}))
    spans = _cred_spans(text)
    if ks and text:
        n0_needles, np_needles, nc_needles = _needles(ks)
        n0 = _Norm(text, "n0")
        spans += _key_spans(n0, n0_needles)
        if n0.mo:
            # 没有两个相连的反斜杠时，每串反斜杠都是单个（奇数），NP 与 N0 逐字相同、NC 等于原文：省掉重复扫描
            dbl = "\\\\" in text
            spans += _key_spans(_Norm(text, "np") if dbl else n0, np_needles)
            spans += _key_spans(_Norm(text, "nc"), nc_needles)
        else:                                           # 原文没有特殊字符：三种规范化都等于原文，查找串去重后再找
            spans += _key_spans(n0, tuple(x for x in dict.fromkeys(np_needles + nc_needles) if x not in n0_needles))
    if not spans:
        return text
    spans.sort()
    parts, pos, cs, ce = [], 0, None, None
    for a, b in spans:
        if cs is not None and a <= ce:
            if b > ce:
                ce = b
            continue
        if cs is not None:
            parts.append(text[pos:cs])
            parts.append("***")
            pos = ce
        cs, ce = a, b
    parts.append(text[pos:cs])
    parts.append("***")
    parts.append(text[ce:])
    return "".join(parts)


def scrub(text, secret: str = "", limit: Optional[int] = None) -> str:
    """服务端文字进报错前：抹掉密钥、Bearer 凭据与 x-api-key 头；limit 不为 None 时再截断（先脱敏后截断）。"""
    t = _mask(str(text), [secret] if secret else [])
    return t if limit is None else t[:limit]


# 日志与错误记录里一律抹掉的环境变量值：厂商密钥、模型密钥（章后整理与转换，经 x-api-key 发出）、token 签名密钥
SECRET_ENVS = ("ARK_API_KEY", "MINIMAX_API_KEY", "VOLC_TTS_API_KEY", "VOLC_TTS_ACCESS_KEY",
               "ANTHROPIC_API_KEY", "STORYBOARD_SECRET")


def scrub_secrets(text, extra=()) -> str:
    """日志文字脱敏：抹掉 Bearer 凭据、环境里配置的各厂商密钥与调用方给的密钥（如厂商对象持有的）。
    非空密钥一律抹掉，没有最短长度。"""
    keys = [os.environ.get(n, "") for n in SECRET_ENVS] + list(extra)
    return _mask(str(text), keys)


def request_seconds(duration: float, caps: Caps) -> int:
    """发给厂商的整数秒：向上取整，夹在 [min_clip_sec, max_clip_sec]。"""
    return int(min(caps.max_clip_sec, max(caps.min_clip_sec, math.ceil(duration - 1e-6))))


def estimate_cny(duration: float, caps: Caps, resolution: str, images: int = 0) -> float:
    """预估金额：整数秒 × 单价，加超出免费张数的图片费。"""
    extra = max(0, int(images or 0) - caps.free_images) * caps.cny_per_image
    return round(request_seconds(duration, caps) * caps.cny_per_sec.get(resolution, 0.0) + extra, 2)


def last_frame_path(video: Path) -> Path:
    return video.with_name(video.stem + ".last.jpg")


def is_playable_mp4(path: Path) -> bool:
    """不依赖 ffmpeg 的最低校验：文件存在且是 MP4 容器（第 4–8 字节为 ftyp）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
    except OSError:
        return False
    return len(head) >= 8 and head[4:8] == b"ftyp"


def typical_sec(provider) -> list:
    """这家厂商一段通常要等多久（秒，[下限, 上限]）。厂商没给用 DEFAULT_TYPICAL_SEC。"""
    lo, hi = getattr(provider, "typical_sec", None) or DEFAULT_TYPICAL_SEC
    return [int(lo), int(hi)]


def try_cancel(provider, task_id: str) -> bool:
    """请厂商取消一个已提交的任务。True = 厂商确认已取消（不计费）；False = 没取消成（厂商没有取消接口、
    任务已在生成、查询或取消出错）：调用方按「不等了」处理，任务可能照常完成并计费。绝不往外抛。"""
    fn = getattr(provider, "cancel", None)
    if fn is None:
        return False
    try:
        return bool(fn(task_id))
    except Exception as e:
        log.warning("%s", scrub_secrets(f"取消任务出错：{type(e).__name__}", [getattr(provider, "_key", "")]))  # i18n: internal
        return False
