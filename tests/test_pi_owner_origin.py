"""B3 默认材料：真实原pipeline、合成不执行的角色/Node、原offline guards。"""

import builtins
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat

import pytest
from jsonschema import Draft202012Validator

from agentcfg import pi_capabilities as capabilities
from agentcfg import pi_dependencies as dependencies
from agentcfg import pi_modern_launcher as launcher
from agentcfg import pi_owner_origin as origin
from agentcfg import pi_runtime_packages as packages
from agentcfg.deployment import json_bytes
from agentcfg.pi_lock_metadata import _Capture, capture_pi_lock_metadata_data
from agentcfg.pi_runtime_files import validate_files
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_pi_dependencies import fake_installer
from test_pi_wheel_lock_integration import _fixture, _write_inputs, _republish
from test_pi_node_archive import fixture as node_archive, BINARY, LICENSE
from test_pi_node_asset import source as node_source


ROOT = Path(__file__).resolve().parents[1]
_CALLBACKS = []


@pytest.fixture(autouse=True)
def callback_sentinel():
  _CALLBACKS.clear()
  yield
  assert _CALLBACKS == []


def _sha(raw):
  return hashlib.sha256(raw).hexdigest()


def _owner():
  return {"schema_version": 1, "protocol_version": 1, "roles": {
    "owner_node": {"source_id": "owner-node", "path": "bin/pi-node"}, **deepcopy(launcher.OWNER_CODE_ROWS)}}


def _prepare(tmp_path, monkeypatch, *, current=True, large_node=False):
  workspace, inputs, path, calls, declaration, archives = _fixture(tmp_path, monkeypatch)
  root = workspace.repository
  full = inputs["profiles"]["pi-full"]
  full["durable_owner"] = _owner()
  by_path = {row["path"]: row for row in full["runtime_files"]}
  for row in launcher.OWNER_REQUIRED_ROWS:
    target = root / row["source"]; target.parent.mkdir(parents=True, exist_ok=True)
    if row["source"].startswith(("src/agentcfg/", "schemas/", "agents/pi/schemas/")):
      target.write_bytes((ROOT / row["source"]).read_bytes())
    else:
      target.write_bytes(b"// synthetic fixed role; never executed\n" if row["transform"] == "ts-module" else b"# synthetic fixed role; never executed\n")
    by_path[row["path"]] = deepcopy(row)
  full["runtime_files"] = list(by_path.values())
  binary = BINARY + (b"inert zero payload\x00" * 65536 if large_node else b"")
  def change(entries):
    return [(name, binary if name.endswith("/bin/node") else raw, kind, mode, link) for name, raw, kind, mode, link in entries]
  raw = node_archive(change=change)
  source = node_source(raw, vendor=True)
  source["node_archive"]["binary_sha256"] = _sha(binary)
  inputs["sources"]["owner-node"] = source
  full["source_ids"].append("owner-node")
  vendor = root / "locks/pi-modern" / source["vendor_path"]; vendor.parent.mkdir(parents=True, exist_ok=True); vendor.write_bytes(raw)
  license_file = root / source["license_files"][0]; license_file.parent.mkdir(parents=True, exist_ok=True); license_file.write_bytes(LICENSE)
  bindings = inputs["capability_bindings"]
  bindings["catalog"]["capabilities"]["durable"]["source_ids"].append("owner-node")
  bindings["catalog"]["source_profiles"]["owner-node"] = ["pi-full"]
  bindings["providers"]["durable-provider"]["support_sources"].append({"source_id": "owner-node", "source_version": None, "source_identity": capabilities.source_identity(source)})
  _write_inputs(path, inputs)
  lock = dependencies.PiBackend(family="modern").resolve_lock(root)
  assert "durable_owner" in lock.metadata["profile_slices"]["pi-full"]
  if current:
    manifest = deepcopy(lock.metadata)
    for selection in manifest["capability_bindings"]["selections"].values(): selection["state"] = "current"
    _republish(root, manifest)
    lock = dependencies.PiBackend(profile="pi-full").read_lock(root)
  workspace.profile = "pi-full"
  installer = fake_installer(calls)
  def checked(argv, *, cwd, env):
    value = installer(argv, cwd=cwd, env=env)
    if argv[:2] == ["npm", "ci"]: (cwd / "node_modules/synthetic-host/extension.js").write_bytes(b"// inert extension\n")
    return value
  monkeypatch.setattr(dependencies, "checked", checked)
  return workspace, lock, inputs, path, declaration, archives, binary


