"""原生验收的新实例与合成 Git 项目；不采纳真实机器模型、账号或 HOME。"""
import base64
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from .adapter import SecretRef
from .deployment import json_bytes, put_field
from .process import DependencyError
from .schema import ConfigError
from .pi_scope import PROFILES
from .storage import Conflict, Tree, ensure_private
from .workspace import load_workspace


MODELS = {role: "agentcfg-native-" + role for role in ("main", "reader", "writer", "reviewer", "second-view")}

# 最小合成 PDF（603 字节，1 页文本“readseek native view fixture”）；readSeek_view 只支持真实文档格式。
NATIVE_SAMPLE_PDF = base64.b64decode(
  "JVBERi0xLjQKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4KZW5kb2Jq"
  "CjIgMCBvYmoKPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4KZW5kb2Jq"
  "CjMgMCBvYmoKPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAgUiAvTWVkaWFCb3ggWzAgMCA2MTIg"
  "NzkyXSAvQ29udGVudHMgNCAwIFIgL1Jlc291cmNlcyA8PCAvRm9udCA8PCAvRjEgNSAwIFIgPj4g"
  "Pj4gPj4KZW5kb2JqCjQgMCBvYmoKPDwgL0xlbmd0aCA1OSA+PgpzdHJlYW0KQlQgL0YxIDI0IFRm"
  "IDcyIDcwMCBUZCAocmVhZHNlZWsgbmF0aXZlIHZpZXcgZml4dHVyZSkgVGogRVQKZW5kc3RyZWFt"
  "CmVuZG9iago1IDAgb2JqCjw8IC9UeXBlIC9Gb250IC9TdWJ0eXBlIC9UeXBlMSAvQmFzZUZvbnQg"
  "L0hlbHZldGljYSA+PgplbmRvYmoKeHJlZgowIDYKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAw"
  "MDA5IDAwMDAwIG4gCjAwMDAwMDAwNTggMDAwMDAgbiAKMDAwMDAwMDExNSAwMDAwMCBuIAowMDAw"
  "MDAwMjQxIDAwMDAwIG4gCjAwMDAwMDAzNTAgMDAwMDAgbiAKdHJhaWxlcgo8PCAvU2l6ZSA2IC9S"
  "b290IDEgMCBSID4+CnN0YXJ0eHJlZgo0MjAKJSVFT0YK")


def _toml(document):
  lines = []
  def visit(table, prefix):
    if prefix: lines.extend(("", "[" + ".".join(json.dumps(part) for part in prefix) + "]"))
    for key, value in table.items():
      if not isinstance(value, dict): lines.append(json.dumps(key) + " = " + json.dumps(value, ensure_ascii=False))
    for key, value in table.items():
      if isinstance(value, dict): visit(value, [*prefix, key])
  visit(document, [])
  return ("\n".join(lines) + "\n").encode()


