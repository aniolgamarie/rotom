# agentcfg model-delegate bridge

该桥为迁移新增的统一入口。完整技能源码与来源见 shared/skills/model-delegate。
它调用现有 AgentManager 的 external executor 和实例 supervisor，不创建第二管理者。
旧 Codex 桥与七个旧角色不注册；用途由七个 preset 表达。
默认测试使用假的 supervisor/backend，原生与账号执行仍需独立验证。
