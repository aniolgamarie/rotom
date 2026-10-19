# 按需模块静态配方与退出边界

核对日期2026-10-19。本文件是候选资料，不是新配置语言或安装清单。
默认均未选。固定`cache-hit-monitor`、`pi-context7`、`pi-brave`、`pi-footer`、`pi-cursor`和`playwright-cli`
已完成静态准入和按选接线，decision=admitted；运行证据按模块和场景分列，
footer与缓存诊断已有Linux本地无账号局部通过，其余原生范围仍not_verified。
显式选择使用公共plugins/mcp/skills数组，变更后必须lock/sync/apply；未选包和支持文件不进入该slice身份。
本文静态配方不抵扣原生加载、服务/账号场景或性能测量。实际A/B/C局部证据见
[原生验收](native-acceptance.md)：官方Pi1.3.0/theme0.1.6、单独footer0.5.1及cache0.1.1
通过本地tmux3.5a三宽度中文粘贴/清除、reload与退出；B偏好经重建保留、C隐藏/重显无残留。
B使用修订observer，最终source为39fa875a…70c1b、锁为e67e22…ec6，完整身份见该记录；
此前250包组合是修订前依赖维护检查点，不能作为新B来源。T037/T058仍partial、T059开放。
真实usage/费用、运行中队列取消、SSH/macOS、D–G原生和账号/服务仍未验证。

## 固定身份和真实读取位置

| module_id/category | 精确canonical、npm gitHead、许可/engines | settings_contract与未满足项 |
| --- | --- | --- |
| context7/documentation | @upstash/context7-mcp@4.4.2；gitHead null；MIT；Node>=20.18.1 | 固定安装的context7-mcp --transport stdio；env CONTEXT7_API_KEY不放argv；Pi原生MCP的toolExposure仅resolve-library-id/query-docs |
| brave/search | @brave/brave-search-mcp-server@2.1.4；8bcb302657b0f072612c2f3e53182ff17912013c；MIT；未声明Node engines | 默认stdio；BRAVE_API_KEY或BRAVE_API_KEY_FILE；真实白名单BRAVE_MCP_ENABLED_TOOLS=brave_web_search；dotenv读取cwd .env需隔离 |
| playwright-cli/browser | @playwright/cli@0.1.22；b85c7a736bb473bf55b584e54a09ffa698d6d871；Apache-2.0；闭包Node>=20 | 选择完整Skill即绑定精确npm与受管CLI；固定PLAYWRIGHT_CLI_SESSION、私有cwd/HOME/XDG/browser目录；禁用通知，不接受用户session/profile/config覆盖 |
| web-access/web | pi-web-access@0.41.0与@kvidzibo/pi-web-access@0.2.1互斥；实际MIT正文已核 | 五类同样例和SRI见module-admission第7节；单provider、scoped缓存隔离未闭合，不注册入口 |
| cursor/subscription | @rahularya01/pi-cursor@1.4.39；实际MIT已核，固定完整选择管线 | plugin pi-cursor与provider cursor配对；固定PI_CURSOR_SYSTEM_CREDENTIALS=0和本实例cache/journal；只允许本实例Pi OAuth；账号/entitlement/实际模型/费用未验证 |
| cache-monitor/cache-diagnostics | @narumitw/pi-cache-hit-monitor@0.1.1；实际MIT已核，按选完整闭包已接通 | src/index.ts；观察实际上报，隐藏widget不能当禁用 |
| tool-monitor/tool-diagnostics | @narumitw/pi-tool@0.3.2；实际MIT已核，闭包待核 | dist/index.ts；pi-tui-kit传递依赖须完整锁定；widget启用每500ms轮询，真实退出待验 |
| ast-grep/structural-search | CLI+完整Skill优先；扩展@nicknisi/pi-ast-grep@0.3.1来源对应未闭合 | CLI身份另固定；不拿0.3.0当0.3.1；限定目录/有界查询/先预览，不冒充C++类型语义 |
| processes/session-process | @aliou/pi-processes@0.13.2；tar无许可正文；精确shutdown hook已核 | 启动/输出/停止候选；PTY才另选unified-exec，单一所有者 |
| tmux/project-long-command | 现有termcfg/项目所有者管理；Pi不另安装 | 显式cwd/session/项目日志；停止/退出/副作用/后代分列，不复建任务数据库 |

