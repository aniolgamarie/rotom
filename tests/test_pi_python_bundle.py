"""七个合成 classic wheel；不读原档案，不导入或执行候选包。"""

import base64
import builtins
import copy
import csv
import hashlib
import io
import json
import struct
import zlib

import pytest

from agentcfg import pi_python_bundle as bundle


_NAMES = ["attrs", "jsonschema", "jsonschema-specifications", "pyyaml", "referencing", "rpds-py", "typing-extensions"]
_VERSIONS = ["25.4.0", "4.25.1", "2025.9.1", "6.0.3", "0.37.0", "0.30.0", "4.15.0"]
_ROOTS = ["attr", "jsonschema", "jsonschema_specifications", "yaml", "referencing", "rpds", "typing_extensions.py"]
_ENTRY = "[console_scripts]\njsonschema = jsonschema.cli:main\n"
_REQUIREMENTS = {
  "jsonschema": ["attrs>=22.2.0", "jsonschema-specifications>=2023.03.6", "referencing>=0.28.4", "rpds-py>=0.25.0",
    "fqdn; extra == 'format'", "idna; extra == 'format'", "isoduration; extra == 'format'",
    "jsonpointer>1.13; extra == 'format'", "rfc3339-validator; extra == 'format'", "rfc3987; extra == 'format'",
    "uri-template; extra == 'format'", "webcolors>=1.11; extra == 'format'", "fqdn; extra == 'format-nongpl'",
    "idna; extra == 'format-nongpl'", "isoduration; extra == 'format-nongpl'", "jsonpointer>1.13; extra == 'format-nongpl'",
    "rfc3339-validator; extra == 'format-nongpl'", "rfc3986-validator>0.1.0; extra == 'format-nongpl'",
    "rfc3987-syntax>=1.1.0; extra == 'format-nongpl'", "uri-template; extra == 'format-nongpl'", "webcolors>=24.6.0; extra == 'format-nongpl'"],
  "jsonschema-specifications": ["referencing>=0.31.0"],
  "referencing": ["attrs>=22.2.0", "rpds-py>=0.7.0", "typing-extensions>=4.4.0; python_version < '3.13'"],
}


def _sha(raw):
  return hashlib.sha256(raw).hexdigest()


def _canonical(value):
  return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _zip(files, directories, method, *, options=None):
  """自有公开格式 fixture，精确生成 ZIP20；正文可任意变异。"""
  options = options or {}
  local, central = bytearray(), bytearray()
  entries = [(path + "/", b"") for path in directories] + list(files.items())
  for name, payload in entries:
    name_bytes = name.encode("ascii")
    directory = name.endswith("/")
    option = options.get(name, {})
    algorithm = option.get("method", method)
    if algorithm == 8:
      compressor = zlib.compressobj(level=6, wbits=-15)
      encoded = compressor.compress(payload) + compressor.flush()
    else:
      encoded = payload
    encoded = option.get("compressed", encoded)
    crc = option.get("crc", zlib.crc32(payload))
    size = option.get("size", len(payload))
    flags = option.get("flags", 0)
    extra = option.get("extra", b"")
    comment = option.get("comment", b"")
    external = option.get("external", ((0o040755 if directory else 0o100644) << 16) | (0x10 if directory else 0))
    offset = len(local)
    local.extend(struct.pack("<4s5H3I2H", b"PK\x03\x04", 20, flags, algorithm, 0, 0, crc, len(encoded), size, len(name_bytes), len(extra)))
    local.extend(name_bytes + extra + encoded)
    central.extend(struct.pack("<4s6H3I5H2I", b"PK\x01\x02", 3 << 8 | 20, 20, flags, algorithm, 0, 0, crc, len(encoded), size,
                               len(name_bytes), len(extra), len(comment), 0, option.get("internal", 0), external, offset))
    central.extend(name_bytes + extra + comment)
  end = struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, len(entries), len(entries), len(central), len(local), 0)
  return bytes(local + central + end)


def _headers(row):
  metadata = row["metadata"]
  lines = ["Metadata-Version: 2.4", "Name: " + metadata["name"], "Version: " + row["version"],
           "Requires-Python: " + metadata["requires_python"]]
  for key, title in (("requires_dist", "Requires-Dist"), ("provides_extra", "Provides-Extra"), ("license_files", "License-File")):
    lines.extend(title + ": " + value for value in metadata[key])
  for key, title in (("license_expression", "License-Expression"), ("legacy_license", "License")):
    if metadata[key] is not None:
      lines.append(title + ": " + metadata[key])
  lines += ["Summary: harmless synthetic metadata", "Description-Content-Type: text/plain", "", "合成正文，保留原字节。"]
  wheel = ["Wheel-Version: 1.0", "Root-Is-Purelib: " + row["wheel"]["root_is_purelib"], "Generator: synthetic-public-data"]
  wheel.extend("Tag: " + tag for tag in row["wheel"]["tags"])
  return ("\n".join(lines) + "\n").encode(), ("\n".join(wheel) + "\n\n").encode()


def _finish(row, files, method, options=None):
  files = dict(files)
  own = row["dist_info"] + "/RECORD"
  files.pop(own, None)
  text = io.StringIO(newline="")
  writer = csv.writer(text, lineterminator="\n")
  for path, raw in sorted(files.items(), reverse=True):
    writer.writerow([path, "sha256=" + base64.urlsafe_b64encode(bytes.fromhex(_sha(raw))).decode().rstrip("="), str(len(raw))])
  writer.writerow([own, "", ""])
  files[own] = text.getvalue().encode()
  return _seal(row, files, method, options)


def _seal(row, files, method, options=None):
  row["members"] = [{"path": path, "size": len(raw), "sha256": _sha(raw), "role": _role(row, path)} for path, raw in sorted(files.items())]
  archive = _zip(files, row["explicit_directories"], method, options=options)
  row["archive_size"], row["archive_sha256"] = len(archive), _sha(archive)
  return archive, dict(files)


def _role(row, path):
  if path.startswith(row["dist_info"] + "/licenses/"): return "license"
  if path.startswith(row["dist_info"] + "/"): return "metadata"
  if path.endswith(".so"): return "native"
  if path.endswith((".py", ".pyi")): return "python"
  return "resource"


