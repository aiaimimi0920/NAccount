# NAccount 工程约定

- 主仓库管理补丁、部署编排、文档与验证。`melody-auth/` 是忽略的独立 Git 仓库，不添加其源码或 gitlink，不建立 `.gitmodules`。
- `melody-auth/main` 保持锁定的官方基线；定制只在 `naccount/main` 上进行。不得向官方上游推送。
- 定制提交是补丁来源，每个提交包含一个已在 `customizations/stack.json` 声明的 `NAccount-Patch-Topic` trailer。没有用户授权时，不代为提交、推送。
- 用 `naccount.ps1 export` 生成补丁、增量 bundle 和锁文件，再执行 `verify`。不得手改 `customizations/generated/` 或 `current.json`。
- 上游升级用 `update`，只 rebase 本地定制分支。冲突保留现场，人工解决后执行 `finalize`；不得自动 reset、clean、skip 或猜测冲突。
- 部署代码、配置模板、操作规则与部署测试统一由 `.sba/` 管理。用户、AI 与 SpringBok 调用同一入口；具体执行规则以 `.sba/AGENTS.md`、`.sba/README.md` 和 `.sba/manifest.json` 为准，不另建平行部署目录。
- 不改动 MiDot。保留既有编辑和数据。测试、构建与临时产物默认放到 `C:/Users/Public/nas_home/AI/GameEditor/linshi`。
- 新增和修改文本使用 UTF-8 无 BOM；兼容 Windows PowerShell 5.1，Python 工具要求 3.11+。UNC 路径先改用持久映射盘或等效本地路径。
- 修改编排脚本后运行 `python -m unittest discover -s tests -v`；部署 dry-run 不等于真实云端验收。
