# 32da4799 冷重建证据

锁 `32da47998e8388a84f291d217b39f105b294dd1f9676831c5e56a2709a8d28ca` 的 Linux x86_64 四配方冷重建报告，布局同 [4c043f8f 目录](../pi-cold-4c043f8f/README.md)。本候选相对 4c043f8f 的增量：T098 darwin 执行器、ReadSeek 原生验收场景（readseek-tools，八项事实）、vendor 交付脚本、test atime 修复及 readseek 原生链路七处接线修复（详见实施记录（二）（三）节）。

四配方双路径全部 `two-fresh-targets-verified`：default 7 case 组、cursor 5、codex 7（含 codex-receipts）、managed 5（含 taskkeeper-lifecycle），readseek-tools 在 default/codex 全步通过。只使用合成模型与本地服务；`passed` 不自动登记为固定 scope 最终证据，也不批准四平台与真实账号交付。
