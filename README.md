# NAccount

以 Melody Auth 为开源基础的统一账号服务工程。主仓库管理补丁、部署编排、文档和验证；`melody-auth/` 是被忽略的独立 Git checkout，不是 submodule，也不把上游源码复制进主仓库。

仓库包含认证服务、管理员后台及 NAccount 定制补丁与 SBA 部署编排。各功能的源码、验证和发布状态分别记录，不以构建或管理员登录成功代表全部账号业务已经交付。

普通用户入口与个人中心正在开发，Google/GitHub 社交绑定为已确认范围，见 [开发与验收边界](docs/USER_CENTER.md)。当前门户源码入口为认证服务的 `/account`；独立 SPA client 的部署配置、社交绑定和真实用户验收尚未完成，不能直接作为已上线入口使用。

## 仓库结构

```text
NAccount/
├── melody-auth/             独立上游仓库，主仓库忽略
├── customizations/
│   ├── stack.json           上游、分支与定制 topic 声明
│   ├── current.json         当前不可变 generation 指针，自动生成
│   └── generated/           补丁、锁文件、非空栈的增量 bundle
├── naccount.ps1             初始化、导出、校验、重放、升级入口
├── .sba/                   部署代码、规则、配置模板、测试与统一入口
├── scripts/stack.py         Git 补丁栈实现
├── tests/                  Git fixture 与 .sba 测试发现入口
└── docs/                   范围、验证记录
```

## 快速开始

需要 Git、Python 3.11+（建议使用维护中的补丁版本）、Windows PowerShell 5.1+；构建还需要 Node.js 22 和 npm。入口检测到 `rtk` 时使用 `rtk proxy`，否则直接运行工具。

从本仓库根目录执行：

```powershell
.\naccount.ps1 init
.\naccount.ps1 verify
```

`init` 在全新目录中从官方获取锁定基线，再用增量 bundle 精确恢复定制提交。已存在的 checkout 只检查，不覆盖。首次联网获取失败时会保留 `melody-auth.initialize-*` 现场。

本工程初始锁定 Melody Auth 提交：`290efee29e4ff7329804530c61880c9c5d36e7fb`。这不是“自动跟随最新版本”；当前有效基线以生成锁文件为准。

上游仓库中，`main` 是锁定的官方基线，`naccount/main` 是本地定制分支。官方远端 `origin` 保留，但 push URL 设置为 `disabled://upstream-read-only`，防止误推。参考 MiDot 的维护方式，但不修改 MiDot。

## 日常工作

- 修改 Melody Auth：只在 `melody-auth/naccount/main` 开发，按 topic 形成定制提交，再运行 `export`、`verify`。详见 [补丁栈说明](customizations/README.md)。脚本不替你提交源码。
- 升级上游：明确运行 `update`；先保存当前 HEAD 的安全引用，再 rebase 本地定制分支。冲突停止并保留现场，不自动 reset、clean 或 skip。
- 部署服务：配置环境后运行 `.sba/deploy.ps1 plan` 和 `build`，审核结果后才显式 `publish --execute`。详见 [部署说明](.sba/README.md)。

## 验证

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
rtk proxy python -m unittest discover -s tests -v
.\naccount.ps1 verify
```

测试中的提交、rebase 和冲突解决仅操作 `linshi` 下的专用 fixture，不提交或重置真实仓库。临时产物默认保留在 `C:/Users/Public/nas_home/AI/GameEditor/linshi`，可用 `NACCOUNT_TEMP` 指定其他合适的本地临时目录。请不要从 UNC 工作目录运行，使用等效本地路径或已经存在的持久映射盘。

[验收范围](docs/IMPLEMENTATION_PLAN.md) · [本轮验证记录](docs/VALIDATION.md)

## 授权与许可边界

提交、推送、资源创建、密钥初始化、真实发布是不同操作，需要各自明确授权。本工程不会自动提交或推送两个仓库，也不会通过构建自动写入 Cloudflare。

Melody Auth 的许可证保留在独立 checkout 的 `LICENSE`，隔离构建复制的是包含许可证的 Git archive。分发上游及其依赖时仍需保留适用的版权、许可声明。
