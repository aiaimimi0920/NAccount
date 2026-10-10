# 初始工程落地范围

## NA-10-READINESS：3.2.2 只读收尾（进行中）

负责人：主 AI。边界为修复发布后 assets 校验误报，通过 SpringBok 正式 repair
只读核验已发布实例；不重做迁移、构建、Worker 发布、初始化或密码修改。
3.2.1 已由 PR #12 合并并发布，main `ee09fb42efddcf1f96d1a84206ceeec578546c07` 检查通过。
修复任务 `dc-9595995db7764b0e88462de04d63b56d` / run `38021757950` 返回
`unknown / NACCOUNT_READINESS_FAILED`。只读实证 0050 及安全触发器已存在，双端均发布新版本，
OIDC/JWKS 通过；认证端仅声明 assets.directory，不声明 ASSETS binding，旧校验误套后台要求。
修正后真实 published 配置核验通过。新增 readiness-only 固定该父任务、源码 generation
及双 Worker version；保全检查仅覆盖新的只读区间，不追认旧回执或历史数据保全。
3.2.2 与 3.2.1 业务补丁完全相同，仅部署校验变化；正式云端收尾及用户登录验收待完成。
本地完整主仓库 110 项测试、补丁 verify 与 diff 检查通过；独立只读审阅未发现新阻断。

## NA-10-REPAIR：3.2.1 远程迁移修复（进行中）

3.2.0 已由 PR #11 合并并发布，main `a8621252ab167e70f4abae6896cc7458faf17235` 检查通过。
SpringBok update `dc-2e367ed28ec944c1943b58fa695ff40e` / run `38019349330` 失败为
`NACCOUNT_SERVER_PUBLISH_COMMAND_CF_7500`，GitHub 执行器绿色不代表应用升级成功。
云端只读核对：0049 已执行、0050 未生效，两个 Worker 均保持 3.1.0 发布版本。
远程 EXPLAIN 复现旧 trigger 的内层 `END;` 分句失败；等价 RAISE/WHERE 修正编译通过，零行写入。
源码提交 `e070108ab9ab93e6bd45dca4059c47a2f192fb7b`；59 项安全/资料/弹窗回归通过。
新增应用自有的 security-migration repair，使用 SpringBok 原生父子任务/permit/回执机制，
只接受固定失败版本与只缺0050的现场。真实只读 preflight 通过；90 项 SBA 测试通过。
只读审阅发现 portal callback 额外值可能被 publish 改写，已改为精确预检和发布只读模式，补拒绝测试。
该修复已执行，但收尾校验失败，最新现场及接续方案见上；原失败记录不修改、不清锁、不 rerun。

## NA-10-RELEASE：3.2.0 发布（进行中）

负责人：主 AI。用户已授权提交推送 GitHub，并通过 SpringBok 更新现有实例。
范围包括 NA-10 用户中心、安全流程与中文认证，不重建数据库、不初始化管理员、不改密码。
迁移 0049/0050 为新增表、列、索引与触发器；由既有 update 流程导出备份并校验旧行保全。
只读发布审阅未发现新版本安全/功能阻断；旧 S2S token 需重新签发，真实 provider 仍须配置。
精确源码全量回归 148 文件 / 3084 项通过，TypeScript 与客户端/Worker 构建通过；主仓库
100 项及版本调整后 SBA 子套件 84 项通过。定制提交 `858eccd4add4bc3873f4835cf9d21d54b543094c`，
导出 generation `91f42ab6b29e379353b79bf907cdb529fdea06f5b8e1bbadbaf8e882c5def88b`，verify 通过。
新增语言覆盖后重新全量复验，同步系统信息测试的中文配置预期，不改变业务断言。
GitHub CI、合并和线上执行结果随后记录；发布前 SpringBok 确认现有实例为 3.1.0。
以下“未发布”段落为各开发阶段的历史状态，最终交付以本节及发布记录为准。

