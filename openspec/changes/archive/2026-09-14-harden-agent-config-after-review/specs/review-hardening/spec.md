## ADDED Requirements

### Requirement: Private configuration is checked before reading
所有本地配置读取 SHALL 检查 0600、私人父目录、属主、普通单链接与路径身份，不跟随链接、不自动更改权限。

#### Scenario: An insecure copy or symlink is rejected
- **WHEN** 任意命令使用 0644、本地符号链接或读取期间被替换的文件
- **THEN** 读取失败且输出不包含文件正文；原文件不被修改

### Requirement: Runtime preparation and repair are recoverable
profile 准备 SHALL 保存先于修改的所有权阶段；运行包 SHALL 校验关键文件收据，损坏时通过持锁暂存修复，pending 部署 SHALL 阻止 sync。

#### Scenario: Preparation fails between package and owner completion
- **WHEN** 首次启动或更新准备中断
- **THEN** 重试可恢复自己的前后值，未知文件仍冲突

#### Scenario: A runtime loses files
- **WHEN** 标记存在但必要依赖缺失或被修改
- **THEN** doctor 显示损坏，run 拒绝，sync 可重建；失败保留旧目录且不改账号

#### Scenario: Configuration recovery is pending
- **WHEN** pending journal 存在时 sync
- **THEN** 任何安装或暂存写入前失败并提示恢复

### Requirement: Native options and lock compatibility are explicit
不支持的 OAuth 参数 SHALL 在校验失败；锁 SHALL 对比真实 adapter、平台与来源声明。

#### Scenario: OAuth options would otherwise be ignored
- **WHEN** 配置没有已核实映射的 OAuth provider_options
- **THEN** validate 失败而不是生成相同输出

#### Scenario: A consistent hash describes an incompatible adapter
- **WHEN** 元数据摘要正确但 adapter 或支持平台不匹配
- **THEN** 锁校验失败且不隐式解析

### Requirement: Capture and diagnostics are actionable without public private values
capture SHALL 支持允许的预览、内建主题和已声明模型选择，并校验完整合并配置；未知选择不伪造模型。计划 SHALL 提供稳定定位标识及私人定位提案，缺凭据 SHALL 有可操作的定位提示。

#### Scenario: A UI selection matches a declared model
- **WHEN** 本机原生偏好选择已声明模型和支持主题
- **THEN** 生成合法本地覆盖提案，不导出账号、动态模型目录，不公开私有 ID

### Requirement: Dependency backends and deferred evidence are explicit
通用命令/启动 SHALL 使用所选 adapter 的依赖后端；独立 Agent、平台和账号验收 SHALL 有前置条件、步骤和待验证状态。

#### Scenario: A fake non npm backend exercises the command path
- **WHEN** 测试 adapter 选择假依赖后端执行命令和启动
- **THEN** 不使用 DSH/npm 固定路径或命令，不暴露假生产工具
