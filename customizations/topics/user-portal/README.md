# user-portal

NA-09 普通用户入口与个人中心。范围与验收见 `docs/USER_CENTER.md`。

首个补丁新增认证服务 `/account` 与公开配置白名单，不开放管理员后台、不请求 S2S 权限。
注册直达既有注册视图；资料与安全操作复用现有 policy，认证使用独立 SPA client 与 PKCE。
`NACCOUNT_PORTAL_CLIENT_ID` 必须指向已登记精确 `AUTH_SERVER_URL/account` 回调的活动 SPA client。

验证：server TypeScript 检查、门户路由/认证/组件测试、既有 Main/SignIn 回归、客户端及 Worker 构建。
Google/GitHub 自助绑定、身份归一和 SBA 配置尚未实现，不能用本补丁声明这些能力已上线。
