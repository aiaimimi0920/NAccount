# NAccount 全界面 Neuro 统一

日期：2026-10-23。状态：本地源码实现与隔离验证通过，3.2.7 发布进行中，尚未部署。

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