def _fixture(method=0):
  declaration = {"schema_version": 1, "layout": "flat-wheel-subset-v1", "profile_id": "pi-full",
    "library_root": "supervisor/python-bundle/site-packages", "inventory_path": "supervisor/python-bundle/inventory.json",
    "file_mode": 384, "directory_mode": 448, "roots": ["jsonschema", "pyyaml"], "extras": [],
    "target": {"implementation": "cpython", "python_release": [3, 11, 9], "abi": "cp311", "sys_platform": "linux", "machine": "x86_64",
               "platform_tags": ["manylinux2014_x86_64", "manylinux_2_17_x86_64"]}, "wheels": []}
  archives, originals = {}, {}
  for name, version, root in zip(_NAMES, _VERSIONS, _ROOTS):
    dist = name.replace("-", "_") + "-" + version + ".dist-info"
    native = name in ("pyyaml", "rpds-py")
    tags = ["cp311-cp311-manylinux_2_17_x86_64", "cp311-cp311-manylinux_2_28_x86_64"] if native else ["py3-none-any"]
    row = {"source_id": "durable-python-" + name, "name": name, "version": version, "dist_info": dist,
      "wheel_filename": name.replace("-", "_") + "-" + version + ("-cp311-cp311-manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl" if native else "-py3-none-any.whl"),
      "archive_size": 1, "archive_sha256": "0" * 64,
      "metadata": {"metadata_version": "2.4", "name": "PyYAML" if name == "pyyaml" else name.replace("-", "_"), "version": version,
        "requires_python": ">=3.11" if name == "rpds-py" else ">=3.9", "requires_dist": list(_REQUIREMENTS.get(name, [])),
        "provides_extra": ["format", "format-nongpl"] if name == "jsonschema" else [], "license_expression": None if name == "pyyaml" else "MIT",
        "legacy_license": "MIT" if name == "pyyaml" else None, "license_files": ["LICENSE"]},
      "wheel": {"wheel_version": "1.0", "root_is_purelib": "false" if native else "true", "tags": tags, "build": None},
      "entry_points": {"member": dist + "/entry_points.txt", "text": _ENTRY} if name == "jsonschema" else None,
      "members": [], "explicit_directories": sorted([dist, root]) if root != "typing_extensions.py" else [dist]}
    metadata, wheel = _headers(row)
    files = {dist + "/METADATA": metadata, dist + "/WHEEL": wheel, dist + "/licenses/LICENSE": b"Synthetic MIT license text.\n",
             root if root.endswith(".py") else root + "/__init__.py": b"# synthetic inert Python text\n"}
    if root != "typing_extensions.py":
      files[root + "/data/schema.json"] = b'{"synthetic":true}\n'
    if name == "attrs": files["attrs/__init__.py"] = b"# second allowed root\n"
    if name == "pyyaml": files["_yaml/__init__.py"] = b"# compatibility text\n"
    if native: files[root + "/_fake.cpython-311-x86_64-linux-gnu.so"] = b"synthetic native resource, never imported\x00"
    if row["entry_points"]: files[row["entry_points"]["member"]] = _ENTRY.encode()
    archive, complete = _finish(row, files, method)
    declaration["wheels"].append(row)
    archives[row["source_id"]], originals[name] = archive, complete
  return declaration, archives, originals


def _plan(declaration, archives, occupied=None):
  return bundle.plan_python_bundle_install(declaration, archives, occupied_files=[] if occupied is None else occupied)


def _reject(function, *args, **kwargs):
  with pytest.raises(ValueError) as caught:
    function(*args, **kwargs)
  assert str(caught.value) == "pi-python-bundle"
  assert caught.value.__cause__ is None
  assert caught.value.__context__ is None


def _archive_replace(declaration, archives, index, raw):
  row = declaration["wheels"][index]
  row["archive_size"], row["archive_sha256"] = len(raw), _sha(raw)
  archives[row["source_id"]] = raw


def _rebuild(declaration, archives, originals, index, *, transform=None, method=0, options=None, regenerate_record=True):
  row = declaration["wheels"][index]
  files = dict(originals[row["name"]])
  if transform: transform(files, row)
  finish = _finish if regenerate_record else _seal
  raw, files = finish(row, files, method, options)
  archives[row["source_id"]] = raw
  originals[row["name"]] = files


def _walk(value):
  yield value
  if type(value) is dict:
    for key, child in value.items():
      yield key
      yield from _walk(child)
  elif type(value) is list:
    for child in value: yield from _walk(child)


@pytest.mark.parametrize("method", [0, 8])
def test_seven_complete_archives_preserve_bytes_and_detach(method):
  declaration, archives, originals = _fixture(method)
  before = copy.deepcopy((declaration, archives))
  bundle.validate_python_bundle_declaration(declaration)
  plan = _plan(declaration, archives)
  assert plan == _plan(declaration, archives)
  assert (declaration, archives) == before
  bundle.validate_python_bundle_inventory(declaration, plan["inventory_template"])
  assert plan["declaration_digest"] == _sha(_canonical(declaration))
  without = {key: value for key, value in plan.items() if key != "plan_digest"}
  assert plan["plan_digest"] == _sha(_canonical(without))
  for file in plan["files"]:
    name = file["source_id"].removeprefix("durable-python-")
    raw = originals[name][file["member"]]
    assert file["size"] == len(raw) and file["sha256"] == _sha(raw)
    assert file["mode"] == 0o600
  assert all(item["mode"] == 0o700 for item in plan["directories"])
  assert not any(item["target"] == "supervisor" for item in plan["directories"])
  assert not any(type(item) in (bytes, bytearray, memoryview) for item in _walk(plan))
  for word in ("authority", "ready", "capability", "payload", "content"):
    assert word not in set(item for item in _walk(plan) if type(item) is str)
  plan["target"]["python_release"][2] = 42
  plan["files"][0]["mode"] = 1
  assert declaration == before[0]
  assert plan["inventory_template"]["target"]["python_release"][2] == 9
  assert plan["inventory_template"]["files"][0]["mode"] == 384


def test_25_typed_rules_8_active_17_inactive_and_original_spelling():
  declaration, archives, unused = _fixture()
  plan = _plan(declaration, archives)
  rules = plan["requirements"]
  assert len(rules) == 25
  assert sum(rule["active"] for rule in rules) == 8
  assert sum(not rule["active"] for rule in rules) == 17
  rule = next(rule for rule in rules if rule["name"] == "jsonschema-specifications")
  assert rule["raw_release"] == "2023.03.6" and rule["release"] == [2023, 3, 6]
  rule = next(rule for rule in rules if rule["name"] == "typing-extensions")
  assert rule["marker"] == {"variable": "python_version", "operator": "<", "value": "3.13"}
  assert rule["active"] is True
  assert "python_full_version" not in _canonical(plan).decode()
  for rule in rules:
    assert (rule["satisfied"] is True and rule["selected_version"] is not None) if rule["active"] else (rule["satisfied"] is None and rule["selected_version"] is None)


@pytest.mark.parametrize("target", [["manylinux_2_17_x86_64"], ["manylinux_2_28_x86_64"]])
def test_native_tag_intersection_is_sufficient(target):
  declaration, archives, unused = _fixture()
  declaration["target"]["platform_tags"] = target
  plan = _plan(declaration, archives)
  bundle.validate_python_bundle_inventory(declaration, plan["inventory_template"])


def test_native_tag_without_intersection_fails_without_archive():
  declaration, unused, unused2 = _fixture()
  declaration["target"]["platform_tags"] = ["manylinux2014_x86_64"]
  _reject(bundle.validate_python_bundle_declaration, declaration)
  _reject(bundle.validate_python_bundle_inventory, declaration, {})


@pytest.mark.parametrize("mutate", [
  lambda d: d.update(extra="unknown"), lambda d: d.update(schema_version=True),
  lambda d: d.update(file_mode=384.0), lambda d: d.update(roots=["pyyaml", "jsonschema"]),
  lambda d: d["target"].update(python_release=[3, 11, True]),
  lambda d: d["target"].update(python_release=[3, 12, 0]),
  lambda d: d["target"].update(machine="aarch64"),
  lambda d: d["target"].update(platform_tags=["manylinux_2_17_x86_64"] * 2),
  lambda d: d["wheels"].reverse(), lambda d: d["wheels"][0].update(version="01.2.3"),
  lambda d: d["wheels"][0].update(archive_size=True),
  lambda d: d["wheels"][0].update(archive_sha256="A" * 64),
  lambda d: d["wheels"][0].update(source_id="foreign"),
  lambda d: d["wheels"][0]["metadata"].update(legacy_license="\ud800"),
  lambda d: d["wheels"][0]["metadata"].pop("legacy_license"),
  lambda d: d["wheels"][0]["members"][0].update(size=False),
  lambda d: d["wheels"][0]["members"][0].update(role="unknown"),
  lambda d: d["wheels"][0].update(explicit_directories=["typing_extensions.py"]),
])
def test_declaration_exact_native_fields_literals_and_order(mutate):
  declaration, unused, unused2 = _fixture()
  mutate(declaration)
  _reject(bundle.validate_python_bundle_declaration, declaration)


