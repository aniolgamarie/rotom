"""现代SDK入口安装：仅复制锁定仓库文件，包入口在CLI中再按公开exports解析。"""

import json
from pathlib import Path
import re

from .deployment import json_bytes
from .process import DependencyError
from .schema import ConfigError
from .storage import Conflict, Tree
from .pi_runtime_files import install_files, validate_files


REQUIRED = {"runtime/official-launch.mjs", "supervisor/scripts/pi-supervisor.py", "supervisor/scripts/pi-control.py",
  "supervisor/scripts/pi-exec.py", "supervisor/scripts/pi-file-operation.py", "supervisor/scripts/pi-project-check",
  "supervisor/src/agentcfg/pi_host.py", "supervisor/scripts/pi-shell.py"}
REQUIRED_SCHEMAS = {"supervisor/agents/pi/schemas/" + name + ".schema.json" for name in (
  "process-identity", "execution-lease", "workspace-write-lease", "termination-evidence", "stop-recovery-plan", "stop-recovery", "permission-policy", "operation-grant", "options")}
LINUX_REQUIRED = {"supervisor/scripts/pi-namespace-exec.py", "supervisor/src/agentcfg/pi_pid_namespace.py",
  "supervisor/src/agentcfg/pi_assets.py"}

COMMANDS = {"schema_version": 1, "programs": {
  "file-operation": {"entrypoint": "supervisor/scripts/pi-file-operation.py", "kind": "external", "engine": "python"},
  "ordinary-command": {"entrypoint": "supervisor/scripts/pi-project-check", "kind": "external", "engine": "python"},
  "ordinary-shell": {"entrypoint": "supervisor/scripts/pi-shell.py", "kind": "external", "engine": "python"}}}

def commands(piece):
  from copy import deepcopy
  value = deepcopy(COMMANDS)
  if "unified-delegate" in piece.get("capability_ids", []):
    value["programs"]["delegate-pi"] = {"entrypoint": "runtime/official-delegate-worker-main.mjs", "kind": "external", "engine": "node"}
  if "task-workflow" in piece.get("capability_ids", []):
    value["programs"]["workspace"] = {"entrypoint": "runtime/workspace-main.mjs", "kind": "external", "engine": "node"}
    value["programs"]["check"] = {"entrypoint": "supervisor/scripts/pi-project-check", "kind": "check", "engine": "python"}
  return value


OWNER_ORIGIN = "runtime/durable-owner-origin.json"
OWNER_MODULES = ("activity", "adapter", "config", "deployment", "local_values", "merge", "model_defaults", "native_projection",
  "paths", "pi_assets", "pi_built_assets", "pi_bwrap_build", "pi_bwrap_source", "pi_capabilities", "pi_catalog", "pi_lock_header",
  "pi_lock_layout", "pi_lock_metadata", "pi_lock_resolution", "pi_modern_launcher", "pi_node_archive", "pi_node_asset",
  "pi_python_bundle", "pi_readseek_vision", "pi_runtime_files", "pi_vendor", "pi_wheel_sources", "process", "schema", "secret_files", "secrets", "storage")
OWNER_CODE_ROWS = {
  "owner_bootstrap": {"source": "agents/pi/runtime/durable-owner-bootstrap.ts", "path": "runtime/durable-owner-bootstrap.mjs", "transform": "ts-module"},
  "owner_codec": {"source": "agents/pi/packages/durable-service/src/owner-message.ts", "path": "runtime/durable-owner-message.mjs", "transform": "ts-module"},
  "owner_controller": {"source": "scripts/pi-durable-owner-controller.py", "path": "supervisor/scripts/pi-durable-owner-controller.py", "transform": "copy"}}
OWNER_REQUIRED_ROWS = tuple({"source": "src/agentcfg/" + name + ".py", "path": "supervisor/src/agentcfg/" + name + ".py", "transform": "copy"}
  for name in (*OWNER_MODULES, "pi_python_bundle_runtime", "pi_python_bundle_stage", "pi_owner_origin")) + (
  {"source": "schemas/pi-lock.schema.json", "path": "supervisor/schemas/pi-lock.schema.json", "transform": "copy"},
  {"source": "agents/pi/schemas/durable-owner-origin.schema.json", "path": "supervisor/agents/pi/schemas/durable-owner-origin.schema.json", "transform": "copy"},
  *OWNER_CODE_ROWS.values())


