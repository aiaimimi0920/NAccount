# NA-09：普通用户入口、个人中心与社交身份绑定

负责人：主 AI。状态：开发中，未发布、未进行云端写入。

## 验收边界

- NA-09-S01：在认证服务的 `/account` 提供普通用户入口，不依赖管理员后台或管理员权限。使用独立 SPA client、Authorization Code + PKCE，登录后展示当前用户资料并接入既有资料/安全 policy。第一阶段使用现有认证域名，不新增域名、Worker 或公开管理员后台。
- NA-09-S02：登录用户主动绑定第三方身份；第一批已由用户确认为 Google/GitHub。绑定必须同时证明本地账号与第三方身份的控制权，并绑定短期、一次性 state/nonce；不能按邮箱自动合并。第三方身份唯一归属一个本地账号，冲突拒绝，重复回调不重放。
- NA-09-S03：绑定后第三方登录返回原账号的 authId 和权限，不创建平行业务账号。不继承第三方独立账号的管理员权限，不通过开放 S2S 管理接口完成自助绑定。解绑不能删除最后一种可用登录方式。
- NA-09-S04：补丁导出、独立门户 client 的 SBA 配置/更新、隔离构建及浏览器回归。真实发布、OAuth 应用配置及用户验收另记。

## 已核实的基础

源码已有注册、邮箱验证与修改个人资料/密码/邮箱/MFA/Passkey policy。管理员后台的 account 页面不是普通用户入口。
既有 `linkedAuthId` 是两个独立用户之间的关联，userinfo 仍返回原 authId 和 linkedAccount；不能直接当作多个社交身份登录同一个账号的实现。

## 配置与安全

门户的 `NACCOUNT_PORTAL_CLIENT_ID` 是公开的独立 SPA client ID，不是管理员 client，也不是 secret。回调为 `AUTH_SERVER_URL/account`，客户端必须启用且登记精确回调；缺配置时返回明确不可用状态，不猜测管理员 client。
门户只请求 openid/profile/offline_access；没有 S2S secret，不调用管理员 API。令牌与 PKCE 状态使用门户独立命名空间的 sessionStorage，access token 仅保留在内存中。
Gmail 管理员资料不等于 Google OAuth 应用；未完成第三方应用配置时，不能宣称社交登录已启用。

## 非目标

不重建数据库、不重置管理员密码、不改 Cloudflare Access，不自动合并历史账号，不新增付费/会员/运营模块。
本文件及开发计划记录实际完成边界；后续不以单元测试或构建成功替代真实第三方授权、邮件和用户验收。

## NA-09-S01 本地证据（2026-10-09）

已实现 `/account` 页面及严格白名单的 `/account/config`，注册按钮直达现有注册视图，普通登录与资料/安全操作复用既有 OAuth/policy。个人中心只读取 userinfo，不使用管理员角色。配置缺失、已停用、S2S client 或回调不匹配时拒绝启用。

浏览器事务使用独立命名空间、随机 state、S256 PKCE、十分钟时限和单次消费；拒绝重复/缺失参数、跨 client 与损坏状态，回调失败也清除授权 URL，不回退成另一个账号。刷新凭据与 portal client 绑定；请求十五秒超时，错误不回显服务端原始内容，退出不相信服务端返回的外部跳转地址。

隔离目录 `C:/Users/Public/nas_home/AI/GameEditor/linshi/naccount-user-center-20261009/source/server`：
- `npm run type:check` 通过。
- 主仓库 `python -m unittest discover -s tests -v`：95/95 通过，包含补丁精确恢复/重放与既有 SBA 编排回归；不是云端部署测试。
- `vitest run src/pages/account src/routes/account.test.ts src/pages/Main.test.tsx src/pages/blocks/SignIn.test.tsx`：107/107 通过（40 项新增门户测试、67 项现有登录视图回归）。
- `npm run build`：客户端与 Worker 构建通过。后续仅新增测试，产品源码未变化。
- 使用 SHA-256 相同的 server/package-lock.json 对应既有依赖缓存；不是 fresh npm install、依赖安全扫描或完整应用测试。

未完成：SBA 自动创建/维护独立 portal client、Google/GitHub 绑定与统一身份登录、浏览器真实 OAuth/邮件验收、云端发布。界面不展示未实现的社交绑定按钮，不改变既有管理员后台和权限。

用户已明确允许本地定制提交与补丁导出；此授权不包括 GitHub 推送或真实部署。SpringBok 本轮无代码及 SBA 合同改动，因此其 ai-docs/pages 无协议同步改动；后续变更部署合同需要重新评估。

已创建定制提交 `2774512cf4eb50bd0a51120e5d896dab425cd2ee`，带 `NAccount-Patch-Topic: user-portal`。
`naccount.ps1 export` 与 `verify` 均通过；新 generation 为 `d88c6ec5846ec3eb31b978dc6560ff0a22b8c724e1cf7d7647a1bddcf8a31ebb`，补丁栈共 3 项，既有 generation 未删除。
