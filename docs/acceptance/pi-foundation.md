# Pi 基础扩展验证

## 本次通过证据

- 完整默认回归：`.venv/bin/python -m pytest -q -p no:cacheprovider`
  — **839 passed，7 subtests passed，244.00秒**。
- 最新渲染/适配器/引用保护定向回归：**80 passed，24.02秒**。
- Node mock边界：`node scripts/test-pi-mock.mjs tests/fixtures/pi/mock-boundaries.test.mjs`
  — **2 passed**，Node24.1.0，仅测试运行工具，不是计划中Node24.14.0的原生认证。

## 已覆盖的基础行为

选中配方就绪回调、未选配方结构与引用检查、历史运行包身份、逐版本凭据引用保护、
引用合法轮换与回滚、损坏已存引用拒绝、capture前复核、渲染generation绑定保护声明、
适配器专用保留环境变量与旧DSH兼容、catalog依赖环/重复/冲突及closed schema。

默认Python测试使用临时HOME/XDG/Pi/Codex目录、网络阻断和假子进程。
沙箱把系统祖先目录属主映射为65534，保护性路径检查按设计拒绝；
上述文件系统回归因此在经工具审批的真实属主视图执行，未放宽路径检查。
测试未启动Pi、DSH或Codex宿主，未读取真实账号、未调用模型或远端服务。

## 当前边界

这是基础阶段通过证据，尚未实现或认证Pi完整适配、依赖安装、Task Keeper桥接和model-delegate替换。
不能据此把Pi或新的平台/工具链组合声明为已支持。
