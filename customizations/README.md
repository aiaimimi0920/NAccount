# 定制补丁栈

## 来源与恢复方式

`melody-auth/main` 固定官方基线；`melody-auth/naccount/main` 上的线性提交才是定制来源。`stack.json` 声明 topic，生成目录不是手工开发入口。

| 命令 | 作用 |
| --- | --- |
| `init` | 新 checkout 获取锁定官方基线，再从 bundle 恢复原始提交 SHA；已有目录只验证 |
| `export` | 从定制提交自动生成补丁、增量 bundle、源码树与文件哈希锁；最后更新指针 |
| `verify` | 检查目录边界、配置与文件哈希、分支、基线、HEAD、源码树和提交顺序 |
| `verify --catalog-only` | 仅校验补丁目录，不要求本地上游 checkout |
| `apply --destination <新目录>` | 用 `git am --3way --keep-cr` 重放，要求源码树相同，不承诺原始提交 SHA |
| `update` | 获取官方分支，在安全引用保护下 rebase 本地定制，成功后自动 finalize/export |
| `finalize` | 手工解决 rebase 冲突并继续完成后，推进官方基线并导出新栈 |
| `abandon` | 用户明确中止 rebase、恢复旧状态后，校验并归档待处理记录 |

上述命令通过根目录 `.\naccount.ps1` 调用。不接受 dirty checkout、父仓库回退或已有重放目标，不猜测如何处理未提交内容。

## 新增一个定制

1. 先在 `stack.json` 的 `topics` 数组添加稳定 ID，例如 `{"id": "account.branding"}`。
2. 添加 `customizations/topics/account.branding/README.md`，记录需求、改动范围和验证方法。
3. 在 `melody-auth/naccount/main` 修改、验证；在获得提交授权后创建线性提交，提交信息末尾必须包含且只包含一个已声明 topic：

   ```text
   NAccount-Patch-Topic: account.branding
   ```

4. 回到根目录：

   ```powershell
   .\naccount.ps1 export
   .\naccount.ps1 verify
   ```

5. 审阅生成差异后，主仓库再按授权提交补丁和文档。不要把 `melody-auth/` 加入主仓库索引，不建立 `.gitmodules`。

当前空栈是有意保留，不为演示而创建没有实际需求的业务补丁。非空栈才生成 `personal-history.bundle`；该 bundle 只包含官方基线之后的定制历史。

## 升级与冲突续接

```powershell
.\naccount.ps1 verify
.\naccount.ps1 update
```

升级仅适用于没有 tracking upstream 的本地定制分支。脚本在 `.git/naccount-update.json` 保存待处理状态，并建立 `refs/naccount/backups/<唯一编号>` 保护旧 HEAD。发生冲突后先审查、手工解决并逐个暂存相关文件，再继续 rebase：

```powershell
# 仅在冲突已经人工解决后执行
rtk git -C melody-auth rebase --continue
.\naccount.ps1 finalize
.\naccount.ps1 verify
```

需要放弃时，先评估当前冲突解决内容是否还需另存；`git rebase --abort` 会撤销该 rebase 中的解决改动，不由自动化代为执行。用户明确执行中止并恢复旧基线/HEAD/目录后，才运行 `abandon` 归档状态。不要通过删除 pending 文件绕过检查。

## 不可变导出

`generated/<SHA256>/` 包含 `series.txt`、`stack.lock.json`、有序补丁及可选 bundle。锁文件本身的 SHA-256 是 generation ID。先在临时目录完整生成，再复制到全新的 generation，最后原子替换 `current.json`。既有 generation 不会被覆盖或自动删除；导出失败不会指向半成品。

`verify` 检查当前 generation，不把旧 generation 当垃圾清理。普通补丁重放仅保证内容；需要精确提交恢复时使用 `init`，不要把重放目录当作已满足原 HEAD 校验。