@pytest.mark.parametrize("raw", ["attrs==25.4.0", "attrs~=25.0", "attrs!=1", "attrs<30", "attrs<=30", "attrs>=1.*", "attrs>=1rc1",
  "attrs>=1+local", "attrs>=1!2", "attrs[extra]", "attrs @ https://example.invalid/a", "attrs; python_full_version < '3.13'",
  "attrs; python_version < '3.14'", "attrs; extra == 'other'", "attrs; extra == 'format' or extra == 'format-nongpl'"])
def test_unknown_dependency_grammar_is_closed(raw):
  declaration, unused, unused2 = _fixture()
  declaration["wheels"][1]["metadata"]["requires_dist"] = [raw]
  _reject(bundle.validate_python_bundle_declaration, declaration)


@pytest.mark.parametrize("raw", ["missing", "typing-extensions>4.15.0", "attrs>=99.0", "fqdn; extra == 'format'"])
def test_active_closure_versions_and_extra_ownership(raw):
  declaration, unused, unused2 = _fixture()
  declaration["wheels"][4]["metadata"]["requires_dist"] = [raw]
  _reject(bundle.validate_python_bundle_declaration, declaration)


@pytest.mark.parametrize("field", ["METADATA", "WHEEL", "RECORD", "licenses/LICENSE", "entry_points.txt"])
def test_required_members_cannot_be_missing_or_replaced_by_directory(field):
  declaration, unused, unused2 = _fixture()
  row = declaration["wheels"][1]
  path = row["dist_info"] + "/" + field
  row["members"] = [member for member in row["members"] if member["path"] != path]
  _reject(bundle.validate_python_bundle_declaration, declaration)
  row["explicit_directories"] = sorted(row["explicit_directories"] + [path])
  _reject(bundle.validate_python_bundle_declaration, declaration)


@pytest.mark.parametrize("path", ["jsonschema/foreign.py", "attr/x.pth", "attr/x.PYC", "attr/__pycache__/x", "attr/sitecustomize.py",
  "attr/UserCustomize.py", "attr/../x", "attr//x", "/attr/x", "attr/a\\b", "attr/a:b", "attr/x.data/file",
  "attr/é.py", "attr/a\x00b", "attrs-25.4.0.dist-info/RECORD.jws", "attrs-25.4.0.dist-info/RECORD.p7s"])
def test_wheel_owned_namespace_and_unsafe_members(path):
  declaration, unused, unused2 = _fixture()
  row = declaration["wheels"][0]
  row["members"].append({"path": path, "size": 1, "sha256": "0" * 64, "role": "resource"})
  row["members"].sort(key=lambda member: member["path"])
  _reject(bundle.validate_python_bundle_declaration, declaration)


def test_entry_null_and_module_file_are_mutually_exclusive():
  declaration, unused, unused2 = _fixture()
  declaration["wheels"][1]["entry_points"] = None
  _reject(bundle.validate_python_bundle_declaration, declaration)
  declaration, unused, unused2 = _fixture()
  declaration["wheels"][-1]["explicit_directories"].append("typing_extensions.py")
  _reject(bundle.validate_python_bundle_declaration, declaration)


@pytest.mark.parametrize("occupied", [
  [{"kind": "directory", "path": "supervisor"}], [{"kind": "file", "path": "supervisor/"}],
  [{"kind": "file", "path": "supervisor"}], [{"kind": "file", "path": "Supervisor"}],
  [{"kind": "file", "path": "supervisor/python-bundle"}],
  [{"kind": "file", "path": "supervisor/python-bundle/unknown-sibling.txt"}],
  [{"kind": "file", "path": "SUPERVISOR/PYTHON-BUNDLE/INVENTORY.JSON"}],
  [{"kind": "file", "path": "supervisor/python-bundle/site-packages/attr/__init__.py/child"}],
  [{"kind": "file", "path": "other"}, {"kind": "file", "path": "other/x"}],
  [{"kind": "file", "path": "Other"}, {"kind": "file", "path": "other"}],
  [{"kind": "file", "path": "z"}, {"kind": "file", "path": "a"}],
])
def test_occupied_files_and_reserved_prefix_fail_before_decode(occupied, monkeypatch):
  declaration, archives, unused = _fixture()
  def no_decode(*args): raise AssertionError("unexpected payload decoding")
  monkeypatch.setattr(bundle, "_archive", no_decode)
  _reject(bundle.plan_python_bundle_install, declaration, archives, occupied_files=occupied)


def test_shared_parent_directory_is_absent_from_occupied_files():
  declaration, archives, unused = _fixture()
  assert _plan(declaration, archives, [{"kind": "file", "path": "supervisor/other-producer/file"}])


@pytest.mark.parametrize("part,offset,value", [
  ("local", 4, 19), ("local", 6, 8), ("local", 8, 12), ("local", 14, 1), ("local", 18, 1), ("local", 22, 1), ("local", 28, 1),
  ("central", 4, 19), ("central", 6, 19), ("central", 8, 1), ("central", 8, 8), ("central", 8, 2048),
  ("central", 10, 12), ("central", 20, 0xffffffff), ("central", 24, 0xffffffff), ("central", 30, 1),
  ("central", 32, 1), ("central", 34, 1), ("central", 42, 0xffffffff),
])
def test_local_central_headers_rejected_with_updated_archive_hash(part, offset, value):
  declaration, archives, unused = _fixture()
  raw = bytearray(archives[declaration["wheels"][0]["source_id"]])
  base = 0 if part == "local" else struct.unpack_from("<I", raw, len(raw) - 6)[0]
  width = "I" if offset in ((14, 18, 22) if part == "local" else (20, 24, 42)) else "H"
  struct.pack_into("<" + width, raw, base + offset, value)
  _archive_replace(declaration, archives, 0, bytes(raw))
  _reject(_plan, declaration, archives)


@pytest.mark.parametrize("kind", ["local-name", "preamble", "suffix", "comment", "disk", "count", "cd-size", "gap", "overlap", "locator"])
def test_classic_framing_exact_boundaries(kind):
  declaration, archives, unused = _fixture()
  raw = bytearray(archives[declaration["wheels"][0]["source_id"]])
  cd_offset = struct.unpack_from("<I", raw, len(raw) - 6)[0]
  if kind == "local-name": raw[30] = ord("x")
  elif kind == "preamble": raw = b"prefix" + raw
  elif kind == "suffix": raw += b"suffix"
  elif kind == "comment": struct.pack_into("<H", raw, len(raw) - 2, 1)
  elif kind == "disk": struct.pack_into("<H", raw, len(raw) - 18, 1)
  elif kind == "count": struct.pack_into("<H", raw, len(raw) - 12, 65535)
  elif kind == "cd-size": struct.pack_into("<I", raw, len(raw) - 10, 0xffffffff)
  elif kind == "gap": struct.pack_into("<I", raw, cd_offset + 42, 1)
  elif kind == "overlap":
    second = cd_offset + 46 + struct.unpack_from("<H", raw, cd_offset + 28)[0]
    struct.pack_into("<I", raw, second + 42, 0)
  else: raw = raw[:-22] + b"PK\x06\x07" + b"\x00" * 16 + raw[-22:]
  _archive_replace(declaration, archives, 0, bytes(raw))
  _reject(_plan, declaration, archives)


