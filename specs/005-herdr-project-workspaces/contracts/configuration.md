# Configuration contract

这是实现接口；本轮未部署到真实HOME。来源为公共静态文件、现有私人machine TOML、已准备工具；未知字段失败，secret不进入work/handoff。

## Machine extension

现有machine表内增加可选work；缺表时work退出2并指导配置，不从默认Agent profile猜测。沿用互斥的--machine NAME / --local FILE，读取普通配置不加载凭据。

普通入口先使用同一严格load_local(..., load_credentials=False)校验本地文档。只有本地原生Agent选项覆盖明确需要adapter-schema上下文时，才加载原完整公共catalog并重新严格读取/校验；未知profile或无效原生字段仍失败。其他schema/版本/路径错误不触发兜底成功；第二次读取仍复核私有路径/属主/权限。无原生选项覆盖的普通终端配置不展开无关Agent公共来源；Agent启动仍经既有prepare/run完整校验。不增加持久缓存、宽松schema或凭据读取。

```toml
[machine]
editor = "/opt/editor-profile/bin/avalon"

[machine.work]
herdr_binary = "/opt/herdr/current/herdr"
session = "main"
pi_profile = "pi-base"
dsh_profile = "dsh-default"
codex_binary = "/opt/codex/bin/codex"
codex_daemon = false
```

示例路径虚构。herdr_binary/session必填；pi_profile/dsh_profile/codex_binary可省略，只在对应role请求时要求。profile必须是已准备且agent匹配的既有ID。binary/editor为单个executable绝对路径或简单PATH名称，不接受带参数shell文本。session为1..64个ASCII字母数字/下划线/连字符，首字符字母数字，不含路径分隔符。codex_daemon为布尔，默认false。无独立Codex适配器，不改Pi委托。

Linux每UID共用 `/tmp/rotom-work-UID/operation.lock` 无内容mutex，与machine.paths.state_root无关，防止不同local选择同server却绕过锁。父0700/文件0600、同用户普通文件、O_NOFOLLOW，锁文件永不unlink，不自动修复不安全既有路径；不存terminal registry。work配置拒绝provider/token/credential/resume-session/recent-project字段。shell/edit使用load_credentials=False，禁止SecretStore.resolve；Agent秘密只在既有run中按需解析。

## Optional termcfg component

herdr加入component enum和init-local显式选择，不自动加入旧machine。catalog只声明：

| ID | Source | Destination relative to target_home | Mode |
| --- | --- | --- | --- |
| herdr.config | terminals/herdr/config.toml | .config/herdr/config.toml | 0600 |

catalog记source SHA256，消费静态字节，不插值私人路径。只支持此默认位置；HERDR_CONFIG_PATH/XDG_CONFIG_HOME若指到不同位置，doctor/plan与work预检报2，不改外部位置或静默重定向。unset或规范路径等于上述位置可用。部署/adopt/冲突/恢复/rollback复用现有API，不接管目录。

state仍v2，只扩component enum/previous可选herdr键。旧zsh/tmux语义不变；旧代码不能读新增记录，代码回退前必须处理pending/受管状态。配置rollback不构成软件/state降级。未选herdr不要求Herdr binary，不阻断旧机器。

## Static initial config

```toml
onboarding = false

[keys]
prefix = "ctrl+x"
detach = "prefix+d"

[terminal]
default_shell = "rotom-work-shell"
shell_mode = "non_login"
new_cwd = "follow"

[ui]
prompt_new_tab_name = false
confirm_close = true
agent_panel_sort = "spaces"
sidebar_collapsed_mode = "hidden"
window_title = "{hostname}: {workspace} / {tab}"

[ui.sound]
enabled = false

[ui.toast]
delivery = "off"

[session]
resume_agents_on_restore = false

[update]
channel = "stable"
version_check = false
manifest_check = false

[experimental]
pane_history = false
```

default_shell/shell_mode是安全argv启动所需的增补。PATH中的launcher必须指向同一准备完毕的Rotom checkout/.venv。work仅为新server子进程PATH前置仓库根，既有server不重启或改环境；手工原生启动先准备PATH。doctor验证入口可执行/来源/venv/配置意图，实际生效靠原生诊断和新tab握手，不能只验证TOML可解析。Herdr解析错误可能退回默认。work要求文件存在且为当前用户的私有普通文件，检查上述三项准入意图；启动新server前以同一绝对路径运行官方herdr config check，非零诊断或检查期间文件改变阻止启动。该只读命令不连接server，但缺文件会无诊断使用默认，因此先验证文件存在。既有server的实际配置仍靠独立原生验收，不因磁盘文件通过而称其已重载。

non_login保证wrapper无额外shell参数。无payload时执行原SHELL（空值/bin/sh），拒绝指回launcher递归。zsh提示符与shell集成要实际验收，不假定wrapper透明。hidden是侧栏折叠后的行为；Goto保留prefix+g，不抢无前缀Ctrl+h/j/k/l。中文/Shift+Enter/前缀字面输入/OSC52只写/resize需逐客户端证明。

## Startup and environment

| Role | Executable / argv | Preserved boundary |
| --- | --- | --- |
| shell/build/debug | 原交互shell，cwd=checkout，无任务命令 | label稳定，不猜编译/调试命令 |
| edit | machine.editor executable，无shell文本，cwd=checkout | 独立Avalon launcher，不用NVIM_APPNAME替代；Review显式刷新/选定文件交接 |
| pi/dsh | repo agentcfg + 原选择器 + --profile ID run AGENT --cwd ROOT | 不sync/apply/install，不另设workspace HOME，不迁移账号/state |
| codex | codex_binary + 默认--no-daemon（true则省略），cwd=checkout | 不改alias/Pi委托/活动daemon，不自动选最近会话 |

参数数组保持字面；handoff在exec前删除，不能被子shell/新分屏再次消费。agentcfg保留既有env白名单，work不全量继承父环境到受管Agent。

## Optional status

默认全关，不装controller skill，不为状态开放socket沙箱。只有显式选择实例并验证公开扩展/依赖后，才经既有资源声明Pi扩展、既有锁声明DSH插件；不强制peer、不新profiles、不改宿主。不兼容则记录原因并保持关闭，普通Agent终端继续可用。

实际需要的HERDR_ENV/HERDR_PANE_ID/HERDR_BIN_PATH/HERDR_SOCKET_PATH仅经machine.environment.inherit逐项选择，不自动加入。环境选择不构成socket隔离，不能称仅有状态上报权限。两个并发实例/子Agent/延迟事件分别证明关联，无法证明则unknown，不猜会话、不自动恢复。状态/通知不调度、不判完成、不关闭终端。

### Ordinary terminal and managed Agent environment boundary

新Herdr server和普通shell继承发起终端已有环境，保留用户已导出的普通开发变量；work只剔除失效的Herdr上下文/一次性handoff并为子进程前置仓库PATH，不新建另一套终端环境白名单。Avalon和独立Codex沿用其已选择入口的原生环境行为。终端复用器不是pane之间的秘密或账号隔离边界；用户已导出的值可被后续普通终端继承。这不表示work读取SecretStore、自动注入账号或新增socket权限。Rotom不把server完整环境写入配置、metadata、摘要或日志。

Pi/DSH仍通过agentcfg已部署run契约，在宿主exec之前重新执行现有环境过滤，只有允许的普通变量和显式声明项被继承；所需秘密仅从部署引用按需解析注入。machine.environment只管该受管Agent契约，不暗中改成server环境策略。合成canary检查覆盖普通自定义变量保留、未声明值/凭据名/socket被受管宿主环境过滤；不读取实际环境秘密作验收。
