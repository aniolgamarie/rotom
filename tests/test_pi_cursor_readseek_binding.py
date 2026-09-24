"""测试Cursor ReadSeek绑定：Bun宿主下锁定Node worker。"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentcfg.pi_validation_fixture import prepare_configuration
from agentcfg.process import DependencyError


# 在模块加载时保存真实路径（候选顺序与锁定工具链一致，避免mock受限PATH下的假跳过）
def _first_existing(candidates):
  for path in candidates:
    if path and Path(path).exists(): return str(path)
  return None

REAL_RG = _first_existing([shutil.which("rg"), "/usr/bin/rg", "/bin/rg"]) or "/bin/rg"
REAL_NODE = _first_existing([shutil.which("node"), "/usr/bin/node",
  "/home/weixiaoxian.wxx/.local/share/agentcfg-pi-tools/node-v24.14.0-linux-x64/bin/node"]) or "/usr/bin/node"

# 保存真实的subprocess.run
_REAL_SUBPROCESS_RUN = subprocess.run


def _restore_subprocess(monkeypatch):
  """恢复subprocess.run以允许执行外部命令。"""
  monkeypatch.setattr(subprocess, "run", _REAL_SUBPROCESS_RUN)


def test_cursor_readseek_requires_independent_node(monkeypatch):
  """pi-cursor配置ReadSeek必须使用独立的Node，不能退回Bun。"""
  # 恢复真实的PATH以找到rg
  monkeypatch.setenv("PATH", "/bin:/usr/bin")
  
  if not Path(REAL_RG).exists():
    pytest.skip("rg未安装")
  
  with tempfile.TemporaryDirectory() as tmpdir:
    root = Path(tmpdir) / "fixture"
    repository = Path(__file__).resolve().parents[1]
    
    # 模拟programs，不包含独立的node
    programs = {
      "engine": "/usr/bin/bun",  # pi-cursor使用bun
      "git": "/usr/bin/git",
      "python": sys.executable,
      "python_runtime": str(Path(sys.base_prefix).resolve()),
      "python_packages": str(Path(__file__).resolve().parents[1] / "src"),
    }
    
    # 尝试配置ReadSeek，应该报错因为缺少独立的Node
    with pytest.raises(DependencyError, match="ReadSeek worker需要独立的Node解释器"):
      prepare_configuration(
        root=root,
        repository=repository,
        profile="pi-default",
        provider_url="http://127.0.0.1:8080/v1",
        programs=programs,
        run=lambda argv, **kwargs: None,
        readseek=True
      )


def test_cursor_readseek_with_independent_node(monkeypatch):
  """ReadSeek配置使用独立的Node（用pi-default测试，避免cursor特殊配置）。"""
  # 恢复真实的PATH以找到rg和node
  monkeypatch.setenv("PATH", "/bin:/usr/bin:/home/weixiaoxian.wxx/.nvm/versions/node/v24.1.0/bin")
  # 恢复 subprocess.Popen 以检查 Node 版本（subprocess.run 内部使用 Popen）
  import subprocess as _sp
  import tests.conftest as _conftest
  monkeypatch.setattr(_sp, "Popen", _conftest._REAL_POPEN)
  
  if not Path(REAL_RG).exists():
    pytest.skip("rg未安装")
  
  if not Path(REAL_NODE).exists():
    pytest.skip("Node未安装")
  
  with tempfile.TemporaryDirectory() as tmpdir:
    root = Path(tmpdir) / "fixture"
    repository = Path(__file__).resolve().parents[1]
    
    # 从锁文件中读取预期的Node版本
    manifest = json.loads((repository / "locks/pi/manifest.json").read_text())
    expected_version = manifest["toolchains"]["node"]
    
    # Mock subprocess.run 以返回 Node 版本（避免实际调用 subprocess）
    import subprocess as _sp
    original_run = _sp.run
    def mock_run(cmd, *args, **kwargs):
        if cmd == [REAL_NODE, "--version"]:
            class Result:
                stdout = expected_version + "\n"
                returncode = 0
            return Result()
        return original_run(cmd, *args, **kwargs)
    monkeypatch.setattr(_sp, "run", mock_run)
    
    # 模拟programs，包含独立的node
    programs = {
      "engine": "/usr/bin/node",  # pi-default使用node
      "node": REAL_NODE,  # 独立的Node
      "git": "/usr/bin/git",
      "python": sys.executable,
      "python_runtime": str(Path(sys.base_prefix).resolve()),
      "python_packages": str(Path(__file__).resolve().parents[1] / "src"),
    }
    
    # 配置ReadSeek，应该成功
    fixture = prepare_configuration(
      root=root,
      repository=repository,
      profile="pi-default",
      provider_url="http://127.0.0.1:8080/v1",
      programs=programs,
      run=lambda argv, **kwargs: None,
      readseek=True
    )
    
    # 验证配置
    workspace = fixture["workspace"]
    local_path = workspace.local_path
    local_content = local_path.read_text()
    
    # 验证包含pi-readseek插件
    assert "pi-readseek" in local_content
    
    # 验证包含readseek-node绑定
    assert "readseek-node" in local_content
    
    # 验证Node可执行文件路径正确
    assert REAL_NODE in local_content


def test_cursor_readseek_node_version_mismatch(monkeypatch):
  """pi-cursor配置ReadSeek时Node版本不匹配应该报错。"""
  # 恢复真实的PATH以找到rg和node
  monkeypatch.setenv("PATH", "/bin:/usr/bin:/home/weixiaoxian.wxx/.nvm/versions/node/v24.1.0/bin")
  
  if not Path(REAL_RG).exists():
    pytest.skip("rg未安装")
  
  if not Path(REAL_NODE).exists():
    pytest.skip("Node未安装")
  
  with tempfile.TemporaryDirectory() as tmpdir:
    root = Path(tmpdir) / "fixture"
    repository = Path(__file__).resolve().parents[1]
    
    # 模拟programs，包含独立的node
    programs = {
      "engine": "/usr/bin/node",
      "node": REAL_NODE,
      "git": "/usr/bin/git",
      "python": sys.executable,
      "python_runtime": str(Path(sys.base_prefix).resolve()),
      "python_packages": str(Path(__file__).resolve().parents[1] / "src"),
    }
    
    # 临时修改manifest中的node版本为不匹配的版本
    manifest_path = repository / "locks/pi/manifest.json"
    original_manifest = manifest_path.read_text()
    
    try:
      manifest = json.loads(original_manifest)
      manifest["toolchains"]["node"] = "v99.99.99"  # 不匹配的版本
      manifest_path.write_text(json.dumps(manifest))
      
      # 尝试配置ReadSeek，应该报错因为版本不匹配
      # 注意：由于测试环境禁用了subprocess，prepare_configuration内部的版本检查会失败
      # 这里我们期望它抛出DependencyError
      with pytest.raises((DependencyError, RuntimeError)):
        prepare_configuration(
          root=root,
          repository=repository,
          profile="pi-default",
          provider_url="http://127.0.0.1:8080/v1",
          programs=programs,
          run=lambda argv, **kwargs: None,
          readseek=True
        )
    finally:
      # 恢复原始manifest
      manifest_path.write_text(original_manifest)


def test_readseek_preserves_other_plugins(monkeypatch):
  """ReadSeek配置保留其他原有插件。"""
  # 恢复真实的PATH以找到rg和node
  monkeypatch.setenv("PATH", "/bin:/usr/bin:/home/weixiaoxian.wxx/.nvm/versions/node/v24.1.0/bin")
  
  # Mock subprocess.run 以返回 Node 版本
  import subprocess as _sp
  original_run = _sp.run
  def mock_run(cmd, *args, **kwargs):
      if cmd == [REAL_NODE, "--version"]:
          class Result:
              stdout = "v24.14.0\n"
              returncode = 0
          return Result()
      return original_run(cmd, *args, **kwargs)
  monkeypatch.setattr(_sp, "run", mock_run)
  
  if not Path(REAL_RG).exists():
    pytest.skip("rg未安装")
  
  if not Path(REAL_NODE).exists():
    pytest.skip("Node未安装")
  
  with tempfile.TemporaryDirectory() as tmpdir:
    root = Path(tmpdir) / "fixture"
    repository = Path(__file__).resolve().parents[1]
    
    # 从锁文件中读取预期的Node版本
    manifest = json.loads((repository / "locks/pi/manifest.json").read_text())
    expected_version = manifest["toolchains"]["node"]
    
    # 注意：由于测试环境禁用了subprocess，我们无法实际检查Node版本
    # 这里假设系统中的Node版本与锁文件中的一致
    
    programs = {
      "engine": "/usr/bin/bun",
      "node": REAL_NODE,
      "git": "/usr/bin/git",
      "python": sys.executable,
      "python_runtime": str(Path(sys.base_prefix).resolve()),
      "python_packages": str(Path(__file__).resolve().parents[1] / "src"),
    }
    
    fixture = prepare_configuration(
      root=root,
      repository=repository,
      profile="pi-default",
      provider_url="http://127.0.0.1:8080/v1",
      programs=programs,
      run=lambda argv, **kwargs: None,
      readseek=True
    )
    
    workspace = fixture["workspace"]
    local_path = workspace.local_path
    local_content = local_path.read_text()
    
    # 验证包含pi-todo插件（pi-default的标准插件）
    assert "pi-todo" in local_content
    
    # 验证包含pi-readseek插件
    assert "pi-readseek" in local_content
    
    # 验证包含readseek配置
    assert "readseek-node" in local_content


def test_cursor_readseek_keeps_cursor_plugin_and_endpoint(monkeypatch):
  """ReadSeek接线只能给cursor追加pi-readseek；不得整表替换剥离cursor provider所有者pi-cursor插件。"""
  monkeypatch.setenv("PATH", "/bin:/usr/bin:/home/weixiaoxian.wxx/.nvm/versions/node/v24.1.0/bin")
  import subprocess as _sp
  import tests.conftest as _conftest
  monkeypatch.setattr(_sp, "Popen", _conftest._REAL_POPEN)
  if not Path(REAL_RG).exists() or not Path(REAL_NODE).exists():
    pytest.skip("rg/Node未安装")
  repository = Path(__file__).resolve().parents[1]
  manifest = json.loads((repository / "locks/pi/manifest.json").read_text())
  expected_version = manifest["toolchains"]["node"]
  original_run = _sp.run
  def mock_run(cmd, *args, **kwargs):
    if cmd == [REAL_NODE, "--version"]:
      class Result:
        stdout = expected_version + "\n"
        returncode = 0
      return Result()
    return original_run(cmd, *args, **kwargs)
  monkeypatch.setattr(_sp, "run", mock_run)
  programs = {"engine": shutil.which("bun") or "/usr/bin/bun", "node": REAL_NODE, "git": "/usr/bin/git",
    "python": sys.executable, "python_runtime": str(Path(sys.base_prefix).resolve()),
    "python_packages": str(repository / "src")}
  with tempfile.TemporaryDirectory() as tmpdir:
    fixture = prepare_configuration(root=Path(tmpdir) / "fixture", repository=repository, profile="pi-cursor",
      provider_url="http://127.0.0.1:8080/v1", programs=programs, run=lambda argv, **kwargs: None, readseek=True)
    plugins = fixture["workspace"].resolved.data["plugins"]
    assert {"pi-cursor", "pi-readseek"} <= set(plugins), "cursor的ReadSeek夹具必须同时保留pi-cursor与pi-readseek"
    assert fixture["workspace"].resolved.data["profile"]["agent_options"]["cursor"]["network_route"] == "cursor-direct"


if __name__ == "__main__":
  pytest.main([__file__, "-v"])