## NA-10-S02/S03：用户中心完整安全流程（本地开发与验证完成，未发布）

负责人：主 AI。补齐已确认的邮箱/独立手机验证码绑定、密码修改、TOTP 三步启用/禁用、
自助注销；使用真实发送适配器和 D1 限时事务，禁止演示码与管理员接口代办。
同时完成安全变更后旧 access/refresh/SSO/auth-code 的用户级失效及安全回归。
本轮仅本地代码和隔离验证，不读取生产秘密，不执行生产数据删除或上线。
已接入完整二级弹窗、D1 一次性事务、发送适配器、身份复核和全用户安全版本撤销。
审阅补齐系统/应用强制 MFA、证明目标变化及配置变化的拒绝；保留最后超级管理员。
最新验证、能力配置和未发布边界见 [USER_CENTER.md](USER_CENTER.md) 的 S02/S03 记录。
标准 Cloudflare 套件 148 文件 / 3072 项全部通过，TypeScript、客户端/Worker 构建和
git diff --check 通过；57 个业务变更文件与测试/浏览器副本逐字节一致、无 BOM。
本地 D1 迁移和真实浏览器弹窗/390px/焦点恢复已验证。下一步为本轮授权后的补丁交付，
以及真实外部 provider 配置/投递、生产升级和用户验收，不再将这些称为未实现的安全接口。

## NA-10-S01：已确认用户中心设计接入（本地实现，未发布）

负责人：主 AI。将本地确认的 Neuro 名片/应用卡片设计迁移到正式 `/account`，
保留 Beaver 标识、紧凑布局、独立用户菜单和已修复的 tab 状态。
本子任务接入真实资料读写、社交管理与已有安全 policy，不使用演示验证码或假成功。
同时核查手机号、MFA、账户删除与应用目录的权限/数据边界；缺少安全接口的动作
不得用本地状态模拟完成。只做本地开发与验证，不推送或生产部署。
已完成名片/应用列表、昵称签名独立存储、社交二级弹窗、真实状态与安全 policy 入口。
TypeScript、161 项聚焦回归及客户端/Worker 构建通过；真实本地浏览器已验证
PKCE 登录、昵称签名写库及刷新保留。详见 [USER_CENTER.md](USER_CENTER.md) 的 NA-10 记录。
未提交、未导出新补丁、未推送或部署；生成补丁仍为上轮版本，不可据此发布新界面。
S01 当时未完成的独立绑定、两步验证启停及注销，已由上方 S02/S03 接续实现；
这里的 161 项和 policy 桥接仅为历史阶段证据，不代表最新完整功能实现。

## NA-09-S02/S03/S04：社交绑定、统一身份与部署集成（本地实现与验证完成，未发布）

负责人主 AI。仅本地开发、验证、提交与导出；无推送/云写授权。
Google/GitHub 使用独立的一次性绑定事务，登录账号确认密码后发起第三方授权；回调同时校验
随机 state、浏览器绑定、PKCE/nonce 和原账号仍有效。社交身份唯一归属，禁止邮箱合并。
已绑定登录解析回原 user/authId；数据库约束覆盖并发绑定与独立社交注册冲突。
部署集成负责独立 portal SPA client、provider 公开参数与 preview 隔离，保留 admin-only repair 边界。
SpringBok 当前没有 optional provider secret 合同，不能在 manifest 中擅加必填秘密；真实启用需单独配置认证 Worker secrets，或使用 standalone CLI 的 secretNames。配置清单、验证证据与限制见 [USER_CENTER.md](USER_CENTER.md)。
主仓库标准测试 100/100、部署子套件 84/84、门户/社交及既有 provider 回归 221/221、既有认证扩展回归 181/181 通过，TypeScript 与客户端/Worker 构建通过。浏览器验证普通用户登录、资料编辑入口与 provider 未配置状态；真实第三方授权、邮件、PG 运行及云发布未验证。
下一步仅为发布准备与外部 OAuth 配置、实际授权验收；没有用历史授权执行云写入。