@pytest.mark.parametrize("external,internal", [(0o120777 << 16, 0), (0o020600 << 16, 0), (0o104644 << 16, 0),
  (0o102644 << 16, 0), (0o101644 << 16, 0), ((0o100644 << 16) | 0x10, 0), ((0o100644 << 16) | 1, 0), (0o100644 << 16, 2), (0o040755 << 16, 0)])
def test_archive_external_and_internal_attributes(external, internal):
  declaration, archives, originals = _fixture()
  row = declaration["wheels"][0]
  path = "attr/__init__.py"
  _rebuild(declaration, archives, originals, 0, options={path: {"external": external, "internal": internal}})
  _reject(_plan, declaration, archives)


@pytest.mark.parametrize("external", [0, 0o644 << 16, 0o100644 << 16])
def test_regular_file_attributes_safe_conventions(external):
  declaration, archives, originals = _fixture()
  _rebuild(declaration, archives, originals, 0, options={"attr/__init__.py": {"external": external, "internal": 1}})
  assert _plan(declaration, archives)


@pytest.mark.parametrize("fault", ["truncated", "trailing", "second-stream", "oversized", "crc", "stored-size"])
def test_strict_decode_framing_and_crc(fault):
  declaration, archives, originals = _fixture(8)
  payload = originals["attrs"]["attr/__init__.py"]
  compressor = zlib.compressobj(wbits=-15)
  encoded = compressor.compress(payload) + compressor.flush()
  option = {}
  if fault == "truncated": option["compressed"] = encoded[:-1]
  elif fault == "trailing": option["compressed"] = encoded + b"tail"
  elif fault == "second-stream": option["compressed"] = encoded + encoded
  elif fault == "oversized":
    compressor = zlib.compressobj(wbits=-15)
    option["compressed"] = compressor.compress(payload + b"extra") + compressor.flush()
  elif fault == "crc": option["crc"] = 0
  else: option.update(method=0, size=len(payload) + 1)
  _rebuild(declaration, archives, originals, 0, method=8, options={"attr/__init__.py": option})
  _reject(_plan, declaration, archives)


def test_member_hash_rejected_after_archive_hash_passes():
  declaration, archives, unused = _fixture()
  member = next(item for item in declaration["wheels"][0]["members"] if item["path"] == "attr/__init__.py")
  member["sha256"] = "0" * 64
  _reject(_plan, declaration, archives)


@pytest.mark.parametrize("fault", ["hash", "size", "padding", "duplicate", "missing", "columns", "self-hash", "unsafe", "utf8"])
def test_record_real_bytes_validation(fault):
  declaration, archives, originals = _fixture()
  def transform(files, row):
    own = row["dist_info"] + "/RECORD"
    lines = files[own].decode().splitlines()
    parsed = list(csv.reader(lines))
    if fault == "hash": parsed[0][1] = "sha256=" + "A" * 43
    elif fault == "size": parsed[0][2] = "0" + parsed[0][2]
    elif fault == "padding": parsed[0][1] += "="
    elif fault == "duplicate": parsed.append(parsed[0])
    elif fault == "missing": parsed.pop(0)
    elif fault == "columns": parsed[0].append("extra")
    elif fault == "self-hash": parsed[-1][1] = "sha256=" + "A" * 43
    elif fault == "unsafe": parsed[0][0] = "../unsafe"
    else:
      files[own] = b"\xff"; return
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(parsed)
    files[own] = output.getvalue().encode()
  _rebuild(declaration, archives, originals, 0, transform=transform, regenerate_record=False)
  _reject(_plan, declaration, archives)


@pytest.mark.parametrize("fault", ["duplicate", "fold", "utf8", "foreign", "name", "version", "python", "tag", "pure", "build", "entry", "list-order"])
def test_metadata_headers_actual_bytes_match_declaration(fault):
  declaration, archives, originals = _fixture()
  def transform(files, row):
    path = row["dist_info"] + "/METADATA"
    raw = files[path]
    if fault == "duplicate": raw = b"Name: jsonschema\n" + raw
    elif fault == "fold": raw = raw.replace(b"Name: jsonschema\n", b"Name: jsonschema\n continuation\n")
    elif fault == "utf8": raw = raw.replace(b"Summary:", b"Summary:\xff")
    elif fault == "foreign": raw = b"Import-Name: foreign\n" + raw
    elif fault == "name": raw = raw.replace(b"Name: jsonschema\n", b"Name: attrs\n")
    elif fault == "version": raw = raw.replace(b"Version: 4.25.1", b"Version: 4.25.2")
    elif fault == "python": raw = raw.replace(b"Requires-Python: >=3.9", b"Requires-Python: >=3.10")
    elif fault == "list-order": raw = raw.replace(b"Requires-Dist: attrs>=22.2.0\nRequires-Dist: jsonschema-specifications>=2023.03.6", b"Requires-Dist: jsonschema-specifications>=2023.03.6\nRequires-Dist: attrs>=22.2.0")
    elif fault in ("tag", "pure", "build"):
      wheel_path = row["dist_info"] + "/WHEEL"
      wheel = files[wheel_path]
      if fault == "tag": wheel = wheel.replace(b"py3-none-any", b"cp311-cp311-manylinux_2_17_x86_64")
      elif fault == "pure": wheel = wheel.replace(b"true", b"false")
      else: wheel = b"Build: 1\n" + wheel
      files[wheel_path] = wheel
    else: files[row["entry_points"]["member"]] = b"[console_scripts]\nforeign = pkg:main\n"
    files[path] = raw
  _rebuild(declaration, archives, originals, 1, transform=transform)
  _reject(_plan, declaration, archives)


def test_nonoperative_fold_and_body_preserved_but_not_emitted():
  declaration, archives, originals = _fixture(8)
  def transform(files, row):
    path = row["dist_info"] + "/METADATA"
    files[path] = files[path].replace(b"Summary: harmless synthetic metadata", b"Summary: harmless\n folded nonoperative text")
  _rebuild(declaration, archives, originals, 0, transform=transform, method=8)
  plan = _plan(declaration, archives)
  assert "folded nonoperative text" not in _canonical(plan).decode()


@pytest.mark.parametrize("field", ["schema_version", "declaration_digest", "layout", "profile_id", "target", "library_root", "inventory_path",
  "file_mode", "directory_mode", "files", "directories", "requirements", "python_requirements", "stats"])
def test_inventory_every_top_level_field_required_and_exact(field):
  declaration, archives, unused = _fixture()
  inventory = _plan(declaration, archives)["inventory_template"]
  removed = copy.deepcopy(inventory)
  removed.pop(field)
  _reject(bundle.validate_python_bundle_inventory, declaration, removed)
  tampered = copy.deepcopy(inventory)
  tampered[field] = None
  _reject(bundle.validate_python_bundle_inventory, declaration, tampered)


@pytest.mark.parametrize("collection,field", [
  ("files", "source_id"), ("files", "member"), ("files", "target"), ("files", "size"), ("files", "sha256"), ("files", "mode"), ("files", "role"),
  ("directories", "target"), ("directories", "mode"), ("directories", "kind"), ("directories", "origins"),
  ("requirements", "source_id"), ("requirements", "ordinal"), ("requirements", "raw"), ("requirements", "name"), ("requirements", "operator"),
  ("requirements", "raw_release"), ("requirements", "release"), ("requirements", "marker"), ("requirements", "active"),
  ("requirements", "selected_version"), ("requirements", "satisfied"),
  ("python_requirements", "source_id"), ("python_requirements", "raw"), ("python_requirements", "operator"),
  ("python_requirements", "raw_release"), ("python_requirements", "release"), ("python_requirements", "satisfied"),
])
def test_inventory_every_record_field_tamper(collection, field):
  declaration, archives, unused = _fixture()
  inventory = _plan(declaration, archives)["inventory_template"]
  inventory[collection][0][field] = {"unknown": "tamper"}
  _reject(bundle.validate_python_bundle_inventory, declaration, inventory)


