#!/usr/bin/env python3
"""显式双 agentcfg CLI / 原生 TUI 并发验收；仅使用隔离 HOME 和本地假模型。"""

import argparse
import copy
from contextlib import ExitStack
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import uuid


class FixtureServer(ThreadingHTTPServer):
  daemon_threads = True


def fixture_snapshot(state):
  with state["gate"]:
    result = {"requests": state["requests"], "responses": sorted(state["responses"]), "error": state["error"]}
    if "request_observations" in state:
      result["request_observations"] = sorted(copy.deepcopy(state["request_observations"]),
        key=lambda item: item["sequence"])
    return result


def request_observation(body, sequence, category):
  # 仅合成本地请求的有界摘要；正文仅在内存中用于哈希/固定短语判别。
  messages = body.get("messages", [])
  roles = [item.get("role") for item in messages]
  system = json.dumps([item.get("content") for item in messages if item.get("role") == "system"],
    ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
  user = json.dumps([item.get("content") for item in messages if item.get("role") == "user"])

  def number(name):
    value = body.get(name)
    if value is None:
      return None
    if type(value) is int and value.bit_length() <= 64:
      return value
    if type(value) is float and math.isfinite(value) and abs(value) <= 1_000_000_000:
      return value
    return "invalid-or-out-of-range"

  tools = body.get("tools")
  return {"sequence": sequence, "stream": bool(body.get("stream")),
    "roles": [role if role in ("system", "developer", "user", "assistant", "tool", "function")
      else "other" for role in roles[:64]], "message_count": len(messages), "roles_truncated": len(roles) > 64,
    "tools_present": "tools" in body, "tool_count": len(tools) if isinstance(tools, list) else 0,
    "tool_calls_present": any("tool_calls" in item or "function_call" in item for item in messages),
    "tool_message_count": roles.count("tool"), "max_tokens": number("max_tokens"),
    "max_completion_tokens": number("max_completion_tokens"), "temperature": number("temperature"),
    "contains_one": "CONCURRENCY_ONE" in user, "contains_two": "CONCURRENCY_TWO" in user,
    "system_prompt_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
    "system_mentions_title": "title" in system.lower(),
    "system_mentions_summary": "summar" in system.lower(),
    "response_category": category, "response_written": False}


def handler(state, key):
  class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
      pass

    def do_POST(self):
      try:
        self.connection.settimeout(3)
        with state["gate"]:
          state["requests"] += 1
          sequence = state["requests"]
          observe_request = "request_observations" in state
          if sequence > 12:
            raise ValueError()
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 2 * 1024 * 1024 or self.headers.get("Authorization") != "Bearer " + key or self.path != "/v1/chat/completions":
          raise ValueError()
        body = json.loads(self.rfile.read(size))
        user = json.dumps([item.get("content") for item in body.get("messages", []) if item.get("role") == "user"])
        selected = [label for label in ("ONE", "TWO") if "CONCURRENCY_" + label in user]
        if len(selected) > 1:
          raise ValueError()
        keep_alive = "KEEP_ALIVE_AFTER_COLLISION" in user
        if keep_alive and selected != ["ONE"]:
          raise ValueError()
        content = "KEPT_ONE_ALIVE" if keep_alive else "DONE_" + selected[0] if selected else "AUXILIARY"
        observation = request_observation(body, sequence, content) if observe_request else None
        if observation is not None:
          with state["gate"]:
            if len(state["request_observations"]) >= 12:
              raise ValueError()
            state["request_observations"].append(observation)
        packet = {"id": "chatcmpl-concurrency", "object": "chat.completion.chunk", "created": 1,
                  "model": body.get("model"), "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}]}
        if not body.get("stream"):
          raw = json.dumps({**packet, "object": "chat.completion", "choices": [{"index": 0,
            "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}).encode()
          self.send_response(200)
          self.send_header("Content-Length", str(len(raw)))
          self.send_header("Content-Type", "application/json")
        else:
          raw = ("data: " + json.dumps(packet) + "\n\ndata: " + json.dumps({**packet,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}) + "\n\ndata: [DONE]\n\n").encode()
          self.send_response(200)
          self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)
        self.wfile.flush()
        with state["gate"]:
          if observation is not None:
            observation["response_written"] = True
          if selected:
            state["responses"].add("KEPT_ONE_ALIVE" if keep_alive else selected[0])
      except Exception:
        with state["gate"]:
          state["error"] = "FIXTURE_REQUEST_REJECTED"
        self.close_connection = True
  return Handler


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true", help="明确授权真实无账号宿主；缺省拒绝执行")
  parser.add_argument("--runtime", required=True, type=Path, help="匹配目标仓库完整锁与原收据的已封存包")
  parser.add_argument("--evidence", required=True, type=Path, help="新的私人证据目录")
  parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("需要 --allow-host；普通测试不启动第三方宿主")
  os.umask(0o077)
  repo, source = args.repository.resolve(), args.runtime.absolute()
  sys.path.insert(0, str(repo / "src"))
  from agentcfg import dependencies, runtime_packages
  from agentcfg.storage import ensure_private
  from agentcfg.workspace import load_workspace
  evidence = args.evidence.absolute()
  evidence.mkdir(mode=0o700, parents=True, exist_ok=False)
  ensure_private(evidence)
  result = {"kind": "two-real-cli-native-tui-local-provider", "overall": "FAIL", "stage": "prepare",
    "platform": sys.platform, "checks": {}, "commands": [], "processes": [], "real_model_calls": 0,
    "accounts": "NOT RUN", "same_session_resume_refusal": "NOT RUN", "jsonl_session_files": "NOT RUN"}
  children, server, key = [], None, "synthetic-" + uuid.uuid4().hex
  state = {"gate": threading.Lock(), "requests": 0, "responses": set(), "error": None}
  deadline = time.monotonic() + 240
  def budget(limit=60):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
      raise RuntimeError("OVERALL_TIMEOUT")
    return min(limit, remaining)
  def pump(seconds=0.05):
    masters = [child["master"] for child in children]
    for fd in select.select(masters, [], [], seconds)[0] if masters else []:
      try:
        next(child for child in children if child["master"] == fd)["output"].extend(os.read(fd, 65536))
      except OSError:
        pass
  def visible(child):
    text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", child["output"].decode(errors="replace"))
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
  def wait(child, predicate, seconds=60):
    until = time.monotonic() + budget(seconds)
    while not predicate() and time.monotonic() < until:
      if child["process"].poll() is not None:
        pump(0)
        if predicate():
          break
        raise RuntimeError("FIXTURE_OR_PROCESS_FAILED")
      if fixture_snapshot(state)["error"]:
        raise RuntimeError("FIXTURE_OR_PROCESS_FAILED")
      pump()
    if not predicate():
      raise RuntimeError("STAGE_TIMEOUT")
  def terminate(child):
    process = child["process"]
    if process.poll() is None:
      if os.getpgid(process.pid) != process.pid:
        raise RuntimeError("OWNED_GROUP_MISMATCH")
      os.killpg(process.pid, signal.SIGTERM)
      try:
        process.wait(timeout=3)
      except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
  def stop_children():
    for child in children:
      try:
        terminate(child)
      except (OSError, RuntimeError, subprocess.TimeoutExpired):
        result.update(overall="FAIL", cleanup="OWNED_CHILD_CLEANUP_FAILED")
  def cli(command, expected=0):
    argv = [str(repo / "agentcfg"), "--local", str(machine), "--profile", "dsh-default", command]
    completed = subprocess.run(argv, cwd=project, env=env, capture_output=True, timeout=budget())
    name = f"cli-{len(result['commands'])}-{command}.log"
    (evidence / name).write_bytes((completed.stdout + completed.stderr).replace(key.encode(), b"<fixture-key>"))
    result["commands"].append({"argv": argv, "exit": completed.returncode, "log": name})
    if completed.returncode != expected:
      raise RuntimeError("CLI_EXIT_MISMATCH")
  try:
    lock = dependencies.read_lock(repo)
    def verify(path):
      if runtime_packages.status(path, lock.identity) != "installed" or any(
          ((path / name).read_bytes() if (path / name).exists() else b"") != value for name, value in
          (("package.json", lock.package), ("package-lock.json", lock.resolution), ("pnpm-lock.yaml", lock.installer_resolution))):
        raise RuntimeError("SEALED_RUNTIME_MISMATCH")
    verify(source)
    original_receipt = (source / ".agentcfg-receipt.json").read_bytes()
    result.update(lock_identity=lock.identity, recipe=lock.metadata["recipe"])
    public = sorted((repo / "src/agentcfg").glob("*.py")) + sorted((repo / "agents/dsh/templates").glob("*")) + [repo / "agentcfg"]
    digests = {str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest() for path in public if path.is_file()}
    result.update(source_files=digests, source_sha256=hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest(),
      harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    with tempfile.TemporaryDirectory(prefix="rotom-dsh-concurrency-") as temporary, ExitStack() as cleanup:
      cleanup.callback(stop_children)
      root = Path(temporary)
      env = {"PATH": os.environ.get("PATH", ""), "TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": "C.UTF-8"}
      for name, suffix in {"HOME": "home", "DSH_HOME": "dsh", "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data",
          "XDG_STATE_HOME": "state", "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp"}.items():
        env[name] = str(root / suffix)
        ensure_private(root / suffix)
      os.environ.clear()
      os.environ.update(env)
      result["candidate_commit"] = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], env=env,
        capture_output=True, text=True, check=True, timeout=budget(5)).stdout.strip()
      node = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True, check=True, timeout=budget(5)).stdout.strip()
      if node != lock.metadata["node"]:
        raise RuntimeError("NODE_VERSION")
      result["node"] = node
      project = root / "project"
      ensure_private(project)
      server = FixtureServer(("127.0.0.1", 0), handler(state, key))
      threading.Thread(target=lambda: server.serve_forever(poll_interval=0.1), daemon=True).start()
      machine = root / "machine.toml"
      machine.write_text('schema_version=1\n[machine]\nid="concurrency-fixture"\n[overrides.providers.fixture]\n'
        'protocol="openai-compatible"\nauth_kind="api-key"\ncredential_ref="secret:fixture"\n'
        f'base_url="http://127.0.0.1:{server.server_port}/v1"\n[overrides.models.fixture]\n'
        'provider="fixture"\nremote_id="fixture-not-real"\ninput=["text"]\n[overrides.profiles.dsh-default]\n'
        'providers=["fixture"]\nmodels=["fixture"]\n[overrides.profiles.dsh-default.roles]\nmain="fixture"\n'
        '[overrides.profiles.dsh-default.agent_options]\nshow_welcome=false\n[secrets]\n'
        f'fixture={json.dumps(key)}\n')
      machine.chmod(0o600)
      workspace = load_workspace(machine, repository=repo)
      candidate = workspace.candidate(lock.identity)
      result.update(config_generation=candidate.generation, config_sha256=hashlib.sha256(machine.read_bytes().replace(key.encode(), b"<fixture-key>")).hexdigest())
      destination = workspace.backend.root(workspace, lock.identity)
      if not destination.is_relative_to(root):
        raise RuntimeError("ISOLATION_BOUNDARY")
      ensure_private(destination.parent)
      shutil.copytree(source, destination, symlinks=True)
      verify(destination)
      cli("apply")
      cli("sync")
      marker = workspace.instance / "user-home/.dsh-tui/resume.txt"
      def session_id():
        value = (marker.read_text().strip() or None) if marker.exists() else None
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
          raise RuntimeError("SESSION_MARKER_INVALID")
        return value
      # 上游 dsh-base 配方及 JSONL README：sessions/<project>/<id>/session.vN.jsonl[.zstd]。
      sessions = workspace.instance / "dsh-home/sessions"
      def session_records():
        return {path.parent.name: path for path in sessions.glob("*/*/session*.jsonl*")
          if re.fullmatch(r"session(?:\.v[1-9][0-9]*)?\.jsonl(?:\.zstd)?", path.name)
          and path.is_file() and not path.is_symlink() and not path.parent.is_symlink()}
      def launch(label, argv):
        master, slave = pty.openpty()
        child = {"master": master, "slave": slave, "before": termios.tcgetattr(slave), "output": bytearray(), "label": label}
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
        child["process"] = subprocess.Popen(argv, cwd=project, env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        children.append(child)
        return child
      def close_panel(child, record):
        os.write(child["master"], b"\x03")
        until = time.monotonic() + 0.3
        while time.monotonic() < until:
          pump()
        if child["process"].poll() is None:
          os.write(child["master"], b"\x03")
        wait(child, lambda: child["process"].poll() is not None, 10)
        record.update(exit=child["process"].returncode, termios_restored=child["before"] == termios.tcgetattr(child["slave"]))
        if not record["termios_restored"]:
          raise RuntimeError("EXIT_TERMIOS")
      def stable_requests():
        count, stable_until, until = fixture_snapshot(state)["requests"], time.monotonic() + 1, time.monotonic() + budget(5)
        while time.monotonic() < stable_until:
          pump()
          if fixture_snapshot(state)["error"] or time.monotonic() > until:
            raise RuntimeError("PROVIDER_NOT_QUIET")
          observed_count = fixture_snapshot(state)["requests"]
          if observed_count != count:
            count, stable_until = observed_count, time.monotonic() + 1
        return count
      for label in ("ONE", "TWO"):
        result["stage"] = "launch_" + label
        prior, known = session_id(), set(session_records())
        argv = [str(repo / "agentcfg"), "--local", str(machine), "--profile", "dsh-default", "run", "--cwd", str(project)]
        child = launch(label, argv)
        master, slave = child["master"], child["slave"]
        record = {"label": label, "argv": argv, "resume_before_start": prior}
        result["processes"].append(record)
        wait(child, lambda: not termios.tcgetattr(slave)[3] & termios.ICANON and "fixture-not-real" in visible(child))
        record["resume_after_start"] = session_id()
        os.write(master, ("\x1b[200~CONCURRENCY_" + label + "\x1b[201~").encode())
        wait(child, lambda: "CONCURRENCY_" + label in re.sub(r"\s+", "", visible(child)), 5)
        os.write(master, b"\r")
        wait(child, lambda: label in fixture_snapshot(state)["responses"] and "DONE_" + label in re.sub(r"\s+", "", visible(child)))
        wait(child, lambda: len(set(session_records()) - known) == 1, 10)
        record["session_id"] = (set(session_records()) - known).pop()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", record["session_id"]):
          raise RuntimeError("SESSION_MARKER_INVALID")
      if len({item["session_id"] for item in result["processes"]}) != 2 or any(child["process"].poll() is not None for child in children):
        raise RuntimeError("DISTINCT_ACTIVE_SESSIONS")
      if any("DONE_" + other in re.sub(r"\s+", "", visible(child)) for child, other in zip(children, ("TWO", "ONE"))):
        raise RuntimeError("MIXED_SESSION_OUTPUT")
      result["checks"].update(distinct_native_sessions="PASS", isolated_plaintext_responses="PASS")
      hosts = tuple(children)
      result["stage"] = "same_session_resume"
      expected_sessions = {row["session_id"] for row in result["processes"]}
      before_collision = stable_requests()
      collision_argv = [*result["processes"][0]["argv"], "--", "--resume", result["processes"][0]["session_id"]]
      collision = launch("COLLISION", collision_argv)
      result["collision"] = {"argv": collision_argv, "target_session_id": result["processes"][0]["session_id"], "requests_before": before_collision}
      phrases = (result["processes"][0]["session_id"], "it is mounted by another TUI terminal", "two processes driving one session log would corrupt it.")
      wait(collision, lambda: all(phrase in " ".join(visible(collision).split()) for phrase in phrases))
      if set(session_records()) != expected_sessions or stable_requests() != before_collision:
        raise RuntimeError("COLLISION_CREATED_SESSION_OR_REQUEST")
      close_panel(collision, result["collision"])
      if set(session_records()) != expected_sessions or stable_requests() != before_collision:
        raise RuntimeError("COLLISION_EXIT_CHANGED_SESSION_OR_REQUEST")
      result["collision"].update(occupied_notice_verified=True, canonical_sessions_unchanged=True, requests_after=fixture_snapshot(state)["requests"])
      result["stage"] = "keep_alive_after_collision"
      os.write(hosts[0]["master"], b"\x1b[200~KEEP_ALIVE_AFTER_COLLISION\x1b[201~")
      wait(hosts[0], lambda: "KEEP_ALIVE_AFTER_COLLISION" in re.sub(r"\s+", "", visible(hosts[0])), 5)
      os.write(hosts[0]["master"], b"\r")
      wait(hosts[0], lambda: "KEPT_ONE_ALIVE" in fixture_snapshot(state)["responses"] and "KEPT_ONE_ALIVE" in re.sub(r"\s+", "", visible(hosts[0])))
      if any(child["process"].poll() is not None for child in hosts) or set(session_records()) != expected_sessions:
        raise RuntimeError("ORIGINAL_HOSTS_NOT_PRESERVED")
      result["same_session_resume_refusal"] = "PASS"
      result["checks"]["collision_refused_and_original_hosts_preserved"] = "PASS"
      result["stage"] = "both_active_maintenance"
      cli("apply", 4)
      result["checks"]["maintenance_blocked_both_active"] = "PASS"
      for index, child in enumerate(hosts):
        result["stage"] = "exit_" + child["label"]
        close_panel(child, result["processes"][index])
        if child["process"].returncode != 0:
          raise RuntimeError("EXIT_OR_TERMIOS")
        if session_id() != result["processes"][index]["session_id"]:
          raise RuntimeError("EXIT_RESUME_MISMATCH")
        artifact = session_records()[session_id()]
        result["processes"][index].update(resume_after_exit=session_id(),
          session_artifact=artifact.relative_to(sessions).as_posix(), session_artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())
        if index == 0:
          if hosts[1]["process"].poll() is not None:
            raise RuntimeError("SECOND_NOT_ALIVE")
          cli("apply", 4)
          result["checks"]["first_exit_preserves_second_lease"] = "PASS"
      cli("apply")
      result["jsonl_session_files"] = "PASS: canonical fixture artifacts; compressed bodies not decoded"
      result["checks"].update(both_clean_exits_termios_restored="PASS", final_maintenance="PASS")
      verify(source)
      if (source / ".agentcfg-receipt.json").read_bytes() != original_receipt:
        raise RuntimeError("SOURCE_RUNTIME_CHANGED")
      result["checks"]["source_runtime_unchanged"] = "PASS"
      result.update(overall="PASS", stage="complete")
  except Exception:
    result.update(error="CONCURRENCY_SMOKE_FAILED", error_location=result["stage"])
  finally:
    stop_children()
    pump(0)
    for child in children:
      result.setdefault("observed_exits", {})[child["label"]] = child["process"].poll()
      (evidence / (child["label"] + ".pty.log")).write_bytes(bytes(child["output"]).replace(key.encode(), b"<fixture-key>"))
      os.close(child["master"])
      os.close(child["slave"])
    if server:
      server.shutdown()
      server.server_close()
    observed_fixture = fixture_snapshot(state)
    result.update(fixture_requests=observed_fixture["requests"], fixture_responses=observed_fixture["responses"], fixture_error=observed_fixture["error"])
    if fixture_snapshot(state)["error"]:
      result.update(overall="FAIL", error="FIXTURE_REQUEST_REJECTED")
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
  print(json.dumps({"overall": result["overall"], "evidence": str(evidence)}))
  return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())
