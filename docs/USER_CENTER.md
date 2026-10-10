# NA-09：普通用户入口、个人中心与社交身份绑定

## NA-12：用户中心内登录/注册（3.2.4 已发布）

用户中心的登录、注册入口现在打开原生模态弹窗，背景保留 Beaver 顶栏和当前用户中心页面，
未登录时不展示私有资料。登录、注册、忘记密码和后续验证码/MFA 复用现有认证组件与服务器，
不使用 iframe，也不将密码转交给新的自建认证接口。样式在弹窗内映射到 Neuro 深色令牌，
独立授权页不受此局部样式影响。

弹窗通过完整验证后的 authorize-view JSON 表示读取公开功能开关与服务器协商语言，
内部 URL 由单个认证上下文保存，界面切换不修改 `/account` 地址或增加浏览器历史。
外部社交授权仍按平台要求离开本站并返回原 callback；不能据此声称已配置真实 provider。
完成后执行现有 state/PKCE/token/profile 链，再收起弹窗显示真实账户资料。
支持 Escape、焦点恢复和背景滚动锁定。关闭时使当前流程失效，迟到响应不能恢复认证界面、
跳转或保存 refresh token；未成功取得资料的流程在关闭时清理本地会话。

本地 661 项认证/UI 测试、110 项仓库/部署测试、TypeScript 和双构建通过，已检查宽/窄屏真实 UI。
PR #17 与 main CI 通过，v3.2.4 经 SpringBok 同实例升级上线，备份/原行保全检查和独立可用性
verify 通过。线上已核对登录/注册/重置密码弹窗和中文样式；新弹窗完整账号登录/MFA 等待用户
自行验证，真实验证码投递及外部 OAuth 本轮尚未验收。任务与证据见实施计划 NA-12。

## 发布状态（2026-10-10 UTC）