def _install(tmp_path, monkeypatch, **kwargs):
  workspace, lock, *rest = _prepare(tmp_path, monkeypatch, **kwargs)
  backend = dependencies.PiBackend(profile="pi-full")
  result = backend._sync(workspace, lock)
  return workspace, lock, backend.root(workspace, result["identity"]), result, rest


def _context(root):
  receipt = json.loads((root / ".agentcfg-receipt.json").read_bytes())
  return {"identity": receipt["identity"], "lock_identity": receipt["lock_identity"], "platform": receipt["platform"],
    "toolchains": receipt["toolchains"], "binding_identity": receipt["binding_identity"]}


def _reject(function, *args, **kwargs):
  try: raise RuntimeError("SYNTHETIC_PRIVATE_SENTINEL")
  except RuntimeError:
    with pytest.raises(ValueError) as caught: function(*args, **kwargs)
  assert type(caught.value) is ValueError and caught.value.args == ("pi-owner-origin",)
  assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize("large_node", [False, True])
def test_actual_generated_full_original_sync_writer_seal_activate_status(tmp_path, monkeypatch, large_node):
  events = []
  original_writer, original_seal, original_activate = origin._write_owner_origin, packages.seal, packages.activate
  def writer(stage, *args, **kwargs):
    events.append("writer")
    assert not (stage / "install-home").exists() and not (stage / origin.ORIGIN).exists()
    assert (stage / "supervisor/python-bundle/inventory.json").is_file()
    return original_writer(stage, *args, **kwargs)
  def seal(*args, **kwargs):
    events.append("seal"); assert (args[0] / origin.ORIGIN).is_file()
    return original_seal(*args, **kwargs)
  def activate(*args, **kwargs):
    events.append("activate"); assert packages.status(args[0], args[2]) == "installed"
    return original_activate(*args, **kwargs)
  monkeypatch.setattr(origin, "_write_owner_origin", writer)
  monkeypatch.setattr(packages, "seal", seal); monkeypatch.setattr(packages, "activate", activate)
  workspace, lock, root, result, rest = _install(tmp_path, monkeypatch, large_node=large_node)
  assert result["installed"] and events == ["writer", "seal", "activate"]
  assert packages.status(root, result["identity"]) == "installed"
  piece = lock.metadata["profile_slices"]["pi-full"]; context = _context(root)
  envelope = origin.validate_installed_owner_origin(root, piece, **context)
  assert set(envelope) == {"schema_version", "profile", "lock_identity", "runtime_identity", "metadata"}
  assert envelope["metadata"] == lock.metadata and json_bytes(envelope) == (root / origin.ORIGIN).read_bytes()
  envelope["metadata"]["profile_slices"].clear(); assert "pi-full" in lock.metadata["profile_slices"]
  assert packages.validate_installed(root, piece, **context) is None
  with pytest.raises(Conflict): packages.validate_installed(root, piece)
  assert (root / "bin/pi-node").read_bytes() == rest[-1]
  assert stat.S_IMODE((root / "bin/pi-node").stat().st_mode) == 0o700
  if large_node: assert len(rest[-1]) > 1048576
  receipt = json.loads((root / ".agentcfg-receipt.json").read_bytes())
  assert origin.ORIGIN in receipt["files"]
  for row in launcher.OWNER_REQUIRED_ROWS: assert row["path"] in receipt["files"]
  assert (root / "supervisor/schemas/pi-lock.schema.json").read_bytes() == (ROOT / "schemas/pi-lock.schema.json").read_bytes()


