# 统一登录面板与应用接入

## 状态与范围

2026-10-24：3.2.8 已通过 SpringBok 更新原生产实例并完成独立可用性验证。
发布 source 为 `5c7bced37e743532082c8c54c4f6996ed6c550e6`，新增 `/login` 已可用，旧生产入口保持兼容。
本轮验证包含线上匿名入口及实际面板切换，不等于对每个接入应用完成真实密码/MFA/邮件/第三方 OAuth 全流程验收。
验收记录见 [实施计划 NA-16](IMPLEMENTATION_PLAN.md)。

统一面板是 **NAccount 自己托管的认证页面**，不是让每个应用复制密码表单，也不是 iframe。
应用只发起 Authorization Code + S256 PKCE，并在自己的回调中完成交易验证。
登录、注册、找回密码、Consent、MFA、Passkey 和恢复码继续使用已有 `Main` 与服务端流程；
实际可用选项仍受全局、应用、组织、账号与 provider 配置约束，不承诺所有方式均已配置。

## 入口契约

| 入口 | 用途 | 兼容性 |
| --- | --- | --- |
| `/login?...` | 新应用推荐的统一托管入口 | 直接返回面板，避免首次登录额外一次 HTTP 跳转及重复 client/scope 校验 |
| `/oauth2/v1/authorize?...` | 现有 OIDC SDK 入口 | 保留原跳转/SSO 行为，不要求已接入应用立即迁移 |
| `/identity/v1/view/authorize?...` | 已有交互视图/账号中心弹窗使用 | 继续校验完整授权参数；不是替代 OAuth 交易的公开密码 API |
| `/account` | 用户个人中心 | 不应被当作所有应用共享的 OAuth client 或 callback |

`/login` 使用与 authorize 相同的必需参数：

- `client_id`：**当前应用自己的**已启用 SPA client，不是门户 client，更不是 S2S secret。
- `redirect_uri`：后台已登记的当前应用回调。建议 HTTPS、固定小写路径、无 fragment。
  本地桌面应用可使用已登记的 loopback 回调并用系统浏览器完成登录；不能据此假定支持任意动态端口或 native scheme。
- `response_type=code`。
- `scope=openid profile`；只有需要刷新且已获许可时才申请 `offline_access`。
- `state`：每次新建、不可预测、回调必须精确校验的随机值。
- `code_challenge` 与 `code_challenge_method=S256`：基于当前交易的独立随机 verifier。

可选 `locale` 支持服务端配置的语言（当前源码包含 `zh/en/fr`）。`screen=signup` 直达注册，
`screen=reset` 直达找回密码；对应功能关闭时仍回到允许的登录方式，不能借参数开启功能。
两种 screen 仅避免**当前应用既有本地 SSO session**自动返回；显式 SAML/OIDC provider policy
仍遵循原 provider 路由，不承诺 screen 覆盖 provider policy。未指定 screen 时保留现有按 client 的 SSO 行为，
并在每次恢复时重新核验活动用户和 `securityVersion`，不是跨所有 client 自动无条件登录。

`org` 只用于既有组织策略/branding，不是任意应用主题开关。
面板上的应用名称来自已经校验的数据库 app，返回站点来自其已登记回调；不接受 query 中伪造的名称或站点。
HTTP(S) 回调只显示 origin，不展示路径、查询内容或凭据。组织 logo 未配置时显示 NAccount 文字标识，不请求空图片。

## 框架无关的发起示例

下面仅示范“发起交易”这一段，不是完整 SDK。示例域名和 client 必须换成部署与登记的实际值。
同一应用的已验证 OIDC 客户端库也可以继续使用 discovery 暴露的旧 authorize endpoint。

```javascript
const config = {
  issuer: 'https://your-naccount.example.com',
  clientId: 'your-registered-spa-client-id',
  redirectUri: 'https://your-app.example.com/auth/callback',
}

function randomValue() {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)),
    (byte) => byte.toString(16).padStart(2, '0')).join('')
}

async function startLogin(screen) {
  const state = randomValue()
  const verifier = randomValue()
  const digest = new Uint8Array(await crypto.subtle.digest(
    'SHA-256', new TextEncoder().encode(verifier)))
  const challenge = btoa(String.fromCharCode(...digest))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

  // sessionStorage 限于当前应用和 tab；不存密码，不向认证页发送 verifier。
  // 同一 tab 只允许一个在途登录交易；新交易会取代旧交易。
  sessionStorage.setItem(`naccount.transaction.${config.clientId}`, JSON.stringify({
    state, verifier, createdAt: Date.now(),
    clientId: config.clientId, redirectUri: config.redirectUri,
  }))
  const url = new URL('/login', config.issuer)
  url.search = new URLSearchParams({
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    response_type: 'code',
    scope: 'openid profile',
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
    locale: 'zh',
  }).toString()
  if (screen === 'signup' || screen === 'reset') url.searchParams.set('screen', screen)
  window.location.assign(url.href)
}
```

