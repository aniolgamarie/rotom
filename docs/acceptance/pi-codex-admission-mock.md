# 官方 Codex 配置准入及 MCP 监督隔离回归

执行日期：2026-09-18。层级：mock。用户已选择官方 CLI 的受限配置准入；本记录不表示 native/live 通过。

## 最后一次完整调度

```sh
.venv/bin/python scripts/verify-pi.py --tier mock --case all \
  --output /tmp/agentcfg-pi-mock-20260918-mcp-supervision.json
```

- Python 3.11.11：1327 passed，7 subtests passed，285.34 秒。
- Node v24.1.0：192 passed，0 failed。
- 报告 status=passed，退出码 0。
- 时间：2026-09-18 03:09:06 至 03:13:55 UTC。
- 报告和 stdout/stderr 位于上述临时路径及其 `.artifacts/` 目录。

完整调度启动后的 Codex 父 resolver 重复预检清理，另由准入／worker／根绑定的 54 项定向测试通过覆盖。最终候选身份尚未冻结。

## 相关覆盖

- 系统配置／规则／未知条目、坏链接、权限与访问失败均在 CLI 创建前拒绝。
- 虚构个人 OAuth 与明确 API key 的分类；组织、未知、混合、重复 JSON 字段及不安全认证文件拒绝。秘密正文不进入输出。
- 假 CoreFoundation 核对官方域、键、对象释放及无法查询时的拒绝；不执行 macOS API。
- 父 resolver 与 worker 启动路径、配置准入策略摘要、默认 doctor 不读认证，以及允许公开的固定错误码。
- 全部委托契约、角色／写权限、生命周期、收据、manager／工具桥和 DSH 默认回归。
- MCP sampling 的受约束模型调用、elicitation 的 URL 分支、stdio 的 UTF-8／背压、脚本私人沙箱意图和假监督通道。
- 脚本取消、迟到准入及未知终止均保留相应保护；不以 Promise 完成代替物理终止证明。

## 静态检查

完整 MCP fork TypeScript 检查通过；新脚本进程入口 Node 语法检查通过。检查使用临时依赖和 Node 24.14.0，不执行宿主或用户脚本。`git diff --check` 通过。

## 局限

没有读取真实认证内容，没有启动真实 Pi、Codex、Cursor、MCP 服务、脚本解释器任务、操作系统沙箱或调用模型。MCP OAuth／Apps UI／direct-tool 配置、ReadSeek、web 和最终锁仍有未完成工作。三个暂无机器的平台保持 not-run，全部已选服务范围保持不变。

受限官方 CLI 要求稳定受信机器与账号，预检不是原子配置绑定。兼容性条件见 [配置准入说明](../pi-codex-admission.md)。这些测试不生成发布批准。
