"""纯数据接缝回归；复用自有合成声明，不读取真实 wheel 或启动宿主。"""

import ast
import builtins
import copy
import hashlib
import json
from pathlib import Path

import pytest

from agentcfg import pi_wheel_sources as wheel


_MODULE = Path(wheel.__file__).read_text()
_SOURCE = "agents/pi/runtime/durable-python-bundle.json"
_PATH = "runtime/durable-python-bundle.json"
_NAMES = ["attrs", "jsonschema", "jsonschema-specifications", "pyyaml", "referencing", "rpds-py", "typing-extensions"]
_FOREIGN_CALLS = []


@pytest.fixture(autouse=True)
def foreign_callback_sentinel():
  _FOREIGN_CALLS.clear()
  yield
  # 固定错误边界会吸收普通异常；必须另外观察是否调用了外来方法。
  assert _FOREIGN_CALLS == []


def _foreign_call(name):
  _FOREIGN_CALLS.append(name)
  raise AssertionError("foreign callback")


def _sha(raw):
  return hashlib.sha256(raw).hexdigest()


def _source(name="attrs", version="25.4.0", *, locked=True):
  filename = name.replace("-", "_") + "-" + version + "-py3-none-any.whl"
  result = {"kind": "wheel", "package": name, "version": version, "url": "https://Files.Example.test/wheels/" + filename,
    "wheel_filename": filename, "archive_digest": "a" * 64, "size": 1024,
    "license_files": [name.replace("-", "_") + "-" + version + ".dist-info/licenses/LICENSE"]}
  if locked:
    result["vendor_path"] = "vendor/wheels/" + result["archive_digest"] + "/" + filename
  return result


def _piece(*, locked=True, raw=b"{}"):
  sources = {"durable-python-" + name: _source(name, locked=locked) for name in _NAMES}
  ref = {"schema_version": 1, "source": _SOURCE, "path": _PATH, "sha256": _sha(raw), "size": len(raw)}
  row = {"source": _SOURCE, "path": _PATH, "transform": "copy"}
  if locked:
    row.update(input_digest=ref["sha256"], digest=ref["sha256"], mode=384)
  return {"source_ids": list(sources), "runtime_files": [row], "python_bundle": ref}, sources


def _body():
  # 导入只发生于需要正文的测试；旧 suite 不收集、不执行。
  from test_pi_python_bundle import _fixture
  declaration, _, _ = _fixture()
  raw = json.dumps(declaration, ensure_ascii=False).encode()
  piece, sources = _piece(raw=raw)
  for row in declaration["wheels"]:
    source = sources[row["source_id"]]
    source.update(version=row["version"], wheel_filename=row["wheel_filename"], archive_digest=row["archive_sha256"],
      size=row["archive_size"], license_files=sorted(row["dist_info"] + "/licenses/" + path for path in row["metadata"]["license_files"]))
    source["url"] = "https://files.example.test/" + source["wheel_filename"]
    source["vendor_path"] = "vendor/wheels/" + source["archive_digest"] + "/" + source["wheel_filename"]
  return declaration, raw, piece, sources


def _reject(function, *args, **kwargs):
  with pytest.raises(ValueError) as caught:
    function(*args, **kwargs)
  assert type(caught.value) is ValueError
  assert str(caught.value) == "pi-wheel-source"
  assert caught.value.__cause__ is None
  assert caught.value.__context__ is None
  return caught.value


def _no_core(monkeypatch):
  original = builtins.__import__
  calls = []
  def guarded(name, *args, **kwargs):
    if "pi_python_bundle" in name or "zipfile" in name:
      calls.append(name)
      raise AssertionError("forbidden core/ZIP import")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)
  return calls


@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("version", ["0", "1.0", "99999999.0.99999999"])
def test_source_valid_declaration_locked_and_version_domain(locked, version):
  source = _source(version=version, locked=locked)
  before = copy.deepcopy(source)
  assert wheel.validate_wheel_source(source, locked=locked) is None
  assert source == before


