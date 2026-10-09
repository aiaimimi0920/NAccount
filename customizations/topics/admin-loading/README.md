# 后台角色刷新与有界配置加载

刷新访问令牌时从当前有效用户角色生成 claims，不复用 refresh token 创建时的旧角色快照。
新增和撤销角色在下一次刷新生效；已有访问令牌仍遵守自身有效期，不承诺即时撤销全部会话。

后台配置加载限定 15 秒，令牌/网络错误或非法响应结束等待并显示重试、退出入口。
超时中止 fetch，卸载、退出和重试后的旧响应不可覆盖当前配置；不自动重试、不绕过 API 权限。

回归入口：server 的 oauth.test.ts，admin-panel 的 Setup.test.tsx、useAdminConfig.test.tsx。