def _owner_rows(declaration, rows, reference, *, locked):
  from .pi_lock_metadata import _Capture
  declaration, rows, reference = _Capture().capture([declaration, rows, reference])
  if (type(declaration) is not dict or set(declaration) != {"schema_version", "protocol_version", "roles"}
      or any(type(declaration[key]) is not int or declaration[key] != 1 for key in ("schema_version", "protocol_version"))): raise ValueError()
  roles = declaration["roles"]
  if type(roles) is not dict or set(roles) != {"owner_node", *OWNER_CODE_ROWS}: raise ValueError()
  node = roles["owner_node"]
  if (type(node) is not dict or set(node) != {"source_id", "path"} or type(node["source_id"]) is not str
      or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", node["source_id"]) or node["path"] != "bin/pi-node"): raise ValueError()
  if any(roles[name] != row for name, row in OWNER_CODE_ROWS.items()): raise ValueError()
  from .pi_runtime_files import _validate, validate_manifest
  if locked: validate_manifest(rows)
  else: _validate(rows, locked=False)
  actual = {row["path"]: row for row in rows}
  if OWNER_ORIGIN in actual: raise ValueError()
  for expected in OWNER_REQUIRED_ROWS:
    if expected["path"] not in actual or any(actual[expected["path"]][key] != value for key, value in expected.items()): raise ValueError()
  if (type(reference) is not dict or set(reference) != {"schema_version", "source", "path", "sha256", "size"}
      or type(reference["schema_version"]) is not int or reference["schema_version"] != 1
      or reference["source"] != "agents/pi/runtime/durable-python-bundle.json" or reference["path"] != "runtime/durable-python-bundle.json"
      or type(reference["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", reference["sha256"])
      or type(reference["size"]) is not int or not 1 <= reference["size"] <= 8388608): raise ValueError()
  body = actual.get(reference["path"])
  if body is None or any(body[key] != value for key, value in {"source": reference["source"], "transform": "copy"}.items()): raise ValueError()
  if locked and (body["input_digest"] != reference["sha256"] or body["digest"] != reference["sha256"]): raise ValueError()
  return declaration


def validate_owner_declaration(name, piece, sources, *, toolchains, locked):
  """公开声明数据核；不导入 origin IO resolver，也不签发角色资格。"""
  failed = False
  try:
    from .pi_lock_metadata import _Capture
    if type(name) is not str or name != "pi-full" or type(locked) is not bool: raise ValueError()
    piece, sources, toolchains = _Capture().capture([piece, sources, toolchains])
    if type(piece) is not dict or type(sources) is not dict or piece["engine"] != "node": raise ValueError()
    declaration = _owner_rows(piece["durable_owner"], piece["runtime_files"], piece["python_bundle"], locked=locked)
    source_id = declaration["roles"]["owner_node"]["source_id"]
    if source_id not in piece["source_ids"]: raise ValueError()
    from .pi_node_asset import validate_node_asset_toolchain
    validate_node_asset_toolchain(sources[source_id], toolchains)
    from .pi_wheel_sources import validate_python_bundle_reference
    validate_python_bundle_reference(name, piece, sources, locked=locked)
  except Exception:
    failed = True
  if failed:
    try: raise ConfigError("pi-runtime-owner-invalid")
    except ConfigError as error:
      error.__cause__ = None; error.__context__ = None
      raise


def validate_destinations(piece, manifest):
  if "durable_owner" in piece:
    if manifest["schema_version"] != 2 or manifest["profile_slices"].get("pi-full") != piece: raise ConfigError("pi-runtime-owner-invalid")
    validate_owner_declaration("pi-full", piece, manifest["sources"], toolchains=manifest["toolchains"], locked=True)
  required = REQUIRED | REQUIRED_SCHEMAS
  if any(name.startswith("linux-") for name in manifest["platforms"]): required |= LINUX_REQUIRED
  # 必要入口子集；不能据此声称完整的静态或动态导入闭包。
  if not required <= {row["path"] for row in piece["runtime_files"]}: raise ConfigError("pi-runtime-entrypoints-missing")
  def intersects(path):
    parts = tuple(path.casefold().split("/"))
    reserved = ("supervisor", "python-bundle")
    return parts == reserved[:len(parts)] or reserved == parts[:len(reserved)]
  if "python_bundle" in piece and any(intersects(row["path"]) for row in piece["runtime_files"]):
    raise ConfigError("pi-runtime-python-bundle-collision")
  for name in piece["source_ids"]:
    source = manifest["sources"][name]
    if "python_bundle" in piece and source["kind"] == "asset" and intersects(source["target"]):
      raise ConfigError("pi-runtime-python-bundle-collision")
    if source["kind"] == "asset" and source["target"].split("/", 1)[0] in ("runtime", "supervisor", "licenses"):
      # 这些命名空间只归显式仓库文件及生成描述，禁止资产被后续复制悄悄覆盖。
      raise ConfigError("pi-runtime-asset-collision")


def _document(tree, path):
  raw = tree.read(path, max_bytes=16 * 1024 * 1024)
  if raw is None: raise ValueError()
  result = json.loads(raw[0])
  if not isinstance(result, dict): raise ValueError()
  return result


def packages(tree, piece):
  """静态还原SDK包根到slice根的Node查找顺序；绝不查运行树之外或全局包。"""
  prefix = Path(piece["package_path"]).parent
  relative = Path(piece["entrypoint"]).relative_to(prefix / "node_modules")
  count = 2 if relative.parts[0].startswith("@") else 1
  sdk_name = "/".join(relative.parts[:count])
  sdk_root = prefix / "node_modules" / sdk_name
  locked = _document(tree, piece["lock_path"])["packages"]
  def package(path, name):
    document = _document(tree, (path / "package.json").as_posix())
    record = locked[path.relative_to(prefix).as_posix()]
    if (document.get("name") != name or document.get("version") != record.get("version")
        or record.get("name", name) != name or not isinstance(record.get("version"), str)):
      raise ValueError()
    return document
  host = package(sdk_root, sdk_name)
  ai_name = piece["ai_package"]
  if not isinstance(ai_name, str) or not re.fullmatch(r"(?:@[a-zA-Z0-9_.-]+/)?[a-zA-Z0-9_.-]+", ai_name): raise ValueError()
  directory = sdk_root
  while True:
    if directory.name != "node_modules":
      candidate = directory / "node_modules" / ai_name
      if tree.read((candidate / "package.json").as_posix()) is not None:
        ai = package(candidate, ai_name)
        return {"sdk_package": host["name"], "sdk_version": host["version"], "ai_package": ai["name"], "ai_version": ai["version"]}
    if directory == prefix: break
    directory = directory.parent
    if not directory.is_relative_to(prefix): raise ValueError()
  raise ValueError()


def validate_locked_ai(resolution, piece):
  prefix = Path(piece["package_path"]).parent
  relative = Path(piece["entrypoint"]).relative_to(prefix / "node_modules")
  count = 2 if relative.parts[0].startswith("@") else 1
  directory = Path("node_modules") / "/".join(relative.parts[:count])
  while True:
    if directory.name != "node_modules" and (directory / "node_modules" / piece["ai_package"]).as_posix() in resolution["packages"]:
      return
    if directory == Path("."): break
    directory = directory.parent
  raise ConfigError("pi-runtime-ai-missing")


def validate_profile(root, piece, *, identity=None, lock_identity=None, toolchains=None, profile_id=None):
  try:
    from .pi_dependencies import platform_id
    with Tree(Path(root)) as tree:
      profile = _document(tree, "runtime/profile.json")
      required = {"schema_version", "profile_id", "package_path", "engine", "entrypoint", "resources", "lock_identity",
        "sdk_package", "sdk_version", "ai_package", "ai_version", "slice_identity", "toolchains", "platform", "runtime_identity"}
      if set(profile) != required or type(profile["schema_version"]) is not int or profile["schema_version"] != 2:
        raise ValueError()
      expected = {"engine": piece["engine"], "package_path": piece["package_path"], "entrypoint": piece["entrypoint"],
        "resources": piece["resource_manifest"], "slice_identity": piece["identity"], "platform": platform_id(), **packages(tree, piece)}
      if (any(profile[key] != value for key, value in expected.items()) or profile["profile_id"] not in ("pi-base", "pi-full")
          or profile["engine"] != "node" or _document(tree, "runtime/commands.json") != commands(piece)):
        raise ValueError()
      if any(wanted is not None and profile[key] != wanted for key, wanted in (
          ("runtime_identity", identity), ("lock_identity", lock_identity), ("toolchains", toolchains), ("profile_id", profile_id))):
        raise ValueError()
  except Exception:
    raise Conflict("Pi现代启动描述与安装内容不一致") from None


def install_launcher(repository, stage, piece, manifest, *, runtime_identity):
  try:
    from .pi_dependencies import platform_id
    from .pi_vendor import install_source_licenses
    if (not isinstance(runtime_identity, str) or not re.fullmatch("[0-9a-f]{64}", runtime_identity) or piece["engine"] != "node"):
      raise ValueError()
    validate_destinations(piece, manifest)
    selected = [name for name, value in manifest["profile_slices"].items() if value == piece]
    if len(selected) != 1: raise ValueError()
    with Tree(Path(stage)) as target:
      info = packages(target, piece)
    host = manifest["sources"]["pi-host"]
    if "pi-host" not in piece["source_ids"] or info["sdk_package"] != host["package"] or info["sdk_version"] != host["version"]:
      raise ValueError()
    install_files(repository, stage, piece["runtime_files"])
    with Tree(Path(repository), private=False) as source, Tree(Path(stage)) as target:
      prefix = Path(piece["package_path"]).parent
      for identity in piece["source_ids"]:
        record = manifest["sources"][identity]
        if record["kind"] in ("local", "git"): install_source_licenses(source, target, prefix, record)
      from .pi_license_bundle import validate_installed
      validate_installed(stage, piece, _document(target, piece["lock_path"]))
      target.write_state("runtime/commands.json", json_bytes(commands(piece)))
      target.write_state("runtime/profile.json", json_bytes({"schema_version": 2, "profile_id": selected[0],
        "engine": piece["engine"], "package_path": piece["package_path"], "entrypoint": piece["entrypoint"],
        "resources": piece["resource_manifest"], "lock_identity": manifest["identity"], **info,
        "slice_identity": piece["identity"], "toolchains": manifest["toolchains"], "platform": platform_id(),
        "runtime_identity": runtime_identity}))
    validate_files(stage, piece["runtime_files"])
    validate_profile(stage, piece, identity=runtime_identity, lock_identity=manifest["identity"],
      toolchains=manifest["toolchains"], profile_id=selected[0])
  except Exception:
    raise DependencyError("Pi现代启动闭包缺失或不一致") from None
