# 初始工程落地范围

## NA-16：统一托管登录面板与请求等待优化（3.2.8 发布进行中，2026-10-24）

用户授权审视当前账号系统、优先改善访问慢的问题并提供其他应用共用的登录面板。
本轮基于外层 `7405fbe8`、定制 `471ca790` 的干净工作区，不回退 NA-13/14/15。
开发阶段只修改本地源码、测试及接入文档，没有操作现有用户。用户随后明确授权提交、推送并使用 SpringBok 更新部署。
测试/构建/浏览器证据位于 `linshi/naccount-unified-login-20261024/`。

### 已落实的改动

- `/login` 复用完整的 authorize/client/redirect/S256 PKCE/scopes/SSO/policy 验证与既有 `Main`，
  无会话时同请求直接返回面板；旧 OIDC authorize 保留原 302 合同。统一展示数据库应用名称、
  已登记回调的 origin 和 NAccount 文字品牌。`screen=signup/reset` 受真实能力开关限制，
  不将 UI 切换当成认证成功、不跳过 MFA 或 consent。详见 [统一登录接入](UNIFIED_LOGIN.md)。
- 同次 Access/ID Token 签名共用 Context 内 Promise，private/public KV 各一次，私钥导入与
  public JWK 转换各一次；并行首次 key 读取。下一请求重新读取，不新增跨请求缓存或权限窗口。
- current/deprecated JWKS 读取并行，保 current-first 与缺当前 key 的失败关闭；process、
  verify-email、expired 页复用已解析 branding。默认 system-ui 消除 Google 字体 stylesheet
  依赖；组织显式自定义字体保留。认证 HTML no-store/no-referrer。
- SSO 直接返回与普通页面完成改用 URL 参数合并，保留回调已有 query 并正确编码 state。
  独立页面使用服务端已经协商的 HTML 语言，避免无 locale/无效 locale 时客户端显示错误语言或空文案；
  账号中心弹窗仍使用自身 runtime 的语言，不继承宿主页面。

### 线上只读观察与边界

北京时间 2026-10-24 00:45，通过无 Cookie、无凭证的独立 curl GET 对 account、config、
discovery、JWKS 各取两次，共 8 次 HTTP 200。总耗时 1.54–3.77 秒，TLS 完成累计时间
约 0.73–3.47 秒；account/discovery 的 app duration 为计时分辨率内 0ms，config 为
637/33ms，JWKS 为 297/311ms。原始数据 `live-readonly/samples.json`，没有保存响应正文。
这是当前线上基线，不是本轮修改的上线效果、浏览器连接复用结果或总体 p95；网络/TLS
等待不能靠减少数据库查询完全消除。没有更改 DNS、代理、Cloudflare 访问策略或 provider。

### 验证与发布边界

最终验证结果：

- 15 文件 209 项聚焦测试通过；完整 CF 套件 155 文件 **3,192/3,192**，独立 key-rotate
  套件 **3/3**。实际路由测试证明 Access/ID Token 同次兑换各只读一次 public/private key，
  两 token 均验签成功；并行/串行共用、下一请求换 key、加载失败、SSO 真实加密 Cookie、
  被撤销 session、坏 client/redirect/PKCE、应用停用、appName 注入与回调 query/state 均有回归。
- 最终 TypeScript、Vite client/Worker 双构建通过；两仓 diff check、UTF-8 无 BOM 和业务源码
  与测试副本逐字节一致检查通过。没有执行 PostgreSQL 全套或更新管理后台依赖。
- 真实 Chrome 打开经 Hono 生成的合成应用 HTML 和生产构建客户端，检查登录→注册→返回→
  重置、1280/320px、88 字应用名称、内部滚动与键盘焦点。320px 下 document/body 宽度均
  320px；无 locale 时沿用 HTML 的中文，screen=signup 直达；网络只有本地 JS/CSS/favicon，
  无远端字体请求。未提交凭据或写业务数据。静态测试 helper 为 favicon 返回 204，不能以
  本地零 console error 声称生产 favicon 404 已修复。专用浏览器和本地 helper 均已关闭。
- 根仓库最终完整 **110/110** 通过。首次有一项 `Source tree differs from lock`，随后单项
  及两次完整复验未复现，根因未证实；第二次复验因测试目录过深报 `Filename too long`，
  改用 `linshi/na-r24` 后完整通过。未改产品校验或全局 Git 配置，原日志及失败 fixture 保留。

中间失败也保留：新增 redirectUris 夹具一度误用 JSON，已按当前逗号分隔存储修正；旧 JWT
测试使用只有 env 的对象冒充 Context，已换成真实 Hono Context，不在产品中放宽缓存/撤销校验。
语言测试改用实际支持的 fr，另有无效语言回退回归；旧 deprecated-key S2S 夹具补上现行
`tokenType=service` 合同并显式断言 200，未把 service 假装成用户或修改生产鉴权。

证据为 `full-tests.json`、`rotation-tests.json`、`focused-verified.json`、`typecheck-verified.log`、
`build-verified.log`、`root-tests-final.log`、`browser-summary.json` 和 `source-verification.json`；
首次/第二次失败日志另存，不以最终通过覆盖历史失败。

发布按既有 topic 定制提交、export/verify、精确 head CI、正常合并、固定 SHA/3.2.8 release、
SpringBok 原实例 update 和独立 verify 推进。官方 upstream 保持只读，不创建平行生产实例；
旧 generation 保留，不新增数据库迁移或改动 provider/账号/密钥/域名。具体发布与生产回执随后补记。
本轮没有真实发邮件、短信、外部 OAuth、线上账号变更或并发压测，不声称已解决全部投递或网络延迟。

## NA-15：全界面主题增量发布（已上线并独立验证，2026-10-23）

