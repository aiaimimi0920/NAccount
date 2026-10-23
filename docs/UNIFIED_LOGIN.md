# 统一登录面板与应用接入

## 状态与范围

2026-10-24：本轮在 `melody-auth/naccount/main` 完成实现及本地验证；用户已授权提交、推送和通过 SpringBok 更新原实例，发布版本为 3.2.8。
旧生产入口保持兼容；新增 `/login` 必须在生产实例实际更新后使用，部署回执另行记录。
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
   `grant_type=authorization_code&code=...&code_verifier=...`。当前服务端绑定的是授权码中保存的
   client/redirect 与 PKCE；**当前 token handler 不另外校验请求体中的 client_id/redirect_uri**，
   不能靠多传这两个字段代替前述客户端交易校验。超时/失败展示明确结果，不自动重放兑换。
4. 用户 API 使用 Access Token，不使用 ID Token 充当 bearer。可请求
   `${issuer}/oauth2/v1/userinfo` 做在线身份/撤销检查；当前 DTO 使用 `authId`，不要假定返回 `sub`。
   不验证签名就 decode ID Token 不能建立可信业务会话。
5. 优先由应用后端/BFF 保存 refresh token 并建立安全 Cookie 会话；纯 SPA 至少避免把 token
   写入 URL、日志或任意第三方 storage。对 refresh 的并发、失败、退出和撤销建立明确状态机。
6. 退出需要区分应用自己的会话、refresh token 撤销与 NAccount 当前 client 的 SSO logout。
   外部服务仅离线验 JWT 时，不能保证 NAccount 停用账号后它的既有会话立即失效。

新接入优先使用整页跳转/系统浏览器。不要直接搬运用户中心专用 `AuthDialog`：它绑定门户
storage key、profile API 与取消生命周期。若应用另做 popup，必须同时校验消息 `origin`、
`source`、state 和在途交易；上游 SDK 的 popup 路径未在本轮做完整安全加固或重新发布。

### 现有兼容限制

- 现有 DTO 会把回调 URI 整体转小写，注册存储也有自身规范化；本轮没有改动这项旧协议。
  不应登记大小写敏感 path/query 并期望原字节保持，应单独迁移并回归后再扩展。
- 注册数据库中的相对 URI/custom scheme 不会仅因新增“显示返回地址”而变成 500；但完整浏览器
  认证完成路径只接受现有 HTTP(S) 回调，这不是新增 native scheme 支持。
- 回调自带查询参数、state 含保留字符时，普通页面完成与 SSO 直接返回均使用 URL 参数合并，
  不再拼接第二个 `?` 或把 state 中的 `&/#` 当成其他参数。

## 本轮性能处理与保留边界

- `/login` 无会话时在同一已验证请求中渲染，少一次跳转、一次 client/scope 校验；旧 OIDC 入口兼容保留。
- Access Token 和 ID Token 在同一请求复用一次签名材料 Promise；私钥、公钥各读取一次，
  私钥导入与公钥转换各一次。下一请求仍重新读 KV，失败不在同请求内自动重试；不缓存用户权限。
- JWKS 的 current/deprecated key 读取并行，输出顺序保持 current-first，缺当前密钥仍失败关闭。
- 默认认证字体改用本地 system-ui，不依赖 Google Fonts stylesheet；组织显式自定义字体保留。
- process/verify-email/expired 页面复用本请求已解析的 branding，不再为 HTML 再读一次组织。
- 认证 HTML 使用 `Cache-Control: no-store` 与 `Referrer-Policy: no-referrer`。

没有放宽 MFA、限流、密码验证、回调白名单或撤销语义；没有跨请求缓存 JWKS/账号/权限，
没有修改生产网络、DNS、Cloudflare 策略、provider 或邮件投递。前端当前仍是共享大 bundle，
本轮不冒险同时重构 Worker/Node 静态资产与 AuthDialog 异步生命周期。
