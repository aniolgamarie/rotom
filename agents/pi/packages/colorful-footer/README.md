# Colorful Footer

多彩 statusbar 扩展，为 pi 提供纯彩色文字风格的状态栏，无背景色块，自然融入暗色/亮色终端。

## 效果预览

```
▸ run │ ↑ 1.0M │ ↓ 43.8k │ $0.0000 │  442.0k 79%
 72/s │ ◷ 5:59 │  main │  starter │  qwen3.7-plus │ think:off
◫ Ctx │ 5% │ ░░░░░░░░░░ │ 52.1k/1.0M
```

- **无背景色块** — 纯彩色文字，不突兀
- **关键指标加粗** — 状态 `▸ run` / `◦ idle` 和上下文百分比
- **优雅分隔符** — dim `│`，可自定义
- **Nerd Font 图标** — 自动检测或手动配置
- **自适应布局** — 根据终端宽度自动切换 compact / normal / detailed

## 安装

将 `colorful-footer` 目录放入 pi 的 packages 目录：

```bash
# 示例：放到 pi 扩展目录
cp -r colorful-footer/ ~/.pi/agent/packages/
```

pi 启动时会自动发现并加载。

## 配置

配置文件路径：`~/.pi/agent/colorful-footer.json`

### 完整配置示例

```json
{
  "maxLines": 4,
  "adaptive": true,
  "separator": "│",
  "colors": {
    "model": "#d787af",
    "path": "#5f87af",
    "git": "#5faf5f",
    "tokens": "#8a8a8a",
    "context": "#5fd7a5",
    "cost": "#d7d787",
    "time": "#707070",
    "cache": "#5faf87",
    "input": "#5fbfd7",
    "output": "#5fd7a5"
  },
  "icons": {
    "model": "\uec19",
    "folder": "\uf115",
    "branch": "\uf126",
    "git": "\uf1d3",
    "tokens": "\ue26b",
    "context": "\ue70f",
    "cost": "\uf155",
    "time": "\uf017",
    "cache": "\uf1c0",
    "input": "\uf090",
    "output": "\uf08b"
  }
}
```

### 配置项说明

| 字段 | 类型 | 默认值 | 说明 |
| ------ | ------ | -------- | ------ |
| `maxLines` | number | `4` | 最大显示行数 |
| `adaptive` | boolean | `true` | 是否根据终端宽度自适应布局 |
| `separator` | string | `"│"` | 指标之间的分隔符字符 |
| `colors` | object | 见下 | 各指标的颜色配置 |
| `icons` | object | 见下 | 各指标的图标配置 |

### 颜色配置 (`colors`)

每个字段支持 **theme token**（如 `"accent"`、`"success"`）或 **hex 颜色**（如 `"#d787af"`）。

| 字段 | 默认值 | 对应指标 |
| ------ | -------- | ---------- |
| `model` | `"accent"` | 模型名称 |
| `path` | `"muted"` | 当前目录 |
| `git` | `"success"` | Git 分支 |
| `tokens` | `"muted"` | Token 用量 |
| `context` | `"success"` | 上下文进度条 |
| `cost` | `"text"` | 费用 |
| `time` | `"dim"` | 会话时长 |
| `cache` | `"success"` | 缓存信息 |
| `input` | `"muted"` | 输入 Token |
| `output` | `"muted"` | 输出 Token |

### 图标配置 (`icons`)

每个字段为一个字符串。支持 Unicode 字符和 Nerd Font 字符。

| 字段 | 默认 ASCII | Nerd Font | 说明 |
| ------ | ----------- | ----------- | ------ |
| `model` | `◆` | `\uec19` | 芯片图标 |
| `folder` | `●` | `\uf115` | 文件夹 |
| `branch` | `⑂` | `\uf126` | 代码分支 |
| `git` | `⑂` | `\uf1d3` | Git 图标 |
| `tokens` | _(空)_ | `\ue26b` | HTML 标签 |
| `context` | `◫` | `\ue70f` | 数据库 |
| `cost` | `$` | `\uf155` | 美元符号 |
| `time` | `◷` | `\uf017` | 时钟 |
| `cache` | _(空)_ | `\uf1c0` | 数据库 |
| `input` | `↑` | `\uf090` | 输入箭头 |
| `output` | `↓` | `\uf08b` | 输出箭头 |

## Nerd Font 图标

自动检测以下终端环境：

- iTerm2、WezTerm、Kitty、Ghostty、Alacritty

**tmux 用户**：自动检测不生效，需要在配置中手动指定 Nerd Font 图标（见上方配置示例中的 `icons` 部分）。

也可以通过环境变量强制控制：

```bash
export POWERLINE_NERD_FONTS=1   # 强制启用
export POWERLINE_NERD_FONTS=0   # 强制禁用
```

## 自适应布局

| 模式 | 终端宽度 | 显示内容 |
| ------ | ---------- | ---------- |
| **compact** | < 70 | 状态 + 上下文% + 速度 + 分支 |
| **normal** | 70-120 | 两行：状态/Token/费用 + 时间/分支/目录/模型 |
| **detailed** | > 120 | 三行：状态/Token/费用/缓存 + 速度/时间/分支/目录/模型 + 上下文进度条 |

设置 `"adaptive": false` 可强制使用 detailed 模式。

## 命令

在 pi 中输入 `/colorful-footer` 可查看当前生效的配置。

## 开发

代码结构（`index.ts`，678 行）：

```
类型定义          L37-L77
图标系统          L79-L130    Nerd Font + ASCII 双套图标
颜色配置          L132-L172   默认颜色 + 配置加载
状态管理          L220-L236   会话/轮次状态
工具函数          L238-L300   fmt / hex / safeFg / segment
数据收集          L316-L400   从 ctx 收集 usage/branch/model 等
渲染              L402-L615   三种布局模式
扩展入口          L617-L678   session_start / turn_start / turn_end / command
```

关键设计：

- **`safeFg()`** — 统一颜色渲染入口，hex 颜色直接用 ANSI，theme 颜色走 `theme.fg()`，失败降级为纯文本，**永不崩溃**
- **`segment()` / `segmentBold()`** — 纯彩色文字渲染，无背景色块
- **`getSep()`** — 从配置读取分隔符，用 dim 着色
