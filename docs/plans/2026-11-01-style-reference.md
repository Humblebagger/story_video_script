# 风格参考图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每部小说可以上传一张风格参考图：
- 出片时，每段在参考位上带上它（排在主要角色之后），首帧优先。
- 风格图不进片段指纹，换图不会让已出的片段过期；界面提示「可按新风格图重出」。
- 设置页上传，概览页显示，画布出片页逐段说明带没带上，关键帧页可以下载这张图。

**Architecture:**
- **后端存储**：`server/novels.py` 管文件（小说目录下的 `style/`）和小说记录里的 `style_image` 元数据；`server/app.py` 加三个接口。
- **出片**：
  - `render/compose.py` 的 `build_clips` / `request_for` 新增参数 `style`。指纹先按「没有风格图」算，再插入风格参考位、重拼提示词。
  - `render/session.py`：
    - `build` 透传 `style`；
    - 每次尝试记下 `style_ref`；
    - `view` 给片段标 `style_outdated`，并给出计数。
  - `server/app.py` 在所有建会话、刷新会话、组装请求的地方传入当前风格图。
- **前端**：
  - 新钩子 `useStyleImage`。
  - 新组件 `StyleImageField`，放在设置页。
  - 概览页显示缩略图。
  - 画布出片页加「风格图」一行，以及「可重出」的提示和计数。
  - 关键帧页加「下载风格图」。

**Tech Stack:** FastAPI（Python 3.12），React 19、TS 6、Tailwind v4、shadcn。

**Spec:** `docs/specs/2026-11-01-style-reference-design.md`

---

## 全局约束

- **提交**：
  - 只 `git add` 具体文件，不用 `git add -A` / `git commit -a`。
  - 提交信息用中文、写成描述式，**不带任何 Claude 署名**（不要 `Co-Authored-By`、不要 `Claude-Session`）。
- **后端检查**（在 `backend/` 下执行）：
  - 改到哪个模块，就跑它的测试脚本：`.venv/bin/python tests/render/test_compose.py`、`test_session.py`、`test_runner.py`、`test_seedance.py`、`test_providers.py`，以及 `tests/server/test_render.py`、`test_novels.py`、`test_summary.py`。
  - 每个任务结束时，上面这些都要通过。
  - venv 里没有 pytest，测试脚本直接用 python 跑。
- **前端检查**（在 `frontend/` 下执行）：
  - `npm test`：16 套全部 `ALL PASS`。
  - `npm run lint`：0 error，warning 不超过 5 个。
  - `npx vite build`：成功。
- **不花钱**：测试只用 `fake` 厂商。真实方舟冒烟由用户手动跑。
- **不改的行为**：
  - **没有风格图时，出片的一切输出与现在逐字一致**：切段、参考位、提示词、指纹、请求都不变。现有的金标准测试（`golden_plan_yao.json` 等）必须原样通过。
  - 转换（分镜生成）流程不动。
- **后端报错文字**：沿用中文，与现有接口一致。
- **前端文字**：
  - 新文字进 `zh.ts`，`en.ts` 同步。
  - 源码里注释以外不许有中文。
  - 测试固定用中文。
- **密钥**：不读 `backend/.env`；日志、报错里不出现密钥。
- **不碰**：`docs/specs/2026-10-27-commercialization-design-contract.md`。

## 实施裁定

1. **审计**：规格第 5 节写了「上传、删除记审计」，但 `server/audit.py` 的 `write(admin, …)` 是管理员操作日志。用户自己改内容（例如上传关键帧）一直不记审计，所以这次也**不记**。同一次提交里，把规格第 5 节的「审计」那条删掉。
2. **风格参考位的数据形状**：与资产参考位一样是 dict：
   ```python
   {"asset_id": "__style__", "role": "style", "variant": None,
    "text": "画风参考：沿用它的色调、线条与光影，不要照搬其中的人物或场景内容",
    "source": "<data:image/...;base64,...>"}
   ```
   - `compose.STYLE_ID = "__style__"`，`STYLE_TEXT` 是上面这句。
   - `neutral_prompt` 已经把每个参考位写成 `【参考】{ref(asset_id)} {text}`，所以不用改它。