负责人主 AI。用户已明确授权提交推送及 SpringBok 升级；基于外层 `33d3943` 和定制
`10bccd5` 继续，不覆盖 NA-13/NA-14 性能更新。版本 3.2.7 不增加迁移、不更改 provider、
账号、密钥、D1/KV、Workers、域名或既有配置。仅提交本轮主题、branding 请求内复用、
弹窗可访问性及保护测试；定制先提交再 export/verify。原实例 update 和独立 verify 分开
执行，未知结果不重放。详细本地验证见 [全界面统一](NEURO_UI_UNIFICATION.md)。
PR #25 正常合并，main CI `39945699531` 通过；正式 v3.2.7 固定
`f306f3e040509d608d7e29a15f99a42df31e94cc`。定制 `471ca790` 直接基于 `10bccd5`，
12 补丁 export/verify 通过；原性能更新、旧 generation 与 immutable tags 保留。
原实例 update `dc-b243e756a5e84ec981c4a19609b901e7` / run `39949925541` 五检查通过，
原回执保持 `deployed-unverified`；独立 verify `dc-0fc9414c82934392938e7ea5b64b4545` /
run `39950926985` 为 `succeeded`、三检查通过。唯一 artifact、ZIP digest、task/run/source 身份
均已独立核对。双 Worker deployment 改变，全部 bindings、runtime settings 和 domains 与升级前一致。
旧 UI 提交未确认任务未重放：另经用户明确批准，平台两侧确认无 reservation/bootstrap 后建立防迟到栅栏，
才从同一原 parent 生成新计划并一次性提交。新建两小时精确维护授权已禁用、原控制配置已恢复，
无 Cookie 负向探针 302。没有解锁、转移锁、删除数据或修改旧部署回执。
正式工作台到 NAccount authorize 的接入与默认深色主题已核验；本轮不复用 3.2.6 的完整真实登录/MFA 结果
冒称新版全业务重验。详细回执、生产观察和剩余边界见 [全界面统一](NEURO_UI_UNIFICATION.md#327-生产升级与独立验证)。

## NA-14-RELEASE：3.2.6 原实例更新与真实业务验收（已上线并通过，2026-10-23）

负责人：主 AI。用户已明确授权提交并通过 SpringBok 上线本轮性能优化，随后进行真实测试。
业务范围只含已合并 PR #22 的 12 文件性能改动与对应文档，source 为
`10bccd55191f8c647a0a8a29412e55582ab990b0`，不夹带当前工作区的并行主题编辑。
本切片将 SBA 版本更新为 3.2.6，按正常精确 head CI/PR/main 流程固定发布 SHA；仅更新
既有 NAccount 实例，保留 D1/KV、Workers、域名、密钥、账号与 provider 配置，不新建实例、
不重置账号或轮换密钥。未知结果不盲目重放，不继承旧 3.2.5 委托或取消任务的专用批准。
通过部署回执、独立 verify、云读回及隔离普通账号的真实注册/收件/MFA/登录/刷新/导航
分别验收。短信、外部 OAuth、密码或邮箱变更不在本轮测试范围。
证据目录：`linshi/naccount-na14-release-20261023/`。本轮验收完成，不需要重复部署。

- 性能代码 PR #22 已正常合并；发布元数据 PR #23 的精确 head 和合并后 main CI 通过。
  正式 `v3.2.6` 标签固定 `0d238a6fee8ce516c9b3cfd2f21f38add7943309`，独立读回一致；
  原 3.2.5 标签未移动。发布前主仓库 110/110、catalog verify、diff check 通过，业务补丁
  generation 仍为 `75e9416497cc8422cfb8c445b2d01a0003e0d9da2d0ab4d8cb1c29ebab405383`。
- 使用原 owner 的正常 Cloudflare Access 登录和 SpringBok 正式 UI，只提交一次原实例更新；
  没有启用旧机器委托、改变 Access 策略或发布 SpringBok 控制 Worker。确认页及回执均绑定
  上述完整 SHA。更新任务 `dc-1a0b24eabcc349919ce90fda40c3d4e7` / run `39939794197`
  原始状态为 `deployed-unverified`，backup-created、data-preserved、discovery、JWKS、
  admin readiness 五项通过。核对唯一 artifact、ZIP SHA-256、task/run/source 身份后保留原回执。
- 独立验证任务 `dc-524ba1fdc3d04d1583cb460b31165774` / run `39940585330` 返回
  `succeeded`，三个可用性检查通过；正式 UI 已显示 3.2.6“可用性已验证”，没有改写原更新状态。
  独立 Cloudflare 读回双 Worker deployment 已改变，原 bindings、运行设置和 domains 全部一致。
  数据保全结论来自正式逐行保全检查，不以资源数量或页面可打开替代。
- 保全检查结束后才创建普通隔离测试账号。真实 Chrome 完成注册、门户 consent、选择邮箱
  MFA、实际收件并验证、退出、密码登录、再次实际收件并验证、刷新恢复和三轮切页；最后退出，
  revocation=200、SSO logout=302、返回页=200，alert=0。未操作用户现有登录会话或账号；
  测试账号和 DPAPI 恢复材料保留，不擅自删除生产数据。隔离浏览器及 loopback helper 已关闭。
- 首次及再次登录资料响应都真实包含安全 social DTO；首次 profile=1/social=0。
  刷新也为 `profile?include=social` 一次请求，无独立 social；切到 apps 再返回仍重新取 social。
  在线快速离开 apps 时实际 GET 为 `net::ERR_ABORTED`，返回资料 social=200、alert=0；
  本项没有 mock 或注入网络延迟，不把浏览器中止当作服务器取消/回滚。
- 3.2.5→3.2.6 的小样本对照：刷新资料与社交 HTTP 耗时合计 976→328ms，请求数 2→1；
  三轮 apps 为 387/402/398ms（旧 551/512/613ms），返回 profile 为 399/608/478ms
  （旧 559/1046/380ms）。注册 POST 4,844→2,434ms；密码 POST 1,683→1,639ms。
  网络、账号及样本很少，不代表 p95，不把全部耗时变化归因于本轮优化。
- 新版两次发码 HTTP 约 1,887/2,000ms，provider 约 898/1,147ms；发送成功后约
  13,204/2,318ms 观察到匹配邮件，两次实际 MFA 验证均 200。收件值包含同步和轮询开销，
  不是 SMTP 精确投递时间，不能宣称邮件投递已稳定提速。一次测试桥只读收件超时发生在
  验证提交前，仅延长只读等待后取得同次邮件，未重复注册、发码、consent 或验证码提交。
- 业务无阻塞错误；浏览器仅见既有 `favicon.ico` 404。短信、真实外部 OAuth、密码/邮箱变更、
  账号删除及总体高分位/并发压测未覆盖。下一步如要继续优化投递体验，应先取得独立的
  邮件投递与网络阶段证据，不能降级 MFA、后台假成功或自动重发掩盖延迟。

## NA-14：注册、收件与登录链路复验（代码交付历史；3.2.6 上线见上，2026-10-23）

负责人：主 AI。基于已上线的 3.2.5，使用隔离浏览器、受控测试邮箱和普通测试账号，
分别测量注册、邮件服务接受、实际收件、验证、登录和页面切换；按真实证据选择最小优化。
保留现有用户、密码、MFA、撤销与限流语义，不跨请求缓存权限，不开启 EMAIL_LOG。
测试及脱敏计时证据放在 `linshi/naccount-na14-auth-performance-20261023/`。
旧机器委托已禁用且只绑定 3.2.5，不能用于新 SHA。本节保留代码交付时的证据与授权边界；
后续用户另行授权的正式上线和新版业务测试见 NA-14-RELEASE。

- 实时云读回仍为 3.2.5 对应双 Worker version。通过现有 EasyEmail NAS 收件服务创建隔离
  测试邮箱；真实 Chrome 完成一个普通账号注册、门户 consent、选择邮箱 MFA、实际收件并
  提交验证码；随后退出、密码登录、再次邮箱 MFA 和刷新恢复均走通。刷新后账户名片可见、
  alert=0。未操作既有用户，未重置密码、发送短信或执行外部 OAuth。
- 注册 POST 约 4,844ms，app=2,391ms、email-provider=1,556ms；首次选择邮箱后 enrollment
  POST 约 2,416ms，随后 send-email-mfa 约 2,073ms（app=1,782ms、provider=1,212ms）。
  发送接口成功后约 3,776ms 观察到匹配收件；这是收件同步/轮询上界，不是精确 SMTP 传输时间。
- 再次密码登录 POST 约 1,683ms（app=895ms），随后发码约 2,690ms（provider=1,423ms）。
  两次验证码均真实验证成功。人工/工具等待不计作产品延迟；这些少量样本不能代表总体分位数。
- 真实刷新显示 config→token→profile→social 串行。profile/social 本轮一组为 336/640ms，
  app 仅 83/74ms；独立三轮切页 apps 为 551/512/613ms，profile 为 559/1046/380ms。
  首次导航脚本未等请求完成，错误地测到约 24ms；该文件单独保留，已修正为等待真实响应后
  重测，不将无请求的旧计时作为性能证据。
- 最小改动为首次 `GET /account/api/profile?include=social` 同时返回白名单社交状态，复用
  本请求已验证 actor，并行读取卡片与绑定记录。健康路径由两个串行 HTTP 请求、2 KV + 6 D1
  减为一个 HTTP 请求、1 KV + 4 D1；默认 profile DTO 和 PATCH 不变。社交读取异常仅省略
  可选字段，现有独立社交请求负责展示真实错误，不能因附加数据故障阻断有效登录。
- 首屏种子仅来自同次 profile 响应；切页、退出、安全流程完成后清除，重试/解绑后重新取值。
  不跨请求缓存用户、权限或 securityVersion。应用/社交视图离开时中止其未完成 GET，并保留
  迟到结果隔离；request 同时遵守调用方取消和既有 15 秒上限，不自动重放任何请求。
  浏览器 abort 不代表服务器执行取消/回滚，不用于注册、发码、验证或其他写操作。
- 发现工作区同时有另一批认证/后台主题编辑，未覆盖、暂存或纳入本性能任务。验证副本由
  当前已提交基线加本轮 12 个明确归属的业务/测试文件构造，文件 SHA 清单单独保留；
  最初混合副本漏掉并行任务的未跟踪 CSS，已改为上述隔离方式，不改别人的主题代码。
- 最终 151 项聚焦测试、完整 CF 套件 3,149/3,149、TypeScript、客户端与 Worker 构建全通过。
  `focused-tests.json`、`full-tests.json` 与三份构建/类型日志为最终证据。新增取消测试最初用
  root render 替换错误模拟组件卸载；已改为 Hono Host 内真实状态切换，验证旧请求被中止且
  迟到结果不覆盖新账号，不更改产品语义迎合测试。首次类型检查的 JSON unknown 展开已显式
  约束为对象。失败记录与最终重跑分开，不将首次失败记为通过。
- 构建产物的隔离真实 Chrome 合成回归通过：首次 profile=1/social=0；切页返回 social=1；
  后续刻意延迟的社交 GET 在离开视图时 net::ERR_ABORTED，alert=0。该回归用合成 token/API
  数据，仅证明客户端请求/生命周期，不冒充新版本线上认证或性能对照。
- 用户已授权仅本轮 12 个业务/测试文件及对应文档的提交、补丁导出、推送与正常 PR 合并，
  不包含另一批主题 UI，也不包含新 release、标签或生产更新。业务提交为
  `10bccd55191f8c647a0a8a29412e55582ab990b0`，父提交保持原 3.2.5 业务补丁。
- 使用无主题编辑的独立普通 clone 执行原版 `naccount.ps1 export` 和完整 `verify`，
  精确恢复本轮提交；导出 11 项补丁，generation 为
  `75e9416497cc8422cfb8c445b2d01a0003e0d9da2d0ab4d8cb1c29ebab405383`。
  工具产物原字节同步回主仓库，主仓库 `verify --catalog-only` 通过。没有修改导出工具或
  绕过 clean 检查；实际业务工作区的并行主题编辑未 stash、重置、覆盖或夹带。
- 主仓库完整 110 项合同测试通过；业务提交与手写文件的 diff check 通过。生成 patch 中的
  空行上下文标记由标准 verify 校验，保持工具原字节，不按普通源码去除空白。
  代码交付只走精确 head CI、正常 PR 合并
  和 main 核验，最终远程状态以对应 PR/检查为准。该代码交付阶段没有生产更新；后续部署必须先确定
  固定新 SHA，再核对新授权，不能复用旧 3.2.5
  委托。不能从本轮本地通过或代码合并推断新性能已上线。

## NA-13：认证、个人中心及后台请求延迟（3.2.5 已上线并独立验证，2026-10-23）

负责人：主 AI。用户授权定位验证码发送、登录和页面切换缓慢，修复后通过 SpringBok
更新现有实例。本子任务只处理已证实的无用 session 工作、请求内重复身份查询及应用列表
逐项串行查询，并增加不含用户、密钥、验证码或 provider 正文的耗时证据。不跨请求缓存
账号、权限或安全版本，不降低 MFA/撤销/限流，不重建资源或初始化账号。
测试、测量与发布回执保存在 `linshi/naccount-na13-performance-20261022/`。
当前认证/后台 Worker 已更新到固定 3.2.5，云端配置/数据资源保留与独立可用性验证通过。
邮件 provider 接受与最终送达必须分开验证；真实收件/账户登录性能仍待业务验收。
原更新的 unknown 历史不改写、不重放。

- 移除 token/proof-only 路径的无用 session KV 和 cookie 工作；最终认证、SSO authorize、
  logout 及未审阅的新身份路径保留 session。真实加密 cookie 跨无状态 view 的往返已回归。
- 后台 bearer-only `/api/v1/*` 和 `/info` 同样不再执行无用 SSO 工作；无 bearer 的真实
  user API 仍返回 401。没有增加跨请求 JWKS 缓存，不扩展密钥撤销或权限失效窗口。
- profile 从原先 2 KV + 4 D1 串行链减少为 1 KV + 3 D1；本请求验证用户复用，下一请求
  仍读数据库。停用、删除和 securityVersion 变化立即拒绝，不引入跨请求权限缓存。
- 100 项公开应用目录合并为一条参数化 JSON join，整个 apps 请求只有用户、portal client、
  catalog 三条 D1 语句；保留 consent 用户隔离、类型/停用过滤、去重和公开目录次序。
- 首轮改动前路径预算 17 项中 12 项失败；含后台补充的完整 CF 测试 3,138/3,138 通过，
  `full-admin-release.json` success=true/exit=0。最新 TypeScript 与 Worker 构建通过；
  客户端构建亦通过，后台补充没有修改客户端源码。
  首轮完整套件缺 SAML 测试证书，补临时一天自签证书后重跑；新增 cookie 测试起初错误地
  只取首个 Set-Cookie，现按浏览器语义取最后一次持久化 cookie 并通过，不改产品 cookie 行为。
- 业务提交 `0ea7490805cb7916dfe20dcc1e0dbd97dc74e410` 与后台补充
  `ce98fe8ce513f9c65f19330567251cc8fc19504a`；导出十项补丁，随后正式发布 3.2.5。
  Server-Timing 只有 app/session-key/email-provider 与数字，不含用户、code、secret、provider 正文。
  主仓库完整 110 项测试、补丁 verify 和 diff check 通过；该本地验证阶段尚未执行生产更新。
- 本地回归不等于真实验证码送达或线上登录性能验收；真实邮箱、短信、外部 OAuth 本轮尚未验。
  用户已批准最多 24 小时、绑定本实例与固定 SHA 的机器更新/结果查询/独立 verify；
  SpringBok 旧机制不支持现代 connected 更新，授权的最小兼容修复另以 SV-11 验证。
- 首轮 PR #19 后，后台补充 PR #20 精确 head 两项检查通过，正常合并后的 main 检查通过；
  v3.2.5 正式发布并固定 `1f89e44fcc9d0659074a71c05da8423fcd26a747`，远程标签 SHA 已核对。
  SpringBok 兼容控制面已上线，真实 scoped session 与原 D1/KV、Workers、域名保留计划通过。
  首轮唯一一次更新提交遇网络中断，后续 state 409 且暂未见对应 run；当时为提交结果未确认，
  不是成功回执，也不能推断为确定未提交。当时没有重发或另建更新任务，专用机器 token 已禁用。
  该停点不能称 3.2.5 已部署；原计划、一次性 marker 与只读证据保留在上述临时目录。
- 用户另行批准精确中断任务的未派发取消栅栏。SpringBok PR #103 正常合并、精确 main CI
  通过并上线后，原任务的 vault/Connected 双侧 fence 真实完成并独立回读；只有确认无
  reservation/bootstrap 才重新预览，未删除 marker、迁移 head、释放旧锁或盲目重放。
- 原实例唯一新更新 `dc-26a817db585145d8bdacac1882c1607f` / run `39823532120`，
  已下载 artifact 并核 ZIP SHA-256、task 与固定 3.2.5 source；业务回执 deployed-unverified，
  backup-created/data-preserved/OIDC/JWKS/admin HTTP 五项全通过。随后独立 verify
  `dc-123d1756fbca45f1a63a334a1ef31c0d` / run `39824371418` 返回 succeeded，三探针全通过。
  不改写原 update 的 deployed-unverified 状态，也不追认历史 unknown。
- 云端独立回读认证与后台均为新 Worker version，全部原 bindings、运行配置、D1/KV 与域名
  保持不变。专用机器 token 已禁用，独立回读 disabled、到期时间不延长；等待 Access
  传播后，无 Cookie 的负向请求 302 到组织登录，原 owner 邮箱 policies 不变。
- 更新前后各 24 个匿名请求全部 200；直连每路四样本总耗时中位数 account/config/discovery
  约 1991/1713/1865ms → 1790/1381/1492ms。新版 account/discovery 的 app 耗时为计时
  分辨率内的 0.0ms，config 为 16–116ms；网络/TLS 占比仍高，代理路线也并非全数改善。
  小样本不是因果或真实登录/邮件送达证明；验证码 provider/最终收件、短信和外部 OAuth
  本轮尚未进行真实业务验收，不开启 EMAIL_LOG，不输出用户资料或邮件内容。
- 隔离的真实 Chrome 匿名检查已打开线上个人中心，完成登录→创建账户→返回登录→
  重置密码及关闭弹窗/切换应用管理；没有填写账号、提交表单或发送邮件，账号路径保持。
  截图 `na13-live-reset.png` 已检查；浏览器唯一控制台资源错误是 favicon.ico 404，
  不将本次匿名交互写成真实账户登录或收件性能验收。已关闭本轮专用浏览器会话。

## NA-12：用户中心内认证弹窗（3.2.4 已上线，2026-10-10 UTC）

负责人：主 AI。复用现有认证视图、PKCE、验证码和 MFA 状态机，将用户中心登录/注册
内嵌到 Neuro 原生弹窗；保留独立授权页与第三方外部授权。不新增密码接口，不改数据库、
账号和云配置。验收包括登录/注册/忘记密码切换、关闭与迟到响应隔离、语言、窄屏及键盘行为。
用户已确认本地效果并授权发布。实现、发布与业务验收分别记录如下。

- `AuthDialog` 直接挂载现有 `Main` 视图；`AuthRuntime` 为每个弹窗隔离认证 URL、初始配置和
  存活状态。不是 iframe，不写入浏览器的地址/历史，不另建密码认证接口。
- 原 authorize-view 在完整验证请求后支持 `Accept: application/json` 返回公开功能配置和协商语言，
  `Cache-Control: no-store`；HTML 与 JSON 共用同一份配置。独立授权页继续使用原布局。
- 注册、忘记密码、MFA/验证码及错误复用原状态机。最终 callback 仍验证精确 origin/path、
  单次 state、S256 PKCE、client 和时限，换取 token 并取得 profile 后才关闭弹窗。
  关闭后的迟到响应不能导航或写入 refresh token；未完成流程在关闭时清理门户事务/会话。
- 66 文件 661 项测试全部通过（`modal-final-tests.json`），TypeScript 与客户端/Worker 构建通过；
  测试覆盖 JSON 请求验证、弹窗内流程切换、MFA 中间态、回调完成、取消与迟到响应。
  初次测试暴露旧 React hook mocks 未提供 context、合成 submit 事件缺少 Hono 所需 detail；
  已修正测试适配，最终退出码为 0，没有忽略未处理异常。
- 真实本地浏览器验证中文切换、直接注册、返回登录/重置密码、Escape/焦点恢复、390×844 窄屏。
  页面始终 `/account`，无 iframe；弹窗底色 `rgb(14,18,24)`，唯一主操作 `rgb(217,255,56)`。
  截图 `linshi/naccount-user-center-20261009/modal-login.png`、`modal-mobile.png`。
- 业务本地提交 `4639ae1bb9b2b91cdd0b1319c44aa19bf79a22c4`，补丁 export/verify 通过；
  generation `7f350959679ca0cc8b1770cbf0bab32cce4b4b08f656cae8baea9ed0aae0802a`。
  本地阶段未发送真实邮件/短信、未进行外部 OAuth 授权或更改线上账号。
- PR #17 精确 head `43a176a53f4b6df7b2ede3e56f84718557a30f33` 两项检查通过后正常合并，
  main `14a0141b53a537a32b8b3d4e677897c86f893e57` CI 通过；v3.2.4 固定此 SHA，远程标签已核对。
  本地完整主仓库 110 项测试与补丁 verify 通过。
- SpringBok 正式控制台完成同实例 update `dc-1f6e7d34c17a467fa1c79d1711ea2572`，
  run `38029127700`。下载 artifact 并验证 ZIP SHA256；原始业务回执为 `deployed-unverified`，
  backup-created、data-preserved、oidc-discovery、jwks-ready、admin-http-ready 全部通过。
- 随后正式 verify `dc-29b8222f5bad49ecb48509180abb708c` / run `38029482660` 返回
  `succeeded`，三项可用性检查通过，控制台显示“可用性已验证”。不改写原 update 回执。
- 真实线上 `/account` 已核对登录、注册、重置密码在原生弹窗内切换、中文与深色配色；
  弹窗内部没有 iframe。保留原 D1/KV、账号、域名和 provider 配置，不重置密码。
  证据 `upgrade-3.2.4-business-receipt.json`、`live-modal-login-3.2.4.png`、
  `springbok-3.2.4-verified.png` 位于上述 linshi 目录。
  用户已通过新版弹窗登录，并确认“已登录，正常进入”。未单独断言此次登录实际触发了 MFA；
  真实邮件/短信和外部 OAuth 未在本轮验收。

## NA-11：认证页面背景一致性（已上线，2026-10-10 UTC）

负责人：主 AI。仅将登录/注册共用的默认页面外层背景改为与用户中心一致的 `#06080d`，
body 同步应用该背景，避免应用挂载前露出白色页面；保持现有白色聚焦表单、组织自定义 branding、
语言与认证逻辑不变。不增加迁移、不改密码和用户数据。
源码提交 `3785a7ba18cb7fbb3ac12d33abac20dc94c04cbe`，已导出补丁并通过 verify。
74 项布局、登录、注册及真实 handler 回归、TypeScript 和客户端/Worker 构建通过。
浏览器验证登录/注册页面外层与 body 均为 `rgb(6, 8, 13)`，表单保留白底黑字。
最初误在仅供浏览器运行、未含 Vitest setup 的副本执行测试，出现 document/env 未初始化错误；
已改用标准测试副本和仓库 vitest.config.mts 完成上述通过验证，没有修改产品逻辑规避错误。
PR #15 与 main CI 通过，v3.2.3 固定 `a5699137b6d97b87175398401065bc2d519e6d89`。
SpringBok 同实例 update `dc-d1b9d494fc134e9d96c0d5f1acc9afe5` / run `38025358596`
完成，备份、原行保全和三个可用性探针通过；update 原始回执为 deployed-unverified。
随后正式 verify `dc-ac8a17727da34302b6b3a9f3660d9343` / run `38025823538` 通过，
控制台显示“可用性已验证”。真实线上浏览器分别检查登录、注册背景为 `rgb(6, 8, 13)`；
未重新注册账号或替用户提交登录凭据。截图 `linshi/naccount-user-center-20261009/live-auth-background-login.jpg`
与 `live-auth-background-signup.jpg`；本次不将样式核验表述为完整安全流程验收。

## NA-10-READINESS：3.2.2 发布与只读收尾（完成，2026-10-10 UTC）

负责人：主 AI。边界为修复发布后 assets 校验误报，通过 SpringBok 正式 repair
只读核验已发布实例；不重做迁移、构建、Worker 发布、初始化或密码修改。
3.2.1 已由 PR #12 合并并发布，main `ee09fb42efddcf1f96d1a84206ceeec578546c07` 检查通过。
修复任务 `dc-9595995db7764b0e88462de04d63b56d` / run `38021757950` 返回
`unknown / NACCOUNT_READINESS_FAILED`。只读实证 0050 及安全触发器已存在，双端均发布新版本，
OIDC/JWKS 通过；认证端仅声明 assets.directory，不声明 ASSETS binding，旧校验误套后台要求。
修正后真实 published 配置核验通过。新增 readiness-only 固定该父任务、源码 generation
及双 Worker version；保全检查仅覆盖新的只读区间，不追认旧回执或历史数据保全。
3.2.2 与 3.2.1 业务补丁完全相同，仅部署校验变化，不再次发布 Workers。
本地完整主仓库 110 项测试、补丁 verify 与 diff 检查通过；独立只读审阅未发现新阻断。
PR #13 两项 CI 及合并后 main CI 通过，发布标签 v3.2.2 固定
`3cb2949d55dce347a902aee5c106a7cfe7c1809e`，远程 SHA 核对一致。
从 SpringBok 正式控制台提交任务 `dc-d12d127cc7214f309eb44d33c393235c`，run
`38023482072`；下载 artifact 并核对 ZIP SHA256，业务回执 succeeded，七项检查全部通过。
控制台显示 v3.2.2 部署成功，升级/预升级测试/删除入口恢复；旧 unknown 历史保留。
线上语言协商三项（中文、英文、显式优先）通过；用户确认已登录新版个人中心，浏览器核对
账户名片与两种应用列表正常加载。Google/GitHub 当前未配置，账号页面邮箱状态未验证；
不声称已完成第三方授权、真实投递、安全变更或 Access 后台的新一轮登录验收。
证据位于 `linshi/naccount-user-center-20261009/repair-3.2.2-business-receipt.json`、
`springbok-3.2.2-success.jpg`、`live-user-center.jpg` 和 `live-chinese-auth.jpg`。

## NA-10-REPAIR：3.2.1 远程迁移修复（已执行，历史 unknown 保留）

3.2.0 已由 PR #11 合并并发布，main `a8621252ab167e70f4abae6896cc7458faf17235` 检查通过。
SpringBok update `dc-2e367ed28ec944c1943b58fa695ff40e` / run `38019349330` 失败为
`NACCOUNT_SERVER_PUBLISH_COMMAND_CF_7500`，GitHub 执行器绿色不代表应用升级成功。
云端只读核对：0049 已执行、0050 未生效，两个 Worker 均保持 3.1.0 发布版本。
远程 EXPLAIN 复现旧 trigger 的内层 `END;` 分句失败；等价 RAISE/WHERE 修正编译通过，零行写入。
源码提交 `e070108ab9ab93e6bd45dca4059c47a2f192fb7b`；59 项安全/资料/弹窗回归通过。
新增应用自有的 security-migration repair，使用 SpringBok 原生父子任务/permit/回执机制，
只接受固定失败版本与只缺0050的现场。真实只读 preflight 通过；90 项 SBA 测试通过。
只读审阅发现 portal callback 额外值可能被 publish 改写，已改为精确预检和发布只读模式，补拒绝测试。
该修复已执行，但收尾校验失败，最新现场及接续方案见上；原失败记录不修改、不清锁、不 rerun。

## NA-10-RELEASE：3.2.0 发布（已发布，升级由上方修复收尾）

负责人：主 AI。用户已授权提交推送 GitHub，并通过 SpringBok 更新现有实例。
范围包括 NA-10 用户中心、安全流程与中文认证，不重建数据库、不初始化管理员、不改密码。
迁移 0049/0050 为新增表、列、索引与触发器；由既有 update 流程导出备份并校验旧行保全。
只读发布审阅未发现新版本安全/功能阻断；旧 S2S token 需重新签发，真实 provider 仍须配置。
精确源码全量回归 148 文件 / 3084 项通过，TypeScript 与客户端/Worker 构建通过；主仓库
100 项及版本调整后 SBA 子套件 84 项通过。定制提交 `858eccd4add4bc3873f4835cf9d21d54b543094c`，
导出 generation `91f42ab6b29e379353b79bf907cdb529fdea06f5b8e1bbadbaf8e882c5def88b`，verify 通过。
新增语言覆盖后重新全量复验，同步系统信息测试的中文配置预期，不改变业务断言。
PR #11 及 main CI 通过后已发布；首次线上升级失败，结果和后续恢复见上方两节。
以下“未发布”段落为各开发阶段的历史状态，最终交付以本节及发布记录为准。

## NA-10-S02/S03：用户中心完整安全流程（本地开发与验证完成，未发布）

负责人：主 AI。补齐已确认的邮箱/独立手机验证码绑定、密码修改、TOTP 三步启用/禁用、
自助注销；使用真实发送适配器和 D1 限时事务，禁止演示码与管理员接口代办。
同时完成安全变更后旧 access/refresh/SSO/auth-code 的用户级失效及安全回归。
本轮仅本地代码和隔离验证，不读取生产秘密，不执行生产数据删除或上线。
已接入完整二级弹窗、D1 一次性事务、发送适配器、身份复核和全用户安全版本撤销。
审阅补齐系统/应用强制 MFA、证明目标变化及配置变化的拒绝；保留最后超级管理员。
最新验证、能力配置和未发布边界见 [USER_CENTER.md](USER_CENTER.md) 的 S02/S03 记录。
标准 Cloudflare 套件 148 文件 / 3072 项全部通过，TypeScript、客户端/Worker 构建和
git diff --check 通过；57 个业务变更文件与测试/浏览器副本逐字节一致、无 BOM。
本地 D1 迁移和真实浏览器弹窗/390px/焦点恢复已验证。下一步为本轮授权后的补丁交付，
以及真实外部 provider 配置/投递、生产升级和用户验收，不再将这些称为未实现的安全接口。

## NA-10-S01：已确认用户中心设计接入（本地实现，未发布）

负责人：主 AI。将本地确认的 Neuro 名片/应用卡片设计迁移到正式 `/account`，
保留 Beaver 标识、紧凑布局、独立用户菜单和已修复的 tab 状态。
本子任务接入真实资料读写、社交管理与已有安全 policy，不使用演示验证码或假成功。
同时核查手机号、MFA、账户删除与应用目录的权限/数据边界；缺少安全接口的动作
不得用本地状态模拟完成。只做本地开发与验证，不推送或生产部署。
已完成名片/应用列表、昵称签名独立存储、社交二级弹窗、真实状态与安全 policy 入口。
TypeScript、161 项聚焦回归及客户端/Worker 构建通过；真实本地浏览器已验证
PKCE 登录、昵称签名写库及刷新保留。详见 [USER_CENTER.md](USER_CENTER.md) 的 NA-10 记录。
未提交、未导出新补丁、未推送或部署；生成补丁仍为上轮版本，不可据此发布新界面。
S01 当时未完成的独立绑定、两步验证启停及注销，已由上方 S02/S03 接续实现；
这里的 161 项和 policy 桥接仅为历史阶段证据，不代表最新完整功能实现。

## NA-09-S02/S03/S04：社交绑定、统一身份与部署集成（本地实现与验证完成，未发布）

负责人主 AI。仅本地开发、验证、提交与导出；无推送/云写授权。
Google/GitHub 使用独立的一次性绑定事务，登录账号确认密码后发起第三方授权；回调同时校验
随机 state、浏览器绑定、PKCE/nonce 和原账号仍有效。社交身份唯一归属，禁止邮箱合并。
已绑定登录解析回原 user/authId；数据库约束覆盖并发绑定与独立社交注册冲突。
部署集成负责独立 portal SPA client、provider 公开参数与 preview 隔离，保留 admin-only repair 边界。
SpringBok 当前没有 optional provider secret 合同，不能在 manifest 中擅加必填秘密；真实启用需单独配置认证 Worker secrets，或使用 standalone CLI 的 secretNames。配置清单、验证证据与限制见 [USER_CENTER.md](USER_CENTER.md)。
主仓库标准测试 100/100、部署子套件 84/84、门户/社交及既有 provider 回归 221/221、既有认证扩展回归 181/181 通过，TypeScript 与客户端/Worker 构建通过。浏览器验证普通用户登录、资料编辑入口与 provider 未配置状态；真实第三方授权、邮件、PG 运行及云发布未验证。
下一步仅为发布准备与外部 OAuth 配置、实际授权验收；没有用历史授权执行云写入。

## NA-09-S01：普通用户入口与个人中心（首阶段历史记录；部署集成见上）

负责人主 AI。边界、社交绑定后续验收与配置见 [USER_CENTER.md](USER_CENTER.md)。
本轮先接入独立普通用户门户与现有认证策略，禁止放宽管理员后台权限。
社交绑定不得复用管理员的双账号 linkedAuthId 关联来伪装统一身份；第三方身份安全绑定和登录归一另验。
用户已授权本地提交与补丁导出。定制提交 `2774512cf4eb50bd0a51120e5d896dab425cd2ee`，topic `user-portal`；
export 与 verify 通过，generation `d88c6ec5846ec3eb31b978dc6560ff0a22b8c724e1cf7d7647a1bddcf8a31ebb`。
门户/既有登录视图回归107项、主仓库回归95项、TypeScript与客户端/Worker构建通过。尚未推送或发布；
独立portal client的SBA自动配置和真实浏览器OAuth验收未完成，不能宣称线上可用。
下一步为已确认的Google/GitHub自助绑定与同账号登录，并补齐部署集成；不使用历史授权云写。

## NA-08-S01：仅补发后台的正式修复（2026-10-09）

负责人主 AI。用户选择 SpringBok 控制台 repair，不通过本地 CLI 补发。
拆出管理员客户端的只读检查：复用现有 SPA/S2S 身份与密钥，要求回调已经登记，
不得借配置读取执行 UPDATE。已接入占位 Worker 前置检查、数据与认证配置保持证明、
admin-only 构建发布和真实资源配置就绪检查。3.0.3新增repair声明，尚未发布或执行修复。
只读客户端路径已实现；新增成功、回调缺失、停用、身份漂移、空ID/密钥及重复客户端
回归，前轮标准 Python 测试 83/83 通过。本轮完整回归及精确PR另验。
只读审阅指出内部表筛选LIKE下划线通配符范围过宽，已改为字面前缀GLOB并加相似名用户表
覆盖；新增provider占位漂移、域名/绑定/vars/assets、认证变化、分页上限及不重放测试。
配置就绪不等于后台登录验收；保持Access，秘密与行内容不上传artifact，不以HTTP登录页判成功。
本轮标准套件94项通过，收尾增加repair unknown回执测试后的部署子套件79项通过；补丁栈verify
通过。真实Cloudflare只读preflight及两次22表/三密钥/auth状态采样通过，未云写。证据在
`linshi/springbok-rebuild-retry-20261009/repair-live-readonly-proof.json`。精确提交、PR及发布另验。

## NA-07-S03：失败发布的安全诊断（2026-10-09）

负责人主 AI。线上固定 3.0.2 的任务 `dc-082d9d6d909a46c6b41cd149e0de729d`
在 admin-publish 阶段停止，认证服务、管理员与数据库已存在，后台只有 secret 占位 Worker。
本子任务仅补充固定命令类别、Cloudflare 数字错误码或固定网络/启动失败类别，沿用 SBA
既有 errorCode 字段，不上传原始 stdout/stderr、参数、异常、凭据或业务内容。不更改 unknown
状态和恢复锁，不重放初始化，不以 Actions success 代替应用结果。安全恢复与线上发布另验。
本地标准测试 81/81 通过，新增 8 项诊断/秘密隔离/不重试/unknown 与构建哈希围栏检查。
只读审阅发现新诊断模块的哈希覆盖遗漏，已修正并完整复验。尚未提交、推送或部署；
线上仍保留原 unknown。证据 `linshi/springbok-rebuild-retry-20261009/diagnostics-tests.log`。

## NA-07-S02：首次管理员自动初始化（2026-10-09）

负责人主 AI，分支 `feat/na-07-admin-bootstrap`。3.0.2 声明可选 Gmail 管理员邮箱和
deployment-only 密码；默认/覆盖密码由 SpringBok 加密管理，经一次性 permit 提供。
仅 deploy 创建不存在的新邮箱用户，以随机 authId 精确关联真实 super_admin 角色。
密码在执行入口移出环境，隔离 helper 用锁定 bcryptjs cost12及20字节OTP材料；
不进入 npm/Next/Wrangler、Worker secret、公开配置或回执。update/preview均不重设密码。
同邮箱碰撞拒绝，邮箱/MFA仍需正常验证。两次D1写入非事务；部分失败为unknown，不重放。
已通过完整46迁移SQLite初始化聚焦检查与真实锁定依赖helper；标准测试、PR/main和真实部署另验。
标准测试73/73通过、补丁栈verify通过；源码只读审阅未发现安全阻断。补齐构建环境不含密码、
初始化先于发布及runtime secret拒绝检查。真实子域名与新管理员登录随SpringBok发布后另验。

## NA-07-S01：后台无限加载修复（2026-10-09）

负责人主 AI，分支 `fix/na-07-admin-loading`。用户已授权开发两仓库的部署体验改进。
本子任务仅修复刷新 token 沿用登录时旧 roles、后台 `/api/info` 失败后读取 undefined.configs
导致无限加载。角色刷新读取当前有效授权，同时覆盖新增与撤销；配置读取有 15 秒超时、
取消、失效响应隔离、明确错误和手动重试，保留服务端权限检查。
线上复现：userinfo 已有 super_admin，刷新 access token roles 为空，配置 API 400 空响应。
本地隔离源测试 83 项 OAuth、16 项后台组件/加载检查通过，双端 TypeScript 检查通过。
首次测试缺本地测试 RSA 密钥而失败，生成隔离测试密钥后完整复验通过；没有访问线上密钥。
补丁 topic `admin-loading`，交付版本 `3.0.1`；标准编排测试、精确 PR/main、上线验收另记。
后续管理员邮箱/部署密码密钥化、Zone/子域名资源为独立任务，尚未实现，不能由本项代称完成。

## 依据

用户要求参照 MiDot，以独立子目录仓库接入 Melody Auth，自动生成和使用定制补丁，并在根目录设置部署入口。MiDot 实际使用忽略的独立 checkout，不是 Git submodule；精确恢复提交依赖增量 bundle，普通补丁重放只保证源码树。

## 本轮验收

1. 主仓库连接 `aiaimimi0920/NAccount`；`melody-auth/` 保留官方 Git 历史、官方远端和独立分支。
2. 提供固定 SHA 初始化、自动导出、完整校验、独立目标补丁重放、上游 rebase 与冲突续接。
3. 导出采用不可变 generation 和最后更新的指针，不删除既有补丁，不让半次导出成为当前版本。
4. `.sba/` 提供环境配置、离线计划、隔离构建、Wrangler dry-run 和显式发布。部署配置不污染上游 checkout，日常更新不自动升级上游或旋转签名密钥。
5. 临时 Git fixture 覆盖空栈、有补丁、精确恢复、内容重放、dirty 拒绝、目录边界、篡改、上游更新与冲突；实际 Melody Auth 做可完成的本地验证。

## 完成状态

上述本地工程验收已完成，详见 [验证记录](VALIDATION.md)：30 项回归通过，服务端和管理后台均完成真实隔离构建及 Wrangler dry-run。当前主仓库尚无提交，未推送；未进行 Cloudflare 外部写入。使用入口见根目录 README、`customizations/README.md` 与 `.sba/README.md`。

## 非目标

- 不新增账号业务功能，不制造一个没有业务需要的示范补丁。
- 不创建 Cloudflare 资源、不读取现有私密凭据、不执行真实云部署。
- 不提交或推送项目，不改动 MiDot，不替换或删除其他仓库内容。
- 不将脚本测试、构建或 dry-run 宣称为注册、邮件、跨应用 SSO 的生产验收。
