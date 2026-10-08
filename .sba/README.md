# Cloudflare 部署与更新

> 2026-10-08：`manifest.json` 升级为 SpringBok SBA v3，资源声明为 v2；统一程序入口为
> `springbok.ps1 -RequestPath ... -ResultPath ...`，见 [联合接入](SPRINGBOK.md)。
> 下文 `deploy.ps1` 的人工/旧 CLI 用法继续保留，但末节 v1 JSON stdout 协议只适用于
> 直接调用 CLI，不再描述 manifest v3 的文件结果协议。新增生命周期与验收边界见
> [v3 生命周期](V3.md)。以下人工 CLI 的历史资源准备方式不代表 SpringBok 自动新建流程。

本目录是 NAccount 的唯一部署入口：`deploy.ps1` 是用户、AI 和 SpringBok 的共同调用点，`manifest.json` 是机器可读的动作清单，`AGENTS.md` 是操作规则。本目录把“本地准备/构建”与“外部写入”分开。部署不会隐式拉取最新上游、提交代码、创建 D1/KV 或轮换 JWT 密钥。提供调用协议不代表 SpringBok 已完成端到端接入。迁移后的本地检查见 [验证记录](VALIDATION.md)。

## 阶段和边界

| 命令 | 行为 | 外部写入 |
| --- | --- | --- |
| `plan` | 校验配置和补丁目录，输出锁定版本与计划，不执行网络命令 | 无 |
| `prepare` | 严格验证 checkout，从 Git archive 生成隔离源码和 Wrangler 配置 | 无 |
| `build` | prepare → npm ci → TypeScript 检查 → 构建 → Wrangler dry-run → 哈希回执 | 无 Cloudflare 写入；会下载 npm 依赖 |
| `bootstrap-keys --execute` | 仅在三个 KV 密钥全不存在时初始化；已有完整密钥不写，部分存在则拒绝 | 有，需单独授权 |
| `publish --execute` | 核验已构建产物和脚本哈希，上传显式声明的应用 secrets，发布指定组件 | 有，需单独授权 |
| `publish --execute --migrate` | 发布前先导出远程 D1 备份，再执行迁移 | 有，需审阅迁移 |

命令默认只处理 `server`，可选 `--component admin` 或 `all`。首次环境应先 server，再配置 admin；两组件不是跨 Worker 原子发布，失败时以发布日志中已完成步骤为准。

## 1. 一次性资源准备

这些操作不由本轮脚本自动执行：准备 Cloudflare 账户、D1 数据库、KV namespace、两个 Worker 和两个可用的自定义域名；准备适当权限的 API token 与邮件提供方账号。对资源创建、域名绑定、费用与 token 权限单独审核。

认证和后台使用不同 HTTPS 自定义域名，例如 `auth.example.com` 与 `accounts-admin.example.com`。当前部署配置有意拒绝同域名、带路径 URL 和 `workers.dev`，沿用锁定上游对同账户 Worker 间访问的部署要求，而非承诺支持所有 Cloudflare 拓扑。

把 `.sba/environments/cloudflare.example.json` 复制为 `.sba/environments/production.local.json`，填写 accountId、D1 ID、KV ID、域名和邮件发送地址。`*.local.json` 已被忽略。使用 UTF-8 无 BOM 保存；示例中的 `REPLACE_*` 占位符会被拒绝。

配置文件只放公开参数和 secret 的名称，不能放值。`server.secretNames` 必须列出实际使用的邮件/短信/社交登录 secrets，发布时由环境变量提供。`vars` 是明确的部署配置源，服务端使用 `keep_vars=false`：请把需要保留的公开 Dashboard 变量同步到配置中，不要依赖手工设置在下次发布后继续存在。

## 2. 计划和构建服务端

从 NAccount 根目录运行：

```powershell
.\naccount.ps1 init
.\naccount.ps1 verify
.\.sba\deploy.ps1 plan --config .\.sba\environments\production.local.json
.\.sba\deploy.ps1 build --config .\.sba\environments\production.local.json --component server
```

记下打印的 `Release:` 绝对路径。配置只写入 `linshi/naccount-release-*/source`，不会修改 `melody-auth/server/wrangler.toml`、lockfile 或安装其 node_modules。

本地构建剥离 Cloudflare 环境凭据以及本配置声明的应用 secrets，不把后台 S2S secret 传入 Next 构建。npm 缓存和 Wrangler 日志默认也保存在该临时 release 下；网络不稳定时可在当前进程设置 `npm_config_cache` 指向已有临时缓存、`npm_config_maxsockets=1` 降低并发，再新建构建。不要修改上游 lockfile 来掩盖下载错误。

构建失败保留现场且回执保持 `prepared`，不能发布。成功后的 `release.json` 记录源提交、源码树、generation、脚本哈希及发布源码/产物清单。源码、配置或编排脚本变更后必须重新构建。

## 3. 首次初始化密钥和发布服务端