3. **「主要角色」怎么判断**：`pick_refs` 给每个保留的参考位加一个键 `"main": bool`（tier 0 为真）。这个键不进指纹，也不进 `RefImage`。
4. **风格图插在哪个位置**：插在保留列表里最后一个 `main` 参考位之后；没有主要角色时插在最前面。占位符编号和请求里的图片顺序都跟着这个列表走。
5. **参考位满了怎么办**：
   - 可用参考位数 `cap = caps.max_refs - (1 if frame_mode == "ref" else 0)`。
   - `len(kept) < cap` 时，直接插入。
   - 已满，但保留的参考位里有非主要角色时：用 `pick_refs(shots, idx, cap - 1)` 重选（裁掉优先级最低的一张），再插入。
   - 全是主要角色时，`style = "full"`，不插入。
6. **风格图要求的格式**：`style` 参数是 `{"source": data_uri, "hash": sha256十六进制}` 或 `None`。由 `server/app.py` 的新函数 `_style_for(uid, nid)` 从文件读出，读不到就是 `None`。
7. **尝试记下当时用的风格图**：
   - `ClipRequest` 新增字段 `style_ref: Optional[str] = None`，由 `request_for` 填入：带上了风格图就是它的哈希，否则是 `None`。
   - `runner._submit` 调 `sess.submitted(root, id, tid, used, style_ref=req.style_ref)`。
   - 这样记下的是**真正发出去**的风格图，不受会话最后一次重建时间的影响。