def prepare_configuration(root, repository, profile, provider_url, programs, *, run, second_view=False, request_limit=100, fixing=False, preinstalled_runtime=None, codex_mode=None, service=None, proxy=False, readseek=False):
  # ReadSeek现在支持pi-default、pi-codex和pi-cursor
  # pi-cursor使用Bun宿主，但ReadSeek worker需要独立的Node
  root = Path(root).absolute(); repository = Path(repository).absolute()
  endpoint = urlsplit(provider_url)
  if (endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or endpoint.port is None or endpoint.path != "/v1"
      or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment): raise ConfigError("pi-native-provider-loopback")
  if profile not in PROFILES: raise ConfigError("pi-native-fixture-profile")
  if codex_mode is not None and (profile != "pi-codex" or codex_mode not in ("readonly", "write")): raise ConfigError("pi-native-codex-mode")
  if service is not None and (profile != "pi-default" or service not in ("mcp", "web", "terminal")): raise ConfigError("pi-native-service")
  if type(proxy) is not bool or proxy and (profile not in ("pi-default", "pi-managed") or service is not None): raise ConfigError("pi-native-proxy")
  if root.exists() or root.is_symlink():
    if preinstalled_runtime is None: raise Conflict("PI_NATIVE_FIXTURE_EXISTS")
    slot = Path(preinstalled_runtime)
    expected = root / "instances_root/pi" / profile / "runtimes" / slot.name
    if slot != expected or slot.resolve(strict=True) != slot or not os.statvfs(slot).f_flag & os.ST_RDONLY: raise Conflict("PI_NATIVE_FIXTURE_EXISTS")
    directory = root
    for component in expected.relative_to(root).parts:
      if directory.is_symlink() or {path.name for path in directory.iterdir()} != {component}: raise Conflict("PI_NATIVE_FIXTURE_EXISTS")
      directory /= component
  required = {"engine", "git", "python", "python_runtime", "python_packages"}
  # 允许programs中包含额外的"node"字段（用于ReadSeek worker）
  allowed = required | {"node"}
  if not set(programs).issubset(allowed) or not required.issubset(set(programs)) or any(not Path(value).is_absolute() for value in programs.values()): raise ConfigError("pi-native-program-bindings")
  if type(second_view) is not bool or type(fixing) is not bool or type(request_limit) is not int or not 1 <= request_limit <= 1000: raise ConfigError("pi-native-fixture-options")
  ensure_private(root)
  project = root / "project"; tools = root / "fixture-tools"; home = root / "home"
  for path in (project, tools, home): ensure_private(path)
  with Tree(project) as tree:
    tree.write_new("code.txt", b"original\n")
    expected = "changed\n" if fixing else "original\n"
    tree.write_new("test_native_fixture.py", ('from pathlib import Path\n\ndef test_bounded_change():\n  assert Path("code.txt").read_text() == ' + json.dumps(expected) + "\n").encode())
    if readseek: tree.write_new("sample.pdf", NATIVE_SAMPLE_PDF)
  driver = ("import os,runpy,sys\n"
    'os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]="1"\n'
    'sys.path.insert(0,sys.argv[1])\n'
    'sys.argv=["pytest","-q","-p","no:cacheprovider","--confcutdir",os.getcwd(),"test_native_fixture.py"]\n'
    'runpy.run_module("pytest",run_name="__main__")\n')
  with Tree(tools) as tree: tree.write_new("check.py", driver.encode())
  environment = {"HOME": str(home), "PATH": os.pathsep.join(dict.fromkeys(str(Path(programs[name]).parent) for name in ("engine", "git", "python"))),
    "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_ATTR_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0", "PYTHONDONTWRITEBYTECODE": "1", "PI_SKIP_VERSION_CHECK": "1",
    **{name: str(home / name.lower()) for name in ("CODEX_HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR")}}
  for name, value in environment.items():
    if value.startswith(str(home) + "/"): ensure_private(Path(value))
  for argv in ([programs["git"], "-c", "init.templateDir=", "init"],
      [programs["git"], "symbolic-ref", "HEAD", "refs/heads/main"],
      [programs["git"], "add", "--", "code.txt", "test_native_fixture.py"],
      [programs["git"], "-c", "user.name=agentcfg native fixture", "-c", "user.email=native@example.invalid", "-c", "commit.gpgsign=false", "commit", "-m", "native fixture baseline"]):
    run(argv, cwd=project, env=environment)
  managed = profile == "pi-managed"
  roles = {"main": "native-main"}
  if managed: roles.update(task_keeper_reader="native-reader", task_keeper_writer="native-writer", task_keeper_reviewer="native-reviewer")
  else: roles.update(scout="native-reader", reviewer="native-reviewer")
  if second_view:
    if not managed: raise ConfigError("pi-native-second-view-profile")
    roles["second_view"] = "native-second-view"
  options = {"permissions": {"policy_ref": "task-keeper-candidate"}, "network": {"routes": {"native-direct": {"mode": "direct", "provider_ids": ["native-fixture"]}}},
    "paths": {"roots": {"project": {"path": str(project), "purpose": "project"},
      "fixture-tools": {"path": str(tools), "purpose": "read"},
      "python-packages": {"path": programs["python_packages"], "purpose": "read"}}},
    "model_settings": {"native-" + role: {"reasoning": True} for role in MODELS}}
  if managed:
    options["task_keeper"] = {"enabled": True, "project_root": "project", "check_ids": ["native-build", "native-tests"],
      "second_view_enabled": second_view, "limits": {"model_requests": request_limit, "model_turns": request_limit, "wall_seconds": 900}}
    options["checks"] = {
      "native-build": {"executable": programs["python"], "args": ["-I", "-c", 'from pathlib import Path; compile(Path("code.txt").read_text(), "code.txt", "exec")'],
        "project_root": "project", "read_roots": [], "foreground": True, "timeout_seconds": 30, "kind": "build", "parser": "exit-code", "minimum_tests": 1, "inputs": []},
      "native-tests": {"executable": programs["python"], "args": ["-B", "-I", str(tools / "check.py"), programs["python_packages"]],
        "project_root": "project", "read_roots": ["python-packages", "fixture-tools"], "foreground": True, "timeout_seconds": 30,
        "kind": "tests", "parser": "pytest", "minimum_tests": 1, "inputs": ["test_native_fixture.py"]}}
  else:
    options["model_delegate"] = {"pi": {"model_roles": ["scout", "reviewer"], "network_route": "native-direct"}}
  if readseek:
    # ReadSeek原生验收接线（场景级显式选择，同服务验收模式）：node配方用锁定node引擎作计算worker解释器；
    # Bun配方(cursor)也需要独立的node绑定，因为ReadSeek worker需要锁定Node版本。
    import shutil
    toolchains = json.loads((repository / "locks/pi/manifest.json").read_text())["toolchains"]
    rg = shutil.which("rg")
    if not rg: raise DependencyError("原生ReadSeek验收需要明确的rg前提")
    # ReadSeek worker必须使用独立的Node，不能退回Bun
    node_executable = programs.get("node")
    if not node_executable:
      raise DependencyError("ReadSeek worker需要独立的Node解释器，但当前环境未提供。请确保Node已安装并在PATH中。")
    # 核验Node版本与锁定版本一致
    node_version_result = subprocess.run([node_executable, "--version"], capture_output=True, text=True, check=True)
    actual_version = node_version_result.stdout.strip()
    expected_version = toolchains["node"]
    if actual_version != expected_version:
      raise DependencyError(f"ReadSeek worker需要Node版本{expected_version}，但实际版本为{actual_version}")
    options["external_tools"] = {
      "readseek-node": {"executable": node_executable, "args": [], "version": toolchains["node"]},
      "readseek-git": {"executable": programs["git"], "args": [], "version": "native-fixture",
        "project_root": "project", "read_roots": ["project"], "write_roots": [], "timeout_seconds": 60},
      "readseek-rg": {"executable": str(Path(rg).resolve(strict=True)), "args": [], "version": "native-fixture",
        "project_root": "project", "read_roots": ["project"], "write_roots": [], "timeout_seconds": 60}}
    options["readseek"] = {"node_tool_ref": "readseek-node", "git_tool_ref": "readseek-git", "rg_tool_ref": "readseek-rg", "max_seconds": 300}
    options["permissions"]["policy_ref"] = "readseek-candidate"
  if codex_mode is not None:
    options["permissions"]["policy_ref"] = "delegate-worktree-readseek" if readseek else "delegate-worktree"
    options["model_delegate"]["codex"] = {"model": "agentcfg-native-codex", "network_route": "native-direct", "api_base_url": provider_url,
      "mode": "explicit-write" if codex_mode == "write" else "readonly"}
    if codex_mode == "write": options["model_delegate"]["allowed_modes"] = ["review", "investigate", "implement"]
  if profile == "pi-cursor":
    # 只验证 Cursor 插件加载；未选 Cursor 模型，不调用该真实账号端点。
    options["cursor"] = {"endpoint": "https://agentn.us.api5.cursor.sh", "network_route": "cursor-direct"}
    options["network"]["routes"]["cursor-direct"] = {"mode": "direct", "provider_ids": ["cursor"]}
  document = {"schema_version": 1, "machine": {"id": "native-fixture", "default_profile": profile,
    "paths": {name: str(root / name) for name in ("instances_root", "state_root", "cache_root")}},
    "overrides": {"providers": {"native-fixture": {"protocol": "openai-compatible", "base_url": provider_url, "auth_kind": "api-key", "credential_ref": "secret:native-key"}},
      "models": {"native-" + role: {"provider": "native-fixture", "remote_id": model, "input": ["text"], "context_window": 32768, "max_output_tokens": 4096} for role, model in MODELS.items()},
      "profiles": {profile: {"providers": ["native-fixture", *(["cursor"] if profile == "pi-cursor" else [])], "models": ["native-" + role for role in MODELS], "roles": roles, "agent_options": options}}},
    "secrets": {"native-key": "synthetic-native-key"}}
  local = root / "local.toml"
  if proxy:
    document["overrides"]["providers"]["native-fixture"]["base_url"] = "http://agentcfg-native.invalid/v1"
    options["network"]["routes"]["native-direct"] = {"mode": "proxy", "proxy_url": provider_url.removesuffix("/v1"),
      "provider_ids": ["native-fixture"], "credential_ref": "secret:native-proxy-key"}
    document["secrets"]["native-proxy-key"] = "Bearer synthetic-proxy-key"
  if service:
    selected = document["overrides"]["profiles"][profile]
    selected["plugins"] = ["pi-subagents", "pi-permissions", "model-delegate", *({"mcp": ["pi-mcp"], "web": ["pi-web"], "terminal": []}[service])]
    origin = provider_url.removesuffix("/v1")
    if service == "mcp":
      selected["mcp"] = ["native-mcp"]
      document["overrides"]["mcp"] = {"native-mcp": {"transport": "streamable-http", "url": origin + "/mcp", "credential_ref": "secret:native-mcp-key"}}
      options["mcp"] = {"servers": {"native-mcp": {"transport": "streamable-http", "network_route": "native-service", "authentication": "bearer"}}}
      options["network"]["routes"]["native-service"] = {"mode": "direct", "provider_ids": [], "service_ids": ["mcp:native-mcp"]}
      document["secrets"]["native-mcp-key"] = "synthetic-mcp-key"
    elif service == "web":
      options["web"] = {"providers": ["searxng"], "services": {"searxng": {"type": "api", "origins": [origin], "network_route": "native-service", "allow_ranges": ["127.0.0.1/32"]}},
        "header_credentials": {"searxng": {"X-Agentcfg-Fixture-Key": "secret:native-web-key"}}, "endpoints": {"searxngBaseUrl": origin + "/searxng"}}
      options["network"]["routes"]["native-service"] = {"mode": "direct", "provider_ids": [], "service_ids": ["web:searxng"]}
      document["secrets"]["native-web-key"] = "synthetic-web-key"
    else:
      service_tools = root / "service-tools"; ensure_private(service_tools)
      script = service_tools / "terminal.py"
      with Tree(service_tools) as tree: tree.write_new(script.name, b'import json,sys\nfrom pathlib import Path\nassert sys.argv[-2] == "native-pane"\nassert sys.argv[-1] in ("working","blocked","idle")\nwith Path("native-terminal-states.jsonl").open("a") as out: out.write(json.dumps(sys.argv[-1])+"\\n")\n')
      options["resources"] = {"extensions": ["gentle-agent-state"]}
      options["agent_state"] = {"mode": "service", "executable": programs["python"], "version": "native-fixture", "args": ["-B", "-I", str(script)],
        "files": [str(script)], "socket_paths": [], "environment": {}, "pane": "native-pane", "timeout_seconds": 10}
  if readseek:
    if service is not None: raise ConfigError("pi-native-readseek-service-exclusive")
    selected = document["overrides"]["profiles"][profile]
    # cursor 配方的 cursor provider 由 pi-cursor 插件拥有；ReadSeek 接线只能追加，不能整表替换后剥离必需插件。
    selected["plugins"] = ["pi-subagents", "pi-permissions", "model-delegate", "pi-todo", "loop-guard", "colorful-footer",
      *(["pi-cursor"] if profile == "pi-cursor" else []), "pi-readseek"]
  with Tree(root) as tree: tree.write_new(local.name, _toml(document))
  workspace = load_workspace(local, profile, repository=repository)
  return {"workspace": workspace, "environment": environment, "project": project, "model_ids": tuple(MODELS.values()), "fixture_root": root}


