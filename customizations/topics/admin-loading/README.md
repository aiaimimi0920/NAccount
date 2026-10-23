# 后台角色刷新与有界配置加载

刷新访问令牌时从当前有效用户角色生成 claims，不复用 refresh token 创建时的旧角色快照。
新增和撤销角色在下一次刷新生效；已有访问令牌仍遵守自身有效期，不承诺即时撤销全部会话。

后台配置加载限定 15 秒，令牌/网络错误或非法响应结束等待并显示重试、退出入口。
超时中止 fetch，卸载、退出和重试后的旧响应不可覆盖当前配置；不自动重试、不绕过 API 权限。

回归入口：server 的 oauth.test.ts，admin-panel 的 Setup.test.tsx、useAdminConfig.test.tsx。

NA-15 在既有加载/权限行为之上统一管理后台 Neuro 语义主题与弹窗交互，保留组织字段、
风险提示、错误/禁用状态；支持窄屏内滚动、Escape 取消及焦点恢复，重发邀请提交中不允许取消。
认证页共用同值主题并保留组织显式 branding，同一次 authorize 请求复用已解析 branding，
不跨请求缓存身份或权限。保护测试覆盖共享 alert-dialog、邀请弹窗和 Layout/authorize。