## NA-09-S01：普通用户入口与个人中心（首阶段历史记录；部署集成见上）

负责人主 AI。边界、社交绑定后续验收与配置见 [USER_CENTER.md](USER_CENTER.md)。
本轮先接入独立普通用户门户与现有认证策略，禁止放宽管理员后台权限。
社交绑定不得复用管理员的双账号 linkedAuthId 关联来伪装统一身份；第三方身份安全绑定和登录归一另验。
用户已授权本地提交与补丁导出。定制提交 `2774512cf4eb50bd0a51120e5d896dab425cd2ee`，topic `user-portal`；
export 与 verify 通过，generation `d88c6ec5846ec3eb31b978dc6560ff0a22b8c724e1cf7d7647a1bddcf8a31ebb`。
门户/既有登录视图回归107项、主仓库回归95项、TypeScript与客户端/Worker构建通过。尚未推送或发布；
独立portal client的SBA自动配置和真实浏览器OAuth验收未完成，不能宣称线上可用。
下一步为已确认的Google/GitHub自助绑定与同账号登录，并补齐部署集成；不使用历史授权云写。

## NA-08-S01：仅补发后台的正式修复（2026-10-09）

负责人主 AI。用户选择 SpringBok 控制台 repair，不通过本地 CLI 补发。
拆出管理员客户端的只读检查：复用现有 SPA/S2S 身份与密钥，要求回调已经登记，
不得借配置读取执行 UPDATE。已接入占位 Worker 前置检查、数据与认证配置保持证明、
admin-only 构建发布和真实资源配置就绪检查。3.0.3新增repair声明，尚未发布或执行修复。
只读客户端路径已实现；新增成功、回调缺失、停用、身份漂移、空ID/密钥及重复客户端
回归，前轮标准 Python 测试 83/83 通过。本轮完整回归及精确PR另验。
只读审阅指出内部表筛选LIKE下划线通配符范围过宽，已改为字面前缀GLOB并加相似名用户表
覆盖；新增provider占位漂移、域名/绑定/vars/assets、认证变化、分页上限及不重放测试。
配置就绪不等于后台登录验收；保持Access，秘密与行内容不上传artifact，不以HTTP登录页判成功。
本轮标准套件94项通过，收尾增加repair unknown回执测试后的部署子套件79项通过；补丁栈verify
通过。真实Cloudflare只读preflight及两次22表/三密钥/auth状态采样通过，未云写。证据在
`linshi/springbok-rebuild-retry-20261009/repair-live-readonly-proof.json`。精确提交、PR及发布另验。

## NA-07-S03：失败发布的安全诊断（2026-10-09）

负责人主 AI。线上固定 3.0.2 的任务 `dc-082d9d6d909a46c6b41cd149e0de729d`
在 admin-publish 阶段停止，认证服务、管理员与数据库已存在，后台只有 secret 占位 Worker。
本子任务仅补充固定命令类别、Cloudflare 数字错误码或固定网络/启动失败类别，沿用 SBA
既有 errorCode 字段，不上传原始 stdout/stderr、参数、异常、凭据或业务内容。不更改 unknown
状态和恢复锁，不重放初始化，不以 Actions success 代替应用结果。安全恢复与线上发布另验。
本地标准测试 81/81 通过，新增 8 项诊断/秘密隔离/不重试/unknown 与构建哈希围栏检查。
只读审阅发现新诊断模块的哈希覆盖遗漏，已修正并完整复验。尚未提交、推送或部署；
线上仍保留原 unknown。证据 `linshi/springbok-rebuild-retry-20261009/diagnostics-tests.log`。

## NA-07-S02：首次管理员自动初始化（2026-10-09）