以下为**外部写入命令示例，不会因为出现在文档中而自动执行**。先由受控的凭据管理方式设置当前进程的 `CLOUDFLARE_API_TOKEN`，以及 `RESEND_API_KEY` 等已声明 secrets；不要把值写进仓库或共享终端记录。没有显式 token 时拒绝发布，不依赖隐式 Wrangler OAuth 登录。

```powershell
$release = 'C:\Users\Public\nas_home\AI\GameEditor\linshi\naccount-release-实际编号'
.\.sba\deploy.ps1 bootstrap-keys --release $release --execute
.\.sba\deploy.ps1 publish --release $release --execute --migrate
```

初始化只处理 `sessionSecret`、`jwtPublicSecret`、`jwtPrivateSecret`，密钥在内存生成并通过 API 上传；已有完整集合直接跳过。若部分存在，人工调查后处理，不自动覆盖。初始化期间不要并发运行其他密钥生成/轮换工具；KV 不是可用于竞争初始化的事务锁。

日常发布**不要运行上游 `prod:secret:generate`**：它会生成新的 JWT 密钥。迁移前的数据库导出含敏感账号数据，保存在独立的 `naccount-publish-*` 目录中，不提交、不公开。导出失败会阻止迁移和发布；迁移失败会停止发布，不自动回滚数据库。

## 4. 初始化管理后台

服务端数据库迁移会创建 `Admin Panel (SPA)` 和 `Admin Panel (S2S)` 两个 app。通过已授权的 Cloudflare 控制台操作核对实际行，把两个 `clientId` 填到配置的 `admin.spaClientId` / `admin.s2sClientId`；将 S2S 的 secret 交给凭据管理，发布时注入 `SERVER_CLIENT_SECRET`，不要填进 JSON。

在 SPA app 的 `redirectUris` 中配置每种启用语言的后台地址，例如：

```text
https://accounts-admin.example.com/en/dashboard,https://accounts-admin.example.com/zh/dashboard
```

登录和退出回调都必须匹配登记地址。后台构建时固定 `NEXT_PUBLIC_*` 参数，修改域名、SPA Client ID 或语言后需要重新构建。

```powershell
.\.sba\deploy.ps1 build --config .\.sba\environments\production.local.json --component admin
# 完成审核并准备 SERVER_CLIENT_SECRET 后，使用本次 admin Release 路径
.\.sba\deploy.ps1 publish --release '本次 admin Release 绝对路径' --execute
```

首次管理员需注册、验证邮箱，核对真实用户行和 `super_admin` 角色行后再授权。**不要机械执行 `userId=1, roleId=1` 的示例 SQL**，以免授予错误账号权限；授权后退出并重新登录。参考锁定源码的 `melody-auth/docs/zh/admin-panel-setup.md`。

## 5. 日常更新

开发、提交定制（需授权）、`export`、`verify` 后重新 `build --component all`；审阅迁移，再显式 `publish`。只有决定吸收官方更新时才先运行 `.\naccount.ps1 update`，不是每次部署都升级。

发布日志会记录 `started`、`failed` 或 `deployed-unverified` 以及已完成步骤。上传 secret 可能已生效，即使后续部署失败；不能把一次命令失败理解为云端完全没变化。回滚需核对当前版本、旧产物与数据库兼容性，不自动恢复备份或轮换密钥。

## 上线验收

本地 dry-run 只验证打包配置，不证明真实账户、资源权限、域名、邮件可用，也不证明注册/登录已经成功。真实发布后至少检查 OIDC discovery、JWKS、注册与邮件验证、后台权限、两个应用登录/退出及 token 刷新。本工程不会把编译或 dry-run 宣称为这些业务流程已通过。

## 程序调用协议

程序先读取 `manifest.json`，选定动作与参数，从非 UNC 的本地或持久映射盘工作目录启动 `powershell.exe -NoProfile -NonInteractive -File <绝对路径到 .sba/deploy.ps1> <动作> ... --json`。`--config` 的相对路径以调用者工作目录为基准；建议程序传绝对路径。Python 3.11+、Git、Node.js 和 npm 按动作准备，不能把 `plan` 的离线结果当作构建或云端验收。

参数语法正确且包含 `--json` 时，stdout 只输出一个 UTF-8 JSON 对象：`schemaVersion=1`、`ok`、`action`，成功时有 `result`，动作执行失败时有 `error.message`；同时检查进程退出码（成功为 0）。参数解析失败可能只有 stderr 和非零退出码。构建与发布的进度日志写到 stderr，不能把 stderr 文本当稳定协议。`plan` 返回 `cloudWrites=false`；`prepare`/`build` 返回 release 和回执路径；`publish` 返回 `deployed-unverified` 与日志目录，仍需业务验收。`bootstrap-keys`/`publish` 的 `--execute` 是防误触门槛，不代替单独授权。现阶段 SpringBok 尚无已确认的 `.sba` 对接协议，本目录仅提供可供其调用的入口，不宣称已完成集成。
