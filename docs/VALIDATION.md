# 初始工程验证记录

验证时间：2026-10-05（America/Los_Angeles），日志 UTC 日期为 2026-10-06。

## 范围与结论

接续会话 `01a10ef8-ad6d-73e3-a1e2-77f14b11b86e` 未完成的工程落地：独立 Melody Auth checkout、可恢复补丁栈、Cloudflare 部署入口。工程底座与本地验证已完成；未新增账号业务定制、未提交或推送、未创建 Cloudflare 资源、未初始化真实密钥、未发布。

主仓库 origin 为 `https://github.com/aiaimimi0920/NAccount.git`。主仓库尚无首次提交，本地文件保留为未跟踪状态，不把此记录当作 GitHub 已发布证据。

## 修复内容

- **CRLF 重放不一致**：原测试报 `Replayed source tree differs from the locked source tree`。逐字节检查确认中文内容相同，但 `git am` 默认将 `0d 0a` 变成 `0a`。重放加入 `--keep-cr`，测试同时覆盖 LF、CRLF、中文和二进制内容，不通过改写文字或放松树哈希检查绕过问题。
- **隔离构建缓存和日志**：npm 缓存和 Wrangler 日志默认存放在 release 临时目录；允许通过标准 `npm_config_cache` 复用临时缓存，通过 `npm_config_maxsockets` 降低并发，限制下载重试次数和超时。
- 补充离线计划、显式执行门槛、产物篡改、脚本变更、缺少凭据等回归测试，以及工程、补丁栈和部署说明。

## 已执行并通过

| 检查 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests -v` | **30 项通过**，161.399 秒 |
| Windows PowerShell 5.1 入口 `naccount.ps1 init` | 通过，验证现有 checkout，不覆盖 |
| `naccount.ps1 export` | 通过，空栈重新导出保持同一 generation |
| `naccount.ps1 verify` | 通过，基线、HEAD、源码树和目录一致 |
| `deploy.ps1 plan --component all` | 通过，测试配置、`cloudWrites=false` |
| server `npm ci` / `npm run type:check` | 通过 |
| server `npm run build` | Vite client 与 SSR 均通过 |
| server `wrangler deploy --dry-run` | 通过，gzip 292.13 KiB |
| admin-panel `npm ci` / `npm run type:check` | 通过 |
| admin-panel `npm run cf:build` | Next.js / OpenNext 完成 |
| admin-panel `wrangler deploy --dry-run` | 通过，gzip 1515.45 KiB |
| 构建后独立哈希复核 | 1,129 个清单项与编排脚本哈希一致，`state=built`、`component=all` |
| 源仓库与忽略边界 | Melody Auth 干净，两分支保持基线；主仓库索引没有源码或 gitlink |

测试中的 Git commit、rebase、abort 和模拟冲突解决全部发生于 `linshi/naccount-stack-test-*`，不是实际项目仓库。覆盖空栈、有补丁、精确恢复、内容重放、dirty 拒绝、父仓库回退、路径越界、补丁/bundle 篡改、上游更新与冲突续接。

后台上游 Next 配置为 `ignoreBuildErrors=true`，本编排在 OpenNext 构建前独立执行 `tsc --noEmit`；类型检查通过不是从 `next build` 推断。

## 版本与证据

- Melody Auth base / head：`290efee29e4ff7329804530c61880c9c5d36e7fb`。
- generation：`84fd0930b4ae0fffe7ffe2aa1c56b446bfb85fa067aa74ec5aa9ce076a4fedf3`。
- Node.js `v22.22.2`，npm `10.9.7`，Python `3.12`。
- 构建使用 Wrangler `4.122.0`、Next.js `16.3.0`、OpenNext Cloudflare `1.20.2`；没有升级上游依赖或 lockfile。
- 成功产物：`C:/Users/Public/nas_home/AI/GameEditor/linshi/naccount-release-slov5_7j`。
- 回执：上述目录的 `release.json`；打包输出：`dry-run/server`、`dry-run/admin-panel`。
- 构建日志：`C:/Users/Public/nas_home/AI/GameEditor/linshi/naccount-validation-20261006/build.log`。
- 回归日志：同目录 `unittest.log`。
- 测试配置：同目录 `cloudflare.validation.json`，使用测试资源 ID、`example.com` 和假 Client ID，**不能用于生产发布**。

前两次安装分别遇到 `EIDLETIMEOUT` 和 `ECONNRESET`；失败现场保留，没有修改 lockfile。复用缓存、并发降至 1 后，两组件均构建成功。部分 Windows npm 可选依赖清理仍有 `EPERM` 警告，最终退出码为 0。

## 未验证及警告

- 没有验证真实 Cloudflare 账户权限、资源、域名、套餐限制和 Worker 运行；dry-run 不证明这些条件成立。
- 未验证注册、邮件、首次管理员授权、跨应用 SSO、退出及 token 刷新。
- OpenNext 提示 Windows 不完全兼容并建议 WSL；生成代码有 `Duplicate key "options" in object literal` 警告，另有旧 compatibility date、middleware 命名及依赖弃用提示。构建通过不等于运行风险已经关闭，本轮未擅自升级上游。
- 真实发布需按 `.sba/README.md` 配置资源和凭据，再分阶段执行；迁移、角色授权、密钥初始化和部署不能由本记录替代授权。

## 后续目录迁移说明

上述构建与测试证据生成于部署目录迁入 `.sba/` 之前；构建回执绑定旧编排脚本哈希，不能作为迁移后的可发布 release 使用。当前部署入口及规则见 `.sba/`；迁移后的检查须另行记录，不把旧证据改写为新验证结果。