8. **`style_outdated` 的判定**：在 `session.view` 里，用会话最近一次 `build` 写到每段上的 `style_hash`（那次重建时的当前风格图）比对：
   ```python
   c["state"] == "done" and c.get("style") == "used" and chosen_attempt.get("style_ref") != c.get("style_hash")
   ```
   - 读取会话的接口每次都会重建（`render_session_get` 传了 `allow_in_flight=True`），所以 `style_hash` 总是最新的。
   - 旧会话里的尝试没有 `style_ref`，按 `None` 处理：如果现在有风格图，它就是「可重出」。

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/server/novels.py` | 修改：`save_style_image`、`style_image_file`、`delete_style_image`；`get_novel` 返回 `style_image` |
| `backend/server/app.py` | 修改：`/novels/{nid}/style-image` 三个接口；`_style_for`；出片相关调用传 `style` |
| `backend/render/providers/base.py` | 修改：`REF_ROLES` 加 `style`；`ClipRequest.style_ref` |
| `backend/render/compose.py` | 修改：`pick_refs` 标 `main`；`build_clips`、`request_for` 加 `style` |
| `backend/render/session.py` | 修改：`build(style=)`、`submitted(style_ref=)`、`view` 标 `style_outdated` |
| `backend/render/runner.py` | 修改：提交后写回 `style_ref` |
| `backend/render/smoke.py` | 修改：`--style <图片路径>` |
| `backend/tests/server/test_style_image.py` | 新建 |
| `backend/tests/render/test_compose.py`、`test_session.py`、`test_runner.py` | 修改：补用例 |
| `frontend/src/api.ts`、`types.ts` | 修改 |
| `frontend/src/useStyleImage.ts` | 新建 |
| `frontend/src/components/params/StyleImageField.tsx` | 新建 |
| `frontend/src/components/NovelPage.tsx`、`NovelOverview.tsx` | 修改：设置页放上传框；概览显示缩略图 |
| `frontend/src/components/FilmPanel.tsx`、`TimelineCanvas.tsx` | 修改：风格图一行、可重出提示与计数、下载风格图 |
| `frontend/src/i18n/zh.ts`、`en.ts`、`frontend/src/styles/chapter.css` | 修改 |
| `frontend/tests/chapter.test.tsx`、`film.test.tsx` | 修改：补用例 |
| `docs/specs/2026-11-01-style-reference-design.md` | 修改：删掉「审计」那条（实施裁定 1） |

---

### Task 1: 后端存储与接口

**Files:**
- Modify: `backend/server/novels.py`、`backend/server/app.py`、`docs/specs/2026-11-01-style-reference-design.md`
- Create: `backend/tests/server/test_style_image.py`

- [ ] **Step 1: 先写失败测试**：写法照抄 `tests/server/test_novels.py`：同样的临时数据目录、`main()` 加 `ALL PASS`，用 FastAPI `TestClient` 打接口。用例如下：
  1. 新小说 `GET /novels/{nid}/style-image` 返回 404，`GET /novels/{nid}` 的 `style_image` 是 `None`。
  2. `PUT` 一张 PNG（用 `b"\x89PNG\r\n\x1a\n" + b"0" * 100`，`Content-Type: image/png`）返回 200，带 `hash`（与 `hashlib.sha256(body).hexdigest()` 相等）、`mime == "image/png"`、`bytes == len(body)`、`updated_at`。
  3. 再 `GET` 返回同样的字节，`content-type` 是 `image/png`；`GET /novels/{nid}` 的 `style_image.hash` 与第 2 条相同。
  4. 换成 `image/jpeg` 再 `PUT`：目录里只剩 `style.jpg`，旧的 `style.png` 被删掉。
  5. `Content-Type: image/gif` 返回 422；空请求体返回 422；`KEYFRAME_MAX_BYTES + 1` 字节返回 422。
  6. 另一个用户读、写、删都返回 404。
  7. `DELETE` 返回 200；之后 `GET` 返回 404，`style_image` 是 `None`；再 `DELETE` 一次仍返回 200。
- [ ] **Step 2: 跑一下，确认失败**：`.venv/bin/python tests/server/test_style_image.py`，应该报 404 或属性不存在。
- [ ] **Step 3: 实现**（`novels.py`，与关键帧那组写法一致，复用 `KEYFRAME_TYPES`、`KEYFRAME_MAX_BYTES`）：

```python
def _style_dir(user_id: str, nid: str) -> Path:
    return _novel_dir(user_id, nid) / "style"


def save_style_image(user_id: str, nid: str, content_type: str, data: bytes) -> dict:
    """小说级风格参考图：一部小说一张，替换时删旧文件。出片时占一个参考位。"""
    ext = KEYFRAME_TYPES.get((content_type or "").split(";")[0].strip())
    if not ext:
        raise NovelError("风格参考图只收 PNG / JPEG / WebP 图片")
    if not data or len(data) > KEYFRAME_MAX_BYTES:
        raise NovelError(f"图片为空或超过 {KEYFRAME_MAX_BYTES // 1024 // 1024}MB")
    novel = get_novel(user_id, nid)            # 不存在或不属于该用户抛 NotFound
    root = _style_dir(user_id, nid)
    root.mkdir(parents=True, exist_ok=True)
    for old in root.glob("style.*"):
        old.unlink()
    (root / f"style.{ext}").write_bytes(data)
    meta = {"hash": hashlib.sha256(data).hexdigest(), "mime": content_type.split(";")[0].strip(),
            "bytes": len(data), "updated_at": now_iso()}
    # 只改 style_image 一项：沿用 update_novel 的读改写方式（同样的锁 / 写法），不带出 memory
    ...
    return meta
```

  - 「只改 `style_image`」的那段，照 `update_novel` 的读、改、写方式写（同样的锁和 `_save_novel`），只改这一个键。
  - `style_image_file(user_id, nid) -> (Path, mime)`：没有图时抛 `NotFound`。
  - `delete_style_image(user_id, nid)`：删文件，把 `style_image` 置为 `None`。没有图也不报错。
  - `get_novel` 返回值里的 `style_image` 默认为 `None`（`novel.get("style_image")`）。
  - 文件头部 `import hashlib`。
- [ ] **Step 4: 接口**（`app.py`，写法照抄 `keyframes_put` / `keyframes_get` / `keyframes_delete`，依赖 `novel_user`，错误都经过 `_novel_call`）：

```python
_STYLE = "/novels/{nid}/style-image"