@pytest.mark.parametrize("fault", ["unknown", "missing-role", "source", "transform", "node-id", "path", "schema-bool", "protocol-float", "engine", "missing-bundle", "missing-helper", "missing-schema", "duplicate-row", "origin-row", "node-version", "node-platform", "not-full"])
def test_closed_role_data_refuses_before_installed_io(tmp_path, monkeypatch, fault):
  _, _, inputs, _, _, _, _ = _prepare(tmp_path, monkeypatch)
  piece = deepcopy(inputs["profiles"]["pi-full"]); sources = deepcopy(inputs["sources"]); tools = deepcopy(inputs["toolchains"]); name = "pi-full"
  declaration = piece["durable_owner"]
  if fault == "unknown": declaration["qualified"] = True
  elif fault == "missing-role": declaration["roles"].pop("owner_codec")
  elif fault == "source": declaration["roles"]["owner_codec"]["source"] = "agents/pi/packages/durable-service/src/other.ts"
  elif fault == "transform": declaration["roles"]["owner_controller"]["transform"] = "ts-module"
  elif fault == "node-id": declaration["roles"]["owner_node"]["source_id"] = "pi-host"
  elif fault == "path": declaration["roles"]["owner_node"]["path"] = "bin/node"
  elif fault == "schema-bool": declaration["schema_version"] = True
  elif fault == "protocol-float": declaration["protocol_version"] = 1.0
  elif fault == "engine": piece["engine"] = "bun"
  elif fault == "missing-bundle": piece.pop("python_bundle")
  elif fault in ("missing-helper", "missing-schema"):
    target = "supervisor/src/agentcfg/pi_lock_metadata.py" if fault == "missing-helper" else "supervisor/schemas/pi-lock.schema.json"
    piece["runtime_files"] = [row for row in piece["runtime_files"] if row["path"] != target]
  elif fault == "duplicate-row": piece["runtime_files"].append(deepcopy(piece["runtime_files"][0]))
  elif fault == "origin-row": piece["runtime_files"].append({"source": "agents/pi/runtime/durable-owner-origin.json", "path": origin.ORIGIN, "transform": "copy"})
  elif fault == "node-version": tools["node"] = "v0.0.0"
  elif fault == "node-platform": sources["owner-node"]["platform"] = "darwin-arm64"
  else: name = "pi-base"
  with pytest.raises(ConfigError, match="pi-runtime-owner-invalid"):
    launcher.validate_owner_declaration(name, piece, sources, toolchains=tools, locked=False)


@pytest.mark.parametrize("target", [origin.ORIGIN, "bin/pi-node", "licenses/owner-node/0-LICENSE", "runtime/durable-owner-bootstrap.mjs", "runtime/durable-owner-message.mjs", "supervisor/scripts/pi-durable-owner-controller.py", "supervisor/schemas/pi-lock.schema.json", "supervisor/agents/pi/schemas/durable-owner-origin.schema.json", "supervisor/src/agentcfg/pi_lock_metadata.py", "supervisor/src/agentcfg/pi_python_bundle_runtime.py", "runtime/durable-python-bundle.json", "pair", "wheel", "extra"])
def test_actual_sealed_inventory_and_context_readback_reject_material_drift(tmp_path, monkeypatch, target):
  _, lock, root, result, _ = _install(tmp_path, monkeypatch)
  piece = lock.metadata["profile_slices"]["pi-full"]
  context = _context(root)
  if target == "pair": target = piece["package_path"]
  elif target == "wheel": target = next(lock.metadata["sources"][name]["vendor_path"] for name in piece["source_ids"] if lock.metadata["sources"][name]["kind"] == "wheel")
  if target == "extra": (root / "runtime/unlocked.json").write_bytes(b"{}")
  else:
    path = root / target; raw = path.read_bytes(); path.write_bytes((bytes([raw[0] ^ 1]) + raw[1:]) if raw else b"x")
  assert packages.status(root, result["identity"]) == "damaged"
  if target != "extra": _reject(origin.validate_installed_owner_origin, root, piece, **context)
  with pytest.raises(Conflict): packages.validate_installed(root, piece, **context)


