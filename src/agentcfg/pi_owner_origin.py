"""显式 Full 安装材料的固定读写；不提供来源、角色或执行资格。"""

import hashlib
import json
from pathlib import Path
import re
import stat

from .deployment import json_bytes
from .pi_lock_metadata import _Capture
from .storage import Tree


ORIGIN = "runtime/durable-owner-origin.json"
MAX_ORIGIN = 16 * 1024 * 1024
_BINDING = {"profile", "selection", "catalog", "bindings", "lock", "slice", "binding_context", "runtime", "adapter_version", "platform"}


def _hex(value):
  if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None: raise ValueError()
  return value


def _context(root, identity, lock_identity, platform, toolchains, binding_identity):
  if type(root) not in (str, type(Path())): raise ValueError()
  if type(root) is str:
    if not root: raise ValueError()
    root.encode("utf-8", "strict")
  identity, lock_identity = _hex(identity), _hex(lock_identity)
  if type(platform) is not str or platform != "linux-x86_64": raise ValueError()
  tools = _Capture().capture(toolchains)
  binding = _Capture().capture(binding_identity)
  if (type(tools) is not dict or set(tools) != {"node", "npm", "bun"} or any(type(value) is not str for value in tools.values())
      or type(binding) is not dict or set(binding) != _BINDING): raise ValueError()
  for key in _BINDING - {"profile", "platform", "adapter_version"}: _hex(binding[key])
  if binding["profile"] != "pi-full" or binding["platform"] != platform or binding["adapter_version"] != "pi-1" or binding["lock"] != lock_identity: raise ValueError()
  if hashlib.sha256(json_bytes(binding)).hexdigest() != identity: raise ValueError()
  return Path(root), {"identity": identity, "lock_identity": lock_identity, "platform": platform, "toolchains": tools, "binding_identity": binding}


def _lexical(text):
  depth = 0
  quoted = escaped = False
  for char in text:
    if quoted:
      if escaped: escaped = False
      elif char == "\\": escaped = True
      elif char == '"': quoted = False
    elif char == '"': quoted = True
    elif char in "[{":
      depth += 1
      if depth > 18: raise ValueError()
    elif char in "]}":
      depth -= 1
      if depth < 0: raise ValueError()


def _object(pairs):
  result = {}
  for key, value in pairs:
    if key in result: raise ValueError()
    result[key] = value
  return result


def _constant(value):
  raise ValueError()


def _encode(envelope):
  raw = json_bytes(envelope)
  if len(raw) > MAX_ORIGIN: raise ValueError()
  return raw


def _decode(raw):
  if type(raw) is not bytes or len(raw) > MAX_ORIGIN: raise ValueError()
  text = raw.decode("utf-8", "strict")
  _lexical(text)
  envelope = json.loads(text, object_pairs_hook=_object, parse_constant=_constant)
  if type(envelope) is not dict or set(envelope) != {"schema_version", "profile", "lock_identity", "runtime_identity", "metadata"}: raise ValueError()
  if type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1 or envelope["profile"] != "pi-full": raise ValueError()
  _hex(envelope["lock_identity"]); _hex(envelope["runtime_identity"])
  # metadata从根depth0独立捕获，不把envelope层次塞进旧图预算。
  if type(envelope["metadata"]) is not dict: raise ValueError()
  envelope["metadata"] = _Capture().capture(envelope["metadata"])
  if _encode(envelope) != raw: raise ValueError()
  return envelope


def _bytes(tree, path, cap):
  raw = tree.read(path, max_bytes=cap)
  if raw is None or raw[1] != 0o600: raise ValueError()
  return raw[0]


def _schema(envelope):
  from jsonschema import Draft202012Validator
  from referencing import Registry
  path = Path(__file__).resolve().parents[2] / "agents/pi/schemas/durable-owner-origin.schema.json"
  with path.open("rb") as resource: raw = resource.read(MAX_ORIGIN + 1)
  if len(raw) > MAX_ORIGIN: raise ValueError()
  text = raw.decode("utf-8", "strict"); _lexical(text)
  schema = _Capture().capture(json.loads(text, object_pairs_hook=_object, parse_constant=_constant))
  Draft202012Validator.check_schema(schema)
  if not Draft202012Validator(schema, registry=Registry()).is_valid(envelope): raise ValueError()


def _piece(metadata, context):
  from .pi_lock_header import validate_lock_header
  from .pi_modern_launcher import validate_owner_declaration
  validate_lock_header(metadata, schema_version=2)
  piece = metadata["profile_slices"]["pi-full"]
  if metadata["identity"] != context["lock_identity"] or metadata["toolchains"] != context["toolchains"] or context["platform"] not in metadata["platforms"]: raise ValueError()
  validate_owner_declaration("pi-full", piece, metadata["sources"], toolchains=context["toolchains"], locked=True)
  node = metadata["sources"][piece["durable_owner"]["roles"]["owner_node"]["source_id"]]
  if node["platform"] != context["platform"]: raise ValueError()
  return piece