@app.get(_STYLE)
def style_image_get(nid: str, user: dict = Depends(novel_user)):
    path, kind = _novel_call(novels.style_image_file, user["id"], nid)
    return FileResponse(path, media_type=kind)

@app.put(_STYLE)
async def style_image_put(nid: str, request: Request, user: dict = Depends(novel_user)):
    return _novel_call(novels.save_style_image, user["id"], nid,
                       request.headers.get("content-type", ""), await request.body())

@app.delete(_STYLE)
def style_image_delete(nid: str, user: dict = Depends(novel_user)):
    _novel_call(novels.delete_style_image, user["id"], nid)
    return {"deleted": True}
```

  - 读取请求体时要有上限：先看 `keyframes_put` 怎么限制，照着做；没有限制就照抄它现在的写法。
  - 在文件头的接口清单注释里加上这三行。
- [ ] **Step 5:** 按实施裁定 1，把规格第 5 节「审计」那一条删掉。
- [ ] **Step 6:** 新测试通过；`test_novels.py`、`test_render.py`、`test_summary.py` 照常通过。
- [ ] **Step 7: 提交**

```bash
git add backend/server/novels.py backend/server/app.py backend/tests/server/test_style_image.py docs/specs/2026-11-01-style-reference-design.md
git commit -m "小说风格参考图的存储与接口：上传（PNG / JPEG / WebP，≤ 8MB，替换删旧文件）、读取、删除，小说详情带上图片元数据；用户内容不记管理员审计"
```

---

### Task 2: 出片切段时带上风格参考位

**Files:**
- Modify: `backend/render/providers/base.py`、`backend/render/compose.py`
- Test: `backend/tests/render/test_compose.py`

- [ ] **Step 1: 先写失败测试**（追加到 `test_compose.py`，用里面已有的分镜夹具和 `fake` 厂商的 `Caps`。`style = {"source": "data:image/png;base64,AAAA", "hash": "h1"}`）：
  1. **不变性**：同一份分镜，`style=None`、风格图 `h1`、风格图 `h2`（换一个 `source`）三次 `build_clips`，各段 `fingerprint` 逐个相等。`style=None` 的输出与不传 `style` 时逐字相等。
  2. **有空位**：主要角色和场景都有图、参考位没满的一段：`style == "used"`，`style_hash == "h1"`；`refs` 里 `__style__` 在主要角色之后、场景之前；`prompt` 里有「画风参考」。
  3. **满了，但有非主要角色**：`max_refs` 设成正好等于保留参考位数，夹具里含一个场景：`style == "used"`，场景（优先级最低的那张）被挪到 `dropped_refs`。
  4. **满了，全是主要角色**：`style == "full"`，`refs` 里没有 `__style__`，提示词里没有「画风参考」。
  5. **首帧单用**：`frame_with_refs=False`、本段 `frame_mode == "frame"`（尾帧接力或关键帧单用）：`style == "first_frame"`。尾帧接力的段和没传风格图时一样，仍是 `relay:`。
  6. **首帧和参考图能同用**：`frame_with_refs=True` 时，同样的段 `style == "used"`。
  7. **关键帧占参考位**：`frame_mode == "ref"` 时，关键帧占一个位置，`cap` 少一，风格图照常参与排序。
  8. **组装请求**：`request_for(..., style=style)` 得到的 `req.refs` 里有 `role == "style"`、`source` 为风格图的一项，`req.style_ref == "h1"`。`style == "full"` 的段 `req.style_ref is None`。同一份分镜、请求时换成风格图 `h2`，不抛 `Stale`，因为指纹不含风格图。
  9. **没有风格图**：`style=None` 时，每段 `style is None`、`style_hash is None`。
- [ ] **Step 2: 跑一下，确认失败**。
- [ ] **Step 3: 实现**：
  - `base.py`：`REF_ROLES` 加 `"style"`；`ClipRequest` 加 `style_ref: Optional[str] = None`（放在已有默认字段之后）。
  - `compose.py`：
    - 加常量：`STYLE_ID = "__style__"`、`STYLE_TEXT = "画风参考：沿用它的色调、线条与光影，不要照搬其中的人物或场景内容"`。
    - `pick_refs` 保留的每一项加上 `"main": tier(sl) == 0`。
    - `build_clips(…, style: Optional[dict] = None)`：现有代码算完 `fp` 之后，加下面这段。`text`、`prompt`、`refs`、`described` 都是现有变量名；没有风格图时不进这段，输出不变。

```python
        style_state, style_hash, slots = None, None, refs["kept"]
        if style:
            cap = caps.max_refs - (1 if frame_mode == "ref" else 0)
            if frame_mode == "frame" and not caps.frame_with_refs:
                style_state = "first_frame"
            elif len(refs["kept"]) < cap or any(not sl.get("main") for sl in refs["kept"]):
                if len(refs["kept"]) >= cap:
                    refs = pick_refs(shots, idx, cap - 1)
                    described = [describe(sl, idx) for sl in refs["missing"] + refs["dropped"]]
                last_main = max((i for i, sl in enumerate(refs["kept"]) if sl.get("main")), default=-1)
                slot = {"asset_id": STYLE_ID, "role": "style", "variant": None,
                        "text": STYLE_TEXT, "source": style["source"]}
                slots = refs["kept"][:last_main + 1] + [slot] + refs["kept"][last_main + 1:]
                text, _ = neutral_prompt(shots, doc, idx, mode=audio_mode, slots=slots,
                                         described=described, first_frame=frame_mode == "ref",
                                         timing="playable", cps=cps)
                prompt = rewrite(text)
                style_state, style_hash = "used", style["hash"]
            else:
                style_state = "full"
