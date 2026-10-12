# Linux / Pi 1.0.1 原生用户 Bash 接口限制

当前决定保持 `official-file-runtime.ts` 的 `user_bash` 固定拒绝：`PI_COMMAND_ADMISSION_UNAVAILABLE`。不接通原生 TUI `!` / `!!` 或 RPC `bash`，不实现会把终止未知折叠为普通取消的 `BashOperations` 入口。模型使用的受管 Bash 工具继续走自己的准入和执行路径，终止未知保留 unknown / protected，不以取消请求释放 Writer。当前设置拒绝非空 `shellCommandPrefix`，不宣称支持任意前缀。

此决定来自固定候选公开 API 的静态源码证据，不是原生执行测试，也不是 OS sandbox 不可行的结论。T013/T020 的原生前端部分仍处于公开 API 不足、环境未验证状态；正式任务保持 7/100。保留现有终止契约，其他工作继续。

## 公开接缝及阻断点

`user_bash` 事件只有原 command、cwd 和 excludeFromContext，没有认证的人类身份或 Bash 专用 signal。返回 `{operations:{exec}}` 可以通过公开接口取得最终 command、cwd、onData 和 executeBash 创建的 AbortSignal；最终 command 已包含配置前缀，未来确认必须展示并 exact true 确认实际最终 command，不能只确认较早的事件字符串。`hasUI` 仅表示可用对话框，不证明人类身份或授权。

返回 `undefined` 会继续其他 handler，最终可回退到本地 Bash。因此空监听不是阻断；当前抛出固定错误阻止此 fallback。公开 operations 回调只返回 exitCode，并提供合并字节流，没有 terminationConfirmed。更关键的是固定 SDK 的 `bash-executor.js:86-103` 在 signal.aborted 时将任何 throw 投影为 `cancelled:true, exitCode:undefined`；自有执行器的终止未知异常也会被折叠。非取消异常才会重新抛出，且 UI/RPC 会展示其 message，未来入口也必须只传固定非秘密错误。

这与 [执行契约](contracts/execution.md) 第33行的“真实终止与资源回收后才报告 canceled”，以及第108/109行的 unknown/blocked 和分离取消/停止/回收观察要求冲突。不能把 SDK 的 cancelled 当作停止收据。禁止修改上游、缓存/vendor副本、monkey patch、原型改写或私有接口绕过。

另一个公开 `{result}` 路由在 executeBash 建立专用 AbortController 前完成，没有 executeBash / abort_bash 的可靠取消关联；ctx.signal可能缺失，因此未选用。SDK onData 超阈值还可能写临时日志，公开输出投影不能自动承担自有有界输出与终止证据契约。

磁盘扩展先于 inline factories 加载的顺序问题已有自有防护：`official-resources.ts` 在公开加载结果上核验守卫工厂、原始 handler 引用和原生 Map，并拒绝其他扩展已登记的非空 `user_bash` handler。公开 `getExtensions()` 返回新的冻结结果和冻结数组，把原守卫扩展放在第一位，保留其他扩展相对顺序、扩展对象和 Map、runtime/errors/warnings 的原引用，不修改 SDK 的缓存或方法。这样公开 `pi.on` 在检查后添加 handler 也只能排在固定守卫后。旧实现的晚注册行为红为52通过/1失败；最终一次默认组合为251通过（54项守卫检查加197项相关检查），独立稳定复审无剩余P1/P2。证据归档在 `native-command-guard`。这是公开接口兼容的离线证据，尚未对当前字节运行官方 SDK；选中扩展仍是可信的同进程代码，投影不是插件隔离沙箱。

需要上游公开错误投影与终止状态扩展，或基于公开接口设计满足同一终止契约的替代入口，才考虑接通原生 ! / !! / RPC。当前不把模型工具的受管能力等同于原生用户 Bash 已支持。

## 固定源码依据

以下路径相对于固定候选 `pi-1.0.1/closure/node_modules/@earendil-works/pi-coding-agent/`，SHA256来自静态报告，均未在本任务执行。

| 文件 | 行与事实 | SHA256 |
| --- | --- | --- |
| `dist/core/extensions/types.d.ts` | 212–242：hasUI/signal；861–871：事件；1062–1071：返回联合 | `abd9e9be0bf21b4c35621fe90b79af75c85b774e8b254b515d699785fda5962a` |
| `dist/core/extensions/runner.js` | 975–1001：undefined继续，operations/result处理，异常重抛 | `258f142bc56cc84d953ef6146222e5ff3a94cc908592a1b3d075d34bbcd68b36` |
| `dist/core/tools/bash.d.ts` | 35–51：公开exec参数与exitCode投影 | `016eb820fa6e426fc590f12cb4a80a88cbeb1dc19697e4720774fe538966e6e3` |
| `dist/core/agent-session.js` | 3058–3116：前缀、专用signal、结果记录及abortBash | `35ca1dabd54d98c236c9601b569c2856b726ade392d06b2eaaf50158f48913ab` |
| `dist/core/bash-executor.js` | 22–84：流与临时日志；86–109：取消时折叠异常 | `22c0547e394ee84eb2f36632bf3f0246f867184e3bf49c68371c7cb709e4fd0b` |
| `dist/modes/interactive/interactive-mode.js` | 2644–2658、5800–5870：!/!!、两路返回、错误阻断 | `14508d43f3dd47faa6b10c4a6537740f1cf238eee3fc873a9e0648125214bbcc` |
| `dist/modes/rpc/rpc-mode.js` | 439–461：bash/abort；625–637：错误响应 | `631697cd35928fc827f4a423538c43ff227b8cbf63c2a2f11060616f55eba6db` |

原静态快照中的自有调用链：`official-file-runtime.ts:15-19`固定拒绝，`:44-76`仅为选中Shell建立模型准入/工具；`official-file-admission.ts:133-147,187-195`要求UI和exact true；`official-shell-tool.ts:30-58`禁止SDK原execute fallback并调用自有执行器；`shell-operation-executor.ts:99-160`保留终止事实，`:154-155`拒绝终止未知；`official-settings.ts:91-100`拒绝非空前缀。后续守卫接线已改变前三个加载相关文件；旧快照保留为历史依据，当前六文件SHA另见守卫归档。

原接口限制证据来源为 `/tmp/pi-public-user-bash-seam.md/.json` 与 `/tmp/pi-user-shell-interface-detail.md/.json`。后者补充了取消时任何错误都会被折叠的限制，覆盖前一报告中“未知终止可通过throw保留”的初步建议。后续守卫只执行默认假宿主检查，没有运行 SDK、Shell、TUI/RPC、模型、账号或网络，不能据此记原生入口或产品验收通过。
