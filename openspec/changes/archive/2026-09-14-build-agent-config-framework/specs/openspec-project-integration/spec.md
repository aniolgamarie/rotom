## ADDED Requirements

### Requirement: OS-01 OpenSpec uses its locked installed CLI

产品 SHALL 将 OpenSpec CLI 及传递依赖纳入实际完整锁，project 命令只执行匹配锁的安装产物，不依赖用户全局 CLI、不用无版本 npx。安装状态和项目初始化状态 SHALL 分别报告。

#### Scenario: Missing CLI does not trigger an unpinned download
- **WHEN** 执行 project init 但锁定 OpenSpec 尚未 sync
- **THEN** 命令失败并提示准备依赖，不使用全局替代或自动下载 latest，不修改项目

### Requirement: OS-02 Project initialization is explicit and bounded

`project init openspec --path PATH` SHALL 仅初始化明确指定项目，按 argv/cwd 调用锁定 CLI，列出产物与冲突。apply/sync SHALL 不初始化业务项目；项目路径检查不得穿透符号链接逃逸，运行环境不接收模型 secret。

#### Scenario: Only the requested test project changes
- **WHEN** 在临时 HOME 下准备两个项目和外部哨兵，对一个含中文空格路径的项目初始化
- **THEN** 仅指定项目产生声明的集成文件，另一个项目、真实 HOME 和外部哨兵不变，进程不收到模型密钥

### Requirement: OS-03 Native or custom integration is verified by DSH loading

适配 SHALL 先核实锁定 OpenSpec 支持的工具列表；若无 DSH 原生目标，必须采用上游文档支持的自定义集成并注明。安装成功不得代替集成验收，生成的规则/技能 SHALL 被锁定 DSH 实际识别。

#### Scenario: Custom integration is tested as a real target artifact
- **WHEN** 选定版本不原生支持 DSH，生成自定义集成产物并执行显式无账号 host smoke
- **THEN** DSH 实际加载对应产物，记录加载证据与集成性质；不创建仅名称相似但工具无法识别的文件冒充成功

### Requirement: OS-04 Repeated initialization preserves project work

初始化 SHALL 预检查现有文件；完全一致的重复执行无非必要变化，存在用户修改的同名产物则报告冲突，不覆盖。失败 SHALL 报告本次已产生的文件，不声称第三方多文件操作完全原子。

#### Scenario: Reinitialization is idempotent or conflicts explicitly
- **WHEN** 连续初始化同一测试项目，随后手改一个集成产物再初始化
- **THEN** 未修改情况下无重复或非必要写入，修改后明确报冲突并保留用户内容，产物范围可核对
