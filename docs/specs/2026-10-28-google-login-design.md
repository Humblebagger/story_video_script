# Google 账号登录设计

日期：2026-10-28 · 分支：langchain

## 0. 决定

| 决定 | 内容 |
|---|---|
| 背景 | 收费暂缓，先面向海外，先做基础体系；Google 登录是第一项 |
| 接入方式 | Google Identity Services 官方按钮（前端拿 ID token）+ 后端 `google-auth` 校验，不用 client secret、不做页面跳转 |
| 密码登录 | 保留；已有账号可绑定 Google，绑定后两种方式都能登录、数据不变 |
| 用户识别 | 按 Google `sub`，不按邮箱 |
| 登录凭证 | 沿用现有 HMAC 自包含 token（`auth.issue_token`），下游接口不改 |
| 不做 | GitHub/Apple 等其他登录；英文界面；按邮箱自动合并、找回密码、注销 |

## 1. 流程

1. 登录页请求 `GET /auth/config`。`google_client_id` 为空则不显示 Google 按钮。
2. 否则加载 `https://accounts.google.com/gsi/client`，渲染官方按钮，放在密码表单上方。
3. 用户完成 Google 登录，回调拿到 ID token（`credential`），前端 `POST /auth/google`。
4. 后端 `google.oauth2.id_token.verify_oauth2_token(credential, request, audience=client_id)`：校验签名（Google 公钥，带缓存）、`aud`、`exp`、`iss`。
5. 按 `("google", sub)` 查绑定：命中则签发 token；未命中则新建用户 + 绑定后签发。
6. 前端 `setSession(token, user)`，此后与密码登录完全一致。

## 2. 数据

### 2.1 `identities.json`（与 `users.json` 同目录）

```json
[{"provider": "google", "subject": "1098…", "user_id": "a1b2c3d4e5f6",
  "email": "x@gmail.com", "name": "…", "picture": "https://…",
  "created_at": "…", "last_login_at": "…"}]
```

- `(provider, subject)` 唯一；一个用户可有多条。
- 写法与 `users.json` 相同：tmp + rename，共用 `auth._lock`。
- 每次 Google 登录更新 `email`、`name`、`picture`、`last_login_at`。

### 2.2 `users.json` 变化

- `salt`、`password_hash` 变为可选；Google 新建的用户没有这两项。
- 用户名自动生成：取邮箱 `@` 前部分，去掉 `USERNAME_RE` 不允许的字符；长度不足 2 时用 `user_` + 4 位随机 hex；超过 32 截断；与已有用户名（不区分大小写）冲突时加 `_2`、`_3`… 后缀。
- `authenticate()`：用户没有 `password_hash` 时按「用户名或密码不正确」处理，不透露注册方式。
- `_public()` 增加 `has_password: bool` 与 `identities: [{provider, email}]`。
- 首个用户（`users.json` 为空时）无论经密码注册还是 Google 新建，都执行 `_adopt_legacy_runs`。

## 3. 接口

| 方法 | 路径 | 鉴权 | 请求 | 响应 / 错误 |
|---|---|---|---|---|
| GET | `/auth/config` | 无 | — | `{google_client_id: str \| null, password_login: true}` |
| POST | `/auth/google` | 无 | `{credential}` | `{token, user, created}`；未配置 404；凭证无效 401；连不上 Google 503 |
| POST | `/auth/google/link` | 需要 | `{credential}` | `{user}`；已绑在别的用户 409；当前用户已绑过另一个 Google 账号 409；其余同上 |
| DELETE | `/auth/identities/google` | 需要 | — | `{user}`；没有密码时 400；未绑定 404 |
| GET | `/auth/me` | 需要 | — | 用户信息含 `has_password`、`identities` |

配置：`backend/.env` 的 `STORYBOARD_GOOGLE_CLIENT_ID`。校验函数可注入（测试替换为假实现）。后端访问 Google 公钥遵循标准 `HTTPS_PROXY` 环境变量。

错误文案：

| 情况 | 状态码 | 文案 |
|---|---|---|
| 凭证无效、过期、`aud` 不符 | 401 | Google 登录失败，请重试 |
| 取公钥失败 | 503 | 暂时无法验证 Google 身份，请稍后再试 |
| Google 账号已绑定其他用户 | 409 | 这个 Google 账号已绑定另一个用户，请先用它登录并解除绑定 |
| 当前用户已绑定其他 Google 账号 | 409 | 当前账号已绑定 Google，请先解除绑定 |
| 解绑但无密码 | 400 | 账号没有设置密码，解除绑定后将无法登录 |
| 未配置 client ID | 404 | 未启用 Google 登录 |

## 4. 前端

- `api.ts`：`authConfig()`、`googleLogin(credential)`、`googleLink(credential)`、`googleUnlink()`。
- `auth.ts`：`User` 增加 `has_password`、`identities`。
- 新组件 `GoogleButton`：动态加载 GIS 脚本（同一页面只加载一次），`google.accounts.id.initialize({client_id, callback})` + `renderButton`；脚本加载失败时显示「Google 登录暂不可用」。供登录页与账号面板复用。
- `LoginView`：有 client ID 时顶部放 `GoogleButton`，下方分隔线「或使用用户名密码」，原表单不变。
- 右上角用户名旁「账号」面板：显示已绑定的 Google 邮箱；未绑定时显示 `GoogleButton`（绑定模式）；已绑定时「解除绑定」，`has_password` 为假时禁用并说明原因。
- GIS 的类型用最小的 `declare global` 声明，不引额外依赖。

## 5. Google Cloud 配置（用户手动，一次性）

1. 新建项目，配置 OAuth 同意屏幕：外部用户；范围仅 `openid email profile`。测试阶段可加测试用户；正式对外前提交品牌信息审核（以 Google 当时要求为准）。
2. 新建凭证「OAuth 客户端 ID → Web 应用」，已获授权的 JavaScript 来源填 `http://localhost:5173`、`http://localhost` 与正式域名。弹窗方式不需要回调地址。
3. client ID 写入 `backend/.env` 的 `STORYBOARD_GOOGLE_CLIENT_ID`。

国内开发时，浏览器需能访问 Google，后端需配置 `HTTPS_PROXY`；部署在海外无此问题。

## 6. 测试

| 层 | 内容 |
|---|---|
| 后端 `tests/server/test_google_login.py` | 注入假校验函数，不连网：新建用户与用户名生成（含冲突后缀、过短、非法字符）；老用户再登录并更新资料；首个用户接管旧数据；绑定、重复绑定 409、当前用户已绑 409；无密码解绑 400；无密码账号走密码登录被拒；未配置 404；凭证无效 401；取公钥失败 503；签发的 token 通过 `verify_token`；`/auth/me` 返回 `has_password` 与 `identities` |
| 前端 | happy-dom 中模拟 `window.google`：有配置渲染按钮、无配置不渲染；回调后请求 `/auth/google` 并保存会话；账号面板绑定、解绑按钮状态；脚本加载失败的提示 |
| 手动 | 配好 client ID 后真实登录、绑定、解绑各一次 |