@pytest.mark.parametrize("fault", ["node-missing", "node-mode", "node-hash", "license", "schema", "helper", "body", "origin-collision"])
def test_original_producer_failure_never_seals_and_keeps_previous_runtime(tmp_path, monkeypatch, fault):
  workspace, lock, *_ = _prepare(tmp_path, monkeypatch)
  from agentcfg import pi_native_build
  original_helpers = pi_native_build.install_platform_helpers; original_seal = packages.seal; sealed = []
  def helpers(repo, stage, platform):
    original_helpers(repo, stage, platform)
    if fault == "node-missing": (stage / "bin/pi-node").unlink()
    elif fault == "node-mode": (stage / "bin/pi-node").chmod(0o600)
    elif fault == "node-hash": (stage / "bin/pi-node").write_bytes(BINARY + b"drift")
    elif fault == "license": (stage / "licenses/owner-node/0-LICENSE").write_bytes(b"drift")
    elif fault == "schema": (stage / "supervisor/schemas/pi-lock.schema.json").unlink()
    elif fault == "helper": (stage / "supervisor/src/agentcfg/pi_lock_metadata.py").unlink()
    elif fault == "body": (stage / "runtime/durable-python-bundle.json").write_bytes(b"{}")
    else:
      with Tree(stage) as tree: tree.write_new(origin.ORIGIN, b"{}\n")
  def seal(*args, **kwargs): sealed.append(True); return original_seal(*args, **kwargs)
  monkeypatch.setattr(pi_native_build, "install_platform_helpers", helpers);monkeypatch.setattr(packages, "seal", seal)
  sentinel = workspace.instance / "previous-runtime"; sentinel.write_bytes(b"old runtime untouched")
  with pytest.raises((DependencyError, ConfigError)): dependencies.PiBackend(profile="pi-full")._sync(workspace, lock)
  assert sealed == [] and sentinel.read_bytes() == b"old runtime untouched"
  assert not list(workspace.instance.glob("runtimes/*/.agentcfg-ready"))


