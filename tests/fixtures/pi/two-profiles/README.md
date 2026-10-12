# T027 日常开发材料与只读 oracle（native/live 全部 not-run）

这些是合成输入和待采集的结果格式，不是已通过的验收。对应 S06（复现、最小修复、相关检查、diff）、S07（有限 Shell、Neovim）。Base/Full 分别记录真实运行身份；材料不依赖 Full 管理器或数据库服务，但不能据此证明 B01–B05、会话恢复 S10、账号或模型能力。后台取消沿用已有产品探针，不重造进程管理。

main.cpp 是六条常量记录的 MVCC lookup。snapshot 应包含恰在该时刻提交的版本和 tombstone，初始 `<` 边界有 bug；推荐最小修复仅改为 `<=`。项目外 checker 保有 16 个指定输入/预期，包含首次提交、更新、删除边界，以及两个其他键、无记录和普通非边界正控制。静态推导 baseline 为六个边界不匹配、十个正常正控制匹配；修复后预计十六个全匹配。没有编译或运行结果。

## 可信布局和待执行工作

```text
<只读oracle>/two-profiles/{checker.py,scenario.json,editor-task.sh,main.cpp,README.md}
/tmp/<显式临时工作目录>/baseline-project/{main.cpp,editor-note.txt}
/tmp/<显式临时工作目录>/fixed-project/{main.cpp,editor-note.txt}
/tmp/<显式临时工作目录>/editor-project/{main.cpp,editor-note.txt}
<父侧受控证据目录>/observations.json
```

由可信父侧准备项目副本，editor-note.txt 初始内容是 `visibility: pending\nboundary: inclusive\n`。只允许模型/Worker 修改项目 main.cpp/editor-note.txt，不能写 oracle、预期或 observations 证据；checker 不复制到项目。不 git init。baseline 与 fixed 用独立临时项目，最小修复后由父侧保存并独立审查 diff，不能用硬编码测试结果或无关重构满足语义检查。检查前停止项目 Writer、冻结源码/命令/工具身份与 oracle；JSON 的 input_identity 由父侧独立提供，不能从被检 JSON 取作“预期”。

真实采集必须走未来已授权受管执行器。以下只是需要采集的固定命令说明，**不是现在可直接运行的主机入口**：

- C++：受管 `CXX -std=c++17 -O0 -Wall -Wextra -Werror -pedantic main.cpp -o build/daily-db`，随后对 checker.CASES 中恰好 16 个 key/snapshot 分别执行受管 `build/daily-db KEY SNAPSHOT`。CXX 是父侧验证的绝对工具路径。构建目录只在显式临时项目内。
- Shell：future sandbox payload `editor-task.sh --run shell PROJECT unused` 执行有限 printf/sort 管道和重定向；stdout 与实际 build/shell-lines.txt 应分别等于 `alpha\nbeta\ngamma\n`。
- 编辑：future sandbox payload `editor-task.sh --run editor PROJECT NVIM` 使用 Neovim headless，固定 `--clean -u NONE -U NONE -i NONE --noplugin -n`、禁 swap/backup。父侧保存实际 editor-note.txt 内容，应为 `visibility: checked\nboundary: inclusive\n`。NVIM 必须先验证，不能加载账号配置/插件。

editor-task.sh 只是将来 sandbox 中的有限 payload，其 `--run` 不授权主机执行。checker **没有** --run、编译器或工具启动选项；不 import subprocess，不写 build、diff、日志或任何产物。终止、隔离、输出截断和进程资源的权威仍属于受管执行器，不能复制第二套管理器。

## observations v2（仅此合成 oracle 的离线输入）

闭合顶层字段：schema_version=2、scenario_id=`daily-mvcc-boundary-v1`、case=`cpp|shell|editor`、input_identity=小写64hex、records 列表、files 对象。无 result/pass/terminated/isolated/lease 等自报字段；不是产品执行协议或授权票据。

- cpp：files 必须 `{}`。records 首条恰为 compiler `{kind,exit_code,stdout,stderr}`；其后恰好16条 program `{kind,key,snapshot,exit_code,stdout,stderr}`，输入集合必须与固定 CASES 完全一致，无重复缺失/额外。key/snapshot 必须整数而非 bool。
- shell/editor：records 恰一条 `{kind,exit_code,stdout,stderr}`，kind 与 case 相同。files 分别只含 `shell-lines.txt` 或 `editor-note.txt`，内容由父侧读取实际有界文件保存，不能取模型总结。
- schema_version/exit_code 必须整数，bool 不算整数；编译或任一条非零退出均拒绝。所有 stdout/stderr/文件内容为严格 UTF-8 文本，每项至多8192字节；program/Shell stdout 不可为空。不能截断后冒充完整检查，若采集超限应记录失败并停止签发 observations，而不是伪造短文本。
- JSON 至多512 KiB，重复键/NaN/未知字段拒绝。checker 先 lstat 限大小，再 nofollow/nonblock 打开、身份复核、至多 limit+1 有界读、前后 stat 复核；不先无界 read_bytes。nonblock 防止路径在检查后被替换为 FIFO 时等待 writer；该读取边界不是恶意同UID进程隔离证明。

纯只读入口（不启动任何被测程序）：

```text
TRUSTED_PYTHON -B -I -S READONLY_ORACLE/checker.py --project-root /tmp/EXPLICIT/project
# 默认：result=not-run，checks=0；绝不能登记产品通过。
TRUSTED_PYTHON -B -I -S READONLY_ORACLE/checker.py --project-root /tmp/EXPLICIT/project \
  --observations PARENT_CONTROLLED/observations.json --expected-input-identity PARENT_FROZEN_HEX64
```

观察匹配返回 `{case,result:"matched",checks:16|2|1,failures:[]}`，不匹配返回 mismatch、非空 failures、退出1。编译失败/非零/缺输出/超限/无效形状/身份不符退出5且固定错误；静态零检查只返回 not-run。正常退出、matched 或 JSON 自报字节都不能证明真实程序执行、隔离、停止或产品验收通过，必须另核对父侧受管执行收据、输入身份、终止证据与人工 diff。checker 仅计算数据匹配，不签 S06/S07/T027 或 gate passed。

## 尚未执行与环境记录

只读路径检查发现 /usr/bin/g++、/usr/bin/bash 存在，未执行或核版本；/usr/bin/clang++、/usr/bin/nvim 缺失。工具缺失记环境不足/not-run，缺授权记 blocked/not-run，不能转成 unsupported/passed。实际编译器、C++、Shell、Neovim、Pi/Codex、模型调用及会话恢复全部尚未执行。后续采集仍须核对对应显式授权、平台、工具和 profile 身份；没有受管采集入口时不提供绕过用主机直跑命令。
