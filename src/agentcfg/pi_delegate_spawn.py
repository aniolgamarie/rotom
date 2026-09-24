"""委托固定入口解析；启动输入只含引用，选中秘密仅进入最小子环境。"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from .activity import digest
from .deployment import json_bytes
from .model_delegate import selected_route
from .model_delegate_backends import backend_environment, codex_permissions
from .paths import relative_path
from .pi_supervisor import SpawnCommand, closed
from .pi_worker_files import snapshot
from .pi_worker_protocol import selected_api_models
from .process import DependencyError
from .storage import Conflict, Tree, ensure_private


def resolve_delegate(host, lease, program, payload):
  closed(payload, ("run_id",))
  value = host.delegates.input(payload["run_id"]); request = value["request"]
  if (program != "delegate-" + request["backend"] or request["lease_id"] != lease["lease_id"]
      or request["attempt_id"] != lease["attempt_id"] or request["owner_nonce"] != host.store.owner["owner_nonce"]
      or request["runtime_identity"] != host.runtime_root.name or request["grant_generation"] != lease["grant_generation"]):
    raise Conflict("DELEGATE_SPAWN_IDENTITY")
  if datetime.now(timezone.utc) >= datetime.fromisoformat(value["grant"]["expires_at"]):
    raise Conflict("DELEGATE_ADMISSION_EXPIRED")
  manifest = host.manifest()
  from .pi_delegate_policy import execution_policy
  if digest(execution_policy(manifest, request["backend"])) != request["execution_policy_digest"]:
    raise Conflict("DELEGATE_EXECUTION_POLICY_MISMATCH")
  route_id, route = selected_route(manifest, request["backend"], request["requested_model"])
  if (value["route"] != {"id": route_id, **route} or request["policy_digest"] != digest(manifest["permission_policy"])
      or host.store.workspaces.identify(request["cwd"])["workspace_key"] != request["workspace_identity_digest"]
      or snapshot(request["cwd"], protected_roots=host.config.get("protected_roots", [])) != request["candidate_digest"]):
    raise Conflict("DELEGATE_ADMISSION_STALE")
  with Tree(host.runtime_root) as tree:
    raw = tree.read("runtime/commands.json")
  registry = json.loads(raw[0]) if raw else {}
  definition = registry.get("programs", {}).get(program)
  if not definition or definition.get("kind") != lease["kind"]:
    raise DependencyError("委托后端未进入所选运行包")
  closed(definition, ("entrypoint", "kind", "engine"), ("backend_entrypoint",))
  if definition["engine"] != ("python" if request["backend"] == "codex" else host.config["engine"]):
    raise DependencyError("委托入口与所选运行引擎不一致")
  entry = host.runtime_root / relative_path(definition["entrypoint"])
  if not entry.is_file() or entry.is_symlink():
    raise DependencyError("委托后端入口缺失")
  temporary = host.root / "activity/delegate-homes" / lease["lease_id"]
  ensure_private(temporary); ensure_private(temporary / "tmp")
  models, credentials = {}, {}
  auth_binding = None
  if request["backend"] == "pi":
    provider_id = request["requested_model"]["provider_id"]
    provider = manifest.get("provider_bindings", {}).get(provider_id, {})
    if provider.get("auth_kind") == "oauth":
      if (provider_id, provider.get("owner")) not in (("openai-codex", "pi-native"), ("cursor", "pi-cursor")):
        raise DependencyError("所选OAuth委托transport尚未适配")
      from .secrets import CredentialError
      from .pi import key_variable
      import math
      with Tree(Path(host.config["instance_root"])) as instance:
        raw = instance.read("pi-home/auth.json", max_bytes=1024 * 1024)
      try:
        selected = json.loads(raw[0]).get(provider_id) if raw and raw[1] == 0o600 else None
        if (not isinstance(selected, dict) or selected.get("type") != "oauth" or not isinstance(selected.get("access"), str)
            or not selected["access"] or any(char in selected["access"] for char in "\0\r\n") or type(selected.get("expires")) not in (int, float)
            or not math.isfinite(selected["expires"])
            or selected["expires"] <= datetime.now(timezone.utc).timestamp() * 1000):
          raise ValueError()
      except (ValueError, TypeError, KeyError):
        raise CredentialError() from None
      if provider_id == "cursor" and (host.config["engine"] != "bun" or route["mode"] != "direct" or value["retry_limit"] != 0):
        raise DependencyError("Cursor 委托要求 Bun、明确 direct 路线与零重试")
      variable = key_variable(provider_id)
      credentials = {variable: selected["access"]}
      models = {"providers": {}}
      auth_binding = {"kind": "oauth-access", "provider_id": provider_id, "environment": variable, "expires_at_ms": selected["expires"]}
    else:
      with Tree(Path(host.config["instance_root"])) as instance:
        raw = instance.read("pi-home/models.json")
      models, credentials = selected_api_models(json.loads(raw[0]), provider_id, request["requested_model"]["model_id"], os.environ,
        supported_apis=("openai-completions", "openai-responses"))
    with Tree(temporary, create=True) as tree:
      tree.write_state("pi-agent/models.json", json_bytes(models))
  elif route.get("credential_ref"):
    # Codex CLI 没有独立的 proxy authorization 注入参数，不能把秘密拼进 URL。
    raise DependencyError("当前Codex代理认证方式未实现")
  env = backend_environment(home=temporary, instance=host.config["instance_root"], route=route, executable=entry, credentials=credentials)
  env.update(AGENTCFG_SUPERVISOR_ENDPOINT=str(host.server.endpoint),
    AGENTCFG_SUPERVISOR_CAPABILITY=host.service.issue_capability("worker", lease["lease_id"]), AGENTCFG_EXECUTION_LEASE_ID=lease["lease_id"],
    AGENTCFG_PYTHON=sys.executable, AGENTCFG_SUPERVISOR_CLIENT=str(host.repository / "scripts/pi-control.py"))
  if request["backend"] == "pi" and route.get("credential_ref"):
    from .pi import route_key_variable
    secret = os.environ.get(route_key_variable(route_id))
    if not secret:
      from .secrets import CredentialError
      raise CredentialError()
    env["AGENTCFG_PI_PROXY_AUTHORIZATION"] = secret
  worker = {"schema_version": 2, "input": value, "reports": str(host.delegates.root / "reports" / request["run_id"]),
    "runtime_root": str(host.runtime_root), "instance_root": host.config["instance_root"], "temporary": str(temporary)}
  if auth_binding:
    worker["auth_binding"] = auth_binding
    if auth_binding["provider_id"] == "cursor":
      cursor = manifest["options"].get("cursor", {})
      if not cursor.get("endpoint"): raise DependencyError("Cursor 委托端点未绑定")
      ensure_private(temporary / "cursor-cache"); ensure_private(temporary / "cursor-home")
      env.update(CURSOR_ACCESS_TOKEN=credentials[auth_binding["environment"]], PI_CURSOR_SYSTEM_CREDENTIALS="deny",
        CURSOR_CONFIG_DIR=str(temporary / "cursor-home"), PI_CURSOR_CACHE_DIR=str(temporary / "cursor-cache"),
        PI_CURSOR_AGENT_URL=cursor["endpoint"], PI_CURSOR_STREAM_IDLE_MAX_RETRIES="0", PI_CURSOR_PROVIDER_DEBUG="0")
      for name in ("PI_CURSOR_CLIENT_VERSION", "PI_CURSOR_RAW_MODELS", "PI_CURSOR_SLIM_TOOLS", "PI_CURSOR_PROMPT_HISTORY",
          "PI_CURSOR_H2_CONNECT_TIMEOUT_MS", "PI_CURSOR_H2_IDLE_TIMEOUT_MS", "PI_CURSOR_STREAM_IDLE_TIMEOUT_MS", "PI_CURSOR_RESUME_IDLE_TIMEOUT_MS"):
        if name in os.environ:
          setting = os.environ[name]
          if len(setting) > 512 or any(char in setting for char in "\0\r\n"): raise DependencyError("Cursor 委托设置无效")
          env[name] = setting
      worker["cursor_endpoint"] = cursor["endpoint"]
      with Tree(Path(host.config["instance_root"])) as instance:
        catalog = instance.read("pi-home/cursor-cache/model-catalog.json", max_bytes=1024 * 1024)
      if catalog is not None:
        try:
          cached = json.loads(catalog[0])
          selected_catalog = {key: cached[key] for key in ("version", "savedAt", "rawModels", "parameterizedModels")}
          if selected_catalog["version"] != 1 or not isinstance(selected_catalog["rawModels"], list) or not isinstance(selected_catalog["parameterizedModels"], list): raise ValueError()
        except (ValueError, KeyError, TypeError): raise DependencyError("Cursor 模型目录格式不兼容") from None
        with Tree(temporary / "cursor-cache") as tree: tree.write_state("model-catalog.json", json_bytes(selected_catalog))
  if request["continuation_of"]:
    prior = host.delegates.runs.read(request["continuation_of"])
    token = prior["receipt"]["backend_resume_token"]
    if request["backend"] == "pi":
      base = host.delegates.root / "reports" / request["continuation_of"] / "sessions"
      path = Path(token).resolve(strict=True)
      if not path.is_relative_to(base) or path.is_symlink() or not path.is_file():
        raise Conflict("DELEGATE_RESUME_TOKEN_IDENTITY")
    worker["resume_token"] = token
  if request["backend"] == "codex":
    from .pi_login import account_available
    account_available(host, lease, login=False)
    if not definition.get("backend_entrypoint"):
      raise DependencyError("Codex CLI 未进入所选运行包")
    executable = (host.runtime_root / relative_path(definition["backend_entrypoint"])).resolve(strict=True)
    if not executable.is_relative_to(host.runtime_root) or not executable.is_file():
      raise DependencyError("Codex CLI 路径越界")
    worker["backend_executable"] = str(executable)
    home = Path(host.config["instance_root"]) / "codex-home"
    ensure_private(home)
    # 统一检查账号归属与配置准入；认证正文不进入 worker 输入或报告。
    from .pi_codex_admission import admit_codex_execution, admit_codex_endpoint
    admit_codex_endpoint(admit_codex_execution(home), value["execution_policy"].get("api_base_url"))
    scratch = temporary / "tools"; ensure_private(scratch)
    worker["native_permissions"] = codex_permissions(manifest["permission_policy"], value["grant"], runtime_root=host.runtime_root,
      codex_home=home, scratch=scratch, protected_roots=host.config.get("protected_roots", []),
      native=value["execution_policy"]["native_execution"], root_limits=value["execution_policy"]["root_limits"])
    from .pi_delegate_policy import record_native_authorization
    record_native_authorization(host.delegates.root, request, worker["native_permissions"])
  with Tree(host.root) as tree:
    name = "activity/delegate-worker-inputs/" + lease["lease_id"] + ".json"
    tree.write_immutable(name, json_bytes(worker))
  engine = sys.executable if definition["engine"] == "python" else getattr(host, "engine_executable", None)
  if not engine or not Path(engine).is_absolute() or not Path(engine).is_file() or not os.access(engine, os.X_OK):
    raise DependencyError("委托解释器未绑定到监督者的显式工具链")
  flags = ("--no-install", "--no-env-file", "--no-macros", "--config=" + str(host.runtime_root / "runtime/bunfig.locked.toml"),
    "--tsconfig-override=" + str(host.runtime_root / "runtime/tsconfig.locked.json")) if definition["engine"] == "bun" else ()
  argv = (engine, "-B", "-I", str(entry), "--input", str(host.root / name)) if definition["engine"] == "python" else (engine, *flags, str(entry), "--input", str(host.root / name))
  return SpawnCommand(argv, Path(request["cwd"]), env)