@pytest.mark.parametrize("change", ["origin-source", "origin-member", "origin-explicit", "stats", "unknown", "order", "count", "bool-int"])
def test_inventory_origins_stats_unknown_order_and_exact_int(change):
  declaration, archives, unused = _fixture()
  inventory = _plan(declaration, archives)["inventory_template"]
  if change.startswith("origin"):
    directory = next(item for item in inventory["directories"] if item["origins"])
    field = {"origin-source": "source_id", "origin-member": "member", "origin-explicit": "explicit"}[change]
    directory["origins"][0][field] = None
  elif change == "stats": inventory["stats"]["file_bytes"] += 1
  elif change == "unknown": inventory["authority"] = True
  elif change == "order": inventory["files"].reverse()
  elif change == "count": inventory["directories"].pop()
  else: inventory["schema_version"] = True
  _reject(bundle.validate_python_bundle_inventory, declaration, inventory)


class ForeignDict(dict):
  def items(self): raise AssertionError("foreign callback executed")


class ForeignList(list):
  def __iter__(self): raise AssertionError("foreign callback executed")


class ForeignBytes(bytes):
  def __len__(self): raise AssertionError("foreign callback executed")


@pytest.mark.parametrize("foreign", [ForeignDict(), ForeignList(), object(), b"bytes", 1.5, float("nan")])
def test_native_only_without_foreign_receiver(foreign):
  _reject(bundle.validate_python_bundle_declaration, foreign)


def test_native_artifacts_and_cycles():
  declaration, archives, unused = _fixture()
  key = declaration["wheels"][0]["source_id"]
  archives[key] = ForeignBytes(archives[key])
  _reject(_plan, declaration, archives)
  declaration["extras"].append(declaration)
  _reject(bundle.validate_python_bundle_declaration, declaration)


@pytest.mark.parametrize("api", ["declaration", "plan", "inventory"])
def test_fixed_errors_clear_outer_context_without_mutating_original(api):
  outer = ValueError("synthetic-private-outer")
  try:
    raise outer from RuntimeError("synthetic-private-cause")
  except ValueError:
    if api == "declaration": _reject(bundle.validate_python_bundle_declaration, {})
    elif api == "plan": _reject(bundle.plan_python_bundle_install, {}, {}, occupied_files=[])
    else: _reject(bundle.validate_python_bundle_inventory, {}, {})
  assert str(outer.__cause__) == "synthetic-private-cause"


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("api", ["declaration", "plan", "inventory"])
def test_base_exception_propagates(exception, api, monkeypatch):
  original = exception("synthetic-private-control")
  def interrupted(*args): raise original
  monkeypatch.setattr(bundle, "_declaration", interrupted)
  function, args, kwargs = {
    "declaration": (bundle.validate_python_bundle_declaration, ({},), {}),
    "plan": (bundle.plan_python_bundle_install, ({}, {}), {"occupied_files": []}),
    "inventory": (bundle.validate_python_bundle_inventory, ({}, {}), {}),
  }[api]
  with pytest.raises(exception) as caught: function(*args, **kwargs)
  assert caught.value is original


def test_signature_binding_remains_type_error():
  with pytest.raises(TypeError): bundle.validate_python_bundle_declaration()
  with pytest.raises(TypeError): bundle.plan_python_bundle_install({}, {})
  with pytest.raises(TypeError): bundle.validate_python_bundle_inventory({}, {}, unknown=True)


def test_no_io_environment_process_or_external_import(monkeypatch):
  import os
  import pathlib
  import subprocess
  declaration, archives, unused = _fixture()
  def prohibited(*args, **kwargs): raise AssertionError("pure API attempted IO")
  with monkeypatch.context() as patch:
    for target, attribute in ((builtins, "open"), (pathlib.Path, "open"), (pathlib.Path, "read_bytes"),
                              (os, "getenv"), (os, "stat"), (subprocess, "run")):
      patch.setattr(target, attribute, prohibited)
    patch.setattr(os, "environ", ForeignDict())
    patch.setattr(builtins, "__import__", prohibited)
    bundle.validate_python_bundle_declaration(declaration)
    plan = _plan(declaration, archives)
    bundle.validate_python_bundle_inventory(declaration, plan["inventory_template"])


def _cap_values(declaration, archives, plan):
  rows = declaration["wheels"]
  members = [member for row in rows for member in row["members"]]
  metadata = [member for member in members if member["role"] == "metadata"]
  paths = [member["path"] for member in members] + [path for row in rows for path in row["explicit_directories"]]
  values = {
    "archive_bytes": max(map(len, archives.values())), "archive_set_bytes": sum(map(len, archives.values())),
    "member_expanded_bytes": max(member["size"] for member in members),
    "wheel_expanded_bytes": max(sum(member["size"] for member in row["members"]) for row in rows),
    "wheel_entries": max(len(row["members"]) + len(row["explicit_directories"]) for row in rows),
    "set_entries": sum(len(row["members"]) + len(row["explicit_directories"]) for row in rows),
    "set_expanded_bytes": sum(member["size"] for member in members),
    "metadata_member_bytes": max(member["size"] for member in metadata),
    "metadata_wheel_total_bytes": max(sum(member["size"] for member in row["members"] if member["role"] == "metadata") for row in rows),
    "archive_member_path_bytes": max(map(len, paths)),
    "target_path_bytes": max(len(file["target"]) for file in plan["files"]),
    "name_bytes": max(len(row["metadata"]["name"]) for row in rows), "version_bytes": max([len(row["version"]) for row in rows] + [len(row["metadata"]["requires_python"]) for row in rows]
      + [len(raw.split(";", 1)[0].split(">", 1)[1].lstrip("=")) for row in rows for raw in row["metadata"]["requires_dist"] if ">" in raw.split(";", 1)[0]]),
    "wheel_filename_bytes": max(len(row["wheel_filename"]) for row in rows), "source_id_bytes": max(len(row["source_id"]) for row in rows),
    "requirement_raw_bytes": max(len(raw) for row in rows for raw in row["metadata"]["requires_dist"]),
    "requires_dist_per_wheel": max(len(row["metadata"]["requires_dist"]) for row in rows), "requires_dist_set": 25,
    "license_files_per_wheel": 1, "canonical_declaration_bytes": len(_canonical(declaration)),
    "canonical_plan_or_inventory_bytes": len(_canonical(plan)), "data_nodes": bundle._native(plan),
    "planned_directories": len(plan["directories"]), "path_components": max(len(file["target"].split("/")) for file in plan["files"]),
  }
  return values


@pytest.mark.parametrize("cap", ["archive_bytes", "archive_set_bytes", "member_expanded_bytes", "wheel_expanded_bytes", "wheel_entries",
  "set_entries", "set_expanded_bytes", "metadata_member_bytes", "metadata_wheel_total_bytes", "archive_member_path_bytes", "target_path_bytes",
  "name_bytes", "version_bytes", "wheel_filename_bytes", "source_id_bytes", "requirement_raw_bytes", "requires_dist_per_wheel", "requires_dist_set",
  "license_files_per_wheel", "canonical_declaration_bytes", "canonical_plan_or_inventory_bytes", "data_nodes", "planned_directories", "path_components"])
