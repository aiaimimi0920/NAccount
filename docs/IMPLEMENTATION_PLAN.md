# 初始工程落地范围

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
