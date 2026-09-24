# 证据汇总与交付批准契约

**Version**: 1.1（2026-09-24 明确规格范围变更与新基线）  
**Resolves**: I1；生成报告永远不要求全部验收先通过。

## 1. 固定验收范围

AcceptanceScope记录scope_id、revision、scope_digest、目标platform/architecture/profile/transport、
必需capability与场景、明确选择的可选能力、所需证据层级、选择理由与记录时间。
由已确认规格、能力配方和用户选择生成；候选锁生成后关联其身份。
候选尚未构建时，AcceptanceItem.identity 为 null，明确表示未冻结；不得填占位摘要或产生通过批准。
原始 CapabilityEvidence.identity 始终需要完整真实身份，不能为 null。范围变更使旧批准失效，不能因测试失败缩减范围。

- 必需代码/契约/mock/native替换验证包含Task Keeper、model-delegate两backend、七模板和旧组件退出。
- Codex/Cursor等真实账号调用按明确选用的能力计算；未选live账号能力不免除上述软件/backend替换验证。
- 缺账号、机器或授权不等于未选择。已选可选能力未验证时仍阻止该范围交付。
- Linux/macOS四个目标架构格子沿用本计划目标，不能由汇总器自动删除失败或缺机器的格子。
- 只有用户明确修改范围并更新规格/设计时才生成新scope revision；历史失败证据保留。

## 2. 证据与展示状态分离

### 2026-09-24 用户授权的规格范围变更

本 spec 按 [范围修订](../scope-change-20260924.md) 使用新基线 `001-unify-pi-capabilities-linux-software` revision 1，仅含 Linux x86_64 四配方 mock/native 的全部 81 项。
其他三平台和 live 已转至独立后续清单；这不是缺环境时的自动删项，也不是把已选服务改成未选。
旧 `001-unify-pi-capabilities` revision 2、全部 364 项和原失败批准结果保留。
两个 scope 通过 `scope-amendment.json` 记录规格变更、父摘要、精确保留规则和转出项；新基线不冒充普通证据 revision。
`validate_revision` 的禁止自动缩减规则不变。本 spec 的最终批准只对新基线生效，不覆盖旧完整范围，也不代表 live 或其他平台通过。

原始CapabilityEvidence继续使用status=passed/failed/not-run；记录真实执行事实，不伪造not-selected的执行证据。
每个AcceptanceItem另有applicability=required/selected_optional/not_selected，引用scope与匹配证据，
并列出evidence_paths（相对evidence-root、无越界/符号链接、无glob的显式文件清单）。
显示状态为passed/failed/not-run/stale/not-selected：

- 未选择的可选live能力显示not-selected，附选择依据，不调用宿主/登录，也不计入通过率分母。
- required或selected_optional无证据、缺前提或缺授权显示not-run，附具体原因。
- identity不匹配显示stale，即使旧status=passed也不能视为通过。
- not-run、failed、stale均保留，汇总成功不改变这些状态。

## 3. 持续汇总接口

```text
scripts/verify-pi.py --report-only --scope PATH --evidence-root PATH --output PATH
scripts/verify-pi.py --check-release --scope PATH --evidence-root PATH --output PATH
```

这两个模式与--tier互斥，不接受--allow-host/--allow-live，不启动宿主或网络。
output仍0600并拒绝覆盖已有报告，每次生成带输入摘要的新快照，支持矩阵的文档指向最新完整快照。
只读取scope列出的evidence_paths，不扫描目录中其他scope/报告/文档。
缺失证据目录或列出的缺项作为not-run汇总；列出且存在但损坏/未知schema/路径越界的证据是输入错误，不能静默忽略。

report-only读取当前可用记录，立即生成所有scope格子的支持矩阵与缺口；即使零测试执行也可以完成。
报告有效生成返回0，不代表验收通过。输入无效返回2。

check-release在同一汇总基础上验证所有required/selected_optional格子有匹配且通过的所需层级证据，
成功返回0；存在failed/not-run/stale返回1并生成缺口报告；输入无效返回2。
脚本退出码与agentcfg管理器不同，不能将报告的0混为管理器能力已就绪。

## 4. 任务完成与条件依赖

- 报告实现/初始汇总任务在报告功能与scope schema完成后即可勾选；此后每批证据变化重新生成报告。
- 每个平台native任务独立执行。live任务只依赖其实际使用的同平台/配方/transport native证据与对应授权，
  不用等待无关平台或另一可选服务的live任务。
- 未选可选live能力的分类可以完成为not-selected，但不能勾成执行通过；任务勾选仅表示
  已处理完当前scope要求的项：无被选项时需有scope和not-selected清单证明。
- 有任何被选项缺账号/授权/证据，该验收任务保持未完成。其他实现、汇总和独立场景继续进行。
- 最终批准任务始终检查全部固定scope条件；不能因为报告已经存在、某任务被分类处理、或测试脚本返回0
  而绕过必需Task Keeper、完整替换、平台重建及真实所选服务的证据。

## 5. 验证

V18/V20/V21增加：零证据照常出报告；部分成功/失败/未执行/过期混合报告；
未选可选live能力不阻塞，但已选未授权能力阻塞；损坏证据报错；scope变更使旧批准失效；
单个平台已就绪可执行其live，不要求其他平台先通过。
最终报告必须明确显示“报告生成成功”和“交付条件是否满足”两个独立结果。
