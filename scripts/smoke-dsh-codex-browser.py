#!/usr/bin/env python3
"""显式真实 Codex browser OAuth 取消验收；无账号，授权 URI 与终端输出不落盘。"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import time
import uuid


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--runtime", required=True, type=Path)
  parser.add_argument("--evidence", required=True, type=Path)
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("需要 --allow-host；默认 pytest 不启动第三方宿主")
  repo = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(repo / "src"))
  from agentcfg import commands, dependencies, runtime_packages
  from agentcfg.process import launch_environment
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace
  lock, runtime = dependencies.read_lock(repo), args.runtime.absolute()
  if (runtime_packages.status(runtime, lock.identity) != "installed" or any((runtime / name).read_bytes() != body
      for name, body in (("package.json", lock.package), ("package-lock.json", lock.resolution), ("pnpm-lock.yaml", lock.installer_resolution)))):
    parser.error("运行包收据与当前完整锁不匹配")
  evidence = args.evidence.absolute(); evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
  if (evidence / "result.json").exists():
    parser.error("请使用新的空证据目录")
  cache = Path("/dev/shm")
  outer_path = os.environ.get("PATH", "")
  result = {"kind": "native-pty-auth-real-codex-browser-cancel", "stage": "prepare", "lock_identity": lock.identity,
    "recipe": lock.metadata["recipe"], "platform": sys.platform, "model_calls": 0,
    "actual_account": "NOT RUN", "actual_clipboard": "NOT RUN", "actual_browser": "NOT RUN"}
  transcript, child, master, slave = bytearray(), None, None, None
  with tempfile.TemporaryDirectory(prefix="rotom-codex-browser-", dir="/dev/shm") as private, tempfile.TemporaryDirectory(prefix="auth-panel-workspace-", dir=cache) as work:
    root, project = Path(private), Path(work)
    env = {"PATH": outer_path, "TERM": "xterm-256color", "LANG": "C.UTF-8"}
    for name, suffix in {"HOME": "home", "DSH_HOME": "dsh", "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data",
        "XDG_STATE_HOME": "state", "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp"}.items():
      env[name] = str(root / suffix); ensure_private(root / suffix)
    fake_bin = root / "fake-bin"; ensure_private(fake_bin)
    for name in ("xdg-open", "open", "wl-copy", "xclip", "xsel", "pbcopy"):
      helper = fake_bin / name
      helper.write_text("#!/bin/sh\nexit 0\n"); helper.chmod(0o700)
    env["PATH"] = str(fake_bin) + ":" + outer_path
    os.environ.clear(); os.environ.update(env)
    native = root / "native-result.json"; ready = root / "ui-ready"; nonce = uuid.uuid4().hex
    def read():
      try:
        return json.loads(native.read_bytes())
      except (FileNotFoundError, ValueError):
        return {}
    try:
      probe = socket.socket()
      try:
        probe.bind(("127.0.0.1", 1455))
      except OSError:
        raise RuntimeError("CALLBACK_PORT_BUSY")
      finally:
        probe.close()
      result["callback_port_initially_free"] = True
      node = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True, check=True).stdout.strip()
      if node != lock.metadata["node"]:
        raise RuntimeError("NODE_VERSION")
      machine = root / "machine.toml"
      machine.write_text('schema_version=1\n[machine]\nid="native-auth-panel"\n'
        '[overrides.providers.fixture]\nprotocol="openai-compatible"\nbase_url="http://127.0.0.1:9/v1"\nauth_kind="api-key"\ncredential_ref="secret:fixture"\n'
        '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture-not-real"\ninput=["text"]\n'
        '[overrides.profiles.dsh-default]\nproviders=["fixture","codex"]\nmodels=["fixture"]\n'
        '[overrides.profiles.dsh-default.roles]\nmain="fixture"\n[overrides.profiles.dsh-default.agent_options]\nshow_welcome=false\n')
      machine.chmod(0o600)
      workspace = load_workspace(machine, repository=repo); candidate = workspace.candidate(lock.identity)
      commands.apply_candidate(workspace, lock, candidate)
      with Tree(workspace.state_root) as tree, instance_lock(tree):
        workspace.adapter.prepare_runtime(workspace, runtime)
      spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=project, runtime_root=runtime,
        instance_root=workspace.instance, lock_identity=lock.identity)
      child_env = launch_environment(spec, workspace.resolved.data["machine"], workspace.secret_store)
      child_env.update(AGENTCFG_AUTH_PANEL_ROOT=str(root), AGENTCFG_AUTH_PANEL_RESULT=str(native), AGENTCFG_AUTH_PANEL_NONCE=nonce,
        AGENTCFG_AUTH_PANEL_READY=str(ready),
        AGENTCFG_AUTH_PANEL_PATCH=str(workspace.instance / "dsh-home/agentcfg.patch.yml"),
        AGENTCFG_AUTH_PANEL_LAUNCHER=str(workspace.instance / "launch.mjs"))
      argv = ["node", str(repo / "scripts/smoke-dsh-codex-browser.mjs"), str(runtime)]
      master, slave = pty.openpty(); before = termios.tcgetattr(slave)
      fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
      child = subprocess.Popen(argv, cwd=project, env=child_env, stdin=slave, stdout=slave, stderr=slave)
      def pump():
        if select.select([master], [], [], 0.1)[0]:
          try:
            transcript.extend(os.read(master, 65536))
          except OSError:
            pass
      def text():
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)", "", transcript.decode(errors="replace"))
      def visible(label):
        # 原生终端用 CSI 前移代替部分空格；比较文字而非控制序列的空格编码。
        return "".join(label.split()) in "".join(text().split())
      def wait(predicate, seconds=30):
        deadline = time.monotonic() + seconds
        while not predicate() and child.poll() is None and time.monotonic() < deadline:
          pump()
          if read().get("error"):
            raise RuntimeError("NATIVE_CASE_FAILED")
        if not predicate():
          raise RuntimeError("STAGE_TIMEOUT")
      result["stage"] = "pty.host-ready"
      wait(lambda: read().get("stage") == "host.agent_ready" and "fixture-not-real" in text()
        and not termios.tcgetattr(slave)[3] & termios.ICANON)
      ready.write_text("ready\n")
      result["stage"] = "pty.auth-command"
      os.write(master, b"/auth login openai-codex\r")
      wait(lambda: visible("Browser login (default)") and visible("Select OpenAI Codex login method:"))
      result["login_method_panel"] = True
      os.write(master, b"\r")
      result["stage"] = "pty.browser-code-panel"
      wait(lambda: visible("Complete login in your browser, or paste the authorization code / redirect URL here:")
        and visible("Custom answer") and visible("auth.openai.com"))
      result["authorization_code_panel"] = True
      deadline = time.monotonic() + 5
      while time.monotonic() < deadline:
        pump()
        if child.poll() is not None or read().get("error"):
          raise RuntimeError("IDLE_PANEL_ABORTED")
      result["idle_seconds"] = 5
      result["stage"] = "pty.cancel"
      os.write(master, b"\x1b")
      result["cancel_input_count"] = 1
      wait(lambda: visible("dsh-auth:") and (visible("cancel") or visible("ASK_CANCELLED")))
      ready.write_text("done\n")
      result["stage"] = "pty.exit"
      wait(lambda: child.poll() is not None, 15)
      while select.select([master], [], [], 0)[0]:
        try:
          transcript.extend(os.read(master, 65536))
        except OSError:
          break
      after = termios.tcgetattr(slave); observed = read()
      result.update(native=observed, exit=child.returncode, termios_before=before[:4], termios_after=after[:4], complete_termios_match=before == after,
        nonce_verified=observed.get("nonce") == nonce, geometry=[100, 24], node=node, candidate_digest=candidate.generation,
        argv=["node", "scripts/smoke-dsh-codex-browser.mjs", str(runtime)])
      if (child.returncode != 0 or before != after or observed.get("nonce") != nonce or observed.get("error")
          or not observed.get("native_complete") or observed.get("model_calls") != 0
          or observed.get("remote_http_requests") != 0 or observed.get("signed_in")
          or observed.get("credential_file_created")):
        raise RuntimeError("NATIVE_RESULT_MISMATCH")
      result.update(overall="PASS", stage="complete", login_success_count=0, credential_write_count=0,
        checks={"real_auth_command": "PASS", "real_browser_flow": "PASS", "idle_five_seconds": "PASS",
          "cancel": "PASS", "no_credential": "PASS", "termios_restore": "PASS"})
    except Exception as error:
      result.update(overall="FAIL", error=str(error) if isinstance(error, RuntimeError) and str(error) in {
        "NODE_VERSION", "NATIVE_CASE_FAILED", "STAGE_TIMEOUT", "NATIVE_RESULT_MISMATCH", "IDLE_PANEL_ABORTED", "CALLBACK_PORT_BUSY"} else "AUTH_PANEL_DRIVER_FAILED",
        error_location=result["stage"], native=read())
    finally:
      if child is not None and child.poll() is None:
        child.terminate()
        try:
          child.wait(timeout=5)
        except subprocess.TimeoutExpired:
          child.kill(); child.wait()
      if child is not None:
        result["observed_exit"] = child.returncode
      if slave is not None:
        result["termios_restored_after_cleanup"] = before == termios.tcgetattr(slave)
      for fd in (master, slave):
        if fd is not None:
          os.close(fd)
    names = ("scripts/smoke-dsh-codex-browser.py", "scripts/smoke-dsh-codex-browser.mjs", "src/agentcfg/dsh.py",
      "agents/dsh/templates/launch.mjs", "agents/dsh/packages/cursor-terminal/index.mjs", "agents/dsh/templates/theme-catppuccin.json")
    source = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in names}
    result.update(source_files=source, source_hash=hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest())
    # 授权 URI 含 PKCE，只用于内存渲染检查，随后销毁。
    transcript.clear()
    result["terminal_transcript"] = "DISCARDED"
    (evidence / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"overall": result["overall"], "evidence": str(evidence)}, ensure_ascii=False))
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())
