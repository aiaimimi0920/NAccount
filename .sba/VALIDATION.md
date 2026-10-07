# `.sba/` 目录迁移验证

验证日期：2026-10-05（America/Los_Angeles）。接续会话 `01a10f3b-280c-7d41-9896-6745d428b9ec` 中断后的目录迁移。迁移前的 `deploy/` 内容和测试备份保留在 `C:/Users/Public/nas_home/AI/GameEditor/linshi/naccount-sba-migration-20261005-212837/`，未清理。

## 已验证

- `.sba/` 包含部署入口、Python 编排、环境模板、规则、机器可读清单、说明与部署测试；旧 `deploy/` 不存在。根目录 `tests/test_sba.py` 仅负责标准测试发现。
- `python -m unittest discover -s tests -v`：33 项通过。迁移后单独运行 `python -m unittest discover -s .sba/tests -v`：20 项通过。
- `naccount.ps1 verify`：`verify: OK; patches=0`，基线与 HEAD 均为 `290efee29e4ff7329804530c61880c9c5d36e7fb`；独立 `melody-auth/naccount/main` 工作区干净。
- Windows PowerShell 5.1 实际调用 `.sba/deploy.ps1 plan --component all --json`：退出码 0、stdout 为单个 JSON 对象、`cloudWrites=false`。分别验证绝对与调用者相对的配置路径。
- 从新入口实际执行 `prepare --component all --json`：退出码 0，`state=prepared`、`cloudWrites=false`，隔离源码及回执位于 `C:/Users/Public/nas_home/AI/GameEditor/linshi/naccount-release-srgb1do7/`。所用配置是 `linshi` 下的假资源验证配置，不能用于真实发布。
- Windows PowerShell 5.1 以 `powershell.exe -NoProfile -NonInteractive -File` 调用 `publish --json`，故意不提供 `--execute`：退出码 1，JSON 报 `Cloud writes are disabled without --execute`，未读取 release 或接触云端。
- 本轮修改文本逐项检查为 UTF-8 无 BOM；源码与文档中未发现旧 `deploy/` 入口引用（历史验证记录的命令名称除外）。

## 未验证与边界

未重新构建 server/admin；针对迁移前 release `naccount-release-slov5_7j` 实测 `checked_release` 拒绝，报 `Deployment tools changed since build; rebuild before publishing`，不能直接作为发布产物。未创建 Cloudflare 资源、初始化真实密钥、运行迁移或真实发布；未验证注册、登录、邮件及后台权限。SpringBok 仓库没有已确认的 `.sba` 接入协议，本轮只交付统一入口与调用格式，不宣称其程序已接入。

## SBA-05-S12：就绪请求标识修复（2026-10-07）

负责人：主 AI；基线 `6964b64cdbc04ada6d896f85ba24298ac6c0b8c0`，分支
`fix/sba-05-s12-readiness-user-agent`。本节是新的联合上线证据，不覆盖上方历史迁移结论。

云端 SpringBok 发起的任务 `sba-20261007-naccount-e7ac963`、GitHub run
`37617881272` attempt 1 已完成实际执行。应用结果为 `unknown / NACCOUNT_READINESS_FAILED`，
不是部署成功回执；线上两个 Worker 已存在，D1 已有业务表，KV 已有三个初始化键。
没有重跑 deploy/update、轮换密钥、清库或覆盖原任务。四条既有恢复历史保持不变。

真实只读对照：三个就绪 URL 使用默认 `Python-urllib/3.12` 返回 HTTP 403、
`error code: 1010`；明确标识 `NAccount-SBA/2.0` 时 OIDC discovery、JWKS、管理页均
返回 200，issuer 匹配、JWKS 非空。修复仅为这三个 GET 显式设置真实探针 User-Agent，
不携带认证信息、不伪装浏览器、不改 Cloudflare 防护、30 秒超时或错误/unknown 语义。

回归先红后绿；全量 `python -m unittest discover -s tests -v` 51/51 通过。
新增覆盖请求标识与零凭据、403 不重试、issuer/JWKS 失败关闭、发布后就绪失败仍为 unknown。
使用修改后的真实 `readiness()` 只读调用线上三项检查也通过，未重新发布应用。
证据：`C:/Users/Public/nas_home/AI/GameEditor/linshi/naccount-sba-05-s12-20261007/`。

精确提交/PR/hosted CI/main 状态以本项交付回执为准；本次不沿用 PR #3 的单次 CI 例外。
旧部署回执不可被本机探针结果替换。注册、邮件送达、登录/退出、后台授权、有数据升级
和云端独立只读复验入口仍需继续验收；HTTP 200 不是这些业务全部通过的证明。
