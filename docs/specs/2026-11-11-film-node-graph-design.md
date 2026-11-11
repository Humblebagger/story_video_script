# 出片画布「节点图」视图与自由节点 设计

日期：2026-11-11 · 分支：langchain · 借鉴：即梦自由画布 · 设计审查：Fable（意见已并入）

## 0. 目标与已定决策

用户确认要做的三件事：

1. 角色、场景、风格参考作为节点显示在画布上，与用到它们的段连线，一眼看出谁参考了谁。
2. 在画布上单独拉一个节点，在剧本之外补拍或重做一段。
3. 节点卡片上直接显示参考图、生成结果和状态，少开弹窗。

讨论中定下的决策：

| # | 问题 | 决定 |
|---|---|---|
| D1 | 节点放哪 | 保留时间轴；画布顶栏加「时间轴 / 节点图」切换，节点图是新视图。时间轴继续负责播放、对齐、合成 |
| D2 | 自由节点的结果怎么用 | 不挂靠 = 独立素材（不进合成，可播放、下载，导出时附带）；挂靠某个剧本段 = 那一段的一次新尝试，可设为采用。**不支持**在两段之间插入新段 |
| D3 | 剧本段的连线能否改 | 只读，跟着分镜与资产卡走（被挤掉的参考虚线显示）。想手动调参考：从这一段「派生自由节点」，在自由节点上改 |
| D4 | 布局 | 全自动布局，不能拖动，不存位置；靠缩放、平移和「选中高亮相关连线」看清关系 |
| D5 | 卡片 | 卡片上显示缩略图、状态、花费，并可直接出这一段 / 重出、切换采用、派生、生成；完整详情在右侧现有出片面板里看，不开弹窗 |
| D6 | 存储 | 出片会话 `session.json` 里与 `clips` 并列加 `free` 列表；剧本段逻辑只在「遍历在跑项」处扩展 |

不做：节点拖动与位置持久化；在成片里插入新段；剧本段连线编辑；在画布上拖线连参考（自由节点的参考用卡片上的下拉多选改，连线随之更新）；自由节点上传任意图片作参考或首帧；助手操作自由节点（助手的出片工具只看 `clips`，保持不变）。

## 1. 数据：会话里的 `free` 列表

会话文件 `chapters/<cid>/render/<vid>/session.json` 新增两个顶层键（旧会话没有按 `free=[]`、`free_seq=0` 处理）：

- `free_seq`：已分配的最大自由节点序号。新建时 +1，id 为 `F{seq:02d}`。删除后不回退，id 永不复用。
- `free`：自由节点列表，每条如下。

```jsonc
{
  "id": "F01",
  "target": "E01-C03",               // 挂靠的剧本段 id；null = 独立素材
  "target_shots": ["E01-SH007", "E01-SH008"],  // 挂靠时目标段的镜头 id，用来识别重新切段后同 id 换了内容
  "target_lost": false,              // 挂靠的段在重新切段后消失或换了镜头（此时 target 已置 null）
  "prompt": "……",                    // 正文：用户写的画面描述，不含参考行与 {ref:}/@图片n 占位（≤ 2000 字）
  "refs": ["c_lin", "style"],        // 资产 id，顺序即发给厂商的顺序；风格图用 compose.STYLE_ID
  "first_frame": "keyframe:E01-SH004" | "tail:E01-C02" | "tail:F02" | null,
  "duration": 5.0,                   // 秒，一位小数；挂靠时等于目标段当前时长
  "estimate_cny": 2.5,
  "state": "planned",                // planned / queued / running / downloading / done / failed
  "error": null,
  "uncertain": false,
  "attempts": [],                    // 与 clip 的尝试记录同格式
  "chosen": null,
  "created_at": "…"
}
```

### 1.1 状态与尝试