def test_caps_at_boundary_and_one_past(cap, monkeypatch):
  declaration, archives, unused = _fixture()
  plan = _plan(declaration, archives)
  boundary = _cap_values(declaration, archives, plan)[cap]
  monkeypatch.setitem(bundle._CAPS, cap, boundary)
  assert _plan(declaration, archives) == plan
  monkeypatch.setitem(bundle._CAPS, cap, boundary - 1)
  _reject(_plan, declaration, archives)


def test_occupied_file_cap_boundary(monkeypatch):
  declaration, archives, unused = _fixture()
  occupied = [{"kind": "file", "path": "a"}, {"kind": "file", "path": "b"}]
  monkeypatch.setitem(bundle._CAPS, "occupied_files", 2)
  assert _plan(declaration, archives, occupied)
  monkeypatch.setitem(bundle._CAPS, "occupied_files", 1)
  _reject(_plan, declaration, archives, occupied)


def test_depth_and_header_caps(monkeypatch):
  declaration, archives, originals = _fixture()
  def depth(value):
    children = list(value.values()) + list(value) if type(value) is dict else value if type(value) is list else []
    return 0 if not children else 1 + max(depth(child) for child in children)
  plan = _plan(declaration, archives)
  monkeypatch.setitem(bundle._CAPS, "data_depth", depth(plan))
  assert _plan(declaration, archives)
  monkeypatch.setitem(bundle._CAPS, "data_depth", depth(plan) - 1)
  _reject(_plan, declaration, archives)
  monkeypatch.setitem(bundle._CAPS, "data_depth", 16)
  headers = [raw.split(b"\n\n", 1)[0].splitlines() for files in originals.values() for path, raw in files.items() if path.endswith(("/METADATA", "/WHEEL"))]
  monkeypatch.setitem(bundle._CAPS, "header_lines", max(len(lines) + 1 for lines in headers))
  assert _plan(declaration, archives)
  monkeypatch.setitem(bundle._CAPS, "header_lines", max(len(lines) for lines in headers))
  _reject(_plan, declaration, archives)


def test_streaming_decode_bounded_output_allocations(monkeypatch):
  declaration, archives, originals = _fixture(8)
  # 不可压缩的大资源仍在 ratio 限额内，强制跨块解码。
  raw = b"".join(hashlib.sha256(str(number).encode()).digest() for number in range(8192))
  _rebuild(declaration, archives, originals, 0, transform=lambda files, row: files.update({"attr/data/large.bin": raw}), method=8)
  original = zlib.decompressobj
  calls = []
  class Decoder:
    def __init__(self, *args): self.wrapped = original(*args)
    def decompress(self, payload, maximum):
      calls.append((len(payload), maximum))
      assert len(payload) <= 65536 and 1 <= maximum <= 65536
      return self.wrapped.decompress(payload, maximum)
    def __getattr__(self, key): return getattr(self.wrapped, key)
  monkeypatch.setattr(bundle.zlib, "decompressobj", Decoder)
  assert _plan(declaration, archives)
  assert len(calls) > 7


def test_artifact_keys_reject_foreign_before_hash_callback():
  declaration, archives, unused = _fixture()
  calls = {"hash": 0, "eq": 0, "repr": 0}
  class Key:
    armed = False
    def __hash__(self):
      if self.armed: calls["hash"] += 1
      return 1
    def __eq__(self, other):
      if self.armed: calls["eq"] += 1
      return self is other
    def __repr__(self):
      if self.armed: calls["repr"] += 1
      return "synthetic foreign key"
  key = Key()
  artifacts = dict(archives)
  artifacts[key] = b"foreign"
  key.armed = True
  _reject(_plan, declaration, artifacts)
  assert calls == {"hash": 0, "eq": 0, "repr": 0}


@pytest.mark.parametrize("cap", ["header_line_bytes", "compression_ratio"])
def test_header_line_and_compression_caps_boundary(cap, monkeypatch):
  declaration, archives, originals = _fixture()
  if cap == "header_line_bytes":
    raw_lines = [line for files in originals.values() for path, raw in files.items() if path.endswith(("/METADATA", "/WHEEL")) for line in raw.split(b"\n\n", 1)[0].splitlines()]
    boundary = max(map(len, raw_lines))
  else: boundary = 1
  monkeypatch.setitem(bundle._CAPS, cap, boundary)
  assert _plan(declaration, archives)
  monkeypatch.setitem(bundle._CAPS, cap, boundary - 1)
  _reject(_plan, declaration, archives)


@pytest.mark.parametrize("external,method", [(0, 0), (0x10, 0), (0o040700 << 16, 8), ((0o040700 << 16) | 0x10, 8)])
def test_explicit_directory_safe_empty_stored_and_deflate(external, method):
  declaration, archives, originals = _fixture(method)
  _rebuild(declaration, archives, originals, 0, method=method, options={"attr/": {"external": external}})
  assert _plan(declaration, archives)


def test_central_order_can_differ_from_local_order():
  declaration, archives, unused = _fixture()
  raw = archives[declaration["wheels"][0]["source_id"]]
  offset = struct.unpack_from("<I", raw, len(raw) - 6)[0]
  cursor = offset
  records = []
  while cursor < len(raw) - 22:
    end = cursor + 46 + struct.unpack_from("<H", raw, cursor + 28)[0]
    records.append(raw[cursor:end])
    cursor = end
  raw = raw[:offset] + b"".join(reversed(records)) + raw[-22:]
  _archive_replace(declaration, archives, 0, raw)
  assert _plan(declaration, archives)


@pytest.mark.parametrize("raw_name", ["typing__extensions", "Typing.-Extensions"])
def test_repair_name_separator_runs_normalize_in_complete_wheel(raw_name):
  declaration, archives, originals = _fixture(8)
  row = declaration["wheels"][-1]
  row["metadata"]["name"] = raw_name
  def transform(files, row):
    files[row["dist_info"] + "/METADATA"] = _headers(row)[0]
  _rebuild(declaration, archives, originals, 6, transform=transform, method=8)
  bundle.validate_python_bundle_declaration(declaration)
  plan = _plan(declaration, archives)
  bundle.validate_python_bundle_inventory(declaration, plan["inventory_template"])
  assert row["metadata"]["name"] == raw_name


@pytest.mark.parametrize("raw_name", ["_typing_extensions", "typing_extensions_", ".typing_extensions", "typing_extensions.",
  "-typing_extensions", "typing_extensions-", "typing/extensions", "typing extensions", "typing:extensions", "typingéextensions"])
def test_repair_name_invalid_boundaries_remain_closed(raw_name):
  declaration, archives, originals = _fixture()
  row = declaration["wheels"][-1]
  row["metadata"]["name"] = raw_name
  def transform(files, row):
    files[row["dist_info"] + "/METADATA"] = _headers(row)[0]
  _rebuild(declaration, archives, originals, 6, transform=transform)
  _reject(bundle.validate_python_bundle_declaration, declaration)


def test_repair_name_normalizer_does_not_expand_requirement_head():
  declaration, unused, unused2 = _fixture()
  declaration["wheels"][4]["metadata"]["requires_dist"] = ["typing__extensions>=4.4.0"]
  _reject(bundle.validate_python_bundle_declaration, declaration)