```

    - 输出的 dict 里：`"refs"` 改为 `[sl["asset_id"] for sl in slots]`，`"_slots": slots`，`dropped_refs` / `missing_refs` 用（可能重选过的）`refs`，再加 `"style": style_state, "style_hash": style_hash`。`fingerprint` 仍是上面先算好的 `fp`。
    - 第 5 条测试会验证「尾帧接力不受影响」：接力的判定写在这段之前，用的是没加风格图的 `refs["kept"]`，不要挪动它。
    - `request_for(…, style: Optional[dict] = None)`：
      - 把 `style` 传给 `build_clips`；
      - 构造 `RefImage` 时照常遍历 `c["_slots"]`，风格位的 `role` 是 `"style"`；
      - `ClipRequest(…, style_ref=c["style_hash"])`。
  - `neutral_prompt` 不用改。
  - 确认 `rewrite_refs` / `provider.rewrite_prompt` 能处理 `{ref:__style__}`：按出现顺序编号，没有对资产 ID 格式的假设。有假设就在那里放行 `STYLE_ID`，并补一条 `test_seedance.py` 用例。
- [ ] **Step 4:** `test_compose.py`、`test_seedance.py`、`test_providers.py`、`test_session.py` 全部通过，金标准不变。
- [ ] **Step 5: 提交**

```bash
git commit -m "出片切段带上风格参考位：排在主要角色之后，参考位满时裁掉优先级最低的非主要角色，全是主要角色则不带；首帧单用时不带，不影响尾帧接力；片段指纹不含风格图，换图不致过期；请求记下实际用的风格图"
```

---

### Task 3: 出片会话记下风格图，并标出可重出

**Files:**
- Modify: `backend/render/session.py`、`backend/render/runner.py`、`backend/server/app.py`、`backend/render/smoke.py`
- Test: `backend/tests/render/test_session.py`、`test_runner.py`、`backend/tests/server/test_render.py`

- [ ] **Step 1: 先写失败测试**：
  - **`test_session.py`**：
    1. `build(…, style=s1)` 后，各段有 `style`、`style_hash`。
    2. 模拟一段出完：沿用文件里已有的「出完一段」辅助写法，让采用的尝试 `style_ref == "h1"`。再 `build(…, style=s2)`（哈希 `h2`）：这一段仍是 `done`；`view` 里这一段 `style_outdated is True`，`style_outdated_count == 1`；`remaining_cny` 不含这一段。
    3. 用回 `s1` 重建后，`style_outdated` 是 `False`。
    4. `style=None` 重建后，`style_outdated` 是 `False`，计数为 0。
    5. 旧会话里的尝试没有 `style_ref` 键、而现在有风格图时，按可重出处理。
  - **`test_runner.py`**：用 `fake` 厂商跑一段，`request_builder` 返回的 `req.style_ref == "h1"`。提交后，会话里这段最后一次尝试的 `style_ref == "h1"`。
  - **`tests/server/test_render.py`**：上传风格图后建会话（`POST …/render/session`）：各段 `style == "used"`（夹具有空位时）。`GET …/render/session` 带回 `style_outdated_count`。
- [ ] **Step 2: 跑一下，确认失败**。
- [ ] **Step 3: 实现**：
  - **`session.build(…, style: Optional[dict] = None)`**：透传给 `compose.build_clips`。`row` 由 `b` 生成，所以 `style`、`style_hash` 每次重建都会更新。
  - **`begin_submit` 不改**：尝试的 `style_ref` 在 `submitted` 里写入。
  - **`submitted(root, clip_id, task_id, first_frame_used, style_ref: Optional[str] = None)`**：把 `style_ref` 一起写进最后一次尝试。
  - **`view`**：
    - 每段加 `style_outdated`，判定按实施裁定 8。采用的尝试是 `c["attempts"][c["chosen"]]`，`chosen` 为 `None` 时不判定，取 `False`。
    - `out["style_outdated_count"]` 是 `style_outdated` 为真的段数。
  - **`runner._submit`**：`sess.submitted(root, c["id"], tid, used, style_ref=getattr(req, "style_ref", None))`。
  - **`app.py`**：
    - 新函数：

```python
def _style_for(uid: str, nid: str) -> Optional[dict]:
    """这部小说当前的风格参考图（data URI + 哈希）；没有或读不到为 None。"""
    try:
        path, _ = novels.style_image_file(uid, nid)
        meta = novels.get_novel(uid, nid).get("style_image") or {}
        return {"source": render_compose.data_uri(path), "hash": meta.get("hash")}
    except (novels.NotFound, OSError):
        return None