- 状态机与 clip 相同，复用 `IN_FLIGHT`、提交中断、上限检查、uncertain 处理。自由节点没有 `stale` 状态：它不依赖分镜。尝试记录里的 `fingerprint` 填 null。
- 下载成功后自动 `chosen = 最新一次`（与 clip 一致）。用户可用 `PUT /free/{fid}/chosen` 改。
- 视频文件为 `clips/F01.<task_id>.mp4`，尾帧按现有 `last_frame_path` 规则命名。
- 尝试的 `style_ref`：只有 `refs` 含 `STYLE_ID` 时，才记当次风格图的哈希；否则为 null。

### 1.2 挂靠时的交付（复制到目标段）

- 一次尝试下载成功后，在**同一把会话锁内**把这条尝试复制一份放进目标段的 `attempts`。复制件的字段：
  - `free_id: "F01"`；
  - `cost_cny: 0`（花费只记在自由节点自身，避免「本段已花」重复计数）；
  - `fingerprint` = 目标段此刻的指纹。
- 插入位置**按尝试状态判断**，不按段状态：
  - 目标段 `attempts[-1].state` 为 `submitting` 或 `running`：插到倒数第一条之前。runner 的 `submitted` / `poll_update` / `downloaded` / `submit_failed` 都认 `attempts[-1]` 为在跑的那次；`chosen` 只可能指向更早的尝试，下标不受影响。
  - 其余情况：直接追加到末尾。
- 不自动改目标段的 `chosen`。用户点「设为这一段的采用」，走现有 `PUT /clips/{clip_id}/chosen`。
- 复制前再核对一次：若目标段已不存在，或目标段镜头已不等于 `target_shots`，则不复制，只记在自由节点上，并按 §1.5 转为独立素材。
- 之后目标段的 done / stale 判定、合成、配音对齐都沿用现有逻辑。
- `_style_outdated` 对带 `free_id` 的采用尝试一律返回 False。用户在自由节点上自己决定是否带风格图。

### 1.3 校验（新建、修改、提交前各查一次）

- `refs` 去重。每个 id 必须满足以下之一：
  - 是本版分镜里的资产，且「第一张可用图」存在。取图规则：用 `image_for` 时 `variant=None`，即角色、生物、道具取 `reference_images` 的第一张可用图，场景取 `angles` 的第一张。资产所属类别由 id 在 `assets_index` 里查到的那一类决定。
  - 是 `STYLE_ID`，且本小说当前有风格图。
- 参考数 ≤ 厂商 `max_refs`。厂商 `frame_with_refs=False` 且带首帧时，首帧占一个参考位（与剧本段同规则，`frame_mode="ref"`）。
- 首帧：
  - `keyframe:<镜头 id>` 要求该镜头当前有关键帧。
  - `tail:<段或自由节点 id>` 要求源已有采用结果，且该次尝试有尾帧文件；不能以自己为来源。
  - 厂商不支持首帧（`caps.first_frame=False`）时只允许 null。
- 独立素材的 `duration`：1 ≤ duration ≤ `caps.max_clip_sec`，保留一位小数。
- `prompt` 去掉首尾空白后，生成时不能为空。

改设置导致参考位变少时，不自动裁剪 `refs`。视图里给该节点附 `over_refs: true`，生成接口返回 422，直到用户删减。

### 1.4 派生

`POST /free` 带 `from_clip` 时，按目标段预填：

- `prompt`：该段已存提示词中，去掉以 `【首帧】`、`【参考】` 开头的行，再去掉残余的 `{ref:…}` 与 `@图片\d+` 占位。
- `refs`：该段的 `refs`（含风格图，顺序不变）。
- `duration`：该段时长。
- `target` 与 `target_shots`：该段的 id 与镜头。
- `first_frame`：`keyframe:X` 原样保留，`relay:X` 换成 `tail:X`；若 `tail:X` 此刻不满足 §1.3，置 null。

### 1.5 重新切段与 `build()`

`GET /session` 每次轮询都会调用 `build(allow_in_flight=True)`，所以下列规则在每次读取时生效：

