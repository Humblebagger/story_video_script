"""出片：视频厂商统一接口。

主流程只用 caps / rewrite_prompt / submit / poll / download / cost。新增厂商 = 新文件 +
在 providers/__init__.py 注册一行。厂商的提示词语法（如 Seedance 的 @图片n）只在厂商模块里。
"""
import math
import os
import re
from functools import lru_cache
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from server.messages import UserError

REF_ROLES = ("character", "creature", "location", "prop", "first_frame", "style")


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

    def caps(self, model: str) -> Caps: ...
    def rewrite_prompt(self, text: str) -> str: ...
    def submit(self, req: ClipRequest) -> str: ...
    def poll(self, task_id: str) -> TaskState: ...
    def download(self, st: TaskState, dest: Path) -> dict: ...   # {"video": Path, "last_frame": Path | None}
    def cost(self, st: TaskState, req: ClipRequest) -> float: ...


# ---- 密钥脱敏：规范化 N + 位置映射（验收 G1 第 4 轮）----
# 不用正则匹配密钥。文本与密钥都过同一个单遍规范化 N：一串反斜杠 R 连同它后面的转义一起解码成
# 一个字符（R 的个数不计，所以 repr / json 任意嵌套层都归到同一个结果），其余字符原样；每个输出字符
# 记下它在原文里的区间。之后在 N(文本) 里用 str.find 找 N(密钥)，命中位置经映射换回原文区间，
# 与 Bearer / x-api-key 的区间取并集后一次替换成 ***。全程不回溯，耗时与文本长度成线性。

_BS_RUN = re.compile(r"\\+")                    # 只做 match：贪婪吃满一串反斜杠，不回溯
_HEXSET = frozenset("0123456789abcdefABCDEF")
_SHORT = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "a": "\a", "0": "\0", "/": "/"}
_HEXLEN = {"u": 4, "U": 8, "x": 2}


def _hex_at(s: str, p: int, n: int):
    """s[p:p+n] 恰好是 n 位十六进制时返回其值，否则 None（只看定长，不回溯）。"""
    h = s[p:p + n]
    if len(h) == n and all(c in _HEXSET for c in h):
        return int(h, 16)
    return None


def _escape_at(s: str, j: int):
    """j 处是一串反斜杠：返回 (输出字符, 原文结束位置)。规则见上；每次只向前看定长。"""
    n = len(s)
    q = _BS_RUN.match(s, j).end()
    if q >= n:
        return "\\", q                                  # R 在末尾：一个反斜杠
    c = s[q]
    if c in _HEXLEN:
        cp = _hex_at(s, q + 1, _HEXLEN[c])
        if cp is None or cp > 0x10FFFF:
            return "\\", q                              # 构不成转义：一个反斜杠，字母留给下一步原样输出
        e = q + 1 + _HEXLEN[c]
        if c == "u" and 0xD800 <= cp <= 0xDBFF and e < n and s[e] == "\\":
            q2 = _BS_RUN.match(s, e).end()              # 这串反斜杠若不成对，主循环还会再扫一次：至多两次
            if q2 < n and s[q2] == "u":
                lo = _hex_at(s, q2 + 1, 4)
                if lo is not None and 0xDC00 <= lo <= 0xDFFF:
                    return chr(0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)), q2 + 5
        return chr(cp), e
    if c in _SHORT:
        return _SHORT[c], q + 1
    return c, q + 1                                     # 其他字符（含引号）：丢掉 R，输出该字符


class _Norm:
    """N(s) 与位置映射。原文没有反斜杠时 N(s) == s、映射是恒等。
    marks 只记转义产生的输出字符（输出下标、原文起止）；输出字符的原文区间首尾相连、恰好铺满原文，
    所以第一次需要换算时一次性展开成 st（st[o] 为第 o 个输出字符的起点，st[o + 1] 即其终点），之后 O(1)。"""
    __slots__ = ("src", "text", "mo", "ms", "me", "_st")

    def __init__(self, s: str):
        self.src = s
        self.mo, self.ms, self.me, self._st = [], [], [], None
        if "\\" not in s:
            self.text = s
            return
        parts, olen, pos = [], 0, 0
        while True:
            j = s.find("\\", pos)
            if j < 0:
                parts.append(s[pos:])
                break
            parts.append(s[pos:j])
            olen += j - pos
            ch, e = _escape_at(s, j)
            parts.append(ch)
            self.mo.append(olen)
            self.ms.append(j)
            self.me.append(e)
            olen += 1
            pos = e
        self.text = "".join(parts)

    def _table(self) -> list:
        if self._st is None:
            st, po, ps = [], 0, 0
            for o, a, b in zip(self.mo, self.ms, self.me):
                st.extend(range(ps, ps + (o - po)))     # 两个转义之间的原样字符：逐一对应
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