负责人主 AI，分支 `feat/na-07-admin-bootstrap`。3.0.2 声明可选 Gmail 管理员邮箱和
deployment-only 密码；默认/覆盖密码由 SpringBok 加密管理，经一次性 permit 提供。
仅 deploy 创建不存在的新邮箱用户，以随机 authId 精确关联真实 super_admin 角色。
密码在执行入口移出环境，隔离 helper 用锁定 bcryptjs cost12及20字节OTP材料；
不进入 npm/Next/Wrangler、Worker secret、公开配置或回执。update/preview均不重设密码。
同邮箱碰撞拒绝，邮箱/MFA仍需正常验证。两次D1写入非事务；部分失败为unknown，不重放。
已通过完整46迁移SQLite初始化聚焦检查与真实锁定依赖helper；标准测试、PR/main和真实部署另验。
标准测试73/73通过、补丁栈verify通过；源码只读审阅未发现安全阻断。补齐构建环境不含密码、
初始化先于发布及runtime secret拒绝检查。真实子域名与新管理员登录随SpringBok发布后另验。

## NA-07-S01：后台无限加载修复（2026-10-09）

负责人主 AI，分支 `fix/na-07-admin-loading`。用户已授权开发两仓库的部署体验改进。
本子任务仅修复刷新 token 沿用登录时旧 roles、后台 `/api/info` 失败后读取 undefined.configs
导致无限加载。角色刷新读取当前有效授权，同时覆盖新增与撤销；配置读取有 15 秒超时、
取消、失效响应隔离、明确错误和手动重试，保留服务端权限检查。
线上复现：userinfo 已有 super_admin，刷新 access token roles 为空，配置 API 400 空响应。
本地隔离源测试 83 项 OAuth、16 项后台组件/加载检查通过，双端 TypeScript 检查通过。
首次测试缺本地测试 RSA 密钥而失败，生成隔离测试密钥后完整复验通过；没有访问线上密钥。
补丁 topic `admin-loading`，交付版本 `3.0.1`；标准编排测试、精确 PR/main、上线验收另记。
后续管理员邮箱/部署密码密钥化、Zone/子域名资源为独立任务，尚未实现，不能由本项代称完成。

## 依据

用户要求参照 MiDot，以独立子目录仓库接入 Melody Auth，自动生成和使用定制补丁，并在根目录设置部署入口。MiDot 实际使用忽略的独立 checkout，不是 Git submodule；精确恢复提交依赖增量 bundle，普通补丁重放只保证源码树。

## 本轮验收

1. 主仓库连接 `aiaimimi0920/NAccount`；`melody-auth/` 保留官方 Git 历史、官方远端和独立分支。
2. 提供固定 SHA 初始化、自动导出、完整校验、独立目标补丁重放、上游 rebase 与冲突续接。
3. 导出采用不可变 generation 和最后更新的指针，不删除既有补丁，不让半次导出成为当前版本。
4. `.sba/` 提供环境配置、离线计划、隔离构建、Wrangler dry-run 和显式发布。部署配置不污染上游 checkout，日常更新不自动升级上游或旋转签名密钥。
5. 临时 Git fixture 覆盖空栈、有补丁、精确恢复、内容重放、dirty 拒绝、目录边界、篡改、上游更新与冲突；实际 Melody Auth 做可完成的本地验证。

## 完成状态

上述本地工程验收已完成，详见 [验证记录](VALIDATION.md)：30 项回归通过，服务端和管理后台均完成真实隔离构建及 Wrangler dry-run。当前主仓库尚无提交，未推送；未进行 Cloudflare 外部写入。使用入口见根目录 README、`customizations/README.md` 与 `.sba/README.md`。

## 非目标

- 不新增账号业务功能，不制造一个没有业务需要的示范补丁。
- 不创建 Cloudflare 资源、不读取现有私密凭据、不执行真实云部署。
- 不提交或推送项目，不改动 MiDot，不替换或删除其他仓库内容。
- 不将脚本测试、构建或 dry-run 宣称为注册、邮件、跨应用 SSO 的生产验收。
