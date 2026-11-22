# user-portal

NA-17（SBA 3.3.0，定制提交 `9ba7db9` / `13e7943`，generation `4f5b4874a029faf51cb5054866b5fdc37700b1a5fdfe5b0149ad914ef37217d8`）：
- **安全与缺陷闭环**：补齐找回密码重置、OAuth policy 改密/改邮箱/重置 MFA、后台停用用户的 `securityVersion` 递增即时撤销；个人中心仅换绑联系人手机号保持当前会话有效（`signInRequired: false`）；修复已注销原生社交账号重新登录撞唯一索引抛 500（返回明确 403 禁用错误），后台删号同步清理 `naccount_profile` 与社交标签；修复邮件空 `emailLogoUrl` 裂图、动态 `<html lang>`、内置无状态 `/favicon.svg` & `/favicon.ico`、OTP `issuer=NAccount` 与 Passkey `rpName`。
- **边缘性能与拆包**：密码哈希切换为原生异步 WebCrypto `PBKDF2-SHA256`（存量 `$2a$/$2b$` 登录无感平滑升级），24 位恢复码切换为 `SHA-256`；新增 SQLite `0051_naccount_optimization.sql`（瞬态表清理索引与应用目录元数据）；`DB.batch` 合并限流、并行发码、异步化过期清理与统计日志；单次 `CryptoKey` 公钥验签与 Google JWKS 5 分钟缓存；客户端 Vite ES Module 按需代码分割（`Account`、`Main`、`qrcode` 独立 chunk）。
- **OIDC 互通与个人中心闭环**：`GET/POST /oauth2/v1/userinfo` 补齐 `sub` 与 `naccount_profile` 字段，`id_token` 映射 `nickname`；跨应用主身份 SSO（`naccount-primary-sso`）按应用校验 Consent 与 App-MFA，支持 `prompt=none` 与携带 `state` 的全局退出；`/oauth2/v1/token` 校验可选 `client_id`/`redirect_uri`，`redirect_uri` 保留路径大小写，前端放行安全自定义 URI Scheme；个人中心支持 `zh`/`en` 双语切换、自助撤销应用授权、活跃设备会话管理、无验证邮箱社交账号绑定邮箱/注销解锁、Passkey 弹窗管理及跨标签页静默 SSO 恢复；通过 `authRuntime.ts` 活动上下文将 52 个上游 `use*Form` 文件还原至官方基线。

NA-14 将首屏资料与白名单社交状态合并为可选的 `GET /account/api/profile?include=social`，
健康首屏从两次串行 HTTP、2 KV + 6 D1 减为一次 HTTP、1 KV + 4 D1。复用同次已验证 actor，
不跨请求缓存权限或安全版本；默认资料 DTO 与 PATCH 不变。可选社交查询失败时省略字段，
客户端退回独立请求和真实错误展示。应用/社交视图离开后取消未完成 GET 并隔离迟到结果，
不取消或重放认证/发码写操作。151 项聚焦、完整 CF 3,149 项、类型检查与双构建通过；
新优化未上线，具体业务实测和交付边界见 `docs/USER_CENTER.md`、`docs/IMPLEMENTATION_PLAN.md`。

NA-10 后续补丁接入确认后的 Neuro 用户中心和 Beaver 标识、独立昵称/签名与应用列表、邮箱/联系人手机验证码绑定、密码修改、TOTP、自助注销及用户安全版本撤销。0049/0050 为对应 D1 迁移；新增认证语言协商，显式 locale 优先于浏览器 Accept-Language。发布为 SBA 3.2.0，不包含 provider 凭据配置。安全与验证边界见 `docs/USER_CENTER.md`、`docs/AUTHENTICATION_LOCALE.md`。

NA-09 普通用户入口与个人中心。范围与验收见 `docs/USER_CENTER.md`。

首个补丁新增认证服务 `/account` 与公开配置白名单，不开放管理员后台、不请求 S2S 权限。
注册直达既有注册视图；资料与安全操作复用现有 policy，认证使用独立 SPA client 与 PKCE。
`NACCOUNT_PORTAL_CLIENT_ID` 必须指向已登记精确 `AUTH_SERVER_URL/account` 回调的活动 SPA client。

验证：server TypeScript 检查、门户路由/认证/组件测试、既有 Main/SignIn 回归、客户端及 Worker 构建。
后续补丁实现 Google/GitHub 自助绑定、原 authId 登录解析、D1 唯一归属与一次性事务；绑定和解绑均要求已验证邮箱与当前密码。不按邮箱合并，不修改原角色，不删除最后一种密码登录方式。
新增 SQLite 0047/0048 迁移，SBA 3.1.0 自动维护独立 portal client 及精确回调；preview 隔离生产回调与 secrets。绑定写入仅支持 D1，PG 只提供身份表读取兼容迁移，未进行 PG 实例验证。
验证范围包括真实 SQLite、provider HTTP mock、Google RSA 签名校验、本地浏览器普通用户登录，以及既有 OAuth/注册回归。真实 Google/GitHub 授权与云发布尚未验收，不能用本补丁声明已上线。
