# NAccount 全界面 Neuro 统一

日期：2026-10-23。状态：3.2.7 已完成 SpringBok 原实例保数据更新及独立平台验证。

本轮获准修改 NAccount 的完整界面，不限登录页。定制源码位于忽略的独立 `melody-auth/` 仓库；外层只记录说明，
不添加嵌套源码或 gitlink，不手改 generated/current。发布进度记录于 `docs/IMPLEMENTATION_PLAN.md` 的 NA-15，不覆盖或回退 account 系列既有实现。

## 实现边界

- server 默认 branding 使用 Neuro 深色中性色、信号黄主操作、信号绿成功及品牌；独立登录、注册、重置、MFA、Consent 等共用 auth-theme.css。
- 管理后台通过原 shadcn/Tailwind 语义 tokens 全局统一 background/card/popover/sidebar、primary、destructive、success、info；补齐 badge、必填、错误、冒充风险等旧固定色。
- 用户中心保留既有 canonical portal 主题；共享认证组件没有引入额外框架、依赖或轮询。
- 组织显式 branding 不重置。自定义 layout/label 成对派生面板、控件、边线和提示色，避免黑字被强制放在深色背景上；secondary hover 同时基于自定义背景/前景派生。
- 320px 下缩减认证内容与六位 MFA 输入宽度，保留键盘焦点；字体提供本地 sans-serif 回退，不依赖远端字体成功才可读。
- 管理弹窗使用 panel 表面、视口内滚动，并补齐 Escape 取消及外部发起控件的焦点恢复；重发邀请提交中仍禁止取消，不将 Escape 接入确认/写操作。
- 同一次已验证 authorize HTML 请求仅解析一次 branding，复用于 initialProps 和 HTML 样式；无跨请求缓存，不削弱组织/客户端/redirect 校验。

## 验证

依赖与运行产物在 `linshi/asset-store-ui-20261023/naccount/`。server 复用 SHA-256 相同 package-lock 的隔离依赖；
admin 用实际锁 `npm ci --ignore-scripts --no-audit --no-fund` 安装，未安装未固定的 latest 工具。
仅在隔离目录生成 RSA 测试密钥，没有复制真实凭据。

- admin：最终 48 文件 472 测试通过；独立 `tsc --noEmit` 与 Next 生产构建通过，不能以 build 的 skip type validation 代替类型检查。
- server：核对并同步最新账号模块到隔离快照后，最终 15 文件 175 项相关测试通过，包括 Layout/authorize、同请求 branding 一次读取、默认精确主题与组织自定义变量、account 邻近回归；Vite client/SSR 构建和独立类型检查通过。
- 既有 account UI/profile/latency 邻近回归使用默认 SQLite/D1 合同；误用 `TEST_MODE=node` 的 pg-mem 失败不能标成 PostgreSQL 通过。
- Chrome 实际编译的登录/注册/重置/OTP/Consent 五类认证视图、六个 Next 管理路由在三种宽度下通过；默认/组织自定义对比度、输入焦点、320px 邀请弹窗、必填错误和 Escape/焦点恢复通过，无业务写请求。截图在同级 `naccount-ui/`。
- 身份/provider 均为合成夹具，外部 logo/font 被阻止，不代表生产会话或第三方 OAuth 验收。构建保留现有 middleware、Vitest 配置和 Node deprecation 警告，未为主题任务扩大框架升级。

用户已明确授权保存与升级：独立定制提交带已声明 topic trailer → `naccount.ps1 export` → verify → 精确 head CI/发行 → SpringBok 原实例保数据更新 → 独立可用性与线上界面检查。
基线为已上线 3.2.6 的外层 `33d3943` / 定制 `10bccd5`；完整保留上一轮性能更新，不以外层文档或本地 build 代替补丁保存或线上验证。

## 3.2.7 生产升级与独立验证

- 定制 commit `471ca79067c378bcab0b449fbde8f4f357f0e30f` 的直接 parent 为
  `10bccd55191f8c647a0a8a29412e55582ab990b0`，祖先检查通过，保留其他 AI 的 3.2.6 性能成果。
  export/verify 为 12 patches；新 generation `03f1db9e67658cc458db6cd26bd52b1ab6be4b1e04f7556a28656ce4113d9585`，旧 generation 保留，未推 upstream。
- PR #25 精确 head CI 和 main CI `39945699531` 成功；正式 `v3.2.7` 固定
  `f306f3e040509d608d7e29a15f99a42df31e94cc`。外层编排最终 110/110，新增补丁的 byte-preserving 重建通过；
  Gitleaks 8.30.1 对原 3.2.6 外层基线至该 release 的实际 Git 变化扫描无泄漏。
- 原 UI 任务 `dc-3227f9277268477dbc3e26212601c33a` 返回提交未确认，没有重放。
  用户另行明确批准最多 24 小时精确维护权限，本次只建立两小时、原实例/parent/完整 SHA 限定的专用 token；
  原 owner policies、旧 token、proof secret 和其他控制 bindings 不变。旧 UI 计划 body 未留存，取消 scope 的 digest
  从可信且未变化的原 parent/固定 release 重新构建，未冒称保存了原始 UI digest。
  平台 vault 与 Connected DO 均独立确认 `cancelled-before-reservation`、双侧 fenced、无 reservation/bootstrap；
  仅保存不可变防迟到记录，不解锁、不修改历史、无 unknown replay。指纹重建计划没有提交。
- 随后原实例 `dc-082d9d6d909a46c6b41cd149e0de729d`、原 parent
  `dc-1a0b24eabcc349919ce90fda40c3d4e7` 保持，新任务 `dc-b243e756a5e84ec981c4a19609b901e7` /
  [run 39949925541](https://github.com/aiaimimi0920/SpringBok/actions/runs/39949925541) 一次性提交，
  `deployed-unverified`、backup/data/discovery/JWKS/admin 五检查通过。
  artifact ZIP SHA-256：`3b29695c51db02760330dccf361263407dbd7ec37566ff5e3b175dd19ec76cce`。
- 独立 verify `dc-0fc9414c82934392938e7ea5b64b4545` /
  [run 39950926985](https://github.com/aiaimimi0920/SpringBok/actions/runs/39950926985)：`succeeded`、三检查通过，
  ZIP SHA-256：`19d5afc1e94e25f36b9459c7af72b057dbbae251adb51fefce833d04878fbd18`。
  两份唯一 artifact 的 digest 和 task/run/source 均匹配，不改写原 update 的 deployed-unverified。
- 独立 Cloudflare before/after：双 Worker deployments 改变，所有 bindings、运行设置、domains 均一致；
  D1/KV、账号/provider、会话及密钥 bindings 保留。secret binding 存在不等于读出或比较 secret 明文。
  维护 token 已禁用、有效期未延长，原控制面 bindings 恢复，独立无 Cookie 负向探针 302；
  控制 bundle SHA-256 未变，新静态资产配置保持，旧 policies 完整保留，不删除审计记录。
- Edge 正式 `/workspace` 到 authorize 使用原 client、固定 callback、openid/profile 与 S256，显示新认证主题和真实表单。
  原空 `COMPANY_LOGO_URL` 仍产生未加载 Logo，占位问题已记录，未擅自改公开品牌配置。
  本轮没有新增测试账号、重复发码或重新执行真实密码/MFA/OAuth/完整后台业务验收，不能用旧版验收替代。

临时证据位于 `linshi/asset-store-ui-20261023/`；凭据、私密配置和响应仅受 Windows DPAPI 保护，不进入 Git。