未来stdio绑定完整安装路径和已审锁，不使用无版本npx/uvx。HTTP服务另核账号/版本，不以可达代替准入。
Context7的CONTEXT7_API_URL和代理/证书env可改路由；Brave白名单不能限制web_search参数summary和Pro的extra_snippets，
因此不能承诺禁额外费用。Exa/Tavily仅作明确替代，无静默fallback。

| 精确官方元数据 | SHA512 SRI | 包内实际LICENSE SHA256 |
| --- | --- | --- |
| [Context7](https://registry.npmjs.org/%40upstash%2Fcontext7-mcp/4.4.2) | `sha512-cH6N/gyCqtrK9h+FnzyFdWeeufQzfoZ9xXYS3X7IbqktH+NkpFnRkr+VVTNTwdPFAATh4jycuv1QWOXRHN0drQ==` | `85cfb556dc2b22b55d2565674fcdaac82f3f2f6b7a928d27003132721bb6736c` |
| [Brave](https://registry.npmjs.org/%40brave%2Fbrave-search-mcp-server/2.1.4) | `sha512-a34HBs6os4Ilp0yHPV/j3UrgBQH1uTDLsNA9y5IlO30RCYUFm9QPfC0coh2c7WEDxKcHuWjVsrfuXIJNheu9YA==` | `43dc6a32f9c44dd4647cdb3f48677a8681c500a89cfd0e682808d241ec4250a9` |
| [Playwright](https://registry.npmjs.org/%40playwright%2Fcli/0.1.22) | `sha512-6WMkQNM4VEzqMkdr/l60X9Cr7i+tI/arK87IWz2K7pB6j8I2ZJ8KN+1JfhJDLnK+SXnab6Op8xGt4adcGLsyfA==` | `9a7110fc2d2f964038e5dc49128f908f29f47a574c961cba16085914e879cbda` |

三个精确tarball已核SRI/许可/入口；Context7/Brave的组合已ignore-scripts安装并完成静态脚本审计，
该Context7/Brave维护步骤未启动宿主/服务；后续A/B/C宿主验证另列。Context7无安装生命周期；Brave的prepare为格式化/构建且已发布dist，
明确审定ignored_not_required；Playwright无安装生命周期，但依赖Playwright/core 1.64.0-alpha-1790635538000，浏览器二进制/下载未验。
完整Playwright Skill正文SHA256为`9bba755285a4c9ad72a4a41b9c7baef6fb516d329c0b44ed0573715f4479b906`，
须保留完整支持文件/许可；它允许eval/run-code、cookie/storage写、上传/trace，frontmatter含npx路线。
完整保留不等于无条件执行其中安装动作，也不能授予首轮受限调查角色。

## data_boundary、required_evidence与退出

Context7接收query/libraryName/libraryId/language；不自动送机密或内部代码/日志，key仅本实例SecretRef。
Brave接收搜索文本，费用/plan/额度/保留待核；网页/PDF服务逐项声明外发和费用。
Playwright默认内存profile在同会话调用间保留cookie/storage，close后销毁；idle 1h不是立即释放证明。
CLI更新检查写registry缓存，关闭通知和隔离缓存仍需验证。Cursor的journal副本、保留/清理、认证和实际模型/费用unknown。
processes不承诺SIGKILL/OOM/脱离后代/重启恢复；tmux交接保存目标、命令、cwd、日志、退出码、失败和下一步。
PTY/stdin/REPL才触发unified-exec比较；取消不等于退出，副作用unknown不自动重试。
AST搜索与改写分开，clangd/编译器由项目管理；Serena先核索引/进程/数据边界，不默认常驻全库服务。

Cursor选择只接受provider ID/route `cursor`、owner `pi-cursor`、protocol `oauth-dynamic`、
auth_kind `oauth`，无base_url/credential_ref。启动清除全部CURSOR_/PI_CURSOR_/USAGE_SESSION_TOKEN
继承项，再只设置固定系统凭据关闭键和本实例缓存路径。允许的账号来源是该实例Pi OAuth存储，
不是“仅环境token”；管理器离线不读auth，原生插件登录另授权。精确selected remote model仍可能
未获entitlement或不在实际catalog，保持待验证、不跨provider回退。禁用保留auth/cache/journal。

禁用只停止下次加载/连接，不删除缓存/账号/会话/下载或终止用户进程；历史清理由明确所有者另行处理。
不接管termcfg/个人浏览器，不复制登录。隐藏widget不是禁用或零成本。
静态evidence_refs为本文件及[module-admission](module-admission.md)；未选零副作用见test_pi_optional_modules。
选择、缺凭据、服务故障、取消、禁用、组合的管理器隔离路径已通过；真实服务/账号六场景仍not_run。
其余未准入候选明确拒绝，不能当同类能力已实现。升级使相关证据失效，须显式重锁重验。
默认未选不等于已交付组合获得豁免；新增可选入口的原生/服务、性能门仍开放，不作更快或省token主张。

## 已实现入口的严格设置契约

- `plugins=["cache-hit-monitor"]`只允许固定canonical/version/entry，无任意namespace；加载src/index.ts，禁用即不传-e。
- `mcp=["pi-context7"]`或`["pi-brave"]`仅接受registry固定stdio command/args和可选credential_ref。
  Context7可无key；若声明引用则必须有值。Brave必需secret:pi_brave_key，缺失在spawn前exit3。
- `pi-home/mcp.json`采用公开mcpServers/exposure/toolExposure。全部env叶子只能是声明的
  `${AGENTCFG_PI_MCP_<16位大写十六进制>}`引用；实际值仅本次环境注入，不进入原生文件或备份。
- stdio command固定为当前Python及sealed support/mcp-launch.py，后者只exec已锁定node入口；
  不fork、不用shell。它清除Pi宿主默认继承的模型/其他服务凭据及路由覆盖，只保留该服务allowlist。
- 每服务cwd/home/XDG均实例私有目录；dotenv不访问项目。Brave仅brave_web_search，仍不限制其收费参数。
- 每类别固定一个所有者，MCP仅官方builtin:mcp承担；未选时--no-mcp，既不创建连接也不默认常驻。
- 禁用通过公共FIELDS与created_parents剪自建空容器；用户新增原生字段和缓存/auth哨兵不删除。

证据：tests/test_pi_optional_modules.py及acceptance继续实施记录。真实数据外发、费用、账号、
provider回执和平台组合仍需独立验收；原生状态保留不是服务成功或零开销证明。


Playwright后续core静态补审已确认：首次open缺浏览器仅失败提示独立install-browser，
不自动下载；它会启动独立daemon并写私有缓存。完整Skill及10份指南已核，
已完成完整Skill和固定CLI接线，9文件299项隔离回归通过；没有下载二进制、启动CLI/daemon或
验证真实关闭闭包，不能抵扣T085/T086。精确core SRI与调用链见module-admission第12节。

`skills=["playwright-cli"]`只将当前实例的受管入口加入Pi主运行PATH，按主运行生成独立session；
禁止attach、install/install-browser、persistent/profile/config、跨会话关闭和session覆盖。
私有自动cli.config.json出现即拒绝，不读取正文。浏览器二进制缺失时停止，不自动下载。
关闭页面、daemon退出、Pi退出和全部后代释放分开判断。禁用删除受管入口、停止下次接线，
保留本实例缓存/下载/状态，不终止进程。完整上游资料原样保留，但其中浮动npx/安装等建议
不适用于受管入口；主会话完整Bash不受wrapper强制约束。

`cpp-bounded-investigation`、`long-command-handoff`是可选纯方法Skill，不增加npm包或工具，
使用项目已验证工具、现有tmux/日志。AST/编译语义和停止/退出/副作用的限制见module-admission第13节。