def test_base_global_full_owner_metadata_stays_cold_to_optional_origin(tmp_path, monkeypatch):
  workspace, _, *_ = _prepare(tmp_path, monkeypatch)
  workspace.profile = "pi-base"; imports = []; reads = []
  original_import, original_read = builtins.__import__, Tree.read
  def importing(name, *args, **kwargs):
    if name.rsplit(".", 1)[-1] == "pi_owner_origin": imports.append(name)
    return original_import(name, *args, **kwargs)
  def read(tree, path, *args, **kwargs):
    if path == origin.ORIGIN: reads.append(path)
    return original_read(tree, path, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", importing);monkeypatch.setattr(Tree, "read", read)
  backend = dependencies.PiBackend(profile="pi-base");lock = backend.read_lock(workspace.repository)
  result = backend._sync(workspace, lock); root = backend.root(workspace, result["identity"])
  assert backend.status(workspace, result["identity"]) == "installed" and not (root / origin.ORIGIN).exists()
  assert imports == reads == []


def test_original_candidate_guard_rejects_before_origin_or_process(tmp_path, monkeypatch):
  workspace, lock, *_ = _prepare(tmp_path, monkeypatch, current=False)
  with pytest.raises(DependencyError, match="候选"): dependencies.PiBackend(profile="pi-full")._sync(workspace, lock)
  assert not (workspace.instance / "runtimes").exists()


@pytest.mark.parametrize("fault", ["piece", "toolchains", "binding", "root", "identity", "platform", "late-key"])
def test_expected_native_capture_before_any_tree_or_foreign_callbacks(tmp_path, monkeypatch, fault):
  calls = []
  class Key(str):
    def __hash__(self): return str.__hash__(self)
    def __eq__(self, other): _CALLBACKS.append("eq"); raise AssertionError()
  class Dict(dict):
    def items(self): _CALLBACKS.append("items"); raise AssertionError()
  binding = {"profile": "pi-full", "selection": "a"*64, "catalog": "b"*64, "bindings": "c"*64, "lock": "d"*64, "slice": "e"*64,
    "binding_context": "f"*64, "runtime": "a"*64, "adapter_version": "pi-1", "platform": "linux-x86_64"}
  context = {"identity": _sha(json_bytes(binding)), "lock_identity": "d"*64, "platform": "linux-x86_64", "toolchains": {"node":"v24.14.0","npm":"11.19.1","bun":"1.0.0"}, "binding_identity": binding}
  piece = {}; root = tmp_path
  if fault == "piece": piece = Dict()
  elif fault == "toolchains": context["toolchains"] = {Key("node"): "x"}
  elif fault == "binding": context["binding_identity"] = Dict(binding)
  elif fault == "root": root = object()
  elif fault == "identity": context["identity"] = Key(context["identity"])
  elif fault == "platform": context["platform"] = Key("linux-x86_64")
  else: piece[Key("durable_owner")] = {}
  class ForbiddenTree:
    def __init__(self, *args, **kwargs): calls.append(True); raise AssertionError()
  monkeypatch.setattr(origin, "Tree", ForbiddenTree)
  _reject(origin.validate_installed_owner_origin, root, piece, **context)
  assert calls == []


@pytest.mark.parametrize("control", [KeyboardInterrupt("x"), SystemExit(7), GeneratorExit("x")])
def test_control_object_and_fixed_ambient_error_semantics(tmp_path, monkeypatch, control):
  def action(*args, **kwargs): raise control
  with pytest.raises(type(control)) as caught: origin._boundary(action)
  assert caught.value is control
  _reject(origin._boundary, lambda: (_ for _ in ()).throw(RuntimeError("SECRET")))


@pytest.mark.parametrize("raw", [b'{', b'\xff', b'{"x":1,"x":2}', b'{"metadata":{"x":1,"x":2}}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e400}', b'{"schema_version":1.0}', b'[' * 19 + b']' * 19])
def test_wire_decoder_strict_failure_and_bounded_lexical_depth(raw):
  with pytest.raises(ValueError): origin._decode(raw)


def test_lexical_strings_escapes_and_metadata_depth_budget_independent():
  origin._lexical('{"s":"escaped \\" [{ }]", "x":' + '['*17 + ']'*17 + '}')
  with pytest.raises(ValueError): origin._lexical('{' + '['*18 + ']'*18 + '}')
  value = {}; current = value
  for _ in range(16): current["x"] = {};current = current["x"]
  assert _Capture().capture(value) == value
  envelope = {"schema_version":1,"profile":"pi-full","lock_identity":"a"*64,"runtime_identity":"b"*64,"metadata":value}
  assert origin._decode(json_bytes(envelope)) == envelope


def test_wire_canonical_exact_cap_and_valid_metadata_expansion_cap_are_distinct(tmp_path, monkeypatch):
  workspace, lock, *_ = _prepare(tmp_path, monkeypatch)
  metadata = deepcopy(lock.metadata)
  metadata["build_steps"].append({"id":"origin-cap-control","platform":"all","source_ids":[],"argv":["\x01"*4096 for _ in range(1024)],"input_digests":{},"expected_outputs":[],"output_digests":{}})
  metadata.pop("identity");metadata["identity"] = dependencies.digest(metadata)
  piece = metadata["profile_slices"]["pi-full"]
  record = {"package_json":lock.pairs["pi-full"][0],"package_lock_json":lock.pairs["pi-full"][1],"python_bundle_json":(workspace.repository/piece["python_bundle"]["source"]).read_bytes()}
  assert capture_pi_lock_metadata_data(metadata,{"pi-full":record},schema_version=2)["metadata"] == metadata
  envelope = {"schema_version":1,"profile":"pi-full","lock_identity":metadata["identity"],"runtime_identity":"b"*64,"metadata":metadata}
  with pytest.raises(ValueError): origin._encode(envelope)
  # 单独wire cap，不把此私有编码核控制伪称完整metadata合法。
  minimal = {"metadata":{"x":""}};overhead = len(json_bytes(minimal));minimal["metadata"]["x"] = "x"*(origin.MAX_ORIGIN-overhead)
  assert len(origin._encode(minimal)) == origin.MAX_ORIGIN
  minimal["metadata"]["x"] += "x"
  with pytest.raises(ValueError): origin._encode(minimal)


@pytest.mark.parametrize("where", ["lock", "receipt"])
def test_current_shared_closed_owner_schema_and_profile_version_domains(tmp_path, monkeypatch, where):
  _, lock, *_ = _prepare(tmp_path, monkeypatch)
  lock_schema = json.loads((ROOT/"schemas/pi-lock.schema.json").read_bytes())
  receipt_schema = json.loads((ROOT/"agents/pi/schemas/runtime-receipt.schema.json").read_bytes())
  owner_schema = lock_schema["properties"]["profile_slices"]["additionalProperties"]["properties"]["durable_owner"]
  assert owner_schema == receipt_schema["properties"]["slice"]["properties"]["durable_owner"]
  validator = Draft202012Validator(owner_schema); assert validator.is_valid(_owner())
  assert not validator.is_valid({**_owner(),"qualified":True})
  schema = lock_schema if where == "lock" else receipt_schema
  if where == "lock":
    value = deepcopy(lock.metadata);assert Draft202012Validator(schema).is_valid(value)
    value["profile_slices"]["pi-base"]["durable_owner"] = _owner()
  else:
    value = {"schema_version":2,"status":"installed","identity":"a"*64,"lock_identity":"b"*64,"slice_identity":lock.metadata["profile_slices"]["pi-full"]["identity"],
      "slice":lock.metadata["profile_slices"]["pi-full"],"files":{},"platform":"linux-x86_64","toolchains":lock.metadata["toolchains"],"toolchain_identity":"c"*64,
      "binding_identity":{"profile":"pi-full","selection":"a"*64,"catalog":"a"*64,"bindings":"a"*64,"lock":"b"*64,"slice":"a"*64,"binding_context":"a"*64,"runtime":"a"*64,"adapter_version":"pi-1","platform":"linux-x86_64"}}
    assert Draft202012Validator(schema).is_valid(value);value["binding_identity"]["profile"] = "pi-base"
  assert not Draft202012Validator(schema).is_valid(value)


@pytest.mark.parametrize("entry", ["reader", "writer"])
def test_one_owned_capture_survives_after_capture_foreign_caller_replacement(tmp_path, monkeypatch, entry):
  _, lock, root, _, _ = _install(tmp_path, monkeypatch)
  caller = deepcopy(lock.metadata["profile_slices"]["pi-full"] if entry == "reader" else lock.metadata)
  context = _context(root); original_tree = origin.Tree; replaced = []
  class Key(str):
    def __hash__(self): return str.__hash__(self)
    def __eq__(self, other): _CALLBACKS.append("eq"); raise AssertionError()
  def tree(path):
    caller.clear();caller[Key("engine")] = "node"
    context["toolchains"].clear();context["toolchains"][Key("node")] = "v24.14.0"
    context["binding_identity"].clear();context["binding_identity"][Key("runtime")] = "a"*64
    replaced.append(True)
    return original_tree(path)
  monkeypatch.setattr(origin,"Tree",tree)
  if entry == "reader": assert origin.validate_installed_owner_origin(root,caller,**context)["metadata"] == lock.metadata
  else:
    (root/origin.ORIGIN).unlink()
    assert origin._write_owner_origin(root,caller,**context) is None
  assert replaced == [True]


def test_actual_tree_named_node_replacement_rejects_even_equal_bytes(tmp_path,monkeypatch):
  from contextlib import contextmanager
  _,lock,root,_,_ = _install(tmp_path,monkeypatch)
  original = Tree.open_read; replaced=[]
  @contextmanager
  def opening(tree,path,**kwargs):
    with original(tree,path,**kwargs) as (stream,opened):
      if path != "bin/pi-node": yield stream,opened
      else:
        class Stream:
          def read(self,count):
            if not replaced:
              replacement=root/"bin/replacement";replacement.write_bytes((root/path).read_bytes());replacement.chmod(0o700);replacement.replace(root/path);replaced.append(True)
            return stream.read(count)
        yield Stream(),opened
  monkeypatch.setattr(Tree,"open_read",opening)
  _reject(origin.validate_installed_owner_origin,root,lock.metadata["profile_slices"]["pi-full"],**_context(root))
  assert replaced == [True]


@pytest.mark.parametrize("entry", ["reader", "writer"])
def test_actual_material_io_preserves_original_control_object(tmp_path,monkeypatch,entry):
  _,lock,root,_,_=_install(tmp_path,monkeypatch);context=_context(root);control=KeyboardInterrupt("inert control");original=Tree.read
  target=origin.ORIGIN if entry=="reader" else lock.metadata["profile_slices"]["pi-full"]["package_path"]
  def read(tree,path,*args,**kwargs):
    if path==target:raise control
    return original(tree,path,*args,**kwargs)
  monkeypatch.setattr(Tree,"read",read)
  with pytest.raises(KeyboardInterrupt) as caught:
    if entry=="reader":origin.validate_installed_owner_origin(root,lock.metadata["profile_slices"]["pi-full"],**context)
    else:origin._write_owner_origin(root,lock.metadata,**context)
  assert caught.value is control


@pytest.mark.parametrize("fault", ["native-version", "unknown", "surrogate", "overflow-float", "overflow-int", "noncanonical", "nested-duplicate"])
def test_complete_wire_fields_strict_scalars_and_json_without_full_lock_claim(fault):
  envelope={"schema_version":1,"profile":"pi-full","lock_identity":"a"*64,"runtime_identity":"b"*64,"metadata":{}}
  if fault=="native-version":envelope["schema_version"]=1.0
  elif fault=="unknown":envelope["qualified"]=True
  elif fault=="overflow-int":envelope["metadata"]["x"]=2**63
  if fault=="surrogate":raw=json_bytes(envelope).replace(b'"metadata":{}',b'"metadata":{"x":"\\ud800"}')
  elif fault=="overflow-float":raw=json_bytes(envelope).replace(b'"metadata":{}',b'"metadata":{"x":1e400}')
  elif fault=="nested-duplicate":raw=json_bytes(envelope).replace(b'"metadata":{}',b'"metadata":{"x":{"y":1,"y":2}}')
  elif fault=="noncanonical":raw=json.dumps(envelope,indent=2).encode()
  else:raw=json_bytes(envelope)
  with pytest.raises(ValueError):origin._decode(raw)


@pytest.mark.parametrize("field", ["piece","sources","tools","name","locked"])
def test_public_role_native_guards_never_hash_foreign_key(field):
  armed=False
  class Key(str):
    def __hash__(self):
      if armed:_CALLBACKS.append("hash");raise AssertionError()
      return str.__hash__(self)
    def __eq__(self,other):_CALLBACKS.append("eq");raise AssertionError()
  value={Key("engine"):"node"};name="pi-full";piece={};sources={};tools={};locked=True
  if field=="piece":piece=value
  elif field=="sources":sources=value
  elif field=="tools":tools=value
  elif field=="name":name=Key(name)
  else:locked=1
  armed=True
  with pytest.raises(ConfigError,match="pi-runtime-owner-invalid"):
    launcher.validate_owner_declaration(name,piece,sources,toolchains=tools,locked=locked)


def test_actual_previous_installed_runtime_survives_new_identity_writer_failure(tmp_path, monkeypatch):
  workspace, oldlock, oldroot, oldresult, _ = _install(tmp_path, monkeypatch)
  backend = dependencies.PiBackend(profile="pi-full")
  oldidentity = oldresult["identity"]
  assert backend.status(workspace, oldidentity) == "installed"
  oldinventory = packages.inventory(oldroot)
  oldreceipt = (oldroot / ".agentcfg-receipt.json").read_bytes()
  oldready = (oldroot / ".agentcfg-ready").read_bytes()
  metadata = deepcopy(oldlock.metadata)
  metadata["build_steps"].append({"id":"owner-preservation-marker","platform":"synthetic-unselected-platform","source_ids":[],
    "argv":["synthetic-inert-marker"],"input_digests":{},"expected_outputs":[],"output_digests":{}})
  _republish(workspace.repository, metadata)
  newlock = backend.read_lock(workspace.repository)
  newidentity = backend.runtime_identity(workspace, newlock)
  assert newidentity != oldidentity and newlock.identity != oldlock.identity
  assert backend.status(workspace, oldidentity) == "installed"
  writer, seal, activate = origin._write_owner_origin, packages.seal, packages.activate
  events = []
  def fault(stage, *args, **kwargs):
    events.append("writer")
    (stage / "bin/pi-node").write_bytes(BINARY + b"synthetic stage drift")
    return writer(stage, *args, **kwargs)
  def sealing(*args, **kwargs): events.append("seal"); return seal(*args, **kwargs)
  def activating(*args, **kwargs): events.append("activate"); return activate(*args, **kwargs)
  monkeypatch.setattr(origin,"_write_owner_origin",fault)
  monkeypatch.setattr(packages,"seal",sealing);monkeypatch.setattr(packages,"activate",activating)
  with pytest.raises(DependencyError,match="owner材料暂存失败"): backend._sync(workspace,newlock)
  assert events == ["writer"]
  assert backend.root(workspace,oldidentity) == oldroot and backend.status(workspace,oldidentity) == "installed"
  assert packages.inventory(oldroot) == oldinventory
  assert (oldroot/".agentcfg-receipt.json").read_bytes() == oldreceipt
  assert (oldroot/".agentcfg-ready").read_bytes() == oldready
  assert not (backend.root(workspace,newidentity)/".agentcfg-ready").exists()