完整用户中心已随 3.2.1 业务补丁发布；3.2.2 仅修复部署校验并从 SpringBok 完成只读收尾，
业务回执 succeeded。用户确认登录成功；真实浏览器核对账户名片与已授权/全部应用列表正常加载。
本次没有替用户修改密码、绑定身份、启停 MFA 或删除账号。Google/GitHub 仍未配置；
真实邮件/短信投递、外部 OAuth 和安全变更业务验收不能以部署成功代替。
具体任务、版本与证据见 [实施计划](IMPLEMENTATION_PLAN.md#na-10-readiness322-发布与只读收尾完成2026-10-10-utc)。

## NA-10-S02/S03：完整自助安全流程（已发布）

此节为最新实现；下方 S01 和 NA-09 保留历史阶段证据，不覆盖当前状态。

### 页面与接口

- 已将密码/邮箱的 OAuth policy 跳转，以及手机/注销的未开放占位，替换为正式二级弹窗。
  `SecurityDialog.tsx` 通过 `GET /account/api/security` 读取真实能力，使用
  `POST /account/api/security/start` 和 `/complete` 完成限时、一次性身份验证和修改。
- 邮箱/独立联系人手机：输入新目标，核验当前身份，发送验证码；只有验证码验证和事务
  成功后才换绑。不使用演示码、不在发送时预先修改。邮箱规范化，手机要求 E.164。
  联系人号码保存到 `naccount_profile.phone`，不复用或改动 `user.smsPhoneNumber` 的 SMS MFA。
- 密码：当前密码复核、新密码强度和双次输入确认；服务端只存新密码 hash。
  成功后清门户会话，必须重新登录，不继续拿旧 access token 假装可用。
- TOTP：当前身份复核、真实 QR/密钥、验证码确认。启用成功写入 secret、verified 和
  `mfaTypes`；禁用须证明现有 TOTP，且不能绕过系统/应用强制 MFA 或唯一必需因素。
  开启 `ENABLE_RECOVERY_CODE` 时提供现有合同的一枚 24 字符恢复码，保存确认后才启用；
  未开启时不显示假恢复码，不宣称能通过恢复码登录。不是原型的多枚演示码。
- 注销：红色风险确认和“删除账户”文字复核；服务端限制当前本人，禁止代登录 token，
  保留最后一名活动超级管理员。事务清除个人资料、密码/MFA、邀请凭据、Passkey、属性、
  组织关系和应用授权；用户保留禁用 tombstone、既有社交身份占用和必要安全日志，
  不是物理擦除全部审计记录。页面准确说明此边界。

### 安全与数据合同

- SQLite `0050_naccount_security.sql` 新增用户 `securityVersion`、请求和限流表、TOTP
  消费唯一约束。请求绑定当前用户、版本和随机 token hash，10 分钟有效，最多 5 次校验。
  验证码存逐请求盐化摘要；发送失败不准备可提交事务，不改变用户资料。
- D1 原子计数实施用户、目标、IP 上限与 30 秒发送冷却；不是 KV get/put 冒充原子限流。
  新安全 API 的 TOTP 消费以 `(userId,secretHash,step)` 唯一约束防并发重放；不宣称
  既有所有登录 TOTP 路径的 KV 防重放已一并改造成 D1。
- SQL trigger 在同一事务中验证原始安全状态、检查目标碰撞和最后管理员、执行修改并
  递增安全版本。旧密码、邮箱/手机验证状态、SMS 目标、OTP、MFA、恢复 hash 或配置变化
  均拒绝继续；同请求/同旧版本并发不能双成功。提交时清掉本人的待处理证明材料。
- 用户 access JWT、refresh、SSO、已 secured 的授权码、普通/embedded MFA 入口和
  remembered-device 都核对证明时的用户版本，不把旧快照升级成新版本。
  社交登录不能绕过用户已启用的本地 MFA。后台活动会话列表过滤旧版本凭据。
  S2S token 明确区分 service，不要求存在同名用户。
- 即时撤销保证覆盖 NAccount 自己的验证/签发入口；外部应用仅离线验 JWT 时仍需其自行
  做短时 token、服务端在线校验或会话撤销，不能据本项目声称外部离线会话即时全部失效。
- 清理过期请求/限流/TOTP 消费记录为后续安全请求触发的惰性清理，不声称存在定时清理服务。

### 配置、验证与交付边界

- 本接口仅 D1；PG 保持失败关闭。邮箱需要当前选中的真实邮件 provider 配置；手机需要
  Twilio account/auth token/sender，未配置会返回不可用，不伪造发送成功。
  系统/portal 应用强制的 OTP、邮箱及 SMS MFA 与个人 enrollment 一并核验。
  无本地密码时可使用当前已验证邮箱证明，仍须继续所有要求的 MFA；无可用证明则拒绝。
  既有原生社交主账号不通过本接口转换为本地密码登录账号；它仍用第三方登录，密码动作
  明确不可用。普通注册账号绑定 Google/GitHub 不受此限制。
- 完整验证运行于 `linshi/naccount-user-center-20261009/source/server`；发送测试使用显式
  provider mock，未发送真实邮件/短信。SAML 使用该隔离目录内新生成的一天有效测试证书。
  结果见 `security-full-regression.log`、`security-typecheck.log`、`security-build.log`。
- 最终 `npm run test:check:cf`：148 个文件、3072 项全部通过（标准脚本排除独立 key-rotate
  套件）；TypeScript、客户端/Worker build、两仓库 `git diff --check` 通过。
  57 个业务变更文件与测试/浏览器副本逐字节一致且无 BOM，见 `security-verification.json`。
  测试日志仍有 jsdom 导航未实现提示和工具弃用告警，退出码为 0；不把这些日志称为真实浏览器导航验收。
- 本地浏览器入口仍为 `http://localhost:4888/account`，使用原合成 fixture 和本地 D1；
  密码/TOTP/注销弹窗均为正式源码。浏览器未提交凭据变更或注销，写入和失败分支由接口测试覆盖。
  浏览器已核对密码字段、注销危险确认、Escape 后焦点恢复；390px 视口 document scrollWidth
  为 375px，没有横向溢出。截图 `security-password-dialog.jpg` 和 `security-delete-mobile.jpg`。
  本地没有配置 OAuth、邮件及短信 provider，不能据此当作真实外部投递/授权验收。
- 未创建本轮定制提交、未 export 新 generation、未推送、未升级线上；既有生成补丁不含本轮修改。
  后续发布前按仓库规则取得本轮提交/导出及部署授权，再验证正式升级和真实 provider。

## NA-10-S01：确认后的 Neuro 用户中心（2026-10-09，本地实现）

本节是 S01 历史阶段记录，完整流程接续实现见上方 S02/S03；当时仅开发与本地验证，未发布。

- 正式源码在 `melody-auth/server/src/pages/account/`，不是继续修改独立 HTML。
  Beaver SVG 原样来自本地 Beaver 品牌资源；520px 名片/应用卡片、无侧栏、图标菜单、
  原位编辑与语义控件颜色按已确认设计接入。没有复制预览用户 ID、等级、验证码或演示身份。
- `GET/PATCH /account/api/profile` 使用门户专用 client、profile scope、活动用户检查。
  DTO 白名单不含 password、OTP secret 或恢复码。SQLite `0049_naccount_profile.sql`
  独立保存昵称（40 字符上限）与签名（120），不覆盖 firstName/lastName。PATCH 只允许
  一个字段，拒绝身份字段、控制字符、越界和大包，尊重 blocked update_info；成功回执后才更新 UI。
  目前沿用 D1-only actor；PG 不支持本接口，不宣称 PG 已验证。
- `GET /account/api/apps` 返回当前用户自己的有效 SPA consent，加显式
  `NACCOUNT_PUBLIC_APP_IDS` 字符串数组中登记的活动 SPA。未配置数组时不枚举其他应用。
  自己已授权的内部 SPA 可见，不代表向其他用户公开；S2S、已删除/停用应用、门户自身不返回。
  输出仅 clientId/name/authorized，不返回 client secret 或 redirect URI；不把 consent 当登录历史，
  不提供未实现的撤销会话或应用跳转功能。
- Google/GitHub 保持真实后端绑定合同，当前密码移到二级弹窗，解绑用应用内红色确认，
  不再调用 `window.confirm`。缺 provider 配置或身份条件不足时禁用；取消不发写请求，失败清空密码。
- 密码、邮箱换绑、MFA/恢复码/Passkey 仍复用受保护 OAuth policy，不降低验证要求。
  页面使用“管理两步验证”，不把 reset_mfa 冒充启用/禁用。手机号与注销入口只显示未开放状态，
  不发后台写请求。原型中的完整验证码弹窗、TOTP 三步启停、自助注销尚未实现。

### 本地验证与边界

运行目录 `linshi/naccount-user-center-20261009/source/server`：TypeScript、10 文件 161 项
Vitest（门户、资料 API、社交后端、既有 Main/SignIn）与客户端/Worker 构建通过。
`na10-tests.log`、`na10-build.log` 为本轮 UTF-8 证据。依赖复用锁文件匹配的缓存，未新安装。
新增资料/目录 22 项测试覆盖真实 SQLite 迁移、独立用户数据、长度/身份字段/控制字符拒绝、
client/scope/停用用户/blocked policy/PG 拒绝、目录隐私和响应白名单。

浏览器副本 `linshi/naccount-user-center-20261009/browser` 仅本地新增 0049 表，保留原 fixture。
`http://localhost:4888/account` 使用真实 Worker 开发入口和合成测试账号，通过 PKCE 登录、
昵称签名保存、刷新持久化、应用分类、弹窗关闭和焦点恢复、退出后重新登录，390px 窄屏无横向溢出。
浏览器样式引擎已检查选中/未选中 tab 的 hover 配色；没有使用线上账号或 provider。
开发服务器已修复 Hono 拦截 Vite SVG import 导致 404 的问题。

新业务代码仍是 `naccount/main` 工作区修改；未创建定制提交或导出新 generation，
不能用旧补丁部署此页面。真实邮件/短信、provider 授权、生产升级及完整安全流程仍需后续验收。

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
