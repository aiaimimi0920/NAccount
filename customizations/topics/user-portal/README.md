# user-portal

NA-09 普通用户入口与个人中心。范围与验收见 `docs/USER_CENTER.md`。

首个补丁新增认证服务 `/account` 与公开配置白名单，不开放管理员后台、不请求 S2S 权限。
注册直达既有注册视图；资料与安全操作复用现有 policy，认证使用独立 SPA client 与 PKCE。
`NACCOUNT_PORTAL_CLIENT_ID` 必须指向已登记精确 `AUTH_SERVER_URL/account` 回调的活动 SPA client。

验证：server TypeScript 检查、门户路由/认证/组件测试、既有 Main/SignIn 回归、客户端及 Worker 构建。
后续补丁实现 Google/GitHub 自助绑定、原 authId 登录解析、D1 唯一归属与一次性事务；绑定和解绑均要求已验证邮箱与当前密码。不按邮箱合并，不修改原角色，不删除最后一种密码登录方式。
新增 SQLite 0047/0048 迁移，SBA 3.1.0 自动维护独立 portal client 及精确回调；preview 隔离生产回调与 secrets。绑定写入仅支持 D1，PG 只提供身份表读取兼容迁移，未进行 PG 实例验证。
验证范围包括真实 SQLite、provider HTTP mock、Google RSA 签名校验、本地浏览器普通用户登录，以及既有 OAuth/注册回归。真实 Google/GitHub 授权与云发布尚未验收，不能用本补丁声明已上线。