## 回调和业务会话的必做检查

1. 只在固定回调 origin/path 上处理。使用 `URLSearchParams`，拒绝重复 `code/state/error`、
   缺失 state、同时存在成功和错误结果等歧义输入。不要用 `split('&')/split('=')` 解析。
2. 读取当前 tab 的交易，核对 `state`、当前 `clientId`、固定 `redirectUri`、verifier 格式以及
   最长 10 分钟有效期（拒绝异常未来时间）。校验成功或确定失败后消费本地交易，禁止重复处理。
   用 `history.replaceState` 去掉回调中的 code/state/error，避免进入日志和后续 referrer。
3. 向 `${issuer}/oauth2/v1/token` POST `application/x-www-form-urlencoded`：
   `grant_type=authorization_code&code=...&code_verifier=...`。服务端除校验授权码与 PKCE 外，
   当请求体传入 `client_id` 或 `redirect_uri` 时也会与授权请求精确比对（不一致即拒绝），
   同时保留不传这两个可选字段的既有客户端兼容。客户端仍须完成本地 `state`/交易核验。
4. 用户 API 使用 Access Token（支持 `GET` 与 `POST` `${issuer}/oauth2/v1/userinfo`），不使用 ID Token 充当 bearer。
   `userinfo` 同时返回标准 `sub` 与兼容字段 `authId`，并在用户配置门户资料后透出 `nickname`、
   `preferred_username`、`signature`、`phone_number`；`id_token` 同步包含 `nickname` 与 `name`。
   不验证签名就 decode ID Token 不能建立可信业务会话。
5. 优先由应用后端/BFF 保存 refresh token 并建立安全 Cookie 会话；纯 SPA 至少避免把 token
   写入 URL、日志或任意第三方 storage。对 refresh 的并发、失败、退出和撤销建立明确状态机。
6. 退出需要区分应用自己的会话、refresh token 撤销与 NAccount SSO logout（Discovery 已暴露
   `end_session_endpoint`，`/oauth2/v1/logout` 会同时清理当前应用与跨应用主 SSO 会话并原样回传 `state`）。
   外部服务仅离线验 JWT 时，不能保证 NAccount 停用账号后它的既有会话立即失效。

新接入优先使用整页跳转/系统浏览器。不要直接搬运用户中心专用 `AuthDialog`：它绑定门户
storage key、profile API 与取消生命周期。若应用另做 popup，必须同时校验消息 `origin`、
`source`、state 和在途交易；上游 SDK 的 popup 路径未在本轮做完整安全加固或重新发布。

### 跨应用 SSO、回调大小写与自定义 Scheme 契约

- **跨应用共享主身份 SSO**：用户在任一 SPA 登录成功后建立受 `securityVersion` 与活动状态保护的主身份会话。切换到另一已登记 SPA 时，若新应用未开启独立强制 App-MFA，服务端会自动检查该应用的 `user_app_consent`（未授权跳 Consent 确认页，已授权直接签发该应用的授权码），无需重复输入密码；同时支持标准 OIDC `prompt=none` 静默探测与浏览器错误回跳。
- **回调大小写与自定义 Scheme**：DTO 规范化仅将 `redirect_uri` 的 scheme 与 host 转为小写，完整保留路径与查询参数大小写；前端 `parseRedirectUri` 除 `http(s)://` 外安全放行显式双斜杠原生应用回调（如 `midot://auth/callback`），严格拦截 `javascript:`/`data:`/`vbscript:` 等脚本伪协议。
- 回调自带查询参数、state 含保留字符时，普通页面完成与 SSO 直接返回均使用 URL 参数合并，
  不再拼接第二个 `?` 或把 state 中的 `&/#` 当成其他参数。

## 性能与前端拆包边界

- `/login` 无会话时在同一已验证请求中渲染，少一次跳转、一次 client/scope 校验；旧 OIDC 入口兼容保留。
- Access Token 和 ID Token 在同一请求复用一次签名材料 Promise；Bearer 验签单次导入 `CryptoKey` 并校核 `kid`；Google JWKS 证书采用 5 分钟进程内短缓存。不跨请求缓存用户权限或 `securityVersion`。
- 密码哈希升级为原生异步 WebCrypto `PBKDF2-SHA256`（存量 bcrypt 账号在登录成功后无感平滑升级），消除 Worker 同步 CPU 阻塞。
- 前端 Vite 客户端开启 ES Module 按需代码分割（`client.js` 入口按路径动态加载 `Account`、`Main` 与 `qrcode` chunk），并通过 `authRuntime.ts` 活动上下文兜底将 52 个上游表单 hook 还原为官方原版。