def test_identity_exact_projection_and_locator_exclusion():
  source = _source()
  projection = {key: value for key, value in source.items() if key not in ("url", "vendor_path")}
  expected = _sha(json.dumps(projection, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())
  assert wheel.wheel_source_identity(source) == expected
  source["url"] = "https://mirror.other.test/" + source["wheel_filename"]
  assert wheel.wheel_source_identity(source) == expected
  source["size"] += 1
  assert wheel.wheel_source_identity(source) != expected
  source["vendor_path"] = "bad"
  _reject(wheel.wheel_source_identity, source)
  _reject(wheel.wheel_source_identity, _source(locked=False))


@pytest.mark.parametrize("key,value", [
  ("kind", "asset"), ("package", "Attrs"), ("package", "a_b"), ("package", "a--b"), ("package", "a" * 97),
  ("version", "01"), ("version", "1.2.3.4"), ("version", "100000000"), ("version", "1rc1"),
  ("wheel_filename", "attrs-25.4.0-1-py3-none-any.whl"), ("wheel_filename", "attrs-25.4.0-PY3-none-any.whl"),
  ("wheel_filename", "other-25.4.0-py3-none-any.whl"), ("archive_digest", "A" * 64), ("archive_digest", "a" * 63),
  ("size", 0), ("size", 2097153), ("size", True), ("size", 1.0),
  ("license_files", []), ("license_files", ["other-25.4.0.dist-info/licenses/LICENSE"]),
  ("license_files", ["attrs-25.4.0.dist-info/licenses/"]),
  ("license_files", ["attrs-25.4.0.dist-info/licenses/../LICENSE"]),
  ("license_files", ["attrs-25.4.0.dist-info/licenses/a b"]),
  ("license_files", ["attrs-25.4.0.dist-info/licenses/a\\b"]),
  ("license_files", ["attrs-25.4.0.dist-info/licenses/许可证"]),
  ("vendor_path", "vendor/wheels/" + "b" * 64 + "/attrs-25.4.0-py3-none-any.whl"),
])
def test_source_field_failures(key, value):
  source = _source()
  source[key] = value
  _reject(wheel.validate_wheel_source, source, locked=True)


@pytest.mark.parametrize("extra", ["resources", "format", "target", "platform", "archive_member", "resolved", "integrity", "license_sources", "build_record", "source_path", "commit"])
def test_source_unknown_fields(extra):
  source = _source()
  source[extra] = None
  _reject(wheel.validate_wheel_source, source, locked=True)


@pytest.mark.parametrize("key", sorted(wheel._FIELDS | {"vendor_path"}))
def test_source_missing_fields(key):
  source = _source()
  del source[key]
  _reject(wheel.validate_wheel_source, source, locked=True)


@pytest.mark.parametrize("prefix", [
  "http://files.example.test/", "https://localhost/", "https://127.0.0.1/", "https://127.1/",
  "https://[::1]/", "https://a.123/", "https://a..test/", "https://a.test./", "https://-a.test/",
  "https://a-.test/", "https://a_foo.test/", "https://user@files.example.test/",
  "https://user:pass@files.example.test/", "https://files.example.test:443/", "https://files.example.test:/",
  "https://K.example.test/", "https://é.example.test/", "https://files.example.test//",
  "https://files.example.test/./", "https://files.example.test/../", "https://files.example.test/%61/",
  "https://files.example.test\\evil/", "https://files.example.test/a b/", "https://files.example.test/\n/",
  "https://" + "a" * 64 + ".test/", "https://" + ".".join(["a" * 63] * 4) + "/",
])
def test_url_negative(prefix):
  source = _source()
  source["url"] = prefix + source["wheel_filename"]
  _reject(wheel.validate_wheel_source, source, locked=True)


@pytest.mark.parametrize("suffix", ["?", "?x=y", "#", "#x", "%20", "\\", "/", " ", "\x00", "\x7f", "\x80", "\x9f"])
def test_url_bad_suffix(suffix):
  source = _source()
  source["url"] += suffix
  _reject(wheel.validate_wheel_source, source, locked=True)


def test_source_limits_and_sorted_unique_licenses():
  source = _source()
  source["size"] = 2097152
  source["license_files"] = ["attrs-25.4.0.dist-info/licenses/" + str(n).zfill(2) for n in range(16)]
  wheel.validate_wheel_source(source, locked=True)
  for licenses in (source["license_files"][::-1], source["license_files"] + [source["license_files"][0]],
                   source["license_files"] + ["attrs-25.4.0.dist-info/licenses/16"],
                   ["attrs-25.4.0.dist-info/licenses/" + "a" * 512]):
    bad = dict(source, license_files=licenses)
    _reject(wheel.validate_wheel_source, bad, locked=True)
  _reject(wheel.validate_wheel_source, _source(), locked=False)


@pytest.mark.parametrize("locked", [0, 1, None, "true", [], object()])
def test_locked_native_bool(locked):
  _reject(wheel.validate_wheel_source, _source(), locked=locked)
  piece, sources = _piece()
  _reject(wheel.validate_python_bundle_reference, "pi-full", piece, sources, locked=locked)


@pytest.mark.parametrize("locked", [False, True])
def test_reference_valid_and_legacy_profiles_no_body_import(locked, monkeypatch):
  calls = _no_core(monkeypatch)
  piece, sources = _piece(locked=locked)
  assert wheel.validate_python_bundle_reference("pi-full", piece, sources, locked=locked) is None
  for profile in ("pi-base", "pi-full"):
    old = {"source_ids": ["old-npm"], "runtime_files": [{"source": "old", "path": "old"}]}
    # 其它种类的正文由原 validator 负责，不调用外来方法。
    all_sources = dict(sources, **{"old-npm": {"kind": "npm", "foreign": object()}})
    wheel.validate_python_bundle_reference(profile, old, all_sources, locked=locked)
  assert calls == []


@pytest.mark.parametrize("fault", ["base", "profile", "partial", "missing-source", "wrong-id", "wrong-kind", "no-ref", "ref-only", "duplicate-id", "unknown-id", "bad-id", "null-ref", "empty-runtime", "duplicate-runtime", "wrong-source", "wrong-target", "wrong-transform", "wrong-mode", "bool-mode", "wrong-input", "wrong-output", "extra-row", "no-runtime"])
def test_reference_pairing_failures_pre_core(fault, monkeypatch):
  piece, sources = _piece()
  profile = "pi-full"
  if fault == "base": profile = "pi-base"
  if fault == "profile": profile = "pi-old"
  if fault == "partial": piece["source_ids"].pop()
  if fault == "missing-source": sources.pop(piece["source_ids"][0])
  if fault == "wrong-id": sources["wrong"] = sources.pop(piece["source_ids"][0])
  if fault == "wrong-kind": sources[piece["source_ids"][0]] = {"kind": "npm"}
  if fault == "no-ref": del piece["python_bundle"]
  if fault == "ref-only": piece["source_ids"] = []
  if fault == "duplicate-id": piece["source_ids"].append(piece["source_ids"][0])
  if fault == "unknown-id": piece["source_ids"].append("absent")
  if fault == "bad-id": piece["source_ids"].append("../bad")
  if fault == "null-ref": piece["python_bundle"] = None
  if fault == "empty-runtime": piece["runtime_files"] = []
  if fault == "duplicate-runtime": piece["runtime_files"] *= 2
  if fault == "no-runtime": piece.pop("runtime_files")
  if fault.startswith("wrong-") and fault in ("wrong-source", "wrong-target", "wrong-transform", "wrong-mode", "wrong-input", "wrong-output"):
    key = {"wrong-source": "source", "wrong-target": "path", "wrong-transform": "transform", "wrong-mode": "mode", "wrong-input": "input_digest", "wrong-output": "digest"}[fault]
    piece["runtime_files"][0][key] = 420 if key == "mode" else "wrong"
  if fault == "bool-mode": piece["runtime_files"][0]["mode"] = True
  if fault == "extra-row": piece["runtime_files"][0]["unknown"] = None
  calls = _no_core(monkeypatch)
  _reject(wheel.validate_python_bundle_reference, profile, piece, sources, locked=True)
  _reject(wheel.validate_selected_python_bundle, b"{}", piece, sources) if fault not in ("base", "profile") else None
  assert calls == []


@pytest.mark.parametrize("key,value", [("schema_version", True), ("schema_version", 2), ("source", "overlay.json"), ("path", "other.json"),
  ("sha256", "A" * 64), ("size", True), ("size", 0), ("size", 8388609), ("extra", None)])
def test_reference_exact_fields(key, value, monkeypatch):
  piece, sources = _piece()
  piece["python_bundle"][key] = value
  calls = _no_core(monkeypatch)
  _reject(wheel.validate_selected_python_bundle, b"{}", piece, sources)
  assert calls == []


@pytest.mark.parametrize("key", ["schema_version", "source", "path", "sha256", "size"])
def test_reference_missing_fields(key):
  piece, sources = _piece()
  del piece["python_bundle"][key]
  _reject(wheel.validate_python_bundle_reference, "pi-full", piece, sources, locked=True)


class _Foreign:
  def __getattribute__(self, name):
    _foreign_call("attribute")
  def __repr__(self):
    _foreign_call("repr")
  def __bool__(self):
    _foreign_call("bool")
  def __eq__(self, other):
    _foreign_call("eq")
  def __deepcopy__(self, memo):
    _foreign_call("deepcopy")


@pytest.mark.parametrize("kind", [dict, list, str, int, bytes])
def test_subclasses_rejected_without_callbacks(kind):
  class Foreign(kind):
    def __iter__(self): _foreign_call("iter")
    def __len__(self): _foreign_call("len")
    def items(self): _foreign_call("items")
    def encode(self, *args): _foreign_call("encode")
    def __eq__(self, other): _foreign_call("eq")
  if kind is dict:
    value = Foreign(_source())
    _reject(wheel.validate_wheel_source, value, locked=True)
  elif kind is list:
    source = _source(); source["license_files"] = Foreign(source["license_files"])
    _reject(wheel.validate_wheel_source, source, locked=True)
  elif kind is bytes:
    piece, sources = _piece()
    _reject(wheel.validate_selected_python_bundle, Foreign(b"{}"), piece, sources)
  else:
    source = _source(); source["package" if kind is str else "size"] = Foreign("attrs" if kind is str else 1)
    _reject(wheel.validate_wheel_source, source, locked=True)


@pytest.mark.parametrize("case", ["foreign", "float", "int-high", "int-low", "surrogate", "long-string"])
def test_native_bad_values(case):
  value = {"foreign": _Foreign(), "float": 1.5, "int-high": 2 ** 63, "int-low": -(2 ** 63) - 1,
    "surrogate": "\ud800", "long-string": "x" * 4097}[case]
  source = _source()
  source["size"] = value
  _reject(wheel.validate_wheel_source, source, locked=True)


def test_nonstring_key_cycle_depth_nodes_and_container_caps(monkeypatch):
  calls = _no_core(monkeypatch)
  source = _source(); source[1] = "bad"
  _reject(wheel.validate_wheel_source, source, locked=True)
  source = _source(); source["loop"] = source
  _reject(wheel.validate_wheel_source, source, locked=True)
  value = None
  for _ in range(18): value = [value]
  _reject(wheel.validate_wheel_source, dict(_source(), extra=value), locked=True)
  _reject(wheel.validate_wheel_source, dict(_source(), extra=[None] * 100001), locked=True)
  _reject(wheel.validate_wheel_source, dict(_source(), extra=[[None] * 50000] * 2), locked=True)
  piece, sources = _piece()
  piece["source_ids"] = ["attrs"] * 4097
  _reject(wheel.validate_python_bundle_reference, "pi-full", piece, sources, locked=True)
  piece, sources = _piece()
  piece["runtime_files"] = [{"source": "a", "path": "b"}] * 2049
  _reject(wheel.validate_python_bundle_reference, "pi-full", piece, sources, locked=True)
  piece, sources = _piece()
  sources.update({"x" + str(n): {"kind": "npm"} for n in range(4097)})
  _reject(wheel.validate_python_bundle_reference, "pi-full", piece, sources, locked=True)
  assert calls == []


@pytest.mark.parametrize("location", ["piece", "sources", "record", "kind", "ids", "runtime", "ref", "profile", "locked"])
def test_foreign_boundary_values(location):
  piece, sources = _piece()
  profile, locked = "pi-full", True
  foreign = _Foreign()
  if location == "piece": piece = foreign
  if location == "sources": sources = foreign
  if location == "record": sources["durable-python-attrs"] = foreign
  if location == "kind": sources["durable-python-attrs"]["kind"] = foreign
  if location == "ids": piece["source_ids"] = foreign
  if location == "runtime": piece["runtime_files"][0] = foreign
  if location == "ref": piece["python_bundle"] = foreign
  if location == "profile": profile = foreign
  if location == "locked": locked = foreign
  _reject(wheel.validate_python_bundle_reference, profile, piece, sources, locked=locked)


@pytest.mark.parametrize("raw", [b"", b"{", b"\xff", b'{"x":1,"x":2}', b'{"a":{"x":1,"x":2}}', b'{"x":NaN}', b'{"x":Infinity}',
  b'{"x":-Infinity}', b'{"x":1.5}', b'{"x":9223372036854775808}', b'{"x":"\\ud800"}', b'{"x":"' + b"a" * 4097 + b'"}',
  b"[" * 18 + b"0" + b"]" * 18, b"[" + b"0," * 100000 + b"0]", b" " * 8388609])
def test_selected_pre_core_body_failures(raw, monkeypatch):
  piece, sources = _piece(raw=raw)
  calls = _no_core(monkeypatch)
  _reject(wheel.validate_selected_python_bundle, raw, piece, sources)
  assert calls == []


@pytest.mark.parametrize("fault", ["sha", "size", "bytes-type", "no-ref"])
def test_selected_raw_binding_failures(fault, monkeypatch):
  piece, sources = _piece()
  raw = b"{}"
  if fault == "sha": piece["python_bundle"]["sha256"] = "a" * 64
  if fault == "size": piece["python_bundle"]["size"] = 3
  if fault == "bytes-type": raw = bytearray(raw)
  if fault == "no-ref":
    piece = {"source_ids": [], "runtime_files": [{"source": "old", "path": "old"}]}
  calls = _no_core(monkeypatch)
  _reject(wheel.validate_selected_python_bundle, raw, piece, sources)
  assert calls == []


def test_selected_real_core_and_detached_result():
  declaration, raw, piece, sources = _body()
  original_piece, original_sources = copy.deepcopy(piece), copy.deepcopy(sources)
  result = wheel.validate_selected_python_bundle(raw, piece, sources)
  assert result == declaration
  result["wheels"][0]["metadata"]["license_files"].append("CHANGED")
  assert declaration["wheels"][0]["metadata"]["license_files"] == ["LICENSE"]
  assert piece == original_piece and sources == original_sources
  assert wheel.validate_selected_python_bundle(raw, piece, sources) == declaration


@pytest.mark.parametrize("index", range(7))
@pytest.mark.parametrize("field", ["package", "version", "wheel_filename", "archive_digest", "size", "license_files"])
def test_selected_valid_source_row_pairing_drift(field, index):
  _, raw, piece, sources = _body()
  source = sources[piece["source_ids"][index]]
  if field == "package":
    # 已有另一个七名 package，ID 不匹配应在正文之前失败。
    source["package"] = "attrs" if index else "jsonschema"
  elif field == "version":
    source.update(_source(source["package"], version="25.4.1"))
  elif field == "wheel_filename":
    source["wheel_filename"] = source["wheel_filename"].replace("-py3-", "-py2.py3-").replace("-cp311-", "-cp310.cp311-", 1)
    source["url"] = "https://files.example.test/" + source["wheel_filename"]
    source["vendor_path"] = "vendor/wheels/" + source["archive_digest"] + "/" + source["wheel_filename"]
  elif field == "archive_digest":
    source[field] = "b" * 64
    source["vendor_path"] = "vendor/wheels/" + source[field] + "/" + source["wheel_filename"]
  elif field == "size": source[field] += 1
  else: source[field] = [source[field][0].rsplit("/", 1)[0] + "/OTHER"]
  _reject(wheel.validate_selected_python_bundle, raw, piece, sources)


@pytest.mark.parametrize("raw", [b"{}", b"[]", b"null", b'{"schema_version":2}'])
def test_selected_core_semantic_failure_imports_only_at_selected_call(raw, monkeypatch):
  piece, sources = _piece(raw=raw)
  original = builtins.__import__
  calls = []
  def observed(name, *args, **kwargs):
    if name == "pi_python_bundle": calls.append(name)
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", observed)
  _reject(wheel.validate_selected_python_bundle, raw, piece, sources)
  assert calls == ["pi_python_bundle"]


def test_selected_snapshot_before_core_never_rereads_caller(monkeypatch):
  declaration, raw, piece, sources = _body()
  from agentcfg import pi_python_bundle as core
  original = core.validate_python_bundle_declaration
  def mutate_caller(value):
    piece.clear()
    sources.clear()
    original(value)
  monkeypatch.setattr(core, "validate_python_bundle_declaration", mutate_caller)
  assert wheel.validate_selected_python_bundle(raw, piece, sources) == declaration


def test_fixed_error_clears_active_context_without_mutating_original():
  original = RuntimeError("caller-private-context")
  cause = RuntimeError("caller-private-cause")
  original.__cause__ = cause
  try:
    raise original
  except RuntimeError:
    _reject(wheel.validate_wheel_source, {}, locked=True)
  assert original.__cause__ is cause
  assert original.__context__ is None


@pytest.mark.parametrize("control", [KeyboardInterrupt("control"), SystemExit(9), GeneratorExit("control"), BaseException("control")])
def test_control_original_object_and_dependency_error_unchanged(control, monkeypatch):
  _, raw, piece, sources = _body()
  from agentcfg import pi_python_bundle as core
  def raising(value): raise control
  monkeypatch.setattr(core, "validate_python_bundle_declaration", raising)
  with pytest.raises(BaseException) as caught:
    wheel.validate_selected_python_bundle(raw, piece, sources)
  assert caught.value is control


def test_dependency_ordinary_error_not_mutated(monkeypatch):
  _, raw, piece, sources = _body()
  from agentcfg import pi_python_bundle as core
  error = RuntimeError("dependency-secret")
  cause = RuntimeError("dependency-cause")
  error.__cause__ = cause
  def raising(value): raise error
  monkeypatch.setattr(core, "validate_python_bundle_declaration", raising)
  _reject(wheel.validate_selected_python_bundle, raw, piece, sources)
  assert error.__cause__ is cause


def test_selected_real_core_without_io_or_zip(monkeypatch):
  declaration, raw, piece, sources = _body()
  with monkeypatch.context() as guard:
    original = builtins.__import__
    calls = []
    def no_zip(name, *args, **kwargs):
      if "zipfile" in name:
        calls.append(name)
        raise AssertionError("unexpected ZIP import")
      return original(name, *args, **kwargs)
    def no_io(*args, **kwargs): raise AssertionError("unexpected IO")
    guard.setattr(builtins, "__import__", no_zip)
    guard.setattr(builtins, "open", no_io)
    guard.setattr(Path, "open", no_io)
    assert wheel.validate_selected_python_bundle(raw, piece, sources) == declaration
    assert calls == []


def test_cold_module_and_common_paths_without_io_zip_core(monkeypatch):
  tree = ast.parse(_MODULE)
  assert [node.module for node in tree.body if isinstance(node, ast.ImportFrom)] == ["urllib.parse"]
  assert {alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names} == {"hashlib", "ipaddress", "json", "re"}
  # 测试自己的文件哨兵在 teardown 需要正常读取，阻断范围限于 API 调用。
  with monkeypatch.context() as guard:
    calls = _no_core(guard)
    def no_io(*args, **kwargs): raise AssertionError("unexpected IO")
    guard.setattr(builtins, "open", no_io)
    guard.setattr(Path, "open", no_io)
    namespace = {"__name__": "agentcfg.pi_wheel_sources", "__package__": "agentcfg"}
    exec(compile(_MODULE, "<pure-wheel-source>", "exec"), namespace)
    source = _source()
    namespace["validate_wheel_source"](source, locked=True)
    namespace["wheel_source_identity"](source)
    piece, sources = _piece()
    namespace["validate_python_bundle_reference"]("pi-full", piece, sources, locked=True)
    namespace["validate_python_bundle_reference"]("pi-base", {"source_ids": [], "runtime_files": [{"source": "old", "path": "old"}]}, sources, locked=True)
    assert calls == []


class _CapturedForeignKey(str):
  __hash__ = str.__hash__

  def __eq__(self, other):
    _foreign_call("captured-key-eq")


def _capture_late_mutation(monkeypatch, target, mutate):
  original = wheel._Snapshot.keys
  calls = []
  def after_keys(snapshot, value, cap):
    pairs = original(snapshot, value, cap)
    if value is target:
      calls.append("capture")
      mutate()
    return pairs
  monkeypatch.setattr(wheel._Snapshot, "keys", after_keys)
  return calls


@pytest.mark.parametrize("location", ["piece", "record", "sources"])
@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_captured_pairs_old_profiles_ignore_late_foreign_keys(location, profile, monkeypatch):
  piece = {"source_ids": ["old-npm"], "runtime_files": [{"source": "old", "path": "old"}]}
  record = {"kind": "npm", "ignored": _Foreign()}
  sources = {"old-npm": record}
  if location == "piece":
    target = piece
    def mutate():
      piece[_CapturedForeignKey("late-piece-key")] = _Foreign()
  elif location == "record":
    target = record
    def mutate():
      record.clear()
      record[_CapturedForeignKey("kind")] = "npm"
  else:
    target = sources
    def mutate():
      sources.clear()
      sources[_CapturedForeignKey("old-npm")] = record
  calls = _capture_late_mutation(monkeypatch, target, mutate)
  assert wheel.validate_python_bundle_reference(profile, piece, sources, locked=True) is None
  assert calls == ["capture"]
  assert _FOREIGN_CALLS == []


@pytest.mark.parametrize("location", ["piece", "record", "sources"])
def test_captured_pairs_full_body_uses_captured_native_keys(location, monkeypatch):
  declaration, raw, piece, sources = _body()
  record = sources["durable-python-attrs"]
  if location == "piece":
    target = piece
    def mutate():
      piece[_CapturedForeignKey("late-piece-key")] = _Foreign()
  elif location == "record":
    target = record
    def mutate():
      remaining = [(key, value) for key, value in record.items() if key != "kind"]
      record.clear()
      record[_CapturedForeignKey("kind")] = "wheel"
      record.update(remaining)
  else:
    target = sources
    def mutate():
      records = list(sources.items())
      sources.clear()
      for key, value in records:
        sources[_CapturedForeignKey(key) if key == "durable-python-attrs" else key] = value
  calls = _capture_late_mutation(monkeypatch, target, mutate)
  assert wheel.validate_selected_python_bundle(raw, piece, sources) == declaration
  assert calls == ["capture"]
  assert _FOREIGN_CALLS == []


@pytest.mark.parametrize("location", ["piece", "record", "sources"])
def test_captured_pairs_foreign_keys_present_at_capture_reject_without_callback(location):
  piece = {"source_ids": ["old-npm"], "runtime_files": [{"source": "old", "path": "old"}]}
  record = {"kind": "npm", "ignored": _Foreign()}
  sources = {"old-npm": record}
  if location == "piece":
    piece[_CapturedForeignKey("late-piece-key")] = None
  elif location == "record":
    record.clear()
    record[_CapturedForeignKey("kind")] = "npm"
  else:
    sources.clear()
    sources[_CapturedForeignKey("old-npm")] = record
  _reject(wheel.validate_python_bundle_reference, "pi-base", piece, sources, locked=True)
  assert _FOREIGN_CALLS == []


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_captured_pairs_native_kind_and_old_profile_control(profile):
  piece = {"source_ids": ["old-npm"], "runtime_files": [{"source": "old", "path": "old"}]}
  sources = {"old-npm": {"kind": "npm", "ignored": _Foreign()}}
  assert wheel.validate_python_bundle_reference(profile, piece, sources, locked=True) is None
  assert _FOREIGN_CALLS == []


def test_captured_pairs_full_public_core_control():
  declaration, raw, piece, sources = _body()
  assert wheel.validate_selected_python_bundle(raw, piece, sources) == declaration
  assert _FOREIGN_CALLS == []
