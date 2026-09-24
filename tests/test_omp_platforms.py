"""平台选择是隔离证据，不代替各平台宿主验收。"""

import pytest

from agentcfg import omp_dependencies as dep
from agentcfg.process import DependencyError
from test_omp_dependencies_foundation import locked


@pytest.mark.parametrize("system,machine,libc,expected", [
  ("linux", "x86_64", "glibc", "linux-x64"),
  ("linux", "aarch64", "glibc", "linux-arm64"),
  ("darwin", "x86_64", "", "macos-x64"),
  ("darwin", "arm64", "", "macos-arm64"),
])
def test_four_platform_asset_selection(locked, monkeypatch, system, machine, libc, expected):
  workspace, _, _, content = locked
  monkeypatch.setattr(dep.sys, "platform", system)
  monkeypatch.setattr(dep.platform, "machine", lambda: machine)
  monkeypatch.setattr(dep.platform, "libc_ver", lambda: (libc, "fixture"))
  backend = dep.OmpBackend()
  lock = backend.read_lock(workspace.repository)
  identity = backend.sync(workspace, lock)["identity"]
  assert identity == lock.identity + "-" + expected
  assert backend.status(workspace, identity) == "installed"
  assert (backend.root(workspace, identity) / "bin/omp").read_bytes() == content


@pytest.mark.parametrize("system,libc", [("linux", "musl"), ("win32", ""), ("freebsd", "")])
def test_unsupported_platform_cannot_use_global_omp(locked, monkeypatch, system, libc):
  workspace, _, _, _ = locked
  monkeypatch.setattr(dep.sys, "platform", system)
  monkeypatch.setattr(dep.platform, "machine", lambda: "x86_64")
  monkeypatch.setattr(dep.platform, "libc_ver", lambda: (libc, "fixture"))
  monkeypatch.setattr(dep.shutil, "which", lambda _: pytest.fail("global host fallback forbidden"))
  backend = dep.OmpBackend()
  with pytest.raises(DependencyError) as error:
    backend.sync(workspace, backend.read_lock(workspace.repository))
  assert error.value.exit_code == 5
  assert not (workspace.cache / "runtimes").exists()
  assert not workspace.instance.exists()
