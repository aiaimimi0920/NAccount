# NA-09：普通用户入口、个人中心与社交身份绑定

负责人：主 AI。状态：普通用户门户、Google/GitHub 自助绑定与部署集成本地实现完成，未发布、未进行云端写入。

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

本阶段当时未完成的 SBA client、社交绑定与统一身份登录，已由下述 S02/S03/S04 实现；此处 107/95 项与旧提交/generation 保留为 S01 历史证据，不代替当前版本证据。

用户已明确允许本地定制提交与补丁导出；此授权不包括 GitHub 推送或真实部署。SpringBok 本轮无代码及 SBA 合同改动，因此其 ai-docs/pages 无协议同步改动；后续变更部署合同需要重新评估。

已创建定制提交 `2774512cf4eb50bd0a51120e5d896dab425cd2ee`，带 `NAccount-Patch-Topic: user-portal`。
`naccount.ps1 export` 与 `verify` 均通过；新 generation 为 `d88c6ec5846ec3eb31b978dc6560ff0a22b8c724e1cf7d7647a1bddcf8a31ebb`，补丁栈共 3 项，既有 generation 未删除。

## NA-09-S02/S03/S04 本地交付（2026-10-09）

- 个人中心提供 Google/GitHub 状态、绑定与解绑。需要活动本地账号、已验证邮箱与当前密码；复用登录失败锁定机制。不支持无密码的原生社交账号自助绑定管理，不伪装成所有账号都支持。
- 绑定事务有效期五分钟，包含一次性 state、浏览器 HttpOnly/Secure cookie 绑定、PKCE 和 Google nonce；D1 原子消费后才换取 provider 身份。验证期间账号停用、删除、密码变化或 client 停用均拒绝。
- Google 校验签名、issuer、aud/azp、nonce、sub、时间与已验证邮箱；GitHub 使用 provider 数字 ID，不依据邮箱归并。provider token 不持久化。
- 社交登录先解析绑定表，返回原账号 authId、邮箱和角色；不创建第二账号、不转移管理员权限。停用/已删除 owner 不会回退注册。
- 数据库同时防止绑定与原生社交身份冲突，包含已删除身份；解绑保留密码和原生主身份。SQLite 0047 新唯一索引遇到历史重复主体会失败关闭，发布前必须备份并检查，不自动合并或选赢家。
- 绑定写入仅支持 Cloudflare D1；PG 附带身份读取表迁移，但本轮未运行 PG 实例，不能宣称 PG 绑定支持。
- SQLite 0048 创建固定公开 client `naccount-user-portal`，仅授予 openid/profile/offline_access。SBA 3.1.0 在认证发布前配置精确 `/account` 回调，正常部署不会偷偷恢复已停用 client；preview 仅恢复隔离副本并改为 preview 回调，清除生产 secretNames。admin-only repair 不执行本配置写入或迁移。

### 验证

隔离源码与运行产物：`linshi/naccount-user-center-20261009/`。

- 主仓库 `python -m unittest discover -s tests -v`：100/100 通过（含部署子套件 84 项，不重复累加）。
- 门户/社交聚焦及既有 provider Vitest：221/221（包括先前 146 项，不重复累加）；Google proof 使用本地真实 RSA 签名，外部 provider HTTP 是 mock。
- OAuth、JWT、identity-main 注册/密码登录/退出等扩展回归：181/181。
- TypeScript、客户端与 Worker 构建通过。依赖使用相同 lockfile 的既有缓存，不是新安装或依赖漏洞审计。
- 本地真实浏览器：注册入口进入注册页；合成普通用户完成密码登录及 PKCE 回调，显示资料、打开修改资料 policy，Google/GitHub 未配置按钮禁用；退出后回到登录/注册入口。注册提交由后端回归覆盖，不等于浏览器注册或真实邮件验证。
- 未验：真实 Google/GitHub 授权往返、真实邮箱投递、PG 运行、线上升级和最终用户验收。

### OAuth 配置

Gmail 管理员资源不提供 OAuth client。需要在两个平台分别创建应用；当前认证域名对应配置如下（仅为未来发布说明，本轮未写云）：

| 平台 | 公开 Worker vars | Worker secret | 精确 callback |
| --- | --- | --- | --- |
| Google | `GOOGLE_AUTH_CLIENT_ID` | `GOOGLE_AUTH_CLIENT_SECRET` | `https://naccount-auth.aiaimimi.com/account/social/google/callback` |
| GitHub | `GITHUB_AUTH_CLIENT_ID`、`GITHUB_AUTH_APP_NAME` | `GITHUB_AUTH_CLIENT_SECRET` | `https://naccount-auth.aiaimimi.com/identity/v1/authorize-github` |

Google 同时配置 JavaScript origin `https://naccount-auth.aiaimimi.com`，用于既有 GIS 登录；绑定采用服务端 code exchange。preview 需要独立的 OAuth 应用配置，不复用生产秘密。

SpringBok 当前只接收声明中的 Cloudflare/管理员初始化 secrets，没有通用 optional OAuth secret 输入/传递合同。本轮保持平台合同不变：公开参数放部署 vars，秘密由管理员单独配置到认证 Worker，或使用 standalone `.sba/deploy.ps1` 的 `server.secretNames` 和受控进程环境。不得把 secret 放公开 vars、JSON、日志或仓库，也不得为绕过平台校验擅加 manifest secret。实际部署后必须再验证秘密配置与真实授权。

官方协议核实：2026-10-09 获取 Google OpenID Connect 与 GitHub OAuth Apps 授权文档，确认 code exchange、精确 redirect_uri 与 GitHub S256 PKCE 支持。单元测试不代替这些应用在真实平台上的注册与启用。

### 本地补丁交付

定制源码提交：`eaa8557390f6ba6d54e5a7cda27b27c1593e17a7`，trailer `NAccount-Patch-Topic: user-portal`。
`naccount.ps1 export`、`verify` 均通过，当前 generation：
`32c8c23027721a42d483795e2e87967c3f0f8ab673818beaf41c52be8750a33b`，补丁栈共 4 项。
退出后再次密码登录已在本地浏览器验证；截图 `linshi/naccount-user-center-20261009/portal-local.jpg` 使用合成测试账号，无线上用户数据。
未推送 GitHub、未发布 3.1.0、未创建/修改 OAuth 应用或 Cloudflare 资源。
