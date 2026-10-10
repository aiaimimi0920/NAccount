# NAccount 部署操作规则

`.sba/` 是本仓库唯一的部署入口与规则目录。SpringBok 读取 v3 `manifest.json` 和自动资源 v2 声明，调用 `springbok.ps1`；应用流程复用 `cloudflare.py` 与 `lifecycle.py`。用户/AI 的 `deploy.ps1` CLI 保留。统一入口说明见 `SPRINGBOK.md`；不要另建平行部署目录或直接改动 `melody-auth/` 中的 Wrangler 配置。

- 先读本目录 `README.md` 和 `manifest.json`。从 NAccount 根目录或其他本地/持久映射盘工作目录调用入口；不要从 UNC 工作目录调用。相对 `--config` 路径以调用者当前工作目录为基准。
- `plan` 是离线校验；`prepare` 只导出隔离源码；`build` 会联网下载 npm 依赖，但不写 Cloudflare。它们均不是发布授权，也不是业务验收。
- `bootstrap-keys`、`publish` 都需要单独的真实云端写入授权，且必须显式提供 `--execute`。`publish --migrate` 还需审阅数据库迁移与备份方案。不要把用户要求完善部署目录理解为授权执行这些动作。
- 真实写入前核对目标账户、资源 ID、域名、构建回执、迁移内容、所需 secrets 和当前 Cloudflare 状态。不能使用示例配置或假 ID 发布；不要在配置、命令行、日志和仓库中写入 secret 值。
- 不自动创建 Cloudflare 资源、不自动升级上游、不自动轮换既有签名/会话密钥。失败时保留 release、发布日志和数据库备份；不自动回滚数据库或重试外部写入。
- SpringBok 按声明创建新实例资源；应用 v3 只消费精确资源 ID。preview 从一致 D1 导出复制数据，独立新建认证状态，不复制 KV 会话/锁定/MFA。清理只允许通过 v3 context 绑定的测试实例，不能按前缀扫账户。
- 程序调用使用 `--json`，以退出码和 stdout 中单个 JSON 对象判断已解析动作的结果；参数语法错误可能只有 stderr 和非零退出码。stderr 是供人排障的日志，不作为稳定协议。`state=deployed-unverified` 只表示命令完成，不能代表注册、登录和邮件等业务验收通过。
- `security-migration` repair 仅处理已固定的 3.2.0 远程0050迁移失败；全部限定条件见 README。不能把它扩展成通用重试或把 admin-publish 的“不迁移”边界套用于此动作；两个动作均不得重放父任务。
- `readiness-only` 仅只读核验固定 3.2.1 已发布现场；不得添加发布或迁移，不将本次区间保全解释为历史追认，不修改旧 unknown 回执。
- 修改本目录编排脚本后运行 `python -m unittest discover -s tests -v`。测试放在 `.sba/tests/`，根目录 `tests/test_sba.py` 只负责标准测试发现。源码、注释和文档使用 UTF-8 无 BOM。