- `build` 构造新会话时显式带上旧会话的 `free` 与 `free_seq`，不能丢。
- **在跑的自由节点**（`state ∈ IN_FLIGHT`）原样保留，不同步时长、不改挂靠；落地之后的下一次 `build` 再同步。
- 不在跑的挂靠节点：
  - 若 `target` 不在新 `clips` 中，或该段镜头 ≠ `target_shots`：`target` 置 null、`target_lost` 置 true，节点转为独立素材，时长保持原值。
  - 否则：`duration` 同步为目标段新时长，并重算 `estimate_cny`。
- 已复制进旧段的尝试随旧段走现有 orphaned 机制。
- 改设置（`allow_in_flight=False` 或带 patch）时，`build` 的「有在跑项就 409」检查要把自由节点算进去。

### 1.6 花费与互锁

在跑判断与金额统计统一经两个辅助函数，在 `clips + free` 上计算：

- `session.items(s)`：返回 `s["clips"] + s.get("free", [])`。
- `session.any_in_flight(s)`。

需要改用它们的调用点：

- 预算检查：`queue_run`（上限）、`begin_submit`（在跑合计）。
- `view`：`reserved_cny` 包含在跑的自由节点；`counts` 与 `remaining_cny` 仍只算 `clips`。
- `begin_compose`：有自由节点在跑时同样拒绝合成。
- `run_quote`：合成进行中拒绝出片的规则，同样适用于自由节点生成。

花费计入会话 `spent_cny`。

### 1.7 删除

- 在跑的节点 409。
- 有其他自由节点以 `tail:<fid>` 作首帧时 409，提示「F02 用它的尾帧作首帧，先改掉那边」。
- 删除时一并删掉**只属于该节点**的已下载文件（视频与尾帧）。已复制进剧本段的尝试共用同一文件，这些文件保留。卡片在删除前先确认。

## 2. 接口

都在现有出片前缀 `/novels/{nid}/chapters/{cid}/versions/{vid}/render` 下，权限与 clips 接口相同（`novel_user`）。成功都返回会话视图 `view(s)`。

| 方法与路径 | 作用 | 错误 |
|---|---|---|
| `POST /free`，body `{from_clip?: str}` | 新建。无 `from_clip` 时建空白独立素材：prompt 空、refs 空、duration = min(5, `max_clip_sec`)；有则按 §1.4 派生 | 无会话 404；`from_clip` 不存在 404 |
| `PATCH /free/{fid}`，body 为 `{prompt, refs, first_frame, duration, target}` 的任意子集 | 修改。`target` 可设为某 clip id（同时记 `target_shots`、`duration` 跟随该段、清 `target_lost`）或 null；挂靠时传 `duration` 返回 422 | 在跑 409；校验不过 422（中文原因）；fid 不存在 404 |
| `DELETE /free/{fid}` | 按 §1.7 删除 | 在跑或被引用 409 |
| `POST /free/{fid}/run`，body `{expected_cny?}` | 生成一次 | 校验不过 422；超上限、合成中、确认金额不符 409 |
| `PUT /free/{fid}/chosen`，body `{attempt}` | 自由节点自身采用哪次（影响卡片显示、尾帧来源、导出） | 下标无效或该次未成功 422 |

`POST /free/{fid}/run` 的步骤与 `_film_run` 对齐：

1. 过验证门（`_render_ctx(gate=True)`）。
2. `build` 刷新会话。
3. 校验（§1.3）。
4. 确认线：预估超过 `confirm_over_cny` 时，必须带与服务端一致的 `expected_cny`，否则 409。
5. 预算与互锁检查（§1.6），节点转 `queued`。
6. 调用 `_render_runner.watch(root)`。

`GET /session` 的视图带 `free`（每条附 `estimate_cny`、`uncertain`、`over_refs`）与 `free_seq`。

## 3. 后台线程与请求组装

### 3.1 遍历在跑项

以下各处由「只看 `clips`」改为经 `session.items(s)` / `any_in_flight(s)` 处理：