@pytest.mark.parametrize("kind", ["extra-native", "many-native", "missing", "extra-foreign"])
def test_repair_artifact_count_rejects_before_keys_set_or_decode(kind, monkeypatch):
  declaration, archives, unused = _fixture()
  assert _plan(declaration, archives)
  artifacts = dict(archives)
  callbacks = {"hash": 0, "eq": 0, "repr": 0}
  class Key:
    armed = False
    def __hash__(self):
      if self.armed: callbacks["hash"] += 1
      return 1
    def __eq__(self, other):
      if self.armed: callbacks["eq"] += 1
      return self is other
    def __repr__(self):
      if self.armed: callbacks["repr"] += 1
      return "synthetic artifact key"
  if kind == "missing": artifacts.pop(declaration["wheels"][0]["source_id"])
  elif kind == "extra-foreign":
    key = Key()
    artifacts[key] = b"extra"
    key.armed = True
  else:
    artifacts.update({"extra-" + str(number): b"extra" for number in range(1 if kind == "extra-native" else 1000)})
  calls = {"key_walk": 0, "set": 0, "decode": 0}
  native_any, native_set = builtins.any, builtins.set
  def observed_any(values):
    # type() 不消费 iterator；记录 native dict key iterator 的实际启动。
    if type(values) is type((item for item in [])):
      iterator = values.gi_frame.f_locals.get(".0")
      if type(iterator) is type(iter({})):
        calls["key_walk"] += 1
    return native_any(values)
  def observed_set(values=()):
    if values is artifacts: calls["set"] += 1
    return native_set(values)
  def no_decode(*args):
    calls["decode"] += 1
    raise AssertionError("unexpected decode")
  monkeypatch.setattr(bundle, "any", observed_any, raising=False)
  monkeypatch.setattr(bundle, "set", observed_set, raising=False)
  monkeypatch.setattr(bundle, "_archive", no_decode)
  _reject(_plan, declaration, artifacts)
  assert calls == {"key_walk": 0, "set": 0, "decode": 0}
  assert callbacks == {"hash": 0, "eq": 0, "repr": 0}


@pytest.mark.parametrize("number", [-(2 ** 63) - 1, 2 ** 63, 2 ** 4096, -(2 ** 4096)])
def test_repair_integer_rejects_before_bad_inventory_encoding(number, monkeypatch):
  declaration, archives, unused = _fixture()
  plan = _plan(declaration, archives)
  inventory = copy.deepcopy(plan["inventory_template"])
  inventory["files"][0]["size"] = number
  calls = {"canonical": 0, "encoder": 0}
  canonical, encoder = bundle._canonical, bundle._ENCODER.iterencode
  def observed_canonical(value, cap):
    if value is inventory: calls["canonical"] += 1
    return canonical(value, cap)
  def observed_encoder(value):
    if value is inventory: calls["encoder"] += 1
    return encoder(value)
  monkeypatch.setattr(bundle, "_canonical", observed_canonical)
  monkeypatch.setattr(bundle._ENCODER, "iterencode", observed_encoder)
  bundle.validate_python_bundle_inventory(declaration, plan["inventory_template"])
  _reject(bundle.validate_python_bundle_inventory, declaration, inventory)
  assert calls == {"canonical": 0, "encoder": 0}


@pytest.mark.parametrize("number", [-(2 ** 63), 2 ** 63 - 1])
def test_repair_integer_generic_signed64_endpoints(number):
  # generic walk 允许边界；各正式字段继续用自己的更小整数范围。
  assert bundle._native({"value": number}) == 3
  declaration, archives, unused = _fixture()
  declaration["wheels"][0]["archive_size"] = number
  _reject(bundle.validate_python_bundle_declaration, declaration)


_DYNAMIC_FIELDS = ["Author", "Author-email", "Classifier", "Description", "Description-Content-Type", "Download-URL",
  "Home-page", "Keywords", "License", "License-Expression", "License-File", "Maintainer", "Maintainer-email",
  "Obsoletes-Dist", "Platform", "Project-URL", "Provides-Dist", "Provides-Extra", "Requires-Dist", "Requires-External",
  "Requires-Python", "Summary", "Supported-Platform"]


def _dynamic_rebuild(declaration, archives, originals, index, markers, *, member="METADATA", method=0):
  def transform(files, row):
    path = row["dist_info"] + "/" + member
    files[path] = markers + files[path]
  _rebuild(declaration, archives, originals, index, transform=transform, method=method)


def test_dynamic_pyyaml_and_operative_markers_preserve_decisions_and_hashes():
  declaration, archives, originals = _fixture(8)
  baseline = _plan(declaration, archives)
  _dynamic_rebuild(declaration, archives, originals, 3,
    b"Dynamic: author\nDynamic: author-email\nDynamic: classifier\nDynamic: home-page\nDynamic: license\nDynamic: platform\n", method=8)
  _dynamic_rebuild(declaration, archives, originals, 1,
    b"Dynamic: Requires-Dist\nDynamic: Requires-Python\nDynamic: Provides-Extra\nDynamic: License-Expression\nDynamic: License-File\n", method=8)
  plan = _plan(declaration, archives)
  assert plan["requirements"] == baseline["requirements"]
  assert plan["python_requirements"] == baseline["python_requirements"]
  assert len(plan["requirements"]) == 25
  assert sum(rule["active"] for rule in plan["requirements"]) == 8
  for row in declaration["wheels"]:
    for member in row["members"]:
      assert member["sha256"] == _sha(originals[row["name"]][member["path"]])
      planned = next(file for file in plan["files"] if file["source_id"] == row["source_id"] and file["member"] == member["path"])
      assert planned["sha256"] == member["sha256"]
  assert b"Dynamic" not in _canonical(plan)
  bundle.validate_python_bundle_inventory(declaration, plan["inventory_template"])


@pytest.mark.parametrize("field", _DYNAMIC_FIELDS)
@pytest.mark.parametrize("case", ["lower", "mixed"])
def test_dynamic_all_core_metadata_24_fields_and_duplicates(field, case):
  declaration, archives, originals = _fixture()
  value = field.lower() if case == "lower" else field.swapcase()
  _dynamic_rebuild(declaration, archives, originals, 0,
    ("dYnAmIc: " + value + "\nDynamic: " + value + "\n").encode())
  plan = _plan(declaration, archives)
  bundle.validate_python_bundle_inventory(declaration, plan["inventory_template"])


@pytest.mark.parametrize("marker", [b"Dynamic:\n", b"Dynamic: \n",
  b"Dynamic: author \n", b"Dynamic: author\t\n", b"Dynamic: author,email\n", b"Dynamic: author email\n",
  b"Dynamic: author\n continuation\n", b"Dynamic: author\n\tcontinuation\n", b"Dynamic: Dynamic\n",
  b"Dynamic: Name\n", b"Dynamic: Version\n", b"Dynamic: Metadata-Version\n", b"Dynamic: unknown\n",
  b"Dynamic: Import-Name\n", b"Dynamic: Import-Namespace\n", b"Dynamic: auth\xc3\xb6r\n", "Dynamic: Keywords\n".encode()])
def test_dynamic_malformed_identity_unknown_or_25_rejected(marker):
  declaration, archives, originals = _fixture()
  _dynamic_rebuild(declaration, archives, originals, 0, marker)
  _reject(_plan, declaration, archives)


@pytest.mark.parametrize("field", _DYNAMIC_FIELDS)
def test_dynamic_rejected_in_wheel(field):
  declaration, archives, originals = _fixture()
  _dynamic_rebuild(declaration, archives, originals, 0, ("Dynamic: " + field + "\n").encode(), member="WHEEL")
  _reject(_plan, declaration, archives)


