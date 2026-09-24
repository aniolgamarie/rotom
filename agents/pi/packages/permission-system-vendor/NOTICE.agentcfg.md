# agentcfg 派生适配

来源：@gotgenes/pi-permission-system 29.3.0 的 npm integrity 核验归档；原 MIT LICENSE 保留。
源文件摘要、resolved URL 与 integrity 见 agents/pi/migration/permission-system-manifest.json。
目标版本29.3.0-agentcfg.1。

- 策略只由 agentcfg 当前实例快照提供，不发现原生全局/项目配置或旧规则目录。
- 原生 engine 保留提示、service、formatter/extractor 与会话生命周期；每次 tool_call 先过 agentcfg 硬权限检查。
- yolo只影响提示层，读取同一个会话状态；不能修改角色、任务grant或写租约。
- 缺策略/缺实际IO能力直接拒绝。原生配置UI不写生成文件，提示修改agentcfg来源。
- 关闭原生通用输入审计日志，避免把命令/路径中的敏感值写入日志。
- parser与依赖只从当前冻结运行包解析，不执行 npm root -g。

实际文件/命令执行的监督接线仍在T086进行；这份补丁本身不能作为完整IO通过证据。