- `Runner.tick`：推进阶段、提交阶段，以及共用并发上限的 `busy` 计数。
- `Runner._settle`：只要还有自由节点在跑，就不放弃这个会话。
- `session.recover`：处理自由节点中断的 `submitting` 尝试；有在跑项的返回值把自由节点算进去。
- `novels.delete_version`：删版本前的在跑检查。
- `session.build`：在跑检查（§1.5）。

session 的现有迁移函数（`begin_submit`、`submitted`、`submit_failed`、`poll_update`、`downloaded`、`download_failed`、`note_error`）改为经 `_item(s, id)`，在 `clips` 与 `free` 里按 id 查找。自由节点 id 以 `F` 开头，与段 id 不冲突。

只在两个分支处区分自由节点：

- 自由节点不做指纹 / stale 判定（`submit_failed(stale=True)` 不会发生在自由节点上）。
- `downloaded` 对挂靠节点额外执行 §1.2。

现有 clip 测试不改即应通过。

### 3.2 请求组装 `compose.request_for_free`

签名：`request_for_free(doc, session, node, *, keyframes, tail_frame, caps, rewrite, style) → (ClipRequest, first_frame_used)`。

1. 按 §1.3 的取图规则，依 `refs` 顺序建参考位；若 `frame_mode="ref"`，首帧排在最前。
2. 拼完整提示词，然后整体调用厂商 `rewrite`（Seedance 会把 `{ref:…}` 按出现顺序换成 `@图片n`，与参考图顺序一致）。拼法为：
   - `node.prompt` 正文；
   - `frame_mode="ref"` 时加一行 `【首帧】{ref:FIRST} 本段开场画面，保持构图与人物位置`；
   - 每个参考一行 `【参考】{ref:<id>} <资产名>`，风格图用 `STYLE_TEXT`。
3. 首帧：`keyframe:` 读关键帧文件；`tail:` 读源采用尝试的尾帧文件。`frame_mode="frame"` 时作为 `first_frame` 发送。
4. 其余字段（模型、分辨率、画幅、声音、`style_ref`）与 `request_for` 相同。
5. 校验失败（资产图没了、尾帧文件丢失、超出参考位、正文为空）时抛 `compose.FreeInvalid(原因)`。runner 收到后经 `submit_failed` 把节点记为失败并写明原因，不提交、不花钱。

`app._render_request` 按 id 前缀分派：

- `F` 开头 → `request_for_free`；
- 其余 → 现有 `request_for`。

## 4. 不受影响与导出

- 合成、批量「出剩余各段」（`_remaining`）、`counts`、助手的出片确认卡与任务轮询只看 `clips`。
- 导出 FCPXML：现有前提不变（要有最新成片）。打包时另读 `session.json` 的 `free`：
  - 每个有采用结果的**独立素材**（`target` 为 null），把视频放进包内 `media/extra/F01.mp4`；
  - README 里列出这些文件与各自的提示词首行；
  - 不写进 FCPXML。
- 挂靠节点的结果已经是剧本段的尝试，不重复导出。

## 5. 前端：节点图视图

### 5.1 入口

- `TimelineCanvas` 顶栏加分段切换「时间轴 | 节点图」。状态只在组件内，不持久化。
- 版本没存进后端（无 nid/cid/vid）时「节点图」禁用，并给提示。
- 有版本但还没有出片会话时，节点图显示空状态：「先在出片页签选好厂商与档位」，加一个打开出片页签的按钮。
- `useFilm` 的 `active` 改为「出片页签可见或节点图可见」。
- `film.ts` 的 `pollDelay` 改为看 `clips` 与 `free` 里任一在跑项。
- `mainAction`（判断「试段已出」）忽略带 `free_id` 的尝试。

### 5.2 布局（纯函数 `frontend/src/nodeGraph.ts`）

`layoutGraph(input) → { nodes, edges, width, height }`。输入为出片会话、分镜资产索引、是否有风格图；不读 DOM，可单测。

**三列**