```

    - 每一处 `render_session.build(…)` 调用都加 `style=_style_for(owner["user_id"], owner["nid"])`。`grep -n "render_session.build" server/app.py` 能列出全部，现在有 5 处。
    - `_render_request` 调 `request_for(…, style=_style_for(o["user_id"], o["nid"]))`。
  - **`smoke.py`**：加 `--style <路径>`。有值时用 `compose.data_uri(Path(路径))` 和文件 sha256 组成 `style`，传给 `build_clips` 和 `request_for`。打印本段 `style` 状态。
- [ ] **Step 4:** 后端全部检查通过。
- [ ] **Step 5: 提交**

```bash
git commit -m "出片会话记下每次尝试实际用的风格图，读取时给用旧风格图出完的段标可重出并计数（仍算完成、批量出剩余不含）；建会话、刷新、提交都带上当前风格图；冒烟脚本可带风格图"
```

---

### Task 4: 前端上传与显示

**Files:**
- Modify: `frontend/src/api.ts`、`types.ts`、`components/NovelPage.tsx`、`components/NovelOverview.tsx`、`i18n/zh.ts`、`en.ts`、`styles/chapter.css`
- Create: `frontend/src/useStyleImage.ts`、`frontend/src/components/params/StyleImageField.tsx`
- Test: `frontend/tests/chapter.test.tsx`（新的一段）

- [ ] **Step 1: 先写失败测试**：渲染 `StyleImageField`，`fetch` 的打桩写法照抄 `workspace.test.tsx`：
  - 空态：有 `[data-testid="style-drop"]`，写着「拖入或选择一张图」。
  - 选择文件：给隐藏的 `input[type=file]` 派发 `change`，文件是 `new File([..], 'a.png', { type: 'image/png' })`。之后会 `PUT /novels/n1/style-image`，请求体就是这个文件，并调用 `onChanged(meta)`。
  - 有图时（传入 `meta` 和 `url`）：显示 `img` 和「替换」「删除」两个按钮。点「删除」先弹确认，确认后发 `DELETE`，并调用 `onChanged(null)`。
  - `image/gif` 文件：不发请求，提示「只收 PNG / JPEG / WebP」。
  - 超过 8MB 的文件：不发请求，给出提示。
  - 渲染 `NovelOverview`：`novel.style_image` 有值时有 `[data-testid="ovw-style"]`；点了调用 `onSection('settings')`；没有时不显示。
- [ ] **Step 2: 实现**：
  - **`types.ts`**：
    - `StyleImageMeta { hash: string; mime: string; bytes: number; updated_at: string }`。
    - `Novel.style_image?: StyleImageMeta | null`。
  - **`api.ts`**（写法照抄 `keyframeUrl` / `uploadKeyframe` / `deleteKeyframe`）：
    - `styleImageUrl(nid)`：带 token 取 blob，转成 blob URL。
    - `uploadStyleImage(nid, file) → StyleImageMeta`。
    - `deleteStyleImage(nid)`。
  - **`useStyleImage(nid, hash)`**：
    - `hash` 为空时返回 `null`。
    - `hash` 变化时重取；卸载或换图时 revoke。
    - 取失败时返回 `null`，不报错。
  - **`StyleImageField({ nid, meta, url, onChanged })`**：
    - 空态是虚线框，可以点选文件，也可以拖放；拖放时 `dragover` 要 `preventDefault`。
    - 有图时：缩略图（最长边 160px）、「替换」「删除」，加一行说明（规格 2.1 的那句）。
    - 前端先校验格式和大小，与后端同样的上限。
    - 删除走 `useConfirm`。
    - 成功、失败都用 `notice`。
  - **设置页 `ParamsTab`**：在风格卡片（`StylePicker`）下面放 `StyleImageField`。`onChanged` 之后让上层重新取小说：沿用设置页现有的保存后刷新回调。`url` 来自 `useStyleImage(novel.id, novel.style_image?.hash)`。
  - **`NovelOverview`**：在故事梗概卡片（`[data-testid="ovw-outline"]`）的标题行右侧放 48px 圆角缩略图，`data-testid="ovw-style"`，是一个 `button`，`aria-label` 为「风格参考图」，点了调用 `onSection('settings')`。
  - **新增文案**：`style.ref.title`、`drop`、`replace`、`remove`、`note`、`badType`、`tooBig`、`uploaded`、`removed`、`confirmTitle`、`confirmBody`、`aria`。
- [ ] **Step 3:** 前端三项检查通过。
- [ ] **Step 4: 提交**

```bash
git commit -m "前端风格参考图：设置页上传框（拖放或选择、替换、删除需确认、前端先校验格式与大小），概览页梗概卡片显示缩略图并可进设置；共用的取图钩子"
```

---

### Task 5: 画布里的风格图说明、可重出提示与下载

**Files:**
- Modify: `frontend/src/types.ts`、`components/FilmPanel.tsx`、`components/TimelineCanvas.tsx`、`i18n/zh.ts`、`en.ts`
- Test: `frontend/tests/film.test.tsx`

- [ ] **Step 1: 先写失败测试**：`film.test.tsx` 已有渲染 `FilmPanel` 的夹具，沿用它：
  - `ClipDetail` 的风格图那一行 `[data-testid="clip-style"]`：
    - `style` 是 `used` / `full` / `first_frame` 时，文字依次是「风格图 ✓」「未带上：参考位已满」「未带上：本段用首帧（关键帧或上一段尾帧）」。
    - `style` 是 `null` 时这一行不存在。
  - `style_outdated: true` 的段：详情里有 `[data-testid="clip-style-outdated"]`，写着「风格图已换，可重出这一段」。段的状态显示仍是完成。
  - 会话 `style_outdated_count: 2` 时，出片页顶部（`Overview` 或 `Precheck` 的汇总处）有「2 段可按新风格图重出」；为 0 时没有。
  - 渲染 `TimelineCanvas` 并传入 `styleUrl`：关键帧区域顶部有 `[data-testid="kf-style"]`，里面有 `img` 和「下载风格图」链接，`download` 属性是 `style-reference.<扩展名>`。不传 `styleUrl` 时没有这块。
- [ ] **Step 2: 实现**：
  - **`types.ts`**：
    - `FilmClip.style?: 'used' | 'full' | 'first_frame' | null`、`style_hash?: string | null`、`style_outdated?: boolean`。
    - `FilmAttempt.style_ref?: string | null`。
    - `FilmSession.style_outdated_count?: number`。
  - **`FilmPanel`**：
    - 在 `ClipDetail` 的参考图那几行（`droppedList` / `missingList` 附近）后面加风格图那一行。
    - 可重出的提示用 `StatusPill tone="warn"`。
    - 计数放在 `Overview` 的汇总里，挨着 `uncertain` 那条。
  - **`TimelineCanvas`**：
    - 新增可选属性 `styleUrl?: string | null`、`styleMime?: string`。
    - 在关键帧计数（`canvas.kfCount`）那一处的上方，渲染缩略图和 `<a href={styleUrl} download=…>`。
    - `StoryboardView` 打开画布时把它们传进去：`StoryboardView` 新增同名可选属性，App 用 `useStyleImage(novel.id, novel.style_image?.hash)` 得到 `url` 后传入，`mime` 取 `novel.style_image.mime`。
  - **新增文案**：`film.style.used`、`full`、`firstFrame`、`outdated`、`outdatedCount`，`canvas.styleDownload`、`styleAria`。
- [ ] **Step 3:** 前端三项检查通过；后端检查照常通过。
- [ ] **Step 4: 提交**

```bash
git commit -m "画布出片页逐段说明风格图带没带上（已带上、参考位已满、首帧单用），用旧风格图出完的段提示可重出并在汇总计数；关键帧区可下载风格参考图"
```

---

## 自查记录

- **规格覆盖**：
  - 2.1 上传：Task 1 后端、Task 4 前端。
  - 2.2 概览：Task 4。
  - 2.3 出片页：Task 3 后端字段、Task 5 显示。
  - 2.4 关键帧页：Task 5。
  - 3.1 参考位、3.2 提示词、3.3 传法：Task 2。
  - 4 指纹与可重出：Task 2 指纹不变，Task 3 的 `style_ref` 和 `style_outdated`。
  - 5 后端：Task 1、3；审计按实施裁定 1 去掉。
  - 6 前端：Task 4、5。
  - 7 测试：分布在各任务；冒烟 `--style` 在 Task 3。
- **类型一致**：
  - `style` 参数的形状 `{source, hash}`：在实施裁定 6 定义，Task 2、3 使用。
  - `style` 片段字段 `used / full / first_frame / null`：Task 2 产生，Task 3、5 使用。
  - `style_ref`：Task 2 放进 `ClipRequest`，Task 3 写进尝试，Task 5 只在类型里出现。
  - `style_outdated` 和 `style_outdated_count`：Task 3 产生，Task 5 使用。
