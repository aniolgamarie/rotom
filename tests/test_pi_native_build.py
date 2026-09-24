"""记录工具链构建身份不等于native通过；编译器只使用替身。"""

from pathlib import Path
import hashlib
import pytest

from agentcfg.pi_native_build import build_macos_helper
from agentcfg.process import DependencyError


ROOT = Path(__file__).resolve().parents[1]


def test_helper_build_records_source_compiler_sdk_and_output_identity(tmp_path):
  calls = []
  def run(argv, *, cwd, env):
    calls.append(argv)
    assert Path(env["HOME"]).is_relative_to(tmp_path)
    if argv == ["/usr/bin/clang", "--version"]:
      return "Apple clang version 17.0.0 (clang-1700.0.1)"
    if argv == ["/usr/bin/xcrun", "--show-sdk-version"]:
      return "26.0"
    if argv == ["/usr/bin/xcrun", "--show-sdk-path"]:
      return "/synthetic-sdk"
    assert argv[0] == "/usr/bin/clang" and "-Werror" in argv
    Path(argv[-1]).write_bytes(b"synthetic helper, never execute")
    return ""
  output = tmp_path / "build/helper"
  record = build_macos_helper(ROOT, output, run=run, platform="darwin")
  assert record["native_verification"] == "not-run"
  assert record["helper_digest"] == hashlib.sha256(output.read_bytes()).hexdigest()
  assert record["sdk_version"] == "26.0"
  assert len(calls) == 4


def test_missing_platform_does_not_produce_a_support_claim(tmp_path):
  with pytest.raises(DependencyError):
    build_macos_helper(ROOT, tmp_path / "helper", platform="linux")
  assert not (tmp_path / "helper").exists()


@pytest.mark.parametrize("platform", ["darwin-arm64", "darwin-x86_64"])
def test_platform_installation_builds_and_checks_the_requested_helper_architecture(tmp_path, platform):
  from agentcfg.pi_native_build import install_platform_helpers
  from test_pi_assets import executable
  from agentcfg.storage import Tree, ensure_private
  stage = tmp_path / "stage"; ensure_private(stage)
  calls = []
  def build(repository, output, **kwargs):
    calls.append(kwargs)
    with Tree(stage) as tree: tree.replace("bin/pi-supervisor-macos", executable(platform), mode=0o700, expected=None)
  install_platform_helpers(ROOT, stage, platform, build=build)
  assert calls == [{"platform": "darwin", "architecture": platform.split("-", 1)[1]}]
  install_platform_helpers(ROOT, stage, "linux-x86_64", build=lambda *_a, **_k: pytest.fail("must not build macOS on Linux"))


def test_platform_installation_does_not_accept_another_architecture(tmp_path):
  from agentcfg.pi_native_build import install_platform_helpers
  from test_pi_assets import executable
  from agentcfg.storage import Tree, ensure_private
  stage = tmp_path / "stage"; ensure_private(stage)
  def build(*_args, **_kwargs):
    with Tree(stage) as tree: tree.replace("bin/pi-supervisor-macos", executable("darwin-arm64"), mode=0o700, expected=None)
  with pytest.raises(DependencyError): install_platform_helpers(ROOT, stage, "darwin-x86_64", build=build)