- **左列：资产节点**
  - 收录两类资产：被任一剧本段或自由节点用到的（出现在 `refs`、`dropped_refs`、`missing_refs` 里），以及所有有参考图的资产（自由节点可选的参考）。
  - 分组顺序：风格 → 主要角色 → 其他角色 / 生物 → 场景 → 道具。组内按资产 id 排序。
- **中列：剧本段**
  - 按 `clips` 顺序竖排，每集前加一行集标题。
- **右列：自由节点**
  - 挂靠节点从目标段所在行开始排；同一段挂了多个就往下错开。若超出该段行高，把中列后续行整体下推，避免重叠。
  - 独立素材排在右列最下方，按 id 排序。

**尺寸常量**：资产卡 180×72；段卡与自由卡 260×176；行距 24；列距 160。

**连线种类**

| 种类 | 线型 | 含义 |
|---|---|---|
| `ref` | 实线 | 资产 → 段 / 自由节点 |
| `dropped` | 虚线 | 被挤掉的参考 |
| `missing` | 点线 | 资产没有图，只写进文字描述 |
| `frame` | 强调色 | 首帧来源：`relay:` / `tail:` 从源节点右侧连到目标节点左侧；关键帧不画线 |
| `target` | 粗虚线 | 自由节点 → 挂靠段 |

连线用三次贝塞尔曲线，端口在卡片左右边的中点。

### 5.3 交互

- **视口**：拖动空白处平移；滚轮或触控板缩放，有上下限；提供「适应画面」按钮。节点图的视口状态与时间轴各自独立。
- **高亮**：默认所有连线低不透明度。悬停或选中某节点时，与它相连的连线和节点高亮，其余变淡。Esc 取消选中。
- **点段卡**：选中该段，右侧切到「出片」页签并定位到这一段（复用 `clipSel`）。
- **点资产卡**：只高亮，不跳转。卡片上的「打开资产」小按钮跳到右侧资产页签。
- **点自由卡**：右侧出片面板显示该自由节点的详情：完整提示词、全部尝试、失败原因。

### 5.4 卡片

**剧本段卡**

- **顶部**：段号、时长、状态徽标（待出 / 排队 / 生成中·已等 m:ss / 下载中 / 已出 / 失败 / 待重出 / 待核对），沿用 `film.ts` 的 `laneKind`、`laneText`。
- **中部**：
  - 有结果时，静态显示采用那次的尾帧图作为封面；悬停或选中时才取视频并播放（静音），移开后暂停。理由是 `filmFileUrl` 会把整个文件取成 blob，不能每张卡都预加载视频。
  - 没有结果时，显示首帧来源的缩略图（关键帧图或源段尾帧）；都没有就显示占位。
- **底部**：提示词前两行、本段已花 / 预估金额（复制件 `cost_cny=0`，不重复计数）、尝试次数。复制来的尝试标「来自 F01」。
- **操作**：
  - 「出这一段」/「重出」：单段预估超过确认线时，先在卡片内显示金额做二次确认，再带 `expected_cny` 调用。
  - 尝试切换（‹ 2/3 ›），调用现有采用接口。
  - 「派生自由节点」。
  - 段在跑时这些操作都禁用。

**资产卡**

- 参考图缩略图、名称、类型标签、「被 N 段用到」（只数剧本段的 `refs`）。
- 无图资产显示占位，并标「无图」。

**自由节点卡**

- **顶部**：F 号、状态徽标、挂靠信息（「顶替 E01-C03」/「独立素材」/「原段已不存在或已变」警示）。
- **编辑项**：
  - 提示词输入框：失焦或 800ms 防抖后 PATCH，显示保存中 / 已保存。
  - 时长：挂靠时只读。
  - 首帧下拉：无 / 有关键帧的镜头 / 有采用结果且有尾帧的段或自由节点。
  - 参考下拉多选：可选左列全部有图的资产与风格图，显示已用 / 上限，超限的选项禁用。
  - 挂靠下拉：无 / 选某段。