@pytest.mark.parametrize("field,raw,changed", [
  ("Requires-Python", b"Requires-Python: >=3.9\n", b"Requires-Python: >=3.10\n"),
  ("Requires-Python", b"Requires-Python: >=3.9\n", b""),
  ("Requires-Dist", b"Requires-Dist: attrs>=22.2.0\n", b"Requires-Dist: attrs>=22.3.0\n"),
  ("Requires-Dist", b"Requires-Dist: attrs>=22.2.0\n", b""),
  ("Provides-Extra", b"Provides-Extra: format\n", b""),
  ("License-Expression", b"License-Expression: MIT\n", b"License-Expression: BSD\n"),
  ("License-Expression", b"License-Expression: MIT\n", b""),
  ("License-File", b"License-File: LICENSE\n", b""),
])
def test_dynamic_does_not_exempt_operative_matching(field, raw, changed):
  declaration, archives, originals = _fixture()
  def transform(files, row):
    path = row["dist_info"] + "/METADATA"
    assert raw in files[path]
    files[path] = ("Dynamic: " + field + "\n").encode() + files[path].replace(raw, changed)
  _rebuild(declaration, archives, originals, 1, transform=transform)
  _reject(_plan, declaration, archives)


@pytest.mark.parametrize("raw", ["attrs~=22.2.0", "attrs>=99.0.0"])
def test_dynamic_requires_dist_keeps_grammar_and_release_checks(raw):
  declaration, archives, originals = _fixture()
  row = declaration["wheels"][1]
  row["metadata"]["requires_dist"][0] = raw
  def transform(files, row):
    files[row["dist_info"] + "/METADATA"] = b"Dynamic: Requires-Dist\n" + _headers(row)[0]
  _rebuild(declaration, archives, originals, 1, transform=transform)
  _reject(_plan, declaration, archives)


@pytest.mark.parametrize("interface", ["declaration", "planner", "inventory"])
def test_metadata_license_fields_mutually_exclusive(interface):
  declaration, archives, originals = _fixture()
  inventory = _plan(declaration, archives)["inventory_template"]
  row = declaration["wheels"][0]
  row["metadata"]["legacy_license"] = "Synthetic legacy license"
  def transform(files, row):
    files[row["dist_info"] + "/METADATA"] = _headers(row)[0]
  _rebuild(declaration, archives, originals, 0, transform=transform)
  if interface == "declaration":
    _reject(bundle.validate_python_bundle_declaration, declaration)
  elif interface == "planner":
    _reject(_plan, declaration, archives)
  else:
    # 独立更新完整 claimed inventory，避免靠无关 hash 漂移拒绝。
    inventory["declaration_digest"] = _sha(_canonical(declaration))
    for file in inventory["files"]:
      member = next(member for item in declaration["wheels"] if item["source_id"] == file["source_id"]
                    for member in item["members"] if member["path"] == file["member"])
      file.update(size=member["size"], sha256=member["sha256"])
    inventory["stats"]["raw_bytes"] = sum(item["archive_size"] for item in declaration["wheels"])
    inventory["stats"]["file_bytes"] = sum(member["size"] for item in declaration["wheels"] for member in item["members"])
    _reject(bundle.validate_python_bundle_inventory, declaration, inventory)


@pytest.mark.parametrize("expression,legacy", [("MIT", None), (None, "Synthetic legacy license"), (None, None)])
def test_metadata_license_nullable_alternatives(expression, legacy):
  declaration, archives, originals = _fixture()
  row = declaration["wheels"][0]
  row["metadata"].update(license_expression=expression, legacy_license=legacy)
  def transform(files, row):
    files[row["dist_info"] + "/METADATA"] = b"Dynamic: License\nDynamic: License-Expression\n" + _headers(row)[0]
  _rebuild(declaration, archives, originals, 0, transform=transform)
  bundle.validate_python_bundle_declaration(declaration)
  plan = _plan(declaration, archives)
  bundle.validate_python_bundle_inventory(declaration, plan["inventory_template"])


@pytest.mark.parametrize("separator", ["", " ", "  ", "\t"])
def test_dynamic_uses_existing_header_separator_grammar(separator):
  declaration, archives, originals = _fixture()
  _dynamic_rebuild(declaration, archives, originals, 0, ("Dynamic:" + separator + "Author\n").encode())
  _plan(declaration, archives)


@pytest.mark.parametrize("method", [0, 8])
def test_dynamic_twelve_pyyaml_markers_with_original_offline_guards(method, monkeypatch):
  import os
  import pathlib
  import subprocess
  declaration, archives, originals = _fixture(method)
  fields = ["author", "author-email", "classifier", "description", "download-url", "home-page", "license", "license-file",
    "platform", "project-url", "requires-python", "summary"]
  _dynamic_rebuild(declaration, archives, originals, 3, "".join("Dynamic: " + field + "\n" for field in fields).encode(), method=method)
  assert declaration["wheels"][3]["metadata"]["legacy_license"] == "MIT"
  assert declaration["wheels"][3]["metadata"]["license_expression"] is None
  before = copy.deepcopy((declaration, archives))
  def prohibited(*args, **kwargs): raise AssertionError("pure API attempted IO")
  with monkeypatch.context() as patch:
    for target, attribute in ((builtins, "open"), (pathlib.Path, "open"), (pathlib.Path, "read_bytes"),
                              (os, "getenv"), (os, "stat"), (subprocess, "run")):
      patch.setattr(target, attribute, prohibited)
    patch.setattr(os, "environ", ForeignDict())
    patch.setattr(builtins, "__import__", prohibited)
    bundle.validate_python_bundle_declaration(declaration)
    plan = _plan(declaration, archives)
    assert plan == _plan(declaration, archives)
    bundle.validate_python_bundle_inventory(declaration, plan["inventory_template"])
  assert (declaration, archives) == before
  path = declaration["wheels"][3]["dist_info"] + "/METADATA"
  def transform(files, row):
    assert b"Requires-Python: >=3.9\n" in files[path]
    files[path] = files[path].replace(b"Requires-Python: >=3.9\n", b"Requires-Python: >=3.10\n")
  _rebuild(declaration, archives, originals, 3, transform=transform, method=method)
  _reject(_plan, declaration, archives)


@pytest.mark.parametrize("cap", ["header_lines", "header_line_bytes"])
def test_dynamic_retains_original_header_caps(cap, monkeypatch):
  declaration, archives, originals = _fixture()
  markers = b"Dynamic: Author\n" * 100 if cap == "header_lines" else b"Dynamic:" + b" " * 300 + b"Author\n"
  _dynamic_rebuild(declaration, archives, originals, 0, markers)
  headers = [raw.split(b"\n\n", 1)[0].splitlines() for files in originals.values()
             for path, raw in files.items() if path.endswith(("/METADATA", "/WHEEL"))]
  boundary = max(len(lines) + 1 for lines in headers) if cap == "header_lines" else max(len(line) for lines in headers for line in lines)
  monkeypatch.setitem(bundle._CAPS, cap, boundary)
  assert _plan(declaration, archives)
  monkeypatch.setitem(bundle._CAPS, cap, boundary - 1)
  _reject(_plan, declaration, archives)


@pytest.mark.parametrize("field", ["Requires-External", "Provides-Dist", "Obsoletes-Dist"])
def test_dynamic_does_not_permit_other_forbidden_actual_headers(field):
  declaration, archives, originals = _fixture()
  _dynamic_rebuild(declaration, archives, originals, 0,
    ("Dynamic: " + field + "\n" + field + ": foreign\n").encode())
  _reject(_plan, declaration, archives)
