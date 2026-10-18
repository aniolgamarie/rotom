"""官方 SSH 的独立 headless 配置；不把宿主路径用作远端路径。"""

from pathlib import PurePosixPath
import sys

from . import native
from .schema import ConfigError


SSH_OPTIONS = {
  "type": "object", "additionalProperties": False,
  "required": ["host", "workspace", "helper", "helper_hash"],
  "properties": {
    "host": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]*$"},
    "workspace": {"type": "string", "minLength": 2},
    "helper": {"type": "string", "minLength": 2},
    "helper_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    "permission_mode": {"type": "string", "enum": ["read-only", "workspace-write"]},
  },
}
SSH_PROJECTIONS = ("@deepseek-ai/dsh-headless", "@deepseek-ai/dsh-ssh",
  "@deepseek-ai/dsh-fs-ssh", "@deepseek-ai/dsh-subprocess-ssh",
  "@deepseek-ai/dsh-sandbox-ssh", "rotom-dsh-ssh-shell-env")
SSH_BUNDLES = ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"]


def is_ssh(data):
  return data["profile"]["agent_options"].get("execution", "local") == "ssh"


def validate_ssh(data, *, selected=False):
  options = data["profile"]["agent_options"]
  remote = options.get("ssh")
  if not is_ssh(data):
    if remote is not None:
      raise ConfigError("dsh-ssh-options-require-ssh-execution")
    return
  # 尚未证明 TUI 全部消费者、MCP 和辅助插件都遵守远端坐标，明确拒绝。
  if data["plugins"] or data["mcp"] or options.get("auto_review", True):
    raise ConfigError("dsh-ssh-headless-only")
  if any(provider["auth_kind"] != "api-key" for provider in data["providers"].values()):
    raise ConfigError("dsh-ssh-api-provider-required")
  if remote is None:
    if selected:
      raise ConfigError("dsh-ssh-not-configured")
    return
  paths = {}
  for key in ("workspace", "helper"):
    value = remote[key]
    path = PurePosixPath(value)
    if (not value.startswith("/") or value.startswith("//") or str(path) != value
        or ".." in path.parts or any(ord(char) < 32 or ord(char) == 127 for char in value)):
      raise ConfigError("dsh-ssh-path")
    paths[key] = path
  helper, workspace = paths["helper"], paths["workspace"]
  if (workspace == PurePosixPath("/") or helper == workspace or workspace in helper.parents
      or any(root == helper or root in helper.parents for root in (PurePosixPath("/tmp"), PurePosixPath("/var/tmp")))):
    raise ConfigError("dsh-ssh-helper-location")
  if selected and sys.platform not in ("linux", "darwin"):
    raise ConfigError("dsh-ssh-posix-required")


def ssh_patch(data):
  validate_ssh(data, selected=True)
  config = data["profile"]["agent_options"]["ssh"]
  return [
    {"id": "fs-sandbox", "disabled": True},
    {"id": "subprocess", "name": "@deepseek-ai/dsh-subprocess-ssh", "disabled": False, "config": {}},
    {"id": "sandbox", "name": "@deepseek-ai/dsh-sandbox-ssh", "config": {}},
    {"id": "sandbox-policy", "config": {"mode": config.get("permission_mode", "read-only"), "workspaceRoot": config["workspace"]}},
    {"id": "bash-sandbox", "config": {"cwd": config["workspace"], "timeoutMs": 60000}},
    {"id": "approval", "config": {"policy": "ask"}},
    {"id": "shell-env", "name": "rotom-dsh-ssh-shell-env", "config": {}},
    {"id": "ptc-runtime", "inject": ["ssh"], "config": {"launch": native.JS("ctx.ssh.ptcLaunch")}},
    # 前台命令保留执行器超时；不将远端 spill 路径交给宿主输出存储读取。
    {"id": "jobs", "disabled": True},
    {"id": "tool-jobs", "disabled": True},
    {"id": "tool-bash", "config": {"enableRunInBackground": False, "promoteOnTimeout": False}},
    {"id": "spill-local", "disabled": True},
    {"id": "spill-policy", "disabled": True},
    {"id": "pwsh-sandbox", "disabled": True},
    {"id": "tool-pwsh", "disabled": True},
    {"id": "llm-deepseek", "disabled": True},
    {"id": "llm-deepseek-account", "disabled": True},
    {"id": "plugin-package-inventory-deepseek", "config": {"enabled": False}},
    {"id": "session-log-deepseek", "config": {"enabled": False}},
    {"insert": [
      {"id": "ssh", "name": "@deepseek-ai/dsh-ssh", "config": {
        "host": config["host"], "launch": {"kind": "executable"}, "helper": config["helper"],
        "helperHash": config["helper_hash"], "workspace": config["workspace"]}},
      {"id": "fs", "name": "@deepseek-ai/dsh-fs-ssh"},
    ]},
  ]