def prepare_fixture(root, repository, runtime, provider_url, programs, *, run, second_view=False, request_limit=100, fixing=False, service=None, proxy=False, readseek=False):
  fixture = prepare_configuration(root, repository, getattr(runtime, "profile", None), provider_url, programs, run=run, second_view=second_view, request_limit=request_limit, fixing=fixing, service=service, proxy=proxy, readseek=readseek)
  workspace, environment = fixture["workspace"], fixture["environment"]
  candidate = workspace.candidate(runtime.lock_identity)
  fields = {}
  with Tree(workspace.instance, create=True) as target:
    for artifact in candidate.artifacts:
      if artifact.target.selector:
        native = fields.setdefault(artifact.target.path, {})
        put_field(native, artifact.target.selector, {"present": True, "value": json.loads(artifact.content)})
      else: target.replace(artifact.target.path, artifact.content, mode=artifact.mode, expected=None)
    for path, native in fields.items(): target.write_new(path, json_bytes(native))
  return finish_fixture(fixture, runtime, candidate)


def prepare_deployed_fixture(root, repository, runtime, provider_url, programs, *, run, codex_mode=None, proxy=False):
  from .deployment import apply
  from .pi_lifecycle import guard
  from .runtime import record
  fixture = prepare_configuration(root, repository, runtime.profile, provider_url, programs, run=run, preinstalled_runtime=runtime.root, codex_mode=codex_mode, proxy=proxy)
  workspace = fixture["workspace"]
  lock = workspace.backend.read_lock(workspace.repository)
  if lock.identity != runtime.lock_identity or workspace.backend.root(workspace, runtime.identity) != runtime.root:
    raise Conflict("PI_NATIVE_DEPLOYMENT_RUNTIME_MISMATCH")
  candidate = workspace.candidate(lock.identity)
  launch = record(workspace, lock)
  if launch.get("runtime_identity") != runtime.identity: raise Conflict("PI_NATIVE_DEPLOYMENT_RUNTIME_MISMATCH")
  with guard(workspace): apply(workspace.instance, workspace.state_root, candidate, workspace.binding, launch)
  return finish_fixture(fixture, runtime, candidate)


def finish_fixture(fixture, runtime, candidate):
  workspace, environment = fixture["workspace"], fixture["environment"]
  workspace.adapter.prepare_runtime(workspace, runtime.root)
  spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=fixture["project"], runtime_root=runtime.root, instance_root=workspace.instance, lock_identity=runtime.lock_identity)
  for binding in spec.environment:
    value = workspace.secret_store.resolve(binding.value, required=binding.required) if isinstance(binding.value, SecretRef) else binding.value
    if value is not None: environment[binding.name] = value
  return {**fixture, "spec": spec, "generation": candidate.generation}
