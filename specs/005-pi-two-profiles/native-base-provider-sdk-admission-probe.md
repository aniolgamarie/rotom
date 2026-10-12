# Base 本地扩展公开 SDK 加载与注册探针

2026-10-09，review01。实现依据为 [加载与注册契约](base-provider-sdk-admission-contract.md)。用户已明确授权本四场及同边界必要修复重跑；四场一次实际运行均通过，未修复或重跑，授权已满足并闭合。下面 fixed false plan 与关闭守卫描述属于授权前准备记录：runner 目录中的 `false-plan.json` 为 2,829 字节，SHA **`944e5250a91f75de7d996d07cba64a576ff265b9995a3510b2741fe4052e018c`**。

## 当前实际结果

| run | case | 扩展/错误 | 结果字节 | 结果 SHA256 |
|---|---|---|---:|---|
| footer01 | footer-only | 1/0 | 691 | `0bebd4946d65fb5120aa6c35b3f81afd2a355e1bf0a6fa3fd51ead11994f769f` |
| loop01 | loop-only | 1/0 | 829 | `ddf0ec5fd827afba6697adc4cb3bd60a8996321399f30dacf16fdba34961686c` |
| todo01 | todo-only | 1/0 | 836 | `32b2e21d89598c7e91d41d2c2e84065f273d56ac6d24c2bc82ad243aa5263308` |
| combined01 | combined | 3/0 | 1,885 | `e36b544c860f067ca961e55a9529b2cc2d83b4391fe1ce00e6bfbf4f5226b305` |

四场均为 Pi/AI/Node 1.0.1/1.0.2/24.14.0，child、wrapper、tool 退出为零；stderr0、pipe EOF、原 group empty，固定材料和完整安装树端点前后一致。root 用原关闭 schema oracle 检查实际结果，与 work 中的实际文件逐字核对；独立 scout 复核保存文件和报告，无差异。stdout 与实际文件一致由执行器当场核对；原始 stdout 没有另存，独立复核不冒称重新取得。

授权前像 receipt `84d88b2e6d08a52077d8afc12da3ce1a84722bdd3cf36443187ba8c3bfca6184`、授权后冻结 `4b23409c24324ef84350de86c7167d483a745e1d16c019299f8b762b00be6ce1`、23 输入 root 有限验收 receipt **`4732056b3c26cb95f16052691e43b5c53d858e7d9aeb19eb8089c945877a8767`**，对应目录均在 `.cache/pi-two-profiles/run-20261004/`。结果只支持本四场公开 SDK 加载与注册，`native_qualified:false`；完整 lifecycle/UI/session 持久化、SourceHold、controller、全后代停止及产品仍未资格，未提升真实 provider 声明或发布正式锁。

## 四个固定场景与验收

| case | 归档扩展 | 必须观察的公开注册项 |
|---|---|---|
| footer-only | `rotom-footer-v1` | 2 个命令、4 种事件，无工具 |
| loop-only | `rotom-loop-guard-v1` | 1 个命令、7 种事件、1 个 entry renderer，无工具 |
| todo-only | `rotom-todo-v1` | 1 个命令、1 个工具、6 种事件、2 个工具 renderer |
| combined | 上述三者 | 同一 loader 中全部出现，命令与工具所有者不重复 |

各场独立 Node 进程和新私有 work。实际归档入口来自当前 Base install01 的只读包。仅通过官方包根的公开 `DefaultResourceLoader`、`SettingsManager.inMemory` 加载入口，关闭自动资源发现，读取公开类型所定义的注册 metadata。没有会话、ModelRuntime、工具或命令调用。错误为零，入口数量、注册名称、每种 handler 数量、版本与所有有限字段必须精确匹配；未知字段、重复 JSON key、非有限数值、缺项或额外资源均拒绝。

三个自有扩展读取的 manager Symbol 只获得本场合成 fixture，提供所选 plugins 和固定 options。此标记不修改官方 SDK 对象或原型，也不授予真实 manager、SourceHold、权限或预算身份。Todo 工厂会创建源码已有的 unref prewarm timer；此包不调用 session handler、UI 或 prewarm 结果来证明业务行为。

## 材料与授权转换

| 材料 | 字节 | SHA256 |
|---|---:|---|
| driver.mjs | 13,301 | `24c8e4858601c5daa5b5c420e97a5d8a1ec1feba3740708e36f4271cff22838a` |
| case plan.json | 2,339 | `f275d29d08a3bd592e39df93af67117a020d87a8600ae1a3ae7f1042ad7de6bf` |
| executor.py | 28,504 | `1c5a0c90e465790964a4a22f9b93f61b9c7eb696bc17065c086fc57fb7df7bd5` |
| material-pins.json | 1,376 | `ccac346186e7451f9c28e185b43d5da0d5fd6d3039e1ce576fbddafddb07dddb` |

