# 初始工程落地范围

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
