# pi-permission-system `ob-make *` deny 规则过度匹配（遗留问题）

- 记录日期：2026-09-22
- 状态：已修复（`deny` → `ask`），观察期；规则语义陷阱记录备查
- 影响范围：rotom 管理的 `agents/pi` 环境、所有需要执行 OB 编译任务（ob-make）的配方与会话
- 关联配置：`~/.pi/agent/extensions/pi-permission-system/config.json`（`@gotgenes/pi-permission-system@29.3.0`，**手写本地配置，不在 rotom 或 starter 的 git 管理下**，修改前备份 `config.json.backup.20260922_163746`）；starter 侧同主题文档 `../starter/docs/pi-permission-ob-make-overmatch.md`
- 相关规则文档：`.claude/rules/ob-build-test.md`（ob-make 无参数是唯一允许的编译命令）

## 摘要

pi-permission-system 配置中 `"ob-make *": "deny"` 规则本意是"禁止 ob-make 带任何参数"（防 `-j` 并行、防绕过 ob-make 的调度语义），但其模式语义是**命令字符串空格后缀匹配**：重定向（`> file 2>&1`）、管道（`| tail -80`）、分组（`{ ...; }`）在命令字符串里都表现为 ob-make 后的空格后缀，全部命中 deny。结果是**意图合规的用法被硬拒**，assistant 为控制编译输出体积（ob-make 输出可达数万行）做的截断/落盘尝试反复撞墙，陷入无效重试循环，编译任务被完全阻断。

这是**权限规则表达方式与 shell 语义之间的阻抗失配**，不是权限系统本身故障，也不是 OB 构建规则的本意。

## 现象

ob_work 编译 session 中 assistant 的合规尝试全部被 `Denied by policy: 'bash' (rule 'ob-make *')` 拒绝：

```bash
cd build_release/unittest/storage/tx && ob-make 2>&1 | tail -80
cd build_release/unittest/storage/tx && ob-make > /tmp/build.log 2>&1; echo "EXIT=$?"
cd build_release/unittest/storage/tx && { ob-make; } > /tmp/build.log 2>&1
```

唯一能命中 `allow` 的形式是子命令精确等于 "ob-make" 的裸命令（`cd ... && ob-make`），但 assistant 不会主动放弃输出控制，反复尝试后放弃并请求用户手动执行——自动化链路断裂。

## 根因

原规则组（8-26 为 OB 构建规则手写定制）：

```
allow  ob-make          ← 仅匹配"ob-make"四字符精确串
deny   ob-make -j*      ← 禁并行参数
deny   ob-make --jobs*
deny   ob-make *        ← 本意"禁任何参数"，实际误伤一切输出控制包装
```

pi-permission-system 的 `cmd *` 通配符匹配的是**字符串后缀**而非 shell 解析后的参数列表。规则作者按"参数"思考，系统按"字符串"匹配。

## 修复（2026-09-22 已执行）

单行修改：

```diff
- "ob-make *": "deny",
+ "ob-make *": "ask",
```

- `-j*` / `--jobs*` 的 deny 保留：核心风险（并行编译、绕过 ob-make 调度）仍然硬阻
- 其他后缀形式降级为询问：用户一键批准即可，不再静默阻断
- yolo 模式与其余 56 条 deny 规则未动
- 新 pi 会话生效（扩展配置不热重载）

## 治理缺口与观察项

1. **配置无版本管理**：该 config.json 是 8-26 手工迭代产物（目录内 3 个历史备份文件），修改历史仅靠本地备份。rotom 对 `agents/pi` 环境的其他部分（packages、skills）有 git 管理，但权限配置这一环游离在外——与 `pi-cursor-stale-pin-legacy.md` 记录的"配置漂移"风险同类。可考虑将 config.json 纳入 rotom 管理（如 `agents/pi/permissions/`）并同步安装。
2. **ask 交互频率观察**：若编译 session 中 `ob-make 2>&1 | tail -N` 形式每次都要批准，可精确白名单输出控制后缀（`"ob-make > *": "allow"`、`"ob-make 2>&1 | *": "allow"`）。
3. **同类规则巡检**：配置中其他 `deny <cmd> *` 形态（`make *`、`cmake --build *`、`git push *` 系列）存在同样的语义陷阱，但这些命令在 OB 规则中本就禁用，误伤反而符合意图，暂不动；将来给常用命令加 `deny cmd *` 规则时须先评估重定向场景。

## 教训

"只允许裸命令"的意图不能用 `deny cmd *` 表达——它连带禁止一切输出控制手段，迫使 assistant 在"裸跑撑爆上下文"和"反复撞墙"之间二选一。推荐形态：

- 精确枚举危险参数形态（`-j*`、`--jobs*`、已知 target）逐一 deny
- 兜底用 `ask` 把判断权交还用户
- 或直接 allow 输出控制后缀

权限规则的思维单位是**字符串**，不是 shell AST。

## 时间线

| 日期 | 事件 |
|---|---|
| 2026-08-26 | 为 OB 构建规则手写 pi-permission-system 配置，当日迭代三版定稿（含争议规则组） |
| 2026-09-22 | 编译 session 暴露误伤，assistant 无效重试循环；定位根因；`ob-make *` 改 `ask` 并备份；starter 与 rotom 两侧记录遗留问题 |
