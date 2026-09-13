"""LOCK-01：入口只消费仓库虚拟环境，不准备依赖。"""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv

# 保留准备 pytest 之前的标准库入口自测能力。
try:
  import pytest
except ModuleNotFoundError:
  pytest = None


ENTRY = Path(__file__).resolve().parents[1] / "agentcfg"


class EntryTests(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory(prefix="agentcfg-entry-")
    self.addCleanup(self.temporary.cleanup)
    self.root = Path(self.temporary.name)
    self.repo = self.root / "管理 仓库"
    self.repo.mkdir()
    self.entry = self.repo / "agentcfg"
    shutil.copy2(ENTRY, self.entry)
    self.cwd = self.root / "业务 中文 目录"
    self.cwd.mkdir()
    self.home = self.root / "home"
    self.home.mkdir()
    self.lock = self.repo / "uv.lock"
    self.lock.write_bytes(b"lock sentinel\n")
    self.sentinel = self.home / "untouched"
    self.sentinel.write_bytes(b"home sentinel\n")
    self.bin = self.root / "bin"
    self.bin.mkdir()
    self.base_python = Path(sys._base_executable).resolve()
    (self.bin / "python3").symlink_to(self.base_python)
    # 子进程同样禁止网络及安装器调用，仅放行入口的虚拟环境 exec。
    guard = self.root / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
      "import os, sys\n"
      "def audit(event, args):\n"
      "  if event.startswith('socket.') or event in "
      "('subprocess.Popen', 'os.system', 'os.posix_spawn'):\n"
      "    raise RuntimeError('forbidden network or child process')\n"
      "  if event == 'os.exec' and os.fsdecode(args[0]) != "
      "os.environ['EXPECTED_VENV_PYTHON']:\n"
      "    raise RuntimeError('forbidden executable')\n"
      "sys.addaudithook(audit)\n",
      encoding="utf-8",
    )
    self.env = {
      "PATH": str(self.bin),
      "HOME": str(self.home),
      "DSH_HOME": str(self.home / "dsh"),
      "XDG_CONFIG_HOME": str(self.home / "config"),
      "XDG_DATA_HOME": str(self.home / "data"),
      "XDG_STATE_HOME": str(self.home / "state"),
      "XDG_CACHE_HOME": str(self.home / "cache"),
      "TMPDIR": str(self.root),
      "PYTHONPATH": str(guard),
      "PYTHONDONTWRITEBYTECODE": "1",
      "PYTHONUTF8": "1",
      "EXPECTED_VENV_PYTHON": str(self.repo / ".venv/bin/python"),
    }

  def invoke(self, command):
    result = getattr(self, "entry_runner", subprocess.run)(
      [str(part) for part in command],
      cwd=self.cwd,
      env=self.env,
      capture_output=True,
      text=True,
      encoding="utf-8",
      timeout=10,
    )
    self.assertEqual(self.lock.read_bytes(), b"lock sentinel\n")
    self.assertEqual(self.sentinel.read_bytes(), b"home sentinel\n")
    self.assertEqual(list(self.home.iterdir()), [self.sentinel])
    self.assertEqual(list(self.cwd.iterdir()), [])
    return result

  def test_entry_opt_in_does_not_allow_other_commands(self):
    if not hasattr(self, "entry_runner"):
      self.skipTest("pytest 专用进程防护未安装，不尝试真实命令")
    for command in (["dsh"], [self.base_python, "-c", "pass"]):
      with self.subTest(command=command):
        with self.assertRaises(AssertionError):
          self.invoke(command)
    with self.assertRaisesRegex(RuntimeError, "process disabled"):
      subprocess.run(["dsh"])

  def test_missing_venv_is_passive(self):
    for command in ("validate", "plan"):
      with self.subTest(command=command):
        result = self.invoke([self.entry, command])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("uv sync --locked", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(set(self.repo.iterdir()), {self.entry, self.lock})

  def test_broken_venv_python_is_passive(self):
    python = self.repo / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(self.root / "missing-python")
    result = self.invoke([self.entry, "plan"])
    self.assertEqual(result.returncode, 2, result.stderr)
    self.assertIn("uv sync --locked", result.stderr)
    self.assertTrue(python.is_symlink())

  def test_symlinked_venv_preserves_cwd_argv_and_exit_code(self):
    environment = self.repo / ".venv"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    python = environment / "bin/python"
    self.assertEqual(python.resolve(), self.base_python)
    site_packages = next((environment / "lib").glob("python*/site-packages"))
    package = site_packages / "agentcfg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    # 仅观察入口契约，不执行尚未实现的 CLI 或第三方宿主。
    (package / "cli.py").write_text(
      "import json, os, sys\n"
      "def main():\n"
      "  print(json.dumps({'prefix': sys.prefix, 'cwd': os.getcwd(), "
      "'argv': sys.argv[1:]}, ensure_ascii=False))\n"
      "  return 17\n",
      encoding="utf-8",
    )
    arguments = ["run", "dsh", "--", "中文 空格", "", 'quote"value',
                 "$(touch forbidden)", "`touch forbidden`", "a;b", "line\nbreak"]
    for launcher in ([self.entry], [self.base_python, self.entry], [python, self.entry]):
      with self.subTest(launcher=launcher):
        result = self.invoke([*launcher, *arguments])
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), {
          "prefix": str(environment),
          "cwd": str(self.cwd),
          "argv": arguments,
        })


if pytest is not None:
  EntryTests = pytest.mark.usefixtures("entry_python")(EntryTests)

if __name__ == "__main__":
  unittest.main()
