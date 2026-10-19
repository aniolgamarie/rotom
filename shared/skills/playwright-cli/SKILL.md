---
name: playwright-cli
description: 仅在用户明确需要浏览器操作时使用受管 Playwright CLI；不连接个人浏览器，不自动安装或下载。
allowed-tools: Bash(playwright-cli:*)
---

# 受管浏览器 CLI

只有用户明确提出浏览器任务，且所需网站访问、数据外发和账号操作已获授权时才使用。
仅调用当前 Pi 实例 PATH 中的受管 `playwright-cli`。禁止 npx、浮动版本、全局安装、
install/install-browser、attach、持久 profile、自定义浏览器/config/session、close-all/kill-all。
浏览器二进制是另行显式准备的依赖；缺失时停止报告，不自行下载。

受管入口已固定运行包、独立私有 cwd/HOME/XDG/browser 目录、关闭更新检查，
并为每个主运行分配独立 session；同一主运行多次命令复用该 session。不要传 -s/--session。
用 `open`、`snapshot`、页面交互及 `close` 操作当前 session。输出和上传路径须按用户任务审阅；
eval/run-code、cookie/storage、上传、trace 均可产生副作用，此 Skill 不是只读调查能力。
CLI 的 open 可留下 daemon，正常 close、主进程退出和全部后代确认释放必须分开；
未知状态不能按超时或父退出清除，也不要停止其他主运行的浏览器。

完整原始 [上游 Skill](upstream/SKILL.md)、其十份 references 和 [Apache-2.0 LICENSE](LICENSE)
保留供查看真实公开命令；其中安装、npx、attach/persistent/session 和全局关闭建议不适用于受管入口，
不能因支持资料出现这些命令而绕过本入口。未知或未开放参数报错时停止，不改用未受管 CLI。
Pi 主会话仍有完整 Bash；受管 wrapper 不构成 OS 沙箱或对任意 shell 的强制限制。
