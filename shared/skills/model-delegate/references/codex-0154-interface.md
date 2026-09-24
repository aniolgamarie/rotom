# Codex 0.154.0 接口核对

仅源码核对，未执行 CLI 或账号测试。

- exec 的 JSONL、输出文件、ignore-user-config、ignore-rules 与显式 resume 参数：
  [固定版本 CLI 源码](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/exec/src/cli.rs)。
- cwd/sandbox 参数及配置字段：
  [shared-options](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/utils/cli/src/shared_options.rs)、
  [config schema](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/core/config.schema.json)。
- provider 支持 HTTP/stream 重试上限、OpenAI 账号认证及基于认证类型的默认 endpoint：
  [model-provider-info](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/model-provider-info/src/lib.rs)。

派生 backend 使用独立 provider 配置；流重试始终为0，请求重试默认0，仅独立只读CLI可显式配置为0–3。不修改内建 provider 定义。
配置禁用额外 agent、插件、hook 和宿主 skill 发现，工具进程不继承模型进程的环境。
真实参数接受、认证、取消、隔离与代理行为仍须独立 native/live 证据。

## 当前执行边界（2026-09-17）

按用户要求继续实施，Codex使用官方CLI与原生工具，execution_boundary=native-sandbox。
agentcfg绑定整次运行授权并监督停止，不承诺逐工具即时撤权；Task Keeper与Pi受控工具保留细粒度授权。
默认控制入口和冻结包不再包含MCP IO替代层；下面的MCP段落只保留原型历史。
[执行边界评估](../../../../specs/001-unify-pi-capabilities/codex-execution-reassessment.md)列出依据与验收边界。

Codex配方须显式声明native_execution.allow_shell及tool_network="none"；缺失则拒绝准入。
请求/收据绑定execution_policy_digest，supervisor保存本次原生权限投影授权；原生候选编辑不要求MCP操作日志。
停止未完成时保留写锁，不自动重发；缺失新边界字段的早期V2记录不能补默认值认证或恢复。

## 工具前授权的未闭合条件

已核对固定版本的 [PreToolUse 实现](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/hooks/src/events/pre_tool_use.rs)：
命令 hook 的错误、超时、缺退出码和无有效拒绝输出不会自动阻止工具执行。
因此普通 hook 不能独立提供 agentcfg 要求的“授权状态未知即拒绝”保障。
现行契约已区分原生运行级授权和受控逐工具授权。仍须验证原生沙箱、停止与资源回收，
不能把停止进程宣称为即时逐工具撤权，也不能把mock结果当成平台认证。

## 前一阶段 MCP 原型记录（接线已暂停）

2026-09-17 用户确认：保留官方 CLI，文件与命令操作经 agentcfg 受控 MCP 工具桥，不维护 Codex 分支。

已实现的控制层：

- MCP 文件工具每次重新核对当前 grant 和策略；写入只作用于已获准的独立 worktree，并记录连续变更凭证。
- MCP `commands` 查询本次可用的绑定；`command` 只接受 `tool:ID`，不接收任意 shell、argv 或环境覆盖。命令使用已有 supervisor 的派生执行，受现有并发上限、父委托截止时间、无网络沙箱和父工作区租约约束；容量不足明确失败。
- 子执行尚未物理终止时父租约不能回收；父委托退出/撤权后取消子执行。启动确认未知不自动重发。离线读取也校验所引用的子执行证据。
- 文件与写命令共用串行变更日志；没有日志的工作区改动、日志缺口或未完成的变更不能认证为成功。
- 受控模式的事件解码只允许本次桥声明的 MCP 服务/工具，拒绝原生命令/文件事件和缺失、重复、身份变化的工具事件。

**尚未完成官方 CLI 启动接线与最终配置封闭验证。** 上述控制层及事件解码器的 mock 通过不代表 CLI 已使用它们。
固定版本的 [配置合并实现](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/config/src/merge.rs)
会深合并表；不能用空 `mcp_servers` 表推断系统/企业云配置的额外服务已移除。
此前MCP原型要求封闭原生 shell、apply_patch 等替代通道；这项接线现已暂停。
推荐原生路线仍须验证沙箱与配置发现，但不再以替换原生文件/命令工具为目标。