def _absorbable_heads(k: str) -> list:
    """文本里紧挨密钥前面的残缺转义（如一个孤立的反斜杠、\\u00）会吞掉密钥开头的几个字符，
    合成一个别的字符。返回所有可能被吞的开头长度 m（只看定长的转义文法）。"""
    ms = set()
    if not k:
        return []
    if k[0] in "ntrbfva0":                              # 文本里的 R + 短转义字母
        ms.add(1)
    for m in range(1, 8):                               # 文本里的 R+u / R+x / R+U 加不足位的十六进制，由密钥补齐
        if m <= len(k) and k[m - 1] in _HEXSET:
            ms.add(m)
        else:
            break
    for c, n in _HEXLEN.items():                        # 文本里的 R + 密钥开头的 u/x/U 加满位十六进制
        if k[0] == c and _hex_at(k, 1, n) is not None:
            ms.add(1 + n)
    if k[0] == "\\":                                    # 文本里的高代理转义 + 密钥开头的 R+u+低代理
        q = _BS_RUN.match(k).end()
        lo = _hex_at(k, q + 1, 4) if k[q:q + 1] == "u" else None
        if lo is not None and 0xDC00 <= lo <= 0xDFFF:
            ms.add(q + 5)
    return sorted(m for m in ms if m < len(k))


def _unstable_tails(k: str) -> list:
    """密钥结尾是残缺转义（孤立的 R、R+u 不足 4 位、R+x 不足 2 位、R+U 不足 8 位）或高代理转义时，
    后面的文本会把它补成别的字符（高代理还会与后面的低代理合成一个字符）。
    返回这段尾巴在 k 里所有可能的起点；结尾稳定时返回空表。"""
    j = k.rfind("\\")
    if j < 0:
        return []
    t = j
    while t > 0 and k[t - 1] == "\\":
        t -= 1
    x = k[j + 1:]
    if x:
        c, h = x[0], x[1:]
        n = _HEXLEN.get(c)
        if n is None or not all(ch in _HEXSET for ch in h[:n]):
            return []                                   # 已是完整的短转义、普通字符或构不成转义：后文改不了它
        if len(h) >= n:
            if c == "u" and len(h) == 4 and 0xD800 <= int(h, 16) <= 0xDBFF:
                return [t]                              # 结尾是完整的高代理转义
            return []                                   # 完整的十六进制转义
    out = [t]
    # 孤立的 R 或残缺的 R+u 前面紧挨着高代理转义：补成低代理后会与它合成一个字符，尾巴也可能从高代理算起
    if (not x or x[0] == "u") and t >= 6 and k[t - 5] == "u" and k[t - 6] == "\\":
        hi = _hex_at(k, t - 4, 4)
        if hi is not None and 0xD800 <= hi <= 0xDBFF:
            s = t - 6
            while s > 0 and k[s - 1] == "\\":
                s -= 1
            out.append(s)
    return out


def _bare(s: str) -> str:
    return s.replace("\\", "")


@lru_cache(maxsize=64)
def _needles(keys: tuple) -> tuple:
    """每个密钥的查找串：(N(片段), 开头被吞的字面, 结尾残缺的字面)。
    开头/结尾字面为 None 表示无附加条件；否则命中时要求原文相邻处确有对应的转义，并把它一并抹掉。"""
    out = {}
    for k in keys:
        heads = [(0, None)] + [(m, _bare(k[:m])) for m in _absorbable_heads(k)]
        tails = [(len(k), None)] + [(t, _bare(k[t:])) for t in _unstable_tails(k) if t > 0]
        for m, hl in heads:
            for e, tl in tails:
                if e <= m:
                    continue
                nd = _Norm(k[m:e]).text
                if nd:
                    out.setdefault((nd, hl, tl), None)
    return tuple(out)


def _key_spans(nt: _Norm, needles) -> list:
    """N(文本) 里每个查找串的全部出现（含重叠），换回原文区间。"""
    src, s, spans = nt.src, nt.text, []
    ident = not nt.mo
    for nd, hl, tl in needles:
        if ident and (hl is not None or tl is not None):
            continue                                    # 原文没有反斜杠：附加条件不可能成立
        L = len(nd)
        i = s.find(nd)
        if hl is None and tl is None:
            # 无附加条件：相互重叠或首尾相接的一串出现只换算首尾两端（输出区间在原文里首尾相连，并集不变）
            while i != -1:
                last = i
                j = s.find(nd, i + 1)
                while j != -1 and j <= last + L:
                    last = j
                    j = s.find(nd, j + 1)
                spans.append((i, last + L) if ident else (nt.start(i), nt.end(last + L - 1)))
                i = j
            continue
        while i != -1:
            a, b, ok = nt.start(i), nt.end(i + L - 1), True
            if hl is not None:                          # 前一个输出字符须是吞掉密钥开头的那个转义
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
            i = s.find(nd, i + 1)
    return spans


def _cred_spans(t: str) -> list:
    """Bearer 凭据与 x-api-key 头：在原文上只收集要抹掉的那一组的区间，不在这一步替换。"""
    return [m.span(1) for pat in (_BEARER, _XAPIKEY) for m in pat.finditer(t)]


_BEARER = re.compile(r"(?i)bearer\s+([^\s\"',;]+)")
_XAPIKEY = re.compile(r"(?i)x-api-key[\"']?\s*[:=]\s*[\"']?([^\s\"',;}]+)")


def _mask(text: str, keys) -> str:
    """区间并集：各密钥与凭据的区间重叠或相邻的合成一段，每段整体换成 ***，一次完成。"""
    ks = tuple(sorted({k.strip() for k in keys if isinstance(k, str) and k.strip()}))
    spans = _cred_spans(text)
    if ks and text:
        spans += _key_spans(_Norm(text), _needles(ks))
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