def _materials(tree, metadata, context, expected_piece=None):
  piece = _piece(metadata, context)
  if expected_piece is not None and piece != expected_piece: raise ValueError()
  record = {"package_json": _bytes(tree, piece["package_path"], 1048576), "package_lock_json": _bytes(tree, piece["lock_path"], 1048576),
    "python_bundle_json": _bytes(tree, piece["python_bundle"]["path"], 8388608)}
  from .pi_lock_metadata import capture_pi_lock_metadata_data
  data = capture_pi_lock_metadata_data(metadata, {"pi-full": record}, schema_version=2,
    accepted_binding_digests={"pi-full": context["binding_identity"]["binding_context"]})
  metadata = data["metadata"]
  piece = metadata["profile_slices"]["pi-full"]
  from .pi_capabilities import validate_selection_data, runtime_identity_payload
  bindings = metadata["capability_bindings"]
  selected = validate_selection_data(bindings["catalog"], bindings["providers"], bindings["selections"]["pi-full"], metadata,
    lock_identity=context["lock_identity"], host_version=metadata["sources"]["pi-host"]["version"], engine=piece["engine"],
    accepted_binding_digest=context["binding_identity"]["binding_context"])
  base = hashlib.sha256(json_bytes({"lock_identity": context["lock_identity"], "slice_identity": piece["identity"],
    "platform": context["platform"], "toolchain_identity": hashlib.sha256(json_bytes(context["toolchains"])).hexdigest()})).hexdigest()
  binding = runtime_identity_payload(selected, runtime_digest=base, adapter_version="pi-1", platform=context["platform"])
  if binding != context["binding_identity"] or hashlib.sha256(json_bytes(binding)).hexdigest() != context["identity"]: raise ValueError()
  from .pi_modern_launcher import OWNER_REQUIRED_ROWS
  rows = {row["path"]: row for row in piece["runtime_files"]}
  for required in OWNER_REQUIRED_ROWS:
    row = rows[required["path"]]
    if hashlib.sha256(_bytes(tree, row["path"], 16 * 1024 * 1024)).hexdigest() != row["digest"]: raise ValueError()
  from .pi_wheel_sources import validate_selected_python_bundle
  declaration = validate_selected_python_bundle(record["python_bundle_json"], piece, metadata["sources"])
  if declaration["target"]["sys_platform"] != "linux" or declaration["target"]["machine"] != "x86_64": raise ValueError()
  for source_id in piece["source_ids"]:
    source = metadata["sources"][source_id]
    if source["kind"] == "wheel":
      raw = _bytes(tree, source["vendor_path"], 2097152)
      if len(raw) != source["size"] or hashlib.sha256(raw).hexdigest() != source["archive_digest"]: raise ValueError()
  node_id = piece["durable_owner"]["roles"]["owner_node"]["source_id"]
  node = metadata["sources"][node_id]
  from .pi_node_archive import MAX_BINARY
  with tree.open_read("bin/pi-node", max_bytes=MAX_BINARY) as (stream, opened):
    if stat.S_IMODE(opened.st_mode) != 0o700 or not 1 <= opened.st_size <= MAX_BINARY: raise ValueError()
    checksum = hashlib.sha256(); size = 0
    for chunk in iter(lambda: stream.read(65536), b""):
      size += len(chunk)
      if size > MAX_BINARY: raise ValueError()
      checksum.update(chunk)
    if size != opened.st_size or checksum.hexdigest() != node["node_archive"]["binary_sha256"]: raise ValueError()
  license_raw = _bytes(tree, "licenses/" + node_id + "/0-LICENSE", 1048576)
  if hashlib.sha256(license_raw).hexdigest() != node["node_archive"]["license_sha256"]: raise ValueError()
  return metadata


def _read(tree, context, piece):
  envelope = _decode(_bytes(tree, ORIGIN, MAX_ORIGIN))
  if envelope["runtime_identity"] != context["identity"] or envelope["lock_identity"] != context["lock_identity"]: raise ValueError()
  _schema(envelope)
  envelope["metadata"] = _materials(tree, envelope["metadata"], context, piece)
  return envelope


def _writer(stage, metadata, **context):
  metadata = _Capture().capture(metadata)
  stage, context = _context(stage, **context)
  with Tree(stage) as tree:
    metadata = _materials(tree, metadata, context)
    envelope = {"schema_version": 1, "profile": "pi-full", "lock_identity": context["lock_identity"], "runtime_identity": context["identity"], "metadata": metadata}
    raw = _encode(envelope)
    _schema(envelope)
    tree.write_new(ORIGIN, raw)
    if _bytes(tree, ORIGIN, MAX_ORIGIN) != raw: raise ValueError()
    _read(tree, context, metadata["profile_slices"]["pi-full"])


def _reader(root, piece, **context):
  piece = _Capture().capture(piece)
  root, context = _context(root, **context)
  with Tree(root) as tree:
    return _read(tree, context, piece)


def _boundary(function, *args, **kwargs):
  failed = False
  try:
    result = function(*args, **kwargs)
  except Exception:
    failed = True
  if failed:
    try: raise ValueError("pi-owner-origin")
    except ValueError as error:
      error.__cause__ = None; error.__context__ = None
      raise
  return result


def _write_owner_origin(stage, metadata, *, identity, lock_identity, platform, toolchains, binding_identity):
  return _boundary(_writer, stage, metadata, identity=identity, lock_identity=lock_identity, platform=platform,
    toolchains=toolchains, binding_identity=binding_identity)


def validate_installed_owner_origin(root, piece, *, identity, lock_identity, platform, toolchains, binding_identity):
  return _boundary(_reader, root, piece, identity=identity, lock_identity=lock_identity, platform=platform,
    toolchains=toolchains, binding_identity=binding_identity)
