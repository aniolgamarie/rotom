# Pi Base / Full 当前 gate 记录

状态日期：2026-10-09。本文件由现有 v2 验收计算器对 [scope revision 1](../../../specs/005-pi-two-profiles/acceptance-scope.json) 重算，保存结果见 [current-gates.json](current-gates.json)。这是当前未完成状态报告，不能用文件名或 report_generated=true 宣称最终验收完成。

| Gate | 当前结果 |
| --- | --- |
| base | 未通过 |
| full | 未通过 |
| isolation | 未通过 |
| whole-process-feasibility | 未通过 |
| maintenance | 未通过 |
| linux-x86_64 | 未通过 |
| accounts | 未通过 |
| experience | 未通过 |

scope 尚未冻结产品 RuntimeIdentity/ConfigIdentity 和独立 checker，未挂入具备所需层级的产品证据，candidate_frozen=false、release_approved=false。已通过的默认组件测试与授权候选 SDK 探针仍保留于实施证据中；它们不会自动变成该产品身份的 passed。scope 共110个子项，其中108个必需项在此产品报告中仍为 not-run，原因是 candidate-identity-unfrozen；另外2个未选择项不计入必需通过数量。这不抹去已有局部观察，也不把它们计为实际产品通过。

主要未闭合项：

- Base：正式来源支持资格/current lock、完整安装与实际启动工具链、主会话认证/国内路线、压缩恢复、原生 MCP/Code Mode、日常 C++/Shell/Neovim和冷安装。
- 权限/隔离：所有执行入口覆盖、Writer 与物理终止组合、整 Pi 进程隔离可行性最终结论；已有 OS 组件探针不代替产品 gate。
- Full：正式 profile、统一 Pi/Codex delegate、Task Keeper、Durable 控制器/服务与持久恢复组合。
- 维护与体验：提供者替换/失败恢复、升级回退/卸载、冻结数值预算后的测量、真实账号和终端、中文手册命令实证、稳定最终审查。

严格发送前输入计量未合格，AUTO OFF。Linux x86_64 是当前必需实测平台；Mac 等其他平台按需处理。OMP 权限问题已交由另一个任务，不影响这里的范围或已有记录。

下一次更新须使用严格 scope revision 规则绑定实际产品身份、oracle 与当前证据后重算，不以任务完成数量、某次退出0或手工改布尔值签发通过。完整判定依据见 [acceptance.md](../../../specs/005-pi-two-profiles/acceptance.md)。
