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
