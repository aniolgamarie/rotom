"""构建输入的离线结构边界；所有摘要与缓存均为虚构测试材料。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from agentcfg.omp_permission_build_inputs import BuildInputUnavailable, read_build_input_lock, verify_build_inputs
from agentcfg.schema import ConfigError


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/omp-permission-build-inputs.schema.json"


def build_inputs():
  return {
    "schemaVersion": 1,
    "platform": "linux-x64",
    "upstreamSource": {"commit": "a" * 40, "archiveSha256": "b" * 64},
    "dependencyLock": {"path": "bun.lock", "sha256": "c" * 64},
    "tools": [{"name": "bun", "version": "1.4.0", "cacheKey": "sha256/" + "d" * 64,
      "sha256": "d" * 64}],
    "dependencyArtifacts": [{"cacheKey": "sha256/" + "e" * 64, "sha256": "e" * 64, "size": 42}],
  }


def validator():
  schema = json.loads(SCHEMA.read_text())
  Draft202012Validator.check_schema(schema)
  return Draft202012Validator(schema)


def test_build_input_schema_accepts_complete_synthetic_document():
  validator().validate(build_inputs())


@pytest.mark.parametrize("location", [(), ("upstreamSource",), ("dependencyLock",),
  ("tools", 0), ("dependencyArtifacts", 0)])
def test_build_input_schema_rejects_unknown_fields(location):
  value = build_inputs()
  obj = value
  for key in location:
    obj = obj[key]
  obj["unrecognized"] = "secret-sentinel"
  assert not validator().is_valid(value)


@pytest.mark.parametrize("field", ["schemaVersion", "platform", "upstreamSource", "dependencyLock",
  "tools", "dependencyArtifacts"])
def test_build_input_schema_requires_complete_envelope(field):
  value = build_inputs()
  del value[field]
  assert not validator().is_valid(value)


@pytest.mark.parametrize("path", ["/tmp/tool", "../tool", "a/../../tool", "a\\tool", "C:/tool", "./bun.lock", "bun.lock\n"])
def test_build_input_schema_rejects_escaping_dependency_lock_path(path):
  value = build_inputs()
  value["dependencyLock"]["path"] = path
  assert not validator().is_valid(value)


@pytest.mark.parametrize("key", ["/tmp/tool", "../tool", "sha256/../tool", "latest", "sha256/" + "g" * 64])
def test_build_input_schema_requires_content_addressed_cache_keys(key):
  value = build_inputs()
  value["tools"][0]["cacheKey"] = key
  assert not validator().is_valid(value)


@pytest.mark.parametrize("field,bad", [("tools", []), ("dependencyArtifacts", []),
  ("platform", "darwin-arm64"), ("schemaVersion", True)])
def test_build_input_schema_rejects_incomplete_or_unsupported_inputs(field, bad):
  value = build_inputs()
  value[field] = deepcopy(bad)
  assert not validator().is_valid(value)


@pytest.fixture
def input_materials(tmp_path):
  value = build_inputs()
  source = tmp_path / "source.tar.gz"
  source.write_bytes(b"synthetic source archive")
  lock = tmp_path / "bun.lock"
  lock.write_bytes(b"synthetic dependency lock")
  value["upstreamSource"]["archiveSha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
  value["dependencyLock"]["sha256"] = hashlib.sha256(lock.read_bytes()).hexdigest()
  for collection, directory in (("tools", "tools"), ("dependencyArtifacts", "dependencies")):
    data = ("synthetic " + collection).encode()
    digest = hashlib.sha256(data).hexdigest()
    item = value[collection][0]
    item.update(cacheKey="sha256/" + digest, sha256=digest)
    if collection == "dependencyArtifacts":
      item["size"] = len(data)
    path = tmp_path / directory / item["cacheKey"]
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
  inputs = tmp_path / "inputs.json"
  inputs.write_text(json.dumps(value))
  args = {"source_archive": source, "dependency_lock": lock,
    "tool_cache": tmp_path / "tools", "dependency_cache": tmp_path / "dependencies"}
  return inputs, value, args


def test_input_materials_are_read_without_running_fake_tool(input_materials):
  path, _, args = input_materials
  value = read_build_input_lock(path, json.loads(SCHEMA.read_text()))
  report = verify_build_inputs(value, **args)
  assert report["toolCount"] == report["dependencyArtifactCount"] == 1
  assert report["toolBytes"] > 0 and report["dependencyBytes"] > 0


@pytest.mark.parametrize("field", ["source_archive", "dependency_lock"])
def test_changed_source_or_dependency_lock_fails(input_materials, field):
  _, value, args = input_materials
  args[field].write_bytes(b"changed secret-sentinel")
  with pytest.raises(BuildInputUnavailable, match="bytes-mismatch") as error:
    verify_build_inputs(value, **args)
  assert error.value.exit_code == 5
  assert "secret-sentinel" not in str(error.value)


@pytest.mark.parametrize("change", ["bytes", "size", "extra", "missing", "symlink", "ancestor-link"])
def test_dependency_cache_boundary(input_materials, change, tmp_path):
  _, value, args = input_materials
  item = value["dependencyArtifacts"][0]
  path = args["dependency_cache"] / item["cacheKey"]
  if change == "bytes":
    path.write_bytes(b"tampered")
  elif change == "size":
    item["size"] += 1
  elif change == "extra":
    path.with_name("f" * 64).write_bytes(b"undeclared")
  elif change == "missing":
    path.unlink()
  elif change == "symlink":
    other = tmp_path / "not-a-cache-file"
    path.rename(other)
    path.symlink_to(other)
  else:
    other = tmp_path / "redirected"
    args["dependency_cache"].rename(other)
    args["dependency_cache"].symlink_to(other, target_is_directory=True)
  with pytest.raises(BuildInputUnavailable):
    verify_build_inputs(value, **args)


@pytest.mark.parametrize("change", ["duplicate-key", "duplicate-tool", "missing-bun", "wrong-key", "duplicate-asset"])
def test_input_lock_rejects_ambiguous_identity(input_materials, change):
  path, value, _ = input_materials
  if change == "duplicate-key":
    path.write_text('{"schemaVersion": 1, "schemaVersion": 1}')
  else:
    if change == "duplicate-tool":
      other = deepcopy(value["tools"][0])
      other["version"] = "another-version"
      value["tools"].append(other)
    elif change == "missing-bun":
      value["tools"][0]["name"] = "another-tool"
    elif change == "wrong-key":
      value["tools"][0]["cacheKey"] = "sha256/" + "f" * 64
    else:
      other = deepcopy(value["dependencyArtifacts"][0])
      other["size"] += 1
      value["dependencyArtifacts"].append(other)
    path.write_text(json.dumps(value))
  with pytest.raises(ConfigError) as error:
    read_build_input_lock(path, json.loads(SCHEMA.read_text()))
  assert error.value.exit_code == 2


def test_offline_patch_requires_exact_context_before_any_write(tmp_path):
  from agentcfg.omp_permission_build import apply_patch_bytes
  root = tmp_path / "source"
  root.mkdir()
  target = root / "example.ts"
  target.write_bytes(b"first\nold\nlast\n")
  patch = b"--- a/example.ts\n+++ b/example.ts\n@@ -1,3 +1,3 @@\n first\n-old\n+new\n last\n"
  apply_patch_bytes(root, patch)
  assert target.read_bytes() == b"first\nnew\nlast\n"
  with pytest.raises(BuildInputUnavailable): apply_patch_bytes(root, patch)
  assert target.read_bytes() == b"first\nnew\nlast\n"


@pytest.mark.parametrize("name,kind,link", [("../outside", "file", ""),
  ("/absolute", "file", ""), ("link", "link", "../outside"),
  ("device", "device", ""), ("link", "link", "/tmp/outside"),
  ("hard", "hardlink", "../outside")])
def test_offline_archive_rejects_escape_before_extract(tmp_path, name, kind, link):
  import io
  import tarfile
  from agentcfg.omp_permission_build import extract_inputs
  archive = tmp_path / "inputs.tar"
  with tarfile.open(archive, "w") as tar:
    entry = tarfile.TarInfo(name)
    entry.size = 0
    if kind == "link": entry.type, entry.linkname = tarfile.SYMTYPE, link
    elif kind == "hardlink": entry.type, entry.linkname = tarfile.LNKTYPE, link
    elif kind == "device": entry.type = tarfile.CHRTYPE
    tar.addfile(entry, io.BytesIO())
  root = tmp_path / "output"
  root.mkdir()
  with pytest.raises(BuildInputUnavailable): extract_inputs(archive, root)
  assert list(root.iterdir()) == []


def test_offline_archive_allows_workspace_relative_package_link(tmp_path):
  import io
  import tarfile
  from agentcfg.omp_permission_build import extract_inputs
  archive = tmp_path / "inputs.tar"
  with tarfile.open(archive, "w") as tar:
    entry = tarfile.TarInfo("packages/example/index.ts")
    entry.size = 5
    tar.addfile(entry, io.BytesIO(b"test\n"))
    entry = tarfile.TarInfo("node_modules/example")
    entry.type, entry.linkname = tarfile.SYMTYPE, "../packages/example"
    tar.addfile(entry)
  root = tmp_path / "output"
  root.mkdir()
  extract_inputs(archive, root)
  assert (root / "node_modules/example/index.ts").read_bytes() == b"test\n"


def test_offline_archive_accepts_internal_package_hardlinks(tmp_path):
  import io
  import tarfile
  from agentcfg.omp_permission_build import extract_inputs
  archive = tmp_path / "inputs.tar"
  with tarfile.open(archive, "w") as tar:
    entry = tarfile.TarInfo("node_modules/one/index.js")
    entry.size = 5
    tar.addfile(entry, io.BytesIO(b"test\n"))
    entry = tarfile.TarInfo("node_modules/two/index.js")
    entry.type, entry.linkname = tarfile.LNKTYPE, "node_modules/one/index.js"
    tar.addfile(entry)
  root = tmp_path / "output"
  root.mkdir()
  extract_inputs(archive, root)
  assert (root / "node_modules/two/index.js").read_bytes() == b"test\n"


def build_module():
  import importlib.util
  spec = importlib.util.spec_from_file_location("permission_build_test_entry", ROOT / "agents/omp/build-permission-control.py")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_retired_builder_entrypoint_does_not_read_materials(monkeypatch, capsys):
  module = build_module()
  monkeypatch.setattr(module, "build", lambda *_args, **_kwargs:
    pytest.fail("retired entrypoint must not invoke the historical builder"))
  monkeypatch.setattr(module.argparse.ArgumentParser, "parse_args", lambda *_args, **_kwargs:
    pytest.fail("retired entrypoint must not parse material paths"))

  assert module.main() == 2
  assert capsys.readouterr().err == "omp-host-patching-retired\n"


@pytest.mark.parametrize("change", ["bytes", "extra", "missing"])
def test_builder_rejects_invalid_material_before_process_or_output(input_materials, monkeypatch, tmp_path, change):
  from types import SimpleNamespace
  module = build_module()
  path, value, supplied = input_materials
  repository = tmp_path / "repository"
  (repository / "schemas").mkdir(parents=True)
  (repository / "schemas/omp-permission-build-inputs.schema.json").write_bytes(SCHEMA.read_bytes())
  (repository / "bun.lock").write_bytes(supplied["dependency_lock"].read_bytes())
  monkeypatch.setattr(module, "REPOSITORY", repository)
  entry = supplied["dependency_cache"] / value["dependencyArtifacts"][0]["cacheKey"]
  if change == "bytes": entry.write_bytes(b"changed")
  elif change == "extra": entry.with_name("f" * 64).write_bytes(b"undeclared")
  else: entry.unlink()
  calls = []
  monkeypatch.setattr(module, "run_bun", lambda *a, **k: calls.append(a))
  output = tmp_path / "artifacts"
  args = SimpleNamespace(build_inputs_lock=path, platform="linux-x64", source=supplied["source_archive"],
    tool_cache=supplied["tool_cache"], dependency_cache=supplied["dependency_cache"], artifact_cache=output)
  with pytest.raises(BuildInputUnavailable): module.build(args)
  assert calls == []
  assert not output.exists()


def test_builder_process_has_no_shell_or_environment_inheritance(monkeypatch, tmp_path):
  from types import SimpleNamespace
  module = build_module()
  observed = []
  def run(command, **kwargs):
    observed.append((command, kwargs))
    return SimpleNamespace(returncode=0, stdout=b"1.4.0\n")
  monkeypatch.setattr(module.subprocess, "run", run)
  env = {"HOME": str(tmp_path), "PATH": ""}
  assert module.run_bun(tmp_path / "bun", ["--version"], tmp_path, env) == b"1.4.0\n"
  command, kwargs = observed[0]
  assert command == [str(tmp_path / "bun"), "--version"]
  assert kwargs["env"] == env
  assert kwargs["preexec_fn"] is module.deny_network
  assert not kwargs.get("shell", False)


def test_builder_process_failure_does_not_copy_raw_error(monkeypatch, tmp_path):
  from types import SimpleNamespace
  module = build_module()
  monkeypatch.setattr(module.subprocess, "run", lambda *a, **k:
    SimpleNamespace(returncode=1, stdout=b"secret-sentinel", stderr=b"secret-sentinel"))
  with pytest.raises(BuildInputUnavailable) as error:
    module.run_bun(tmp_path / "bun", [], tmp_path, {})
  assert "secret-sentinel" not in str(error.value)
@pytest.mark.parametrize("damage", ["missing", "symlink", "parent-link", "existing"])
def test_permission_core_staging_rejects_missing_links_and_overwrites(tmp_path, damage):
  from agentcfg.omp_permission_build import PERMISSION_CORE_FILES, stage_permission_core
  plugin, source = tmp_path / "plugin", tmp_path / "source"
  plugin.mkdir()
  source.mkdir()
  for name in PERMISSION_CORE_FILES:
    (plugin / name).write_text("export {};\n")
  target = source / "packages/coding-agent/src/permission-control/core"
  if damage == "missing":
    (plugin / "controller.ts").unlink()
  elif damage == "symlink":
    (plugin / "controller.ts").unlink()
    (plugin / "controller.ts").symlink_to(plugin / "types.ts")
  elif damage == "parent-link":
    (source / "packages").symlink_to(plugin, target_is_directory=True)
  else:
    target.mkdir(parents=True)
    (target / "controller.ts").write_text("sentinel")
  with pytest.raises(BuildInputUnavailable):
    stage_permission_core(plugin, source)
  assert not (target / "types.ts").exists()
  if damage == "existing":
    assert (target / "controller.ts").read_text() == "sentinel"


def test_permission_core_staging_copies_only_declared_bytes_without_loading(tmp_path):
  from agentcfg.omp_permission_build import PERMISSION_CORE_FILES, stage_permission_core
  plugin, source = tmp_path / "plugin", tmp_path / "source"
  plugin.mkdir()
  source.mkdir()
  for name in (*PERMISSION_CORE_FILES, "index.ts"):
    (plugin / name).write_text(f'throw Error("{name}");\n')
  stage_permission_core(plugin, source)
  target = source / "packages/coding-agent/src/permission-control/core"
  assert sorted(p.name for p in target.iterdir()) == sorted(PERMISSION_CORE_FILES)
  for name in PERMISSION_CORE_FILES:
    assert (target / name).read_bytes() == (plugin / name).read_bytes()
