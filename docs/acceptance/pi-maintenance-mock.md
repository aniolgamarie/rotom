# Pi 维护流程的隔离验证

状态：mock 已执行；native/live 未运行。全部路径位于测试临时目录，第三方宿主、网络和真实进程操作被阻断。

## 已执行

US4 及复用的部署/监督测试共 **75 passed**：

```text
tests/test_pi_migration_flow.py
tests/test_pi_recovery.py
tests/test_pi_capture.py
tests/test_pi_inventory.py
tests/test_pi_control_recovery.py
tests/test_pi_workspace_leases.py
tests/test_pi_pipeline.py
tests/test_deployment.py
```

- 旧 home 的自定义资源、认证哨兵、`.starter-sync-manifest.json` 均保留；标记不会转为新所有权。
- 新实例首次接管已有文件或符号链接拒绝，退出4。没有 apply-import 命令或旧同步器自动执行入口。
- 连续两次 apply：第二次 changes=0，deployment.json 字节不变，previous 不轮换。
- 逐文件/日志故障注入保留旧配置和旧备份；pending/current/previous 的非法秘密拒绝恢复。
- 合法环境引用可轮换与回滚；回滚恢复历史 runtime_identity，但保留 auth/任务库/用户 keybindings/未知原生字段。
- worker/check/codex/external 活动在父控制者退出后仍使 apply/sync/rollback 返回4，不发停止信号抢占部署。
- 跨实例工作区争用、路径别名、未知标记、显式stop、恢复中再崩溃和旧控制者身份核验使用进程替身通过。
- capture 输出0600私人提案；只含所选主题/主模型，经完整配置与渲染复核；不读取 auth 或修改机器来源。

另新增的 capture 未知字段/错误类型拒绝测试会并入下一次全量回归。以上不证明真实依赖安装、平台隔离器或账号调用可用。
