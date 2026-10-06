# SpringBok 联合部署接入

任务 `SBA-03`，负责人主 AI，2026-10-06 开始。范围为 `.sba` 统一入口、测试及说明，
不改上游源码，不提前执行实际云端写入。用户已授权通过云端 SpringBok 从 GitHub
部署 NAccount；本地只开发、测试并推送，不直接发布本地工作区。

采用 SpringBok `docs/sba-contract.md` 定义的 manifest v2。保留 `deploy.ps1` 原有
plan/prepare/build/bootstrap-keys/publish CLI，统一入口为 `springbok.ps1`。
统一入口接收 `-RequestPath` 和 `-ResultPath`，不接收任意 shell 字符串。

应用负责：重建锁定上游、构建 server、首次密钥初始化、迁移前备份、迁移、发布，
然后从实际 D1 中取得唯一的管理后台客户端，追加所需回调，构建和发布 admin。
S2S secret 仅在当前进程环境中传递，禁止写入配置、结果和共享日志。
update 不初始化或轮换签名密钥；资源 ID 从同一环境配置复用，不创建/删除数据库。

资源准备仍在实际发布前核实：Cloudflare account、既有或明确创建的 D1/KV、两个
独立自定义域名、邮件提供方与 secret。平台不替应用推断这些字段。
configuration 沿用 `environments/cloudflare.example.json` 的公开结构，不接受示例 ID。
干净 GitHub checkout 可由 `Stack.initialize()` 重建锁定的 melody-auth；GitHub runner
设置 `NACCOUNT_TEMP` 指向 `RUNNER_TEMP`，不依赖开发者 C 盘路径。

所有动作先核对源码 SHA 与 manifest 身份，只有 `SBA_EXECUTE=1` 才允许 deploy/update。
外部发布过程中失败报告 unknown（可能已部分写入），不自动重试。verify 只验证
OIDC/JWKS 与后台 HTTP 就绪，不冒充注册、邮件和数据保留的完整联合业务验收。
部署成功返回 deployed-unverified；真实业务验收由后续 SBA-05/SBA-08 完成。

原 v1 manifest 的字段不会被静默重新解释；只使用旧 CLI 的调用方不受影响，
读取 manifest 的调用方必须支持 v2 或明确拒绝。测试执行 `python -m unittest discover -s tests -v`。

## 本次证据与剩余范围

- 标准测试入口已执行：40 项通过（219 秒，包含未修改的补丁栈回归）。随后新增公开
  配置拒绝用例并补齐凭据前置检查，当前 `.sba/tests` 28 项再次全部通过；不重复运行
  未改变的完整上游 Git 场景。PowerShell 语法解析、`git diff --check` 通过。
- 当前 manifest 已通过 SpringBok main 的 `validateManifest`，标识
  `naccount-cloudflare`、应用版本 `1.0.0`。这是跨仓库契约检查，不是实际发布。
- 本子项为 `SBA-03-S01`（应用统一入口）；后续 `SBA-03-S02` 从推送后的干净 GitHub
  checkout 重建/构建，`SBA-04` 接入云端任务和 GitHub runner。不从本地开发目录发布。
- Cloudflare 只读盘点未发现 NAccount 的 D1/KV；未找到已提供的 Resend/SMTP 凭据。
  已请求确认域名和邮件发送配置；本项未创建云资源、数据库行、密钥或部署。
