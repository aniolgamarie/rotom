#!/usr/bin/env python3
"""显式 PTY + 本地模拟模型验收；普通 pytest 不启动宿主。"""

import argparse
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import tomllib
import uuid


class FixtureServer(ThreadingHTTPServer):
  daemon_threads = True


def fixture_handler(state, gate, key, target, content):
  class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
      pass

    def do_POST(self):
      try:
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 2 * 1024 * 1024:
          raise ValueError("REQUEST_SIZE")
        body = json.loads(self.rfile.read(size))
        if self.headers.get("Authorization") != "Bearer " + key or not self.path.endswith("/chat/completions"):
          raise ValueError("REQUEST_ROUTE")
        with gate:
          state["requests"] += 1
          if state["requests"] > 6:
            raise ValueError("REQUEST_LIMIT")
          messages, tools = body.get("messages", []), body.get("tools", [])
          user = "\n".join(json.dumps(item.get("content", ""), ensure_ascii=False) for item in messages if item.get("role") == "user")
          results = [item for item in messages if item.get("role") == "tool" and item.get("tool_call_id") == "ui-write-call"]
          delta, finish = {"role": "assistant", "content": "临时验收"}, "stop"
          cancel_stream = bool(tools) and "CANCEL_TASK_MARKER" in user
          if not tools:
            state["auxiliary_requests"] += 1
          elif state.get("session_resume") and "RESUME_TASK_UNIQUE_MARKER" in user:
            calls = [call for item in messages if item.get("role") == "assistant" for call in item.get("tool_calls", [])
              if call.get("id") == "ui-write-call"]
            arguments = json.loads(calls[0]["function"]["arguments"]) if len(calls) == 1 else {}
            state["resume_history"] = {"write_content": arguments.get("content") == content,
              "write_path": arguments.get("file_path") == str(target), "tool_result": len(results) == 1,
              "last_task": messages[-1].get("role") == "user" and "RESUME_TASK_UNIQUE_MARKER" in json.dumps(messages[-1].get("content", ""))}
            state["resume_model"] = body.get("model")
            if state["resume_model"] != "fixture-b" or not all(state["resume_history"].values()):
              raise ValueError("RESUME_HISTORY_MISMATCH")
            delta["content"] = "RESUME_DONE_MARKER"
            state["resume_completed"] = True
          elif cancel_stream:
            state["cancel_started"] = True
            delta["content"] = "CANCEL_PENDING_MARKER"
          elif results:
            if state["tool_results"] or len(results) != 1 or not target.is_file() or target.read_text() != content:
              raise ValueError("TOOL_RESULT_MISMATCH")
            state["tool_results"] = 1
            delta["content"] = "已完成 UI_DONE_MARKER"
            state["completed"] = True
            if state.get("session_resume"):
              state["tool_result_model"] = body.get("model")
              if state["tool_result_model"] != "fixture-b":
                raise ValueError("MODEL_ROUTE_MISMATCH")
          else:
            state["task_requests"] += 1
            state["paste"] = {"chinese": "中文第一行" in user, "multiline": "第二行" in user and "\\n" in user, "marker": "TASK_MARKER" in user}
            if state["write_calls"] or not all(state["paste"].values()):
              raise ValueError("TASK_PASTE_MISMATCH")
            tool = next((item["function"] for item in tools if item.get("function", {}).get("name") == "write"), None)
            schema = tool.get("parameters", {}) if tool else {}
            if (not tool or not {"file_path", "content"} <= set(schema.get("required", []))
                or any(schema.get("properties", {}).get(name, {}).get("type") != "string" for name in ("file_path", "content"))):
              raise ValueError("WRITE_SCHEMA_NOT_FOUND")
            state["write_calls"] = 1
            if state.get("session_resume"):
              state["new_model"] = body.get("model")
              if state["new_model"] != "fixture-b":
                raise ValueError("MODEL_ROUTE_MISMATCH")
            state["tool_name"] = tool["name"]
            delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "ui-write-call", "type": "function", "function": {
              "name": tool["name"], "arguments": json.dumps({"file_path": str(target), "content": content}, ensure_ascii=False)}}]}
            finish = "tool_calls"
        packet = {"id": "chatcmpl-ui-fixture", "object": "chat.completion.chunk", "created": int(time.time()), "model": body.get("model", "fixture")}
        if body.get("stream"):
          self.send_response(200)
          self.send_header("Content-Type", "text/event-stream")
          self.send_header("Cache-Control", "no-cache")
          self.send_header("Connection", "close")
          self.end_headers()
          time.sleep(0.2)
          if cancel_stream:
            value = {**packet, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
            self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
            self.wfile.flush()
            state["cancel_chunk_sent"] = True
            # 只观察本地假服务连接关闭，证明 UI 取消了正在进行的请求。
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
              if select.select([self.connection], [], [], 0.1)[0] and not self.connection.recv(1, socket.MSG_PEEK):
                state["cancel_disconnected"] = True
                self.close_connection = True
                return
            raise ValueError("CANCEL_NOT_OBSERVED")
          for value in ({**packet, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
              {**packet, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}):
            self.wfile.write(("data: " + json.dumps(value, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()
          self.wfile.write(b"data: [DONE]\n\n")
          self.close_connection = True
          if state.get("session_resume") and tools and (results or "RESUME_TASK_UNIQUE_MARKER" in user):
            state["resume_response_sent" if "RESUME_TASK_UNIQUE_MARKER" in user else "task_response_sent"] = True
        else:
          payload = json.dumps({**packet, "object": "chat.completion", "choices": [{"index": 0, "message": delta, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}, ensure_ascii=False).encode()
          self.send_response(200)
          self.send_header("Content-Type", "application/json")
          self.send_header("Content-Length", str(len(payload)))
          self.end_headers()
          self.wfile.write(payload)
      except Exception as error:
        with gate:
          state["error"] = str(error) if isinstance(error, ValueError) and str(error) in {
            "REQUEST_SIZE", "REQUEST_ROUTE", "REQUEST_LIMIT", "TOOL_RESULT_MISMATCH", "TASK_PASTE_MISMATCH", "WRITE_SCHEMA_NOT_FOUND", "CANCEL_NOT_OBSERVED",
            "MODEL_ROUTE_MISMATCH", "RESUME_HISTORY_MISMATCH"} else "FIXTURE_HTTP_FAILED"
        self.send_response(400)
        self.send_header("Content-Length", "0")
        self.end_headers()
  return Handler


def session_resume_smoke(spec, env, project, instance, state, target, content, result, transcript):
  """真实公开 --resume 路径；偏好及会话标记只属于本任务临时 HOME。"""
  prefs = instance / "user-home/.dsh-tui"
  def preference(model):
    path = prefs / "model.json"
    path.write_text(json.dumps({"provider": "agentcfg-fixture", "model": model}))
    path.chmod(0o600)
  preference("fixture-b")
  for phase in ("new", "resume"):
    result["stage"] = "session." + phase + ".launch"
    argv = list(spec.argv)
    if phase == "resume":
      session_id = (prefs / "resume.txt").read_text().strip()
      if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
        raise RuntimeError("SESSION_MARKER_INVALID")
      preference("fixture-a")
      argv.extend(["--resume", session_id])
      result["resume_argument"] = session_id
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
    child, start = None, len(transcript)
    try:
      child = subprocess.Popen(argv, cwd=project, env=env, stdin=slave, stdout=slave, stderr=slave)
      def pump():
        if select.select([master], [], [], 0.1)[0]:
          try:
            transcript.extend(os.read(master, 65536))
          except OSError:
            pass
      def visible():
        raw = transcript[start:].decode(errors="replace")
        raw = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", raw)
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw)
      def wait(predicate, seconds=30):
        deadline = time.monotonic() + seconds
        while not predicate() and child.poll() is None and time.monotonic() < deadline:
          pump()
          if state.get("error"):
            raise RuntimeError("FIXTURE_REJECTED")
        if not predicate():
          raise RuntimeError("STAGE_TIMEOUT")
      result["stage"] = "session." + phase + ".ready"
      wait(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON and "fixture-b" in visible())
      settle = time.monotonic() + 1
      while time.monotonic() < settle:
        pump()
      result["stage"] = "session." + phase + ".request"
      text = "中文第一行\n第二行 TASK_MARKER" if phase == "new" else "RESUME_TASK_UNIQUE_MARKER"
      os.write(master, ("\x1b[200~" + text + "\x1b[201~").encode())
      marker = "TASK_MARKER" if phase == "new" else "RESUME_TASK_UNIQUE_MARKER"
      wait(lambda: marker in re.sub(r"\s+", "", visible()), 5)
      os.write(master, b"\r")
      wait(lambda: state.get("completed" if phase == "new" else "resume_completed") is True)
      # Ink 的增量重绘会交错文字；本分支以实际 HTTP 响应 flush 和恢复后的主历史验证完成。
      wait(lambda: state.get("task_response_sent" if phase == "new" else "resume_response_sent") is True)
      if not target.is_file() or target.read_text() != content:
        raise RuntimeError("PROBE_FILE_MISMATCH")
      settle = time.monotonic() + 1
      while time.monotonic() < settle:
        pump()
      result["stage"] = "session." + phase + ".exit"
      os.write(master, b"\x03")
      settle = time.monotonic() + 0.3
      while time.monotonic() < settle:
        pump()
      if child.poll() is None:
        os.write(master, b"\x03")
      wait(lambda: child.poll() is not None, 10)
      after = termios.tcgetattr(slave)
      result.setdefault("session_processes", []).append({"phase": phase, "exit": child.returncode,
        "termios_before": before[:4], "termios_after": after[:4], "complete_termios_match": before == after})
      if child.returncode != 0 or before != after:
        raise RuntimeError("EXIT_OR_TTY_RESTORE")
    finally:
      if child is not None and child.poll() is None:
        child.terminate()
        try:
          child.wait(timeout=5)
        except subprocess.TimeoutExpired:
          child.kill()
          child.wait()
      if child is not None:
        result.setdefault("observed_session_exits", {})[phase] = child.returncode
      os.close(master)
      os.close(slave)
  if state["write_calls"] != 1 or state["tool_results"] != 1:
    raise RuntimeError("PROBE_FILE_MISMATCH")
  result["checks"].update(new_session_native_preference="PASS", public_launch_resume_recorded_route="PASS",
    resumed_main_write_history="PASS", native_write_tool_roundtrip="PASS", both_termios_restored="PASS")
  result.update(overall="PASS", stage="complete", route_evidence={"core_fallback": "fixture-a", "initial_preference": "fixture-b",
    "restart_preference": "fixture-a", "new_request": state["new_model"], "resumed_request": state["resume_model"]},
    file_content_sha256=hashlib.sha256(target.read_bytes()).hexdigest(), http=dict(state),
    resume_picker="NOT RUN", cursor_account="NOT RUN", compaction="NOT RUN", geometry=[[100, 24], [100, 24]])


def settings_migration_smoke(spec, env, project, workspace, lock, runtime, state, result, transcript):
  """真实首导与重启；仅编辑测试实例的原生用户偏好，不复制真实账号。"""
  from agentcfg import commands
  from agentcfg.storage import Tree, instance_lock
  prefs = workspace.instance / "user-home/.dsh-tui"
  settings = prefs / "settings.json"
  effort = prefs / "effort.json"
  assert not settings.exists()
  for phase in ("import", "restart"):
    result["stage"] = "settings." + phase
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
    child, start = None, len(transcript)
    try:
      child = subprocess.Popen(list(spec.argv), cwd=project, env=env, stdin=slave, stdout=slave, stderr=slave)
      def pump():
        if select.select([master], [], [], 0.1)[0]:
          try:
            transcript.extend(os.read(master, 65536))
          except OSError:
            pass
      def visible():
        text = transcript[start:].decode(errors="replace")
        text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", text)
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
      def wait(predicate, seconds=30):
        deadline = time.monotonic() + seconds
        while not predicate() and child.poll() is None and time.monotonic() < deadline:
          pump()
        if not predicate():
          raise RuntimeError("SETTINGS_STAGE_TIMEOUT")
      def settle():
        deadline = time.monotonic() + 0.7
        while time.monotonic() < deadline:
          pump()
      def command(text):
        os.write(master, (text + "\r").encode())
        settle()
      wait(lambda: settings.exists() and not termios.tcgetattr(slave)[3] & termios.ICANON)
      settle()
      os.write(master, b"\r")
      settle()
      document = json.loads(settings.read_bytes())
      result.setdefault("observed_settings", {})[phase] = document
      result["stage"] = "settings." + phase + ".assert_values"
      assert document["version"] == 1
      values = document["values"]
      if phase == "import":
        assert values["brand"] == "deepseek" and values["whale"] is True
        assert values["statusBar"]["tps"] is True
        assert values["taskNotifications"] == "unfocused" and values["notificationMethod"] == "auto"
        assert values.get("effortDefault", "auto") == "auto"
        result["settings_imports_upstreamRetry"] = "upstreamRetry" in values
        result["checks"]["native_settings_first_import"] = "PASS"
        result["stage"] = "settings.import.effort"
        command("/effort high")
        wait(lambda: effort.exists() and json.loads(effort.read_bytes()).get("effort") == "high", 10)
      else:
        assert values["statusBar"]["tps"] is False
        assert values["statusBar"]["rotomFixtureUnknown"] == {"keep": True}
        assert values["taskNotifications"] == "off"
        result["checks"]["native_user_values_survive_restart"] = "PASS"
      result["stage"] = "settings." + phase + ".effort_status"
      command("/effort status")
      wait(lambda: "Currentreasoningefforthigh" in re.sub(r"\s+", "", visible()), 10)
      result["checks"]["manual_effort_" + phase] = "PASS"
      model = prefs / "model.json"
      model_before = model.read_bytes() if model.exists() else None
      result["stage"] = "settings." + phase + ".model_cancel"
      command("/model")
      wait(lambda: "fixture-not-real" in visible(), 10)
      os.write(master, b"\t")
      settle()
      os.write(master, b"\x1b")
      settle()
      assert (model.read_bytes() if model.exists() else None) == model_before
      result["checks"]["model_tabs_cancel_" + phase] = "PASS"
      os.write(master, b"\x03")
      settle()
      if child.poll() is None:
        os.write(master, b"\x03")
      wait(lambda: child.poll() is not None, 10)
      assert child.returncode == 0 and before == termios.tcgetattr(slave)
      result.setdefault("settings_processes", []).append({"phase": phase, "exit": 0, "termios_restored": True})
    finally:
      if child is not None and child.poll() is None:
        child.terminate()
        try:
          child.wait(timeout=5)
        except subprocess.TimeoutExpired:
          child.kill()
          child.wait()
      os.close(master)
      os.close(slave)
    if phase == "import":
      document = json.loads(settings.read_bytes())
      document["values"]["statusBar"].update(tps=False, rotomFixtureUnknown={"keep": True})
      document["values"]["taskNotifications"] = "off"
      settings.write_text(json.dumps(document) + "\n")
      settings.chmod(0o600)
      saved_settings, saved_effort = settings.read_bytes(), effort.read_bytes()
      applied = commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
      assert applied["changes"] == 0
      assert settings.read_bytes() == saved_settings and effort.read_bytes() == saved_effort
      # apply 投影生产运行包路径；此测试显式使用外部封存包，重启前恢复其公开投影。
      with Tree(workspace.state_root) as tree, instance_lock(tree):
        workspace.adapter.prepare_runtime(workspace, runtime)
      result["checks"]["repeat_apply_preserves_native_preferences"] = "PASS"
  assert state["requests"] == 0
  result.update(overall="PASS", stage="complete", settings_shape="version/values/imported",
    settings_edits="synthetic file edits in isolated HOME", real_model_calls=0,
    http=dict(state), geometry=[[120, 32], [120, 32]])


def prepare_inline_preference(argv, env, project, instance, state, result, evidence):
  """首启完成上游迁移，再保存测试实例的原生 inline 偏好；不碰迁移标记。"""
  settings = instance / "user-home/.dsh-tui/settings.json"
  master, slave = pty.openpty()
  before = termios.tcgetattr(slave)
  fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
  child, output = None, bytearray()
  try:
    child = subprocess.Popen(list(argv), cwd=project, env=env, stdin=slave, stdout=slave, stderr=slave,
      start_new_session=True)
    def pump():
      if select.select([master], [], [], 0.1)[0]:
        output.extend(os.read(master, 65536))
    deadline = time.monotonic() + 30
    while (not settings.exists() or termios.tcgetattr(slave)[3] & termios.ICANON) and child.poll() is None and time.monotonic() < deadline:
      pump()
    if not settings.exists() or child.poll() is not None:
      raise RuntimeError("INLINE_PREFERENCE_PREPARATION_FAILED")
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
      pump()
    os.write(master, b"\r")
    deadline = time.monotonic() + 0.7
    while time.monotonic() < deadline:
      pump()
    for _ in range(2):
      if child.poll() is None:
        os.write(master, b"\x03")
        deadline = time.monotonic() + 1
        while child.poll() is None and time.monotonic() < deadline:
          pump()
    child.wait(timeout=10)
    if child.returncode or before != termios.tcgetattr(slave) or state["requests"]:
      raise RuntimeError("INLINE_PREFERENCE_PREPARATION_FAILED")
    document = json.loads(settings.read_bytes())
    assert document["version"] == 1 and isinstance(document["values"], dict)
    document["values"]["fullscreen"] = False
    settings.write_text(json.dumps(document) + "\n")
    settings.chmod(0o600)
    result["inline_preparation"] = {"exit": 0, "model_requests": 0,
      "preference": {"fullscreen": False}, "method": "native settings file after first launch"}
  finally:
    if child is not None and child.poll() is None:
      if os.getpgid(child.pid) == child.pid:
        os.killpg(child.pid, signal.SIGTERM)
      try:
        child.wait(timeout=5)
      except subprocess.TimeoutExpired:
        if child.poll() is None and os.getpgid(child.pid) == child.pid:
          os.killpg(child.pid, signal.SIGKILL)
        child.wait()
    os.close(master)
    os.close(slave)
    path = evidence / "inline-first-launch.log"
    path.write_bytes(output)
    path.chmod(0o600)


def agentcfg_cli_argv(repo, machine, command, project=None):
  # --machine 接受配置名称，临时配置文件必须使用公开 --local 选择器。
  argv = [str(repo / "agentcfg"), "--local", str(machine), "--profile", "dsh-default", command]
  if project is not None:
    argv.extend(["--cwd", str(project)])
  return argv


def project_sealed_runtime(workspace, runtime, identity):
  """完整复制已封存包及其原收据；不生成或改写安装所有权标记。"""
  from agentcfg.storage import ensure_private
  destination = workspace.backend.root(workspace, identity)
  ensure_private(destination.parent)
  shutil.copytree(runtime, destination, symlinks=True)
  if workspace.backend.status(workspace, identity) != "installed":
    raise RuntimeError("RUNTIME_PROJECTION_INVALID")
  return destination


def prepare_agentcfg_cli(repo, workspace, machine, runtime, identity, project, env, result, evidence):
  destination = project_sealed_runtime(workspace, runtime, identity)
  result.update(runtime_source=str(runtime), runtime_root=str(destination), agentcfg_cli=True)
  result["cli_preparation"] = []
  for command in ("apply", "sync"):
    argv = agentcfg_cli_argv(repo, machine, command)
    completed = subprocess.run(argv, cwd=repo, env=env, capture_output=True, timeout=60)
    (evidence / ("cli-" + command + ".log")).write_bytes(completed.stdout + completed.stderr)
    result["cli_preparation"].append({"argv": argv, "exit": completed.returncode})
    if completed.returncode != 0:
      raise RuntimeError("CLI_PREPARATION_FAILED")
  result["checks"]["sealed_runtime_installed_before_sync"] = "PASS"
  return agentcfg_cli_argv(repo, machine, "run", project)


def fixture_plugin_override(repo, agent_teams=False):
  if not agent_teams:
    return ""
  defaults = tomllib.loads((repo / "agents/dsh/agent.toml").read_text())["defaults"]["plugins"]
  return "plugins=" + json.dumps([*defaults, "agent-teams"]) + "\n"


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--runtime", required=True, type=Path)
  parser.add_argument("--evidence", required=True, type=Path)
  parser.add_argument("--agentcfg-cli", action="store_true", help="通过真实 agentcfg apply/sync/run 验收已封存包，不联网安装")
  parser.add_argument("--agent-teams", action="store_true", help="显式选入 Teams，保留完整默认插件及 Perry；仅与 --agentcfg-cli 使用")
  parser.add_argument("--maid-portrait", action="store_true", help="验证原生女仆立绘及伙伴皮肤优先级，仍使用假模型")
  parser.add_argument("--session-resume", action="store_true", help="验证原生模型偏好、公开 --resume 路由和短工具正文历史")
  parser.add_argument("--settings-migration", action="store_true", help="验证原生设置首导、重启与手动 effort，不调用真实模型")
  parser.add_argument("--inline", action="store_true", help="以公开 fullscreen=false 验收终端普通屏、输入、工具和退出")
  args = parser.parse_args()
  if args.agent_teams and not args.agentcfg_cli:
    parser.error("--agent-teams 需要 --agentcfg-cli")
  if not args.allow_host:
    parser.error("需要 --allow-host；默认测试不启动第三方宿主")
  if args.agentcfg_cli and (args.session_resume or args.maid_portrait):
    parser.error("--agentcfg-cli 单独验收欢迎、输入、工具、取消与退出")
  if args.session_resume and args.maid_portrait:
    parser.error("--session-resume 与 --maid-portrait 分别验收")
  if args.settings_migration and (args.agentcfg_cli or args.session_resume or args.maid_portrait):
    parser.error("--settings-migration 单独验收")
  if args.inline and (args.session_resume or args.settings_migration or args.maid_portrait):
    parser.error("--inline 只与普通交互或 --agentcfg-cli 组合验收")
  repo = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(repo / "src"))
  from agentcfg import commands, dependencies, runtime_packages
  from agentcfg.process import launch_environment
  from agentcfg.deployment import parse_native, encode_native
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace
  lock, runtime = dependencies.read_lock(repo), args.runtime.absolute()
  if (runtime_packages.status(runtime, lock.identity) != "installed" or any(((runtime / name).read_bytes() if (runtime / name).exists() else b"") != value
      for name, value in (("package.json", lock.package), ("package-lock.json", lock.resolution), ("pnpm-lock.yaml", lock.installer_resolution)))):
    parser.error("运行包收据与当前完整锁不匹配")
  evidence = args.evidence.absolute()
  evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
  if (evidence / "result.json").exists():
    parser.error("使用新的空证据目录")
  cache = repo / ".cache/dsh-upgrade"
  cache.mkdir(mode=0o700, parents=True, exist_ok=True)
  result = {"kind": "native-pty-simulated-local-model", "stage": "prepare", "checks": {}, "lock_identity": lock.identity,
    "recipe": lock.metadata["recipe"], "platform": sys.platform, "agentcfg_cli": args.agentcfg_cli,
    "fixture_flags": {"agent_teams": args.agent_teams, "session_resume": args.session_resume,
      "settings_migration": args.settings_migration, "inline": args.inline},
    "lock_files": {name: hashlib.sha256(value).hexdigest() for name, value in (("package.json", lock.package),
      ("package-lock.json", lock.resolution), ("pnpm-lock.yaml", lock.installer_resolution)) if value}, "color_environment": "COLORTERM=truecolor",
    "ssh": "NOT RUN", "tmux": "NOT RUN", "real_accounts": "NOT RUN"}
  outer_path = os.environ.get("PATH", "")
  transcript, child, master, slave, server = bytearray(), None, None, None, None
  with tempfile.TemporaryDirectory(prefix="rotom-dsh-ui-", dir="/dev/shm") as private, tempfile.TemporaryDirectory(prefix="ui-workspace-", dir=cache) as work:
    root, project = Path(private), Path(work)
    env = {"PATH": outer_path, "TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": "C.UTF-8"}
    for name, suffix in {"HOME": "home", "DSH_HOME": "dsh", "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data",
        "XDG_STATE_HOME": "state", "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp"}.items():
      env[name] = str(root / suffix)
      ensure_private(root / suffix)
    os.environ.clear()
    os.environ.update(env)
    target, content, key = project / "ui-tool-result.txt", "中文原生工具写入\nUI_TOOL_CONTENT_MARKER\n", "synthetic-" + uuid.uuid4().hex
    state = {"requests": 0, "auxiliary_requests": 0, "task_requests": 0, "write_calls": 0, "tool_results": 0, "completed": False}
    if args.session_resume:
      state["session_resume"] = True
    gate = threading.Lock()
    try:
      node = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True, check=True).stdout.strip()
      if node != lock.metadata["node"]:
        raise RuntimeError("NODE_VERSION")
      server = FixtureServer(("127.0.0.1", 0), fixture_handler(state, gate, key, target, content))
      threading.Thread(target=server.serve_forever, daemon=True).start()
      machine = root / "machine.toml"
      machine.write_text('schema_version=1\n[machine]\nid="native-ui"\n[overrides.providers.fixture]\nprotocol="openai-compatible"\n'
        f'base_url="http://127.0.0.1:{server.server_port}/v1"\nauth_kind="api-key"\ncredential_ref="secret:fixture"\n'
        '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture-not-real"\ninput=["text"]\n'
        '[overrides.profiles.dsh-default]\n' + fixture_plugin_override(repo, args.agent_teams) +
        'providers=["fixture"]\nmodels=["fixture"]\n[overrides.profiles.dsh-default.roles]\nmain="fixture"\n'
        f'[secrets]\nfixture={json.dumps(key)}\n')
      machine.chmod(0o600)
      if args.settings_migration:
        machine.write_text(machine.read_text().replace('input=["text"]\n', 'input=["text"]\nreasoning_efforts=["low","high"]\n'))
      if args.session_resume:
        raw = machine.read_text().replace('remote_id="fixture-not-real"', 'remote_id="fixture-a"')
        raw += '\n[overrides.models.fixture_b]\nprovider="fixture"\nremote_id="fixture-b"\ninput=["text"]\n'
        raw = raw.replace('models=["fixture"]', 'models=["fixture","fixture_b"]')
        raw += '[overrides.profiles.dsh-default.agent_options]\nshow_welcome=false\n'
        machine.write_text(raw)
      workspace = load_workspace(machine, repository=repo)
      candidate = workspace.candidate(lock.identity)
      if args.agentcfg_cli:
        result["stage"] = "cli.prepare"
        launch_argv = prepare_agentcfg_cli(repo, workspace, machine, runtime, lock.identity, project, env, result, evidence)
      else:
        commands.apply_candidate(workspace, lock, candidate)
      with Tree(workspace.state_root) as tree, instance_lock(tree):
        if args.maid_portrait:
          with Tree(workspace.instance) as instance_tree:
            name = "dsh-home/profiles/agentcfg/cordis.patch.yml"
            previous = instance_tree.read(name)
            document = parse_native(previous[0], "cordis-yaml")
            config = document["dsh-tui"]["config"]
            config["whaleGirl"] = True
            config.setdefault("companion", {})["skin"] = "whale"
            instance_tree.replace(name, encode_native(document, "cordis-yaml"), mode=previous[1], expected=previous[2])
        if not args.agentcfg_cli:
          workspace.adapter.prepare_runtime(workspace, runtime)
      native_runtime = workspace.backend.root(workspace, lock.identity) if args.agentcfg_cli else runtime
      spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=project, runtime_root=native_runtime, instance_root=workspace.instance, lock_identity=lock.identity)
      child_env = env if args.agentcfg_cli else launch_environment(spec, workspace.resolved.data["machine"], workspace.secret_store)
      if not args.agentcfg_cli:
        launch_argv = list(spec.argv)
      result.update(argv=launch_argv, native_argv=list(spec.argv), candidate_digest=candidate.generation)
      if args.inline:
        result["stage"] = "inline.preference"
        prepare_inline_preference(launch_argv, child_env, project, workspace.instance, state, result, evidence)
      if args.settings_migration:
        result.update(candidate_digest=candidate.generation, node=node)
        settings_migration_smoke(spec, child_env, project, workspace, lock, native_runtime, state, result, transcript)
      elif args.session_resume:
        result.update(candidate_digest=candidate.generation, node=node)
        session_resume_smoke(spec, child_env, project, workspace.instance, state, target, content, result, transcript)
      else:
        master, slave = pty.openpty()
        before = termios.tcgetattr(slave)
        initial_columns, initial_rows = (160, 50) if args.maid_portrait else (100, 24)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", initial_rows, initial_columns, 0, 0))
        child = subprocess.Popen(launch_argv, cwd=project, env=child_env, stdin=slave, stdout=slave, stderr=slave,
          start_new_session=args.agentcfg_cli)
        def pump():
          if select.select([master], [], [], 0.1)[0]:
            try:
              transcript.extend(os.read(master, 65536))
            except OSError:
              pass
        def wait(predicate, seconds=30):
          deadline = time.monotonic() + seconds
          while not predicate() and child.poll() is None and time.monotonic() < deadline:
            pump()
            if state.get("error"):
              raise RuntimeError("FIXTURE_REJECTED")
          if not predicate():
            raise RuntimeError("STAGE_TIMEOUT")
        def rendered_text():
          visible = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", transcript.decode(errors="replace"))
          return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", visible)
        result["stage"] = "ui.welcome"
        wait(lambda: "Saysomething,ortype/forcommand" in re.sub(r"\s+", "", rendered_text())
          and not termios.tcgetattr(slave)[3] & termios.ICANON)
        # 原生 welcome 的输入框默认获焦点；空 Enter 只关闭启动页，不发送模型请求。
        ready_deadline = time.monotonic() + 1
        while time.monotonic() < ready_deadline:
          pump()
        result["checks"]["native_welcome_rendered"] = "PASS"
        if args.maid_portrait:
          # 上游女仆字符画静态精灵的两种独有 RGB；鲸鱼及当前主题没有这些像素色。
          def maid_pixels_present(output):
            return all(any((f"\x1b[{prefix};2;{color}m").encode() in output for prefix in (38, 48))
              for color in ("247;192;126", "248;181;153"))
          wait(lambda: maid_pixels_present(transcript), 5)
          result["checks"]["native_maid_character_art"] = "PASS"
          result["native_ui_preferences"] = {"whaleGirl": True, "companion.skin": "whale"}
        chat_frame_start = len(transcript)
        os.write(master, b"\r")
        result["stage"] = "ui.ready"
        ready_deadline = time.monotonic() + 1
        while time.monotonic() < ready_deadline:
          pump()
        if child.poll() is not None or state["requests"]:
          raise RuntimeError("WELCOME_EMPTY_SUBMIT")
        if args.maid_portrait:
          wait(lambda: maid_pixels_present(transcript[chat_frame_start:]), 5)
          result["checks"]["native_maid_chat_header"] = "PASS"
        result["checks"]["welcome_empty_enter_no_model_call"] = "PASS"
        result["checks"]["native_ui_ready"] = "PASS"
        if args.inline:
          # 偏好异步载入前上游可能短暂开备用屏；实际聊天必须已返回普通屏。
          switches = re.findall(rb"\x1b\[\?(?:47|1047|1049)([hl])", transcript)
          if switches and switches[-1] != b"l":
            raise RuntimeError("INLINE_ENTERED_ALTERNATE_SCREEN")
          inline_chat_start = len(transcript)
          result["inline_bootstrap_alternate_screen"] = b"h" in switches
        if args.agent_teams:
          result["stage"] = "ui.team-status"
          start = len(transcript)
          os.write(master, b"/team status\r")
          def team_status_visible():
            text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", transcript[start:].decode(errors="replace"))
            return (("Team bundle: on" in text and re.search(r"Team service: run(?:n|\x1b\[1C)ing", transcript[start:].decode(errors="replace"))) or
              ("团队 bundle：已开启" in text and "团队服务：运行中" in text))
          wait(team_status_visible, 15)
          result["team_status"] = {"bundle": "on", "service": "running", "command": "/team status"}
          result["checks"]["team_bundle_and_service_running"] = "PASS"
          os.write(master, b"\x1b")
          for _ in range(5):
            pump()
          start = len(transcript)
          os.write(master, b"/auto-review status\r")
          wait(lambda: any(value in transcript[start:].decode(errors="replace") for value in
            ("Auto-review is ON", "本会话的自动审查已开启")), 15)
          result["checks"]["perry_status_on_with_teams"] = "PASS"
          os.write(master, b"\x1b")
          for _ in range(5):
            pump()
          if state["requests"]:
            raise RuntimeError("STATUS_COMMAND_SENT_TO_MODEL")
        result["stage"] = "ui.paste-tool"
        os.write(master, "\x1b[200~中文第一行\n第二行 TASK_MARKER\x1b[201~".encode())
        wait(lambda: b"TASK_MARKER" in transcript, 5)
        os.write(master, b"\r")
        wait(lambda: state["write_calls"] == 1)
        result["stage"] = "ui.resize"
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 18, 40, 0, 0))
        (os.killpg if args.agentcfg_cli else os.kill)(child.pid, signal.SIGWINCH)
        resize_start = len(transcript)
        wait(lambda: state["completed"] and target.is_file() and target.read_text() == content)
        # Ink 在窄窗逐段重绘；ANSI 光标控制和换行会拆开可见标记。
        def rendered_marker(marker="UI_DONE_MARKER"):
          return marker in re.sub(r"\s+", "", rendered_text()) and len(transcript) > resize_start
        wait(rendered_marker)
        # 只检查公开 Theme 字段在真实渲染中的色值，不调用宿主私有 resolver。
        palette = json.loads((repo / "agents/dsh/templates/theme-catppuccin.json").read_bytes())["colors"]
        def ansi_color(value):
          return ("\x1b[38;2;" + ";".join(str(int(value[index:index + 2], 16)) for index in (1, 3, 5)) + "m").encode()
        if not all(ansi_color(palette[key]) in transcript for key in ("text", "promptBorder", "success")):
          raise RuntimeError("THEME_RENDER_MISMATCH")
        result["checks"]["native_catppuccin_truecolor"] = "PASS"
        result["checks"].update(chinese_multiline_paste="PASS", narrow_resize="PASS", native_write_tool_roundtrip="PASS")
        result["stage"] = "ui.cancel-stream"
        os.write(master, b"CANCEL_TASK_MARKER\r")
        wait(lambda: state.get("cancel_started") is True)
        wait(lambda: state.get("cancel_chunk_sent") is True, 5)
        os.write(master, b"\x03")
        wait(lambda: state.get("cancel_disconnected") is True, 10)
        assert child.poll() is None and state["write_calls"] == 1 and state["tool_results"] == 1
        result["checks"]["ctrl_c_active_request_cancel"] = "PASS"
        idle_deadline = time.monotonic() + 1
        while time.monotonic() < idle_deadline:
          pump()
        result["stage"] = "ui.ctrl-c"
        os.write(master, b"\x03")
        time.sleep(0.3)
        if child.poll() is None:
          os.write(master, b"\x03")
        wait(lambda: child.poll() is not None, 10)
        after = termios.tcgetattr(slave)
        result.update(exit=child.returncode, termios_before=before[:4], termios_after=after[:4],
          complete_termios_match=before == after, geometry=[[initial_columns, initial_rows], [40, 18]],
          file_content_sha256=hashlib.sha256(target.read_bytes()).hexdigest(), http=dict(state), candidate_digest=candidate.generation, node=node)
        if before != after or child.returncode != 0 or state["write_calls"] != 1 or state["tool_results"] != 1:
          raise RuntimeError("EXIT_OR_TTY_RESTORE")
        if args.agentcfg_cli:
          with Tree(workspace.state_root) as tree, instance_lock(tree):
            result["checks"]["cli_instance_lock_released"] = "PASS"
        result["checks"].update(ctrl_c_exit="PASS", termios_restored="PASS")
        if args.inline:
          # 真实聊天、工具和取消阶段不能重新进入备用屏。
          if re.search(rb"\x1b\[\?(?:47|1047|1049)h", transcript[inline_chat_start:]):
            raise RuntimeError("INLINE_ENTERED_ALTERNATE_SCREEN")
          result["checks"]["inline_chat_normal_screen"] = "PASS"
        result["overall"], result["stage"] = "PASS", "complete"
    except Exception as error:
      result.update(overall="FAIL", error="FIXTURE_REJECTED" if state.get("error") else str(error) if isinstance(error, RuntimeError)
        and str(error) in {"NODE_VERSION", "STAGE_TIMEOUT", "EXIT_OR_TTY_RESTORE", "FIXTURE_REJECTED", "WELCOME_EMPTY_SUBMIT", "THEME_RENDER_MISMATCH", "SESSION_MARKER_INVALID", "PROBE_FILE_MISMATCH", "CLI_PREPARATION_FAILED", "RUNTIME_PROJECTION_INVALID", "INLINE_ENTERED_ALTERNATE_SCREEN", "INLINE_PREFERENCE_PREPARATION_FAILED"} else "UI_SMOKE_FAILED", error_location=result["stage"], http=dict(state))
    finally:
      if child is not None and child.poll() is None:
        # 仅在自建 leader 尚未退出且组身份仍匹配时终止整个组，避免 PID 复用。
        try:
          if args.agentcfg_cli and os.getpgid(child.pid) == child.pid:
            os.killpg(child.pid, signal.SIGTERM)
          else:
            child.terminate()
        except ProcessLookupError:
          pass
        try:
          child.wait(timeout=5)
        except subprocess.TimeoutExpired:
          try:
            if args.agentcfg_cli and child.poll() is None and os.getpgid(child.pid) == child.pid:
              os.killpg(child.pid, signal.SIGKILL)
            else:
              child.kill()
          except ProcessLookupError:
            pass
          child.wait()
      if child is not None:
        result["observed_exit"] = child.returncode
      if server:
        server.shutdown()
        server.server_close()
      for fd in (master, slave):
        if fd is not None:
          os.close(fd)
    source_names = ["scripts/smoke-dsh-ui.py", "src/agentcfg/dsh.py", "agents/dsh/templates/launch.mjs",
      "agents/dsh/packages/cursor-terminal/index.mjs", "agents/dsh/templates/theme-catppuccin.json"]
    if args.agentcfg_cli:
      source_names.extend(["agentcfg", "src/agentcfg/cli.py", "src/agentcfg/commands.py", "src/agentcfg/runtime.py",
        "src/agentcfg/backends.py", "src/agentcfg/dependencies.py", "src/agentcfg/runtime_packages.py", "src/agentcfg/deployment.py"])
    source = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in source_names}
    result.update(source_files=source, source_hash=hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest())
    (evidence / "transcript.log").write_bytes(transcript)
    (evidence / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"overall": result["overall"], "evidence": str(evidence)}, ensure_ascii=False))
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())
