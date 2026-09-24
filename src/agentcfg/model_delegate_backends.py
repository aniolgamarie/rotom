"""固定 backend 命令与最小环境；不执行二进制、不发现全局账号或代理。"""

from pathlib import Path
import os
import re
import sys

from .schema import ConfigError
from .storage import Conflict


def backend_environment(*, home, instance, route, executable, credentials=None):
  env = {"HOME": str(home), "TMPDIR": str(Path(home) / "tmp"), "PATH": str(Path(executable).parent) + ":/usr/bin:/bin", "LANG": "C.UTF-8",
    "CODEX_HOME": str(Path(instance) / "codex-home"), "PI_CODING_AGENT_DIR": str(Path(home) / "pi-agent"),
    "PI_CODING_AGENT_SESSION_DIR": str(Path(home) / "sessions"), "NODE_OPTIONS": "", "BUN_OPTIONS": "", "PI_OFFLINE": "1"}
  if route["mode"] == "proxy":
    url = route.get("proxy_url")
    from urllib.parse import urlsplit
    parsed = urlsplit(url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
      raise ConfigError("delegate-proxy-route")
    # 每个大小写变量都来自同一显式路线；没有继承 NO_PROXY 的绕行路径。
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
      env[key] = url
    env["NO_PROXY"] = env["no_proxy"] = ""
  elif route["mode"] != "direct":
    raise ConfigError("delegate-network-route")
  for key, value in (credentials or {}).items():
    if not re.fullmatch(r"AGENTCFG_PI_CREDENTIAL_[A-F0-9]{16}", key) or not isinstance(value, str) or not value or "\0" in value:
      raise ConfigError("delegate-credential-environment")
    env[key] = value
  return env


def codex_command(executable, request, output, *, permissions, resume_token=None, retry_limit=0, native=None, api_base_url=None):
  from .pi_delegate_policy import native_execution
  native = native_execution(native or {})
  if request["execution_boundary"] != "native-sandbox": raise ConfigError("delegate-execution-boundary")
  if request["backend"] != "codex" or not Path(executable).is_absolute() or not request["requested_model"]["model_id"]:
    raise ConfigError("delegate-codex-binding")
  if type(retry_limit) is not int or not 0 <= retry_limit <= 3 or request["mode"] == "implement" and retry_limit:
    raise ConfigError("delegate-retry-limit")
  if resume_token is not None and (not isinstance(resume_token, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,199}", resume_token)):
    raise ConfigError("delegate-resume-token")
  import json
  if (not isinstance(permissions, dict) or permissions.get(":root") != "deny" or permissions.get(":minimal") != "read"
      or any(not isinstance(key, str) or value not in {"read", "write", "deny"} for key, value in permissions.items())):
    raise ConfigError("delegate-permission-profile-required")
  filesystem = "{" + ",".join(json.dumps(key, ensure_ascii=False) + "=" + json.dumps(value) for key, value in sorted(permissions.items())) + "}"
  # 参数已按官方 rust-v0.154.0 exec/shared-options/config schema 核对；不使用 shell 字符串。
  settings = ['default_permissions="agentcfg-delegate"', 'permissions.agentcfg-delegate.filesystem=' + filesystem,
    'permissions.agentcfg-delegate.network.enabled=false', 'project_doc_max_bytes=0', 'approval_policy="never"', 'cli_auth_credentials_store="file"', 'shell_environment_policy.inherit="none"',
    'shell_environment_policy.set.PATH="/usr/bin:/bin"',
    'model_provider="agentcfg-delegate"', 'model_providers.agentcfg-delegate.name="OpenAI"',
    'model_providers.agentcfg-delegate.wire_api="responses"', "model_providers.agentcfg-delegate.requires_openai_auth=true",
    "model_providers.agentcfg-delegate.request_max_retries=" + str(retry_limit), "model_providers.agentcfg-delegate.stream_max_retries=0",
    "model_providers.agentcfg-delegate.supports_websockets=false", "model_providers.agentcfg-delegate.supports_standalone_web_search=true",
    "web_search=" + json.dumps(native.get("web_search", "disabled")),
    "agents.enabled=false", "features.multi_agent=false", "features.multi_agent_v2=false", "features.plugins=false", "features.apps=false",
    "features.hooks=false", "features.codex_hooks=false", "features.plugin_hooks=false", "features.shell_snapshot=false",
    "features.shell_snapshot_v2=false", "features.skip_host_skill_discovery=true", "skills.include_instructions=false",
    "sandbox_workspace_write.network_access=false", "sandbox_workspace_write.exclude_slash_tmp=true", "sandbox_workspace_write.exclude_tmpdir_env_var=true"]
  settings.append("features.shell_tool=" + str(native["allow_shell"]).lower())
  if api_base_url is not None:
    from .pi_delegate_policy import codex_api_base_url
    settings.append("model_providers.agentcfg-delegate.base_url=" + json.dumps(codex_api_base_url(api_base_url)))
  # CLI override 的键按点拆分，不识别 TOML 引号；动态路径必须放到值里。
  settings.append("projects={" + json.dumps(request["cwd"], ensure_ascii=False) + '={trust_level="untrusted"}}')
  argv = [str(executable)]
  for setting in settings:
    argv.extend(("-c", setting))
  argv.extend(("exec", "--json", "--strict-config", "--ignore-user-config", "--ignore-rules", "--color", "never",
    "--model", request["requested_model"]["model_id"], "--cd", request["cwd"], "--skip-git-repo-check", "--output-last-message", str(output)))
  if resume_token is not None:
    argv.extend(("resume", resume_token))
  argv.append("-")
  return tuple(argv)


def codex_permissions(policy, grant, *, runtime_root, codex_home, scratch, protected_roots=(), native=None, root_limits=None):
  """转成固定版本的原生权限 profile；无法无扩权表达的操作规则拒绝。"""
  from .pi_delegate_policy import native_execution
  native_execution(native or {})
  from .pi_catalog import validate_policy
  from .pi_guarded_files import ALIASES
  from .paths import relative_path
  validate_policy(policy)
  if policy["default"] != "deny" or grant["execution_mode"] not in {"delegate-readonly", "delegate-write"}:
    raise ConfigError("delegate-permission-unrepresentable")
  root = Path(grant["root_bindings"]["project"]["path"]).resolve(strict=True)
  # root-deny 已覆盖未授权临时路径；显式屏蔽整个 /tmp 会遮住其中获准的稀疏挂载。
  compiled = {":root": "deny", ":minimal": "read",
    str(Path(runtime_root).resolve(strict=True)): "read", str(Path(scratch).resolve(strict=True)): "write"}
  if sys.platform != "linux": compiled.update({":tmpdir": "deny", ":slash_tmp": "deny"})
  from .pi_native_roots import project_root_limits, restrict_permissions
  limits = project_root_limits(root_limits, root) if root_limits is not None else {"bindings": {}, "readonly": [], "denied": []}
  grants, denials = [], list(limits["denied"])
  write = grant["execution_mode"] == "delegate-write"
  for rule in policy["rules"]:
    if rule["kind"] != "file":
      if rule["effect"] == "deny":
        raise ConfigError("delegate-command-denial-unrepresentable")
      continue
    if rule["root_ref"] != "project":
      if rule["effect"] == "deny":
        targets = limits["bindings"].get(rule["root_ref"])
        if targets is None: raise ConfigError("delegate-root-denial-unrepresentable")
        for base in targets:
          target = base if rule["relative_path"] == "." else base / relative_path(rule["relative_path"])
          if (target.resolve(strict=False) != target or not target.exists()
              or rule["match"] == "exact" and target.is_dir()):
            raise ConfigError("delegate-path-denial-unrepresentable")
          denials.append(target)
      continue
    target = root if rule["relative_path"] == "." else root / relative_path(rule["relative_path"])
    # 原生规则按文件或子树匹配；不把一个 exact 目录规则扩大为整个子树。
    if target.is_symlink() or not target.exists() or target.resolve(strict=True) != target or rule["match"] == "exact" and target.is_dir():
      raise ConfigError("delegate-path-denial-unrepresentable")
    if rule["effect"] == "deny":
      denials.append(target); continue
    tools = {ALIASES.get(name) for name in rule["tool_ids"]}
    readable = bool(tools & {"tk_read", "tk_grep", "tk_find", "tk_ls", "tk_edit"}) and "read" in rule["operations"]
    writable = write and bool(tools & {"tk_write", "tk_edit"}) and "write" in rule["operations"]
    if writable and not {"write", "create", "delete", "rename"}.issubset(rule["operations"]):
      raise ConfigError("delegate-native-write-policy-unrepresentable")
    if readable or writable:
      grants.append((target, "write" if writable else "read"))
  private = [Path(codex_home).resolve(strict=True), *[Path(path).resolve(strict=True) for path in protected_roots]]
  denials.append(root / ".git")
  for path, access in grants:
    if any(path == denied or path.is_relative_to(denied) for denied in [*denials, *private]):
      continue
    compiled[str(path)] = "write" if access == "write" or compiled.get(str(path)) == "write" else "read"
  if sys.platform == "linux":
    # 对应锁定 CLI 的 LINUX_PLATFORM_DEFAULT_READ_ROOTS；:minimal 不开放 HOME 或 /tmp。
    defaults = tuple(Path(name) for name in ("/bin", "/sbin", "/usr", "/etc", "/lib", "/lib64", "/nix/store", "/run/current-system/sw"))
    exposed = [*defaults, *[path for path, _ in grants if compiled.get(str(path)) in ("read", "write")]]
    intrinsic = (Path(runtime_root).resolve(strict=True), Path(scratch).resolve(strict=True))
    for path in private:
      if any(path.is_relative_to(base) or base.is_relative_to(path) for base in exposed):
        # 过宽项目根不能同时暴露私有实例及其内的可信运行包；拒绝该无法分离的布局。
        if any(base.is_relative_to(path) or path.is_relative_to(base) for base in intrinsic):
          raise ConfigError("delegate-private-root-overlap")
        denials.append(path)
      # 其他私有路径仍由 root-deny 保护；只有密封代码和本次空白 scratch 明确开放。
  else: denials += private
  for path in [*limits["readonly"], *limits["denied"]]:
    if not path.exists(): raise ConfigError("delegate-path-denial-unrepresentable")
  compiled = restrict_permissions(compiled, readonly=limits["readonly"], denied=denials)
  if not any(path == str(root) or path.startswith(str(root) + os.sep) for path, mode in compiled.items() if mode in {"read", "write"}):
    raise ConfigError("delegate-project-access-denied")
  if write and not any(mode == "write" and (path == str(root) or path.startswith(str(root) + os.sep)) for path, mode in compiled.items()):
    raise ConfigError("delegate-project-write-denied")
  return compiled


class CodexEvents:
  """仅从固定 JSONL 语义提取进度；不发布推理、命令、stdout 或原始错误。"""

  def __init__(self, *, mcp_tools=None):
    # 指定受控工具集合后，不再接受任何原生文件/命令执行事件。
    self.mcp_tools = None if mcp_tools is None else frozenset(mcp_tools)
    self.mcp_calls = {}
    self.finished_mcp_calls = set()
    self.thread = None
    self.started = False
    self.completed = False
    self.failed = False
    self.active = set()
    self.last_message = None
    self.usage = {"input_tokens": None, "output_tokens": None, "cost": None}

  def accept(self, event):
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
      raise ConfigError("delegate-codex-event")
    kind = event["type"]
    # 官方流可先报告 error，再用 turn.failed 收尾同一次失败；不能因此二次取消。
    if self.failed and not self.completed and kind == "turn.failed": return None
    if self.completed or self.failed:
      raise Conflict("DELEGATE_EVENT_AFTER_TERMINAL")
    if kind == "thread.started":
      token = event.get("thread_id")
      if self.thread is not None or not isinstance(token, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,199}", token):
        raise ConfigError("delegate-codex-thread")
      self.thread = token
      return ("ready", "started")
    if kind == "turn.started":
      if not self.thread or self.started:
        raise Conflict("DELEGATE_EVENT_ORDER")
      self.started = True
      return None
    if kind in {"item.started", "item.updated", "item.completed"}:
      item = event.get("item")
      if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        raise ConfigError("delegate-codex-item")
      name = item.get("type")
      # 官方 CLI 可在 turn.started 之前报告非致命配置／模型元数据提示。
      # 它不是工具执行或完成证据；只允许已有 thread 的 completed error item。
      if not self.started and self.thread and kind == "item.completed" and name == "error": return None
      if not self.started:
        raise Conflict("DELEGATE_EVENT_ORDER")
      if name == "collab_tool_call":
        raise Conflict("DELEGATE_UNDECLARED_EXTERNAL_WORK")
      if name == "mcp_tool_call":
        return self.mcp_event(kind, item)
      if self.mcp_tools is not None and name in {"command_execution", "file_change"}:
        raise Conflict("DELEGATE_NATIVE_TOOL_FORBIDDEN")
      if name not in {"agent_message", "reasoning", "command_execution", "file_change", "web_search", "todo_list", "error"}:
        raise ConfigError("delegate-codex-item-type")
      if name in {"command_execution", "web_search"}:
        if kind == "item.started": self.active.add(item["id"])
        if kind == "item.completed": self.active.discard(item["id"])
      if name == "agent_message" and kind == "item.completed":
        if not isinstance(item.get("text"), str):
          raise ConfigError("delegate-codex-message")
        self.last_message = item["text"]
      return ("checkpoint", "tool-completed") if kind == "item.completed" and name in {"command_execution", "file_change", "web_search"} else None
    if kind == "turn.completed":
      if not self.started or self.active or self.last_message is None:
        raise Conflict("DELEGATE_EVENT_GAP")
      usage = event.get("usage")
      if not isinstance(usage, dict):
        raise ConfigError("delegate-codex-usage")
      for key in ("input_tokens", "output_tokens"):
        count = usage.get(key)
        if type(count) is not int or count < 0:
          raise ConfigError("delegate-codex-usage")
        self.usage[key] = count
      self.completed = True
      return ("completed", "turn-completed")
    if kind in {"turn.failed", "error"}:
      self.failed = True
      return ("failed", "terminated")
    raise ConfigError("delegate-codex-event-type")

  def mcp_event(self, kind, item):
    """进度只接受本次桥的完整调用对，不输出参数、文件内容或服务错误。"""
    identity, tool = item["id"], item.get("tool")
    if (self.mcp_tools is None or item.get("server") != "agentcfg_delegate"
        or not isinstance(tool, str) or tool not in self.mcp_tools):
      raise Conflict("DELEGATE_UNDECLARED_EXTERNAL_WORK")
    if identity in self.finished_mcp_calls:
      raise Conflict("DELEGATE_EVENT_REPLAY")
    status = item.get("status")
    if kind == "item.started":
      if identity in self.mcp_calls or status != "in_progress":
        raise Conflict("DELEGATE_EVENT_ORDER")
      self.mcp_calls[identity] = tool
      self.active.add(identity)
      return None
    if self.mcp_calls.get(identity) != tool or identity not in self.active:
      raise Conflict("DELEGATE_EVENT_GAP")
    if kind == "item.updated":
      if status != "in_progress": raise Conflict("DELEGATE_EVENT_ORDER")
      return None
    if status not in {"completed", "failed"}:
      raise Conflict("DELEGATE_EVENT_ORDER")
    self.active.remove(identity)
    self.mcp_calls.pop(identity)
    self.finished_mcp_calls.add(identity)
    return ("checkpoint", "tool-completed")