- **结果区**：与剧本段卡相同。
- **操作**：
  - 「生成」：确认线规则同剧本段。
  - 挂靠时，每次成功尝试旁有「设为这一段的采用」。
  - 独立素材有「下载」。
  - 「删除」：有已下载结果时先在卡内确认。
  - 节点在跑时，编辑与操作都禁用。

## 6. 出错处理

- 接口 422 / 409 的中文原因在卡片内联显示或用 toast，与出片面板现有做法一致。网络失败不改本地显示，等下次轮询再对齐。
- 提交前校验失败（§3.2）：自由节点转 failed 并写明原因，不花钱。
- 参考超限（§1.3）：卡片显示「参考超出当前厂商上限（n / m）」，生成按钮禁用。
- 挂靠段消失或换了镜头：卡片显示「原段已不存在或已变，已转为独立素材」。
- 并发：所有自由节点写操作都在会话锁内。PATCH / DELETE 遇到在跑节点返回 409。复制到目标段与写自由节点记录在同一把锁里完成（§1.2）。

## 7. 测试

后端测试不调真实厂商，沿用现有假厂商。涉及 `backend/tests/render/test_session.py`、`test_runner.py`、`test_compose.py`、`test_export_fcpxml.py` 与 `backend/tests/server/test_render.py`。

**会话与 `build`**

- 旧会话没有 `free` / `free_seq` 也能读。
- `build` 保留 `free` 与 `free_seq`。
- 在跑的自由节点在 `build` 中原样保留。
- 目标段消失 → `target_lost`。
- 目标段 id 不变但镜头变了 → `target_lost`。
- 目标段时长变 → 自由节点时长与预估同步。

**新建、派生、修改、删除**

- 删除后 id 不复用。
- 派生预填：去掉参考行与占位，`relay:` → `tail:`。
- 各项校验返回 422；在跑时返回 409。
- 被 `tail:` 引用时删除返回 409；删除只删属于该节点的文件。

**确认线、上限与互锁**

- 超确认线不带金额 → 409。
- 超上限 → 转失败，不提交。
- 有自由节点在跑时 `begin_compose` 被拒；合成进行中生成被拒。
- 有自由节点在跑时删除版本被拒。

**runner**

- 只有一个自由节点在跑时，经 `tick` → `_settle` 不被丢弃；`recover` 能续上。
- 自由节点与 clips 共用并发上限。
- 提交、轮询、下载、失败各路径。
- `FreeInvalid` 记失败，不提交。

**复制到目标段**

- 目标段空闲时追加到末尾。
- 目标段处于 `queued` 且最后一次尝试是 `submitting`（提交窗口）时，插在倒数第一条之前；随后 `submitted` / `downloaded` 落到正确的尝试上。
- 目标段 `running` 时同样插在倒数第一条之前。
- 复制件 `cost_cny=0`、带 `free_id`；`_style_outdated` 不误报。

**`request_for_free`**

- 参考顺序与 `@图片n` 编号一致，改参考后依然一致。
- 首帧两种来源。
- `frame_mode="ref"` 时首帧占一个参考位。
- 风格图位。

**其他**

- 合成、`_remaining`、`counts` 不受自由节点影响。
- 导出：独立素材进 `media/extra/` 并列入 README，不写进 FCPXML；挂靠节点不重复导出。

前端测试：`frontend/tests/node-graph.test.ts`（纯函数），`frontend/tests/node-graph.test.tsx`（组件）。

- **布局**：三列分组顺序、集标题、挂靠节点与目标段对齐且不重叠、各种连线正确、无会话 / 空会话。
- **轮询与判断**：`pollDelay` 认自由节点在跑；`mainAction` 忽略复制件。
- **组件**：
  - 切换视图；选中高亮；点段卡打开出片页签。
  - 自由卡：编辑后 PATCH、生成（含确认线二次确认）、设为采用、删除确认、参考超限禁用、在跑禁用。
  - 卡片不预加载视频，悬停时才取。

真实冒烟由用户手动进行。