driver 与 case plan 位于 `.cache/pi-two-profiles/run-20261004/base-provider-sdk-admission-preparation-review01/`；外层 runner 与 material pins 位于 `.cache/pi-two-profiles/run-20261004/base-provider-sdk-admission-runner-preparation-review01/`。两个可执行守卫是 driver、executor 中的自有字面 false，CLI 和环境不能开启。case plan 的 `EXECUTION_AUTHORIZED:false` 是材料元数据，runner 绑定它的完整 SHA；它不构成第三个可执行守卫。

用户批准具体固定计划后，root 先保存这些文件及 material pins 的即时前像，再仅开启两个自有守卫，将 case plan 的授权元数据同步为 true，按依赖次序更新 plan/probe 的 material SHA 和 executor 预期 SHA，冻结授权后材料。保持 `native_qualified:false`，不更改官方 SDK、第三方源码、安装树、生产配置、插件声明或锁。同边界必要修复须保留失败材料和日志，并使用新 run-name；扩大场景、接口、资源或隔离边界时重新审查授权范围。

固定调用形状如下；依次使用四个 case，初次 run-name 分别为 `footer01`、`loop01`、`todo01`、`combined01`。

```text
/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8
  /usr/bin/python3.11 -I -S -B
  /data/1/weixiaoxian.wxx/dev_tool/rotom/.cache/worktrees/pi-toolkit-upgrade/.cache/pi-two-profiles/run-20261004/base-provider-sdk-admission-runner-preparation-review01/executor.py
  --case CASE_ID --run-name PRIVATE_NAME
```

## 隔离、观测与限制

自有 Python supervisor 在 bwrap 外核对固定材料和安装树，运行前后必须一致。每场通过固定 `/usr/bin/bwrap --unshare-all --die-with-parent --new-session --cap-drop ALL` 启动固定 Node v24.14.0 单文件。候选包、Node、driver、plan 以及 `/usr /lib /lib64` 只读；新 `/proc`、`/dev`、临时 tmp 和私有 work 可写。Popen 父环境为空，内部仅固定临时 HOME/XDG、empty-bin PATH 和 offline 环境；不挂真实 HOME、业务根或 socket。

不读取真实账号或凭据，不调用模型或网络，不启动 Pi TUI、Codex、MCP，不部署。官方 Pi/AI 版本必须为 1.0.1/1.0.2。安装树为 16,653 条目、124,615,286 regular bytes，保存的完整 inventory 为 5,318,454 字节；原生前后校验复用这一固定来源证据，不创建 seal 或当前运行包。

每场 driver soft timeout 20 秒，GNU timeout 为 60 秒、kill-after 5 秒，wrapper 执行预算 70 秒，原 group 收尾另最多 30 秒、pipe drain 2 秒。有限 preflight/postflight 和材料保存不计入执行预算，不承诺整个操作硬截止。stdout、stderr、结果各最多 64 KiB；材料小文件 128 KiB；Node 单文件精确 122,466,960 字节且 ceiling 128 MiB；树最多 512 MiB、65,536 条目、深度 128、每 regular file 64 MiB。

成功必须 child/wrapper/tool 均为零、stderr 为空、pipe EOF、原 group empty、前后材料及完整树一致；仅此后保存实际 work 结果，并确认 stdout 与实际文件逐字一致。每场结果采用关闭 schema，只保存固定 ID、公开注册名称和计数、实际版本；不保存原 SDK 错误、项目内容或路径。失败的 work、报告和已写工件全部保留。退出和端点核对不证明 namespace 全部后代、持续 SourceHold 或生产锁释放。

这四场只补三个本地扩展的 SDK 加载/注册证据，不证明 UI、session 生命周期、checkpoint、Todo 重放、真人交互、真实模型账单、工具沙箱、controller 或产品 gate；不写 `verified_host_versions`，不晋升 current/accepted。正式任务仍为 8/100，严格输入计量得到验证前 AUTO OFF。

## 准备验证与稳定复核

driver 原默认 fake suite 一次 22/22；其后原生入口移除测试注入，相关两项检查通过，独立 delta review 关闭该 P2。runner 默认一次 8/8，材料 finalization 后两个受影响检查通过；14 个 group/tree 函数和 11 个 reader 函数沿用已审来源，正文逐字核对。后续 driver pin 更新仅改变一个材料行和 executor 中的摘要常量，没有重复测试。保留所有原失败、修复前像和每轮日志，不能把多轮数字相加为同次测试数量。

稳定 runner 另由 executor 独立只读审查，P1=0/P2=0，五个被审文件首末 pins 一致。报告位于 `.cache/pi-two-profiles/run-20261004/base-provider-sdk-admission-runner-independent-review01/report.json`；该审查没有执行测试、SDK 或原生流程。driver delta 的独立 scout 报告位于 `base-provider-sdk-admission-native-entry-delta-review01/report.md`。两处静态审查不等于官方 SDK 实测；四场原生结果均仍未验证。

独立授权要求来自 [AGENTS.md](../../AGENTS.md)：“真实 smoke 为独立显式步骤，需用户明确授权”。之前 SDK6、RPC5、项目信任和 Node 引导器的授权均已满足并闭合，不覆盖本次新的三个归档扩展组合。
