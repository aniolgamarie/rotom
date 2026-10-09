# OMP v18.8.6 升级验收

日期：2026-10-09。目标为官方稳定版 v18.8.6，固定提交
`f068751e2f1dbdbc195977776d47a26db8697495`。只修改 rotom 自有版本声明、
插件兼容元数据、锁和测试；不修改上游源码、二进制或宿主内部实现。
机器可读状态见 [验收证据](omp-upgrade-18.8.6-evidence.json)。

## 风险判断与已完成验证

- 官方源码归档、官方 SHA256SUMS 和 Linux x64 二进制实际字节均核验。四平台资产
  摘要来源于官方发行清单；另外三个平台没有实际下载/启动通过证据。
- 新版公开 Settings、BashTool.approval 和 ctx.invokeTool 接口兼容。全部权限插件
  生产 TypeScript 严格类型检查通过，无需更改原生 Bash 接线。
- 配置 pytest 97 passed / 7 skipped，运行时 pytest 133 passed。7 项跳过属于退休的
  历史宿主补丁测试，不计作新版宿主通过。初次 UID 映射失败保留记录，正常用户环境
  重跑保持临时 HOME、假子进程和网络阻断。
- 完整权限 Bun 包 477 passed / 0 failed，56,198 assertions。HOME/query 修复与
  固定 583 行差量保留；历史语料不重生。外部语料模块的结果另记证据。
- 有界独立审查未发现 P1/P2。源码比较表明 agent schema 仍为 6、auth schema 仍为 8，
  本次无新增破坏性迁移；这不等于真实账号库降级已验。未读取、备份或哈希真实账号库。
- v18.8.2 移除 task/eval 的逐次 model 覆盖；现有配方使用角色及 agent 定义，
  没有该参数依赖。会话标题的新默认行为与 native model 角色配置不混为权限主审配置。

升级门槛是上述验证加隔离官方宿主加载、原生 Bash 智能审批与 deny 下限验收。
真实 Cursor 高负载仍由外部服务决定，不把版本更新当作服务可用性保证。

## 隔离宿主与本机部署

allow 与 deny 两个独立场景已通过、退出 0，外部模型请求 0。allow 审查/委派/成功执行各一次，人工 0；deny 在模型前阻断，四项均为 0。deny 未执行过委派，coverage limited 和 delegate availability null 是已核实状态，不能要求它宣称委派已可用。最初旧欢迎文案、旧原生结果 details 和 deny coverage 的 harness 断言失败保留，不把修复后的分别通过说成首次整体全绿。另两个语料模块 71 passed / 0 failed，11,784 assertions；全部 11,473 行符合冻结合同及固定 583 行差量。当前本机部署状态由机器可读证据记录。隔离宿主使用合成模型
和密钥、临时 HOME，以及只有 loopback 的私有网络命名空间。管理器在正常用户环境
持实例和状态锁，仅将实际官方宿主放入 namespace；不放宽文件属主检查。

日常更新使用 sync → plan → apply → doctor；保留上一版受管配置与旧运行包。
遵守用户授权边界：凭据只由 agentcfg 内部加载，不向代理展示或复制秘密正文，
不盘点账号、会话和日志。真正开始新版日常会话后可能写入账号库，跨版本回退
兼容性不能凭当前 schema 版本相同就宣称已经验证。

## 网络代理与 Cursor 高负载

[网络代理方案](../follow-ups/omp-network-proxy-design-2026-10-09.md)单独规划执行
模型 provider、权限 reviewer 和 GitHub 下载路线；Cursor 默认直连。此轮不新增
网络配置字段或改变本机代理。

Cursor `RESOURCE_EXHAUSTED / High Load` 表示服务端容量/限流信号，不能据此认定
本机代理故障或账号额度耗尽。上游 fallback 警告携带来源模型的旧错误，并在目标
模型实际继续请求前发出；仅看 Kimi→GLM 警告不能证明 GLM 已被请求或成功。
保留有界重试及现有 Cursor 内备用链，不擅自增加自动按量付费 DeepSeek fallback。
