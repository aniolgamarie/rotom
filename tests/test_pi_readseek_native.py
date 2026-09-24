"""只检查假 ELF/Mach-O 和许可投影；绝不执行原生发行物。"""
import hashlib
import json

import pytest

from agentcfg.deployment import json_bytes
from agentcfg.pi_readseek_native import install_native, PACKAGES
from agentcfg.process import DependencyError
from agentcfg.storage import Tree


def fixture(tmp_path, platform="linux-x86_64"):
  repo, stage = tmp_path / "repo", tmp_path / "stage"
  package = PACKAGES[platform]
  raw = bytearray(64)
  if platform.startswith("linux"):
    raw[:6] = b"\x7fELF\x02\x01"; raw[16:18] = (2).to_bytes(2, "little")
    raw[18:20] = (62 if platform.endswith("x86_64") else 183).to_bytes(2, "little")
  else:
    raw[:4] = b"\xcf\xfa\xed\xfe"; raw[4:8] = (0x100000c).to_bytes(4, "little"); raw[12:16] = (2).to_bytes(4, "little")
  with Tree(repo, create=True) as tree:
    tree.write_new("agents/pi/build/licenses/readseek/LICENSE.native", b"synthetic license")
    tree.write_new("agents/pi/build/licenses/readseek/SOURCE.json", json_bytes({"sha256": hashlib.sha256(b"synthetic license").hexdigest()}))
  with Tree(stage, create=True) as tree:
    tree.write_new("profile/node_modules/@jarkkojs/readseek-api/package.json", json_bytes({"version": "0.9.16"}))
    tree.write_new("profile/node_modules/" + package + "/package.json", json_bytes({"name": package, "version": "0.9.16",
      "os": [platform.split("-")[0]], "cpu": ["x64" if platform.endswith("x86_64") else "arm64"]}))
    tree.write_new("profile/node_modules/" + package + "/bin/readseek", bytes(raw))
  return repo, stage, {"package_path": "profile/package.json"}


@pytest.mark.parametrize("platform", list(PACKAGES))
def test_native_projection_binds_the_declared_platform_without_claiming_execution(tmp_path, platform):
  repo, stage, piece = fixture(tmp_path, platform)
  install_native(repo, stage, piece, platform)
  receipt = json.loads((stage / "runtime/readseek-native.json").read_text())
  assert receipt["native_verification"] == "not-run" and receipt["platform"] == platform
  assert (stage / "bin/readseek").stat().st_mode & 0o777 == 0o700
  assert (stage / "licenses/readseek/LICENSE.native").read_bytes() == b"synthetic license"


@pytest.mark.parametrize("kind", ["wrong-arch", "wrong-version", "missing", "license", "unbuilt-macos-x86"])
def test_invalid_native_dependencies_do_not_produce_an_executable_projection(tmp_path, kind):
  repo, stage, piece = fixture(tmp_path)
  root = stage / "profile/node_modules/@jarkkojs/readseek-linux-x64"
  platform = "linux-x86_64"
  if kind == "wrong-arch":
    raw = bytearray((root / "bin/readseek").read_bytes()); raw[18:20] = (183).to_bytes(2, "little"); (root / "bin/readseek").write_bytes(raw)
  if kind == "wrong-version":
    metadata = json.loads((root / "package.json").read_text()); metadata["version"] = "0.9.17"; (root / "package.json").write_text(json.dumps(metadata))
  if kind == "missing": (root / "bin/readseek").unlink()
  if kind == "license": (repo / "agents/pi/build/licenses/readseek/LICENSE.native").write_bytes(b"changed")
  if kind == "unbuilt-macos-x86": platform = "darwin-x86_64"
  with pytest.raises(DependencyError): install_native(repo, stage, piece, platform)
  assert not (stage / "bin/readseek").exists()
