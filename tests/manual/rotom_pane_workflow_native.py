"""显式授权的真实 Herdr/官方 Agent 位置维护链路；默认 pytest 不收集，不向终端输入。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import struct
import subprocess
import sys
import termios
import threading
import time
import uuid


REPO = Path(__file__).resolve().parents[2]
SID = "12345678-1234-4234-8234-123456789abc"
ROOT = Path("/p")
sys.path.insert(0, str(REPO / "src"))
sys.dont_write_bytecode = True


def save(name, value):
  path = ROOT / name
  path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
  path.chmod(0o600)


def wait_for(check, label, timeout=60):
  until = time.monotonic() + timeout
  while time.monotonic() < until:
    value = check()
    if value:
      return value
    time.sleep(0.05)
  raise RuntimeError("timeout: " + label)


def configure(session, thinking="medium", tool="pi", pi_profile="pi-base", dsh_url=None, pi_base_cursor=False):
  document = ('schema_version=1\n[machine]\nid="pane-native-fixture"\ndefault_profile="pi-base"\n'
    '[machine.paths]\ninstances_root="/p/i"\nstate_root="/p/a"\ncache_root="/p/cache"\n'
    '[machine.work]\nherdr_binary="/opt/herdr"\nsession="' + session + '"\npi_profile="pi-base"\n'
    '[overrides.providers.fixture]\nprotocol="openai-compatible"\nauth_kind="api-key"\n'
    'credential_ref="secret:fixture"\nbase_url="https://example.invalid/v1"\n'
    '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fictional-chat"\ninput=["text"]\n'
    '[overrides.profiles.pi-base]\nproviders=["fixture"]\nmodels=["fixture"]\n'
    '[overrides.profiles.pi-base.roles]\nmain="fixture"\n'
    '[overrides.profiles.pi-base.agent_options.settings]\ndefaultThinkingLevel="' + thinking + '"\n'
    '[secrets]\nfixture="SYNTHETIC_NATIVE_FIXTURE"\n')
  if tool != "pi":
    profile = tool + "-default"
    roles = ("main",) if tool == "dsh" else ("main", "smol", "slow", "plan", "task", "advisor", "vision")
    options = ('[overrides.profiles.dsh-default.agent_options]\nshow_welcome=false\nterminal_images=' +
      ('true' if thinking == "low" else 'false') + '\n' if tool == "dsh" else
      '[overrides.profiles.omp-default.agent_options.ui]\ntheme_dark="' +
      ('light-catppuccin' if thinking == "low" else 'dark-catppuccin') + '"\n')
    document = ('schema_version=1\n[machine]\nid="pane-native-fixture"\ndefault_profile="' + profile + '"\n'
      '[machine.paths]\ninstances_root="/p/i"\nstate_root="/p/a"\ncache_root="/p/cache"\n'
      '[machine.work]\nherdr_binary="/opt/herdr"\nsession="' + session + '"\n'
      + ('dsh_profile="dsh-default"\n' if tool == "dsh" else '') +
      '[overrides.providers.fixture]\nprotocol="openai-compatible"\nauth_kind="api-key"\n'
      'credential_ref="secret:fixture"\nbase_url="' + (dsh_url or "http://127.0.0.1:9/v1") + '"\n' +
      '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture-not-real"\ninput=' +
      ('["text","image"]\n' if tool == "omp" else '["text"]\n') +
      'context_window=32768\nmax_output_tokens=4096\n'
      '[overrides.profiles.' + profile + ']\nproviders=["fixture"]\nmodels=["fixture"]\n'
      '[overrides.profiles.' + profile + '.roles]\n' + ''.join(role + '="fixture"\n' for role in roles) + options +
      '[secrets]\nfixture="SYNTHETIC_NATIVE_FIXTURE"\n')
  if tool == "pi" and pi_base_cursor:
    document = document.replace('providers=["fixture"]\nmodels=["fixture"]',
      'providers=["fixture","cursor"]\nplugins=["pi-footer","pi-cursor"]\nmodels=["fixture"]')
  if tool == "pi": document = document.replace("pi-base", pi_profile)
  for path in (ROOT / "m.toml", ROOT / "h/.config/agentcfg/machines/default.toml"):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(document)
    path.chmod(0o600)


def environment():
  os.umask(0o077)
  if (ROOT / "h/.omp/natives").exists(): (ROOT / "h/.omp/natives").chmod(0o700)
  for path in (ROOT / "i", ROOT / "cache"):
    path.chmod(0o700)
  paths = {"HOME": ROOT / "h", "XDG_CONFIG_HOME": ROOT / "h/.config", "XDG_DATA_HOME": ROOT / "d",
    "XDG_STATE_HOME": ROOT / "s", "XDG_CACHE_HOME": ROOT / "c", "XDG_RUNTIME_DIR": ROOT / "x", "TMPDIR": ROOT / "t"}
  for path in [*paths.values(), ROOT / "project", ROOT / "logs"]:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
  audit = ROOT / "audit"
  audit.mkdir(mode=0o700)
  # 公开 Python 启动钩子只记录仓库 shell 初始终端属性；不修改 Agent 或运行逻辑。
  (audit / "sitecustomize.py").write_text(
    "import json, os, sys, termios\n"
    "if os.path.basename(sys.argv[0]) == 'rotom-work-shell' and os.isatty(0):\n"
    "  with open('/p/tty-start-' + str(os.getpid()) + '.json', 'w') as stream:\n"
    "    json.dump(termios.tcgetattr(0), stream, default=lambda item: list(item))\n"
    "if os.environ.get('ROTOM_PANE_DIAGNOSTIC') == '1' or (os.environ.get('ROTOM_PANE_INITIAL_DIAGNOSTIC') == '1' and sys.argv[0] == '-c' and '--here' in sys.argv) or (os.environ.get('ROTOM_PANE_RESTORE_DIAGNOSTIC') == '1' and os.path.basename(sys.argv[0]) == 'restore_child.py'):\n"
    f"  _owned_prefix = {str(REPO / 'src/agentcfg') + '/'!r}\n"
    "  def _trace(frame, event, arg):\n"
    "    if event == 'exception' and frame.f_code.co_filename.startswith(_owned_prefix):\n"
    "      with open('/p/diagnostic.jsonl', 'a') as stream:\n"
    "        stream.write(json.dumps({'file': os.path.basename(frame.f_code.co_filename), 'line': frame.f_lineno,\n"
    "          'function': frame.f_code.co_name, 'exception': arg[0].__name__}) + '\\n')\n"
    "    return _trace\n"
    "  sys.settrace(_trace)\n"
    "if os.environ.get('ROTOM_PANE_STOP_DIAGNOSTIC') == '1':\n"
    f"  _owned_prefix = {str(REPO / 'src/agentcfg') + '/'!r}\n"
    "  _stop_stage = os.environ.get('ROTOM_PANE_STOP_STAGE', '2')\n"
    "  _selected = {'manager_exit.py', 'dsh_stop_client.py', 'dsh_stop_completion.py', 'stop_locks.py', 'run_owners.py'}\n"
    "  def _stop_trace(frame, event, arg):\n"
    "    filename = frame.f_code.co_filename\n"
    "    if event == 'exception' and filename.startswith(_owned_prefix) and (_stop_stage == '3' or os.path.basename(filename) in _selected):\n"
    "      with open('/p/stop' + _stop_stage + '-diagnostic.jsonl', 'a') as stream:\n"
    "        stream.write(json.dumps({'file': os.path.basename(filename), 'line': frame.f_lineno,\n"
    "          'function': frame.f_code.co_name, 'exception': arg[0].__name__}) + '\\n')\n"
    "    return _stop_trace\n"
    "  sys.settrace(_stop_trace)\n"
    "if os.environ.get('ROTOM_PANE_CONTROL_DIAGNOSTIC') == '1' and (os.path.basename(sys.argv[0]) == 'restore_child.py' or (sys.argv[0] == '-c' and '--here' in sys.argv)):\n"
    f"  _owned_prefix = {str(REPO / 'src/agentcfg') + '/'!r}\n"
    "  _selected_control = {'dsh_stop_control.py', 'dsh_process.py', 'run_owners.py', 'spawned_host.py', 'stop_service.py', 'stop_inbox.py', 'tool_sessions.py'}\n"
    "  def _control_trace(frame, event, arg):\n"
    "    name = os.path.basename(frame.f_code.co_filename)\n"
    "    if frame.f_code.co_filename.startswith(_owned_prefix) and name in _selected_control:\n"
    "      value = {'file': name, 'line': frame.f_lineno, 'function': frame.f_code.co_name, 'event': event}\n"
    "      if event == 'exception':\n"
    "        value['exception'] = arg[0].__name__\n"
    "      elif event == 'return' and name == 'dsh_stop_control.py' and frame.f_code.co_name in ('supported', 'default_factory', 'factory'):\n"
    "        value.update(return_type=type(arg).__name__, returned_none=arg is None, returned_true=arg is True)\n"
    "      else:\n"
    "        return _control_trace\n"
    "      with open('/p/control-diagnostic-' + str(os.getpid()) + '.jsonl', 'a') as stream:\n"
    "        stream.write(json.dumps(value) + '\\n')\n"
    "    return _control_trace\n"
    "  sys.settrace(_control_trace)\n")
  os.environ.clear()
  os.environ.update({key: str(value) for key, value in paths.items()})
  os.environ.update(PATH=str(REPO) + os.pathsep + str(REPO / ".venv/bin") + ":/opt/node/bin:/usr/bin:/bin", TERM="xterm-256color", LANG="C.UTF-8",
    PYTHONPATH=str(audit) + os.pathsep + str(REPO / "src"), PYTHONDONTWRITEBYTECODE="1", SHELL=str(ROOT / "probe-shell"))


def inside(args):
  from agentcfg import commands, run_owners
  from agentcfg.workspace import load_workspace
  from agentcfg.storage import Tree, instance_lock
  from termcfg.herdr import Deadline, HerdrClient, discover
  from termcfg.work import source_digest
  from rotom import pane_dispatch
  import rotom_herdr_pane_native as native
  environment()
  if args.diagnose: os.environ["ROTOM_PANE_DIAGNOSTIC"] = "1"
  if args.diagnose_control: os.environ["ROTOM_PANE_CONTROL_DIAGNOSTIC"] = "1"
  if args.diagnose_initial: os.environ["ROTOM_PANE_INITIAL_DIAGNOSTIC"] = "1"
  if args.diagnose_restore: os.environ["ROTOM_PANE_RESTORE_DIAGNOSTIC"] = "1"
  sid = args.session_id or SID
  marker = "DONE_ONE" if args.tool == "dsh" else "SYNTHETIC_HISTORY_NO_CONTINUATION"
  project = Path("/probe/project") if args.tool == "dsh" else ROOT / "project"
  fixture_server = fixture_thread = fixture = None
  dsh_url = None
  if args.tool == "dsh" and not args.prepare_only:
    import importlib.util
    specification = importlib.util.spec_from_file_location("pane_native_model_fixture", REPO / "scripts/smoke-dsh-concurrency.py")
    fixture_module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(fixture_module)
    fixture = {"gate": threading.Lock(), "requests": 0, "responses": set(), "error": None, "request_observations": []}
    fixture_server = fixture_module.FixtureServer(("127.0.0.1", 0), fixture_module.handler(fixture, "SYNTHETIC_NATIVE_FIXTURE"))
    fixture_thread = threading.Thread(target=fixture_server.serve_forever, daemon=True)
    fixture_thread.start()
    dsh_url = "http://127.0.0.1:" + str(fixture_server.server_port) + "/v1"
  session = "pw-" + uuid.uuid4().hex[:10]
  configure(session, tool=args.tool, pi_profile=args.profile, dsh_url=dsh_url, pi_base_cursor=args.pi_base_cursor)
  profile = args.profile if args.tool == "pi" else args.tool + "-default"
  ws = load_workspace(ROOT / "m.toml", profile, repository=REPO)
  lock = ws.backend.read_lock(REPO)
  runtime_identity = getattr(ws.backend, "runtime_identity", None)
  identity = runtime_identity(ws, lock) if runtime_identity is not None else lock.identity
  evidence = {"commands": [], "lock": lock.identity, "runtime": identity, "source": source_digest(REPO),
    "agent": args.tool, "diagnose": args.diagnose, "diagnose_stop2": args.diagnose_stop2,
    "diagnose_stop3": args.diagnose_stop3, "diagnose_control": args.diagnose_control,
    "paired": args.paired, "diagnose_initial": args.diagnose_initial, "diagnose_restore": args.diagnose_restore, "input_bytes": 0, "load_confirmation": "unknown", "continue_status": "not_sent"}
  from termcfg.work import LAUNCH_FILES
  evidence["candidate_sources"] = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in LAUNCH_FILES}
  names = (("locks/pi/manifest.json", "locks/pi/" + profile + "/package.json", "locks/pi/" + profile + "/package-lock.json")
    if args.tool == "pi" else ("locks/" + args.tool + "/manifest.json",))
  evidence["lock_sources"] = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in names}
  evidence["node_version"] = subprocess.run(["node", "--version"], capture_output=True, text=True, check=True).stdout.strip()
  server = client = server_identity = None
  terminals, owned = [], []
  prefix = ["--no-input", "agent", "--local", str(ws.local_path), "--profile", ws.profile, "maintenance"]
  cli = [str(REPO / ".venv/bin/python"), "-B", "-c", "from rotom.cli import main; raise SystemExit(main())"]
  def call(label, tokens, expected=0, context=None, json_output=True):
    env = dict(os.environ)
    env.update(context or {})
    if (args.diagnose_stop2 and label == "stop-2") or (args.diagnose_stop3 and label == "stop-3"):
      env.update(ROTOM_PANE_STOP_DIAGNOSTIC="1", ROTOM_PANE_STOP_STAGE="2" if label == "stop-2" else "3")
    argv = [*cli, *tokens]
    started = time.monotonic()
    completed = subprocess.run(argv, cwd=project, env=env, capture_output=True, timeout=120)
    (ROOT / "logs" / (label + ".stdout")).write_bytes(completed.stdout)
    (ROOT / "logs" / (label + ".stderr")).write_bytes(completed.stderr)
    evidence["commands"].append({"label": label, "argv": argv, "exit_code": completed.returncode,
      "elapsed_seconds": time.monotonic() - started})
    save("calls.json", evidence["commands"])
    if completed.returncode != expected:
      raise RuntimeError(label + ":exit=" + str(completed.returncode))
    return (json.loads(completed.stdout) if completed.stdout.strip() else None) if json_output else completed.stdout.decode()
  def maintenance(label, action, *tokens):
    return call(label, [*prefix, action, *tokens, "--format", "json"])
  startup_locations = {}
  initial_metadata_poll = args.tool == "omp"
  def records():
    if initial_metadata_poll:
      # 仅 OMP 初始只读高频探针，避免验收自身争抢短 EX；ready 后正式复核。
      return {path.stem: json.loads(path.read_text()) for path in (ws.state_root / "run-owners").glob("*.json")}
    return run_owners.Registry(ws.state_root / "run-owners", ws.binding).snapshot()
  def begin_startup_observation():
    nonlocal initial_metadata_poll
    initial_metadata_poll = args.tool == "omp"
  def confirm_initial_records(runs):
    nonlocal initial_metadata_poll
    initial_metadata_poll = False
    rows = records()
    for run in runs:
      row = rows[run]
      host = row.get("host_identity")
      if (host is None or run_owners.observed_process_identity(row["manager_identity"]["pid"]) != row["manager_identity"]
          or run_owners.observed_process_identity(host["identity"]["pid"]) != host["identity"]):
        raise RuntimeError("initial native owner identity changed after ready")
      if run in startup_locations:
        actual = pane_dispatch.container_for(ws, run)
        expected = startup_locations[run]
        keys = ("container_id", "scope", "terminal_ref", "manager_identity", "child_identity")
        if actual is None or any(actual[1][key] != expected[key] for key in keys):
          raise RuntimeError("startup container differs from formal owner observation")
  run_sessions, run_markers = {}, {}
  def observed(run):
    expected_sid = run_sessions.get(run, sid)
    if args.tool != "pi":
      row = records()[run]
      if row.get("host_identity") is None: return None
      proc = Path("/proc") / str(row["host_identity"]["identity"]["pid"])
      try:
        argv = (proc / "cmdline").read_bytes().decode().split("\0")
        cwd = os.readlink(proc / "cwd")
      except (OSError, ValueError): return None
      native_file = None
      if args.tool == "omp":
        from agentcfg.tool_session_headers import lookup
        native_file = str(lookup(ws, expected_sid).path)
        selected = any(argv[index:index + 2] == ["--resume", native_file] for index in range(len(argv) - 1))
      else:
        selected = expected_sid in argv
      return {"requested_session": expected_sid, "native_session_file": native_file, "cwd": cwd,
        "source": "native-argv-and-kernel-cwd", "confirmation": "unknown"} if selected and cwd == str(project) else None
    path = ws.state_root / "pi-session-observations" / (run + ".json")
    if not path.exists(): return None
    value = json.loads(path.read_text())
    return value if value.get("session_id") == expected_sid and value.get("cwd") == str(project) else None
  def container(run):
    if initial_metadata_poll:
      from agentcfg.pane_records import ContainerStore
      owner = records().get(run)
      if owner is None: return None
      scope = {"local": str(ws.local_path), "profile": ws.profile, "agent": ws.agent}
      found = []
      for path in (ROOT / "s/rotom/panes").glob("*/container.json"):
        value = ContainerStore(path.parent, path.parent.name).read()
        if (value is not None and value["scope"] == scope and value["state"] == "running"
            and value["child_identity"] == owner["manager_identity"]
            and value["run_id"] in (None, run)
            and run_owners.observed_process_identity(value["manager_identity"]["pid"]) == value["manager_identity"]):
          found.append((path.parent, value))
      if len(found) > 1: raise RuntimeError("startup container ownership not unique")
      if found:
        startup_locations[run] = found[0][1]
        return found[0]
      return None
    found = pane_dispatch.container_for(ws, run)
    return found if found is not None else None
  def ready(run, reference=None):
    from agentcfg.dsh_stop_control import available
    row = records()[run]
    expected_marker = run_markers.get(run, marker)
    if row.get("host_identity") is None or not available(ws, row): return None
    if reference is None:
      terminal = next((item for item in terminals if item[0].pid == row["manager_identity"]["pid"]), None)
      if terminal is None or expected_marker.encode() not in terminal[4]: return None
      if termios.tcgetattr(terminal[2])[3] & termios.ICANON: return None
    else:
      observed_pane = native.native_request(client, ROOT, "pane.read", {"pane_id": reference["pane_id"],
        "source": "recent", "lines": 200, "strip_ansi": True})
      if expected_marker not in observed_pane["read"]["text"]: return None
      path = Path("/proc") / str(row["manager_identity"]["pid"]) / "fd/0"
      try:
        fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
        try:
          if termios.tcgetattr(fd)[3] & termios.ICANON: return None
        finally: os.close(fd)
      except (OSError, termios.error): return None
    return row
  def start_initial(tokens):
    import fcntl
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 110, 0, 0))
    before = termios.tcgetattr(slave)
    child = subprocess.Popen([*cli, *tokens], stdin=slave, stdout=slave, stderr=slave,
      cwd=project, start_new_session=True, close_fds=True)
    birth = run_owners.observed_process_identity(child.pid)
    if birth is None: raise RuntimeError("initial child birth unavailable")
    owned.append(birth)
    output = bytearray()
    def drain():
      while child.poll() is None:
        ready, _, _ = select.select([master], [], [], 0.1)
        if ready:
          try: output.extend(os.read(master, 65536))
          except OSError: break
    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    terminals.append((child, master, slave, before, output, thread))
    evidence["commands"].append({"label": "initial-resume", "argv": [*cli, *tokens], "identity": birth})
    return child
  def workflow(run, number, thinking):
    configure(session, thinking, tool=args.tool, pi_profile=args.profile, dsh_url=dsh_url, pi_base_cursor=args.pi_base_cursor)
    runs = [run] if isinstance(run, str) else list(run)
    selectors = []
    for selected in runs:
      selectors += ["--run", selected, "--session", selected + "=" + run_sessions.get(selected, sid),
        "--label", selected + "=Synthetic history"]
    plan = maintenance(f"plan-{number}", "plan", *selectors)
    stopped = maintenance(f"stop-{number}", "stop", *selectors, "--plan-id", plan["plan_id"])
    batch = stopped["batch_id"]
    if args.diagnose_stop2 and number == 2:
      evidence["diagnostic_stop2"] = stopped
      return batch
    for selected in runs:
      final_owner = wait_for(lambda: row if (row := records()[selected])["lifecycle_state"] == "idle_confirmed"
        and row["process_observation"]["coverage"] == "complete" else None, "complete stop owner")
      wait_for(lambda: run_owners.observed_process_identity(final_owner["manager_identity"]["pid"]) != final_owner["manager_identity"],
        "single-run CLI exit before setup")
      if container(selected) is not None:
        wait_for(lambda: found if (found := container(selected)) and found[1]["state"] == "parked" else None,
          "resident parked before setup")
    preview = maintenance(f"setup-plan-{number}", "plan", "--batch", batch)
    updated = maintenance(f"execute-{number}", "execute", "--batch", batch, "--plan-id", preview["setup_preview"]["plan_id"])
    if updated["status"] != "updated": raise RuntimeError("actual setup did not update")
    if args.tool == "pi" and json.loads((ws.instance / "pi-home/settings.json").read_text())["defaultThinkingLevel"] != thinking:
      raise RuntimeError("actual settings update missing")
    return batch
  def restore_tokens(batch, run, location):
    selection = ["--run", run] if isinstance(run, str) else ["--all"]
    return ["--no-input", "resume", args.tool, "--local", str(ws.local_path), "--profile", ws.profile,
      "--stopped", "--batch", batch, *selection, "--" + location,
      "--wait-seconds", str(args.restore_wait_seconds), "--format", "json"]
  def start_herdr():
    nonlocal server, server_identity, client
    import shlex
    wrapper = ROOT / "probe-shell"
    wrapper.write_text("#!/bin/sh\nexec " + shlex.join([sys.executable, "-B", str(REPO / "tests/manual/rotom_herdr_pane_native.py"),
      "--shell-probe", str(ROOT)]) + "\n")
    wrapper.chmod(0o700)
    config = ROOT / "h/.config/herdr/config.toml"
    config.parent.mkdir(mode=0o700)
    config.write_text('[terminal]\ndefault_shell="rotom-work-shell"\nshell_mode="non_login"\n'
      '[session]\nresume_agents_on_restore=false\n[update]\nversion_check=false\nmanifest_check=false\n')
    from termcfg.work_config import read_settings, validate_native_config
    from termcfg.herdr import native_inputs, observe_process, record_startup_evidence
    validate_native_config(Path("/opt/herdr"), Deadline(10))
    settings = read_settings(local=ws.local_path)
    startup_inputs = native_inputs(settings, Path("/opt/herdr"), Deadline(10))
    with (ROOT / "logs/herdr.stdout").open("wb") as output, (ROOT / "logs/herdr.stderr").open("wb") as errors:
      argv = ["/opt/herdr", "--session", session, "server"]
      server = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
        start_new_session=True, close_fds=True, umask=0o077)
    server_identity = run_owners.observed_process_identity(server.pid)
    if server_identity is None: raise RuntimeError("server birth unavailable")
    evidence["commands"].append({"label": "herdr-server", "argv": argv, "identity": server_identity})
    discovered = wait_for(lambda: discover(Path("/opt/herdr"), session, Deadline(5)), "own Herdr endpoint")
    client = HerdrClient(discovered["socket_path"], Deadline(30))
    client.expected_peer_pid = server.pid
    evidence["herdr_ping"] = client.request("ping", {})
    evidence["startup_evidence"] = record_startup_evidence(client, settings, Path("/opt/herdr"),
      observe_process(server.pid), startup_inputs)
    native.native_request(client, ROOT, "workspace.create", {"cwd": str(project), "label": "pane-workflow", "focus": False, "env": {}})
    shell_path = wait_for(lambda: next(ROOT.glob("shell-*.json"), None), "control shell bootstrap")
    shell = json.loads(shell_path.read_text())
    if not all(shell["tty"]): raise RuntimeError("Herdr control shell lacks PTY")
    return {key: value for key, value in shell["bootstrap"].items() if value is not None}
  def work_entry():
    # 仅公开 work CLI；全新会话不声明 SID 恢复或加载确认。
    if args.work_entry_only == "v1":
      subprocess.run(["/usr/bin/git", "init", "-q", str(project)], check=True,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}, capture_output=True)
    else:
      for path in (ROOT / "m.toml", ROOT / "h/.config/agentcfg/machines/default.toml"):
        text = path.read_text().replace('[machine.work]\n',
          '[machine.work]\nmodel="structured-v1"\ninclude_rotom=false\n'
          'workspaces=[{kind="project",path="' + str(project) + '",mode="directory",template="fixture"}]\n')
        text += ('[machine.work.templates.fixture]\norder=["shell","agent"]\ninitial="shell"\n'
          '[machine.work.templates.fixture.tab_types.shell]\nlabel="Shell"\nlauncher="shell"\n'
          '[machine.work.templates.fixture.tab_types.agent]\nlabel="Agent"\nlauncher="' + args.tool + '"\n')
        path.write_text(text)
    context = start_herdr()
    existing = set(ROOT.glob("shell-*.json"))
    work = ["--no-input", "work", "--local", str(ws.local_path)]
    call("work-enter", [*work, "enter", str(project)], context=context, json_output=False)
    if args.work_entry_only == "v2":
      shell_path = wait_for(lambda: next((p for p in ROOT.glob("shell-*.json") if p not in existing), None), "work project shell")
      shell = json.loads(shell_path.read_text())
      if not all(shell["tty"]): raise RuntimeError("work shell lacks PTY")
      context = {key: value for key, value in shell["bootstrap"].items() if value is not None}
    call("work-open-agent", [*work, "open", args.tool if args.work_entry_only == "v1" else "agent", "--new"],
      context=context, json_output=False)
    run = wait_for(lambda: next(iter(records()), None), "work initial run")
    _, active = wait_for(lambda: container(run), "work resident registration")
    parent = active["manager_identity"]
    owned.append(parent)
    reference = active["terminal_ref"]
    from agentcfg.dsh_stop_control import available
    def work_ready():
      current = records()[run]
      if current.get("host_identity") is None or not available(ws, current): return None
      fd = os.open(str(Path("/proc") / str(current["manager_identity"]["pid"]) / "fd/0"), os.O_RDWR | os.O_NOCTTY)
      try:
        if termios.tcgetattr(fd)[3] & termios.ICANON: return None
      finally: os.close(fd)
      pane = native.native_request(client, ROOT, "pane.read", {"pane_id": reference["pane_id"],
        "source": "recent", "lines": 200, "strip_ansi": True})
      if ("fictional-chat" if args.tool == "pi" else "fixture-not-real") not in pane["read"]["text"]: return None
      return current
    row = wait_for(work_ready, "work native model UI/raw/control ready")
    def process(pid):
      root = Path("/proc") / str(pid)
      fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
      return {"argv": (root / "cmdline").read_bytes().decode().split("\0"), "ppid": int(fields[1]),
        "cwd": os.readlink(root / "cwd"), "terminal": os.readlink(root / "fd/0")}
    parent_process = process(parent["pid"])
    manager = row["manager_identity"]
    child_process = process(manager["pid"])
    host_process = process(row["host_identity"]["identity"]["pid"])
    if (not any(value.endswith("resident.py") for value in parent_process["argv"])
        or child_process["ppid"] != parent["pid"] or host_process["ppid"] != manager["pid"]
        or host_process["cwd"] != str(project)
        or len({item["terminal"] for item in (parent_process, child_process, host_process)}) != 1):
      raise RuntimeError("work resident child/native terminal ancestry mismatch")
    evidence["work_entry"] = {"model": args.work_entry_only, "run": run, "terminal_ref": reference,
      "parent_identity": parent, "manager_identity": manager, "host_identity": row["host_identity"],
      "parent_process": parent_process, "child_process": child_process, "host_process": host_process,
      "session_restore_claimed": False}
    stop = ["--no-input", "agent", "--local", str(ws.local_path), "--profile", ws.profile, "instances", "stop", "--run", run]
    plan = call("work-stop-plan", [*stop, "--dry-run"])
    call("work-stop", [*stop, "--plan-id", plan["plan_id"]])
    _, parked = wait_for(lambda: found if (found := container(run)) and found[1]["state"] == "parked" else None, "work parked")
    if parked["child_identity"] is not None or run_owners.observed_process_identity(parent["pid"]) != parent:
      raise RuntimeError("work resident did not survive child release")
    from agentcfg.lifecycle import observation_guard
    with observation_guard(ws, shared=False), Tree(ws.state_root) as state, instance_lock(state):
      evidence["parked_exclusive_resources_available"] = True
    baseline = json.loads((ROOT / ("tty-start-" + str(parent["pid"]) + ".json")).read_text())
    fd = os.open(str(Path("/proc") / str(parent["pid"]) / "fd/0"), os.O_RDWR | os.O_NOCTTY)
    try:
      actual = json.loads(json.dumps(termios.tcgetattr(fd), default=lambda item: list(item)))
      if actual != baseline: raise RuntimeError("work parked terminal not restored")
    finally: os.close(fd)
    evidence["parked_terminal_restored"] = True
    evidence["status"] = "passed"
    return 0

  def paired_workflow():
    # 两个不同原生会话共用同一明确 profile/batch；不制造 writer 冲突。
    ids = [sid, "22345678-1234-4234-8234-123456789abc"]
    if args.tool == "pi": sessions = ws.instance / "pi-home/sessions"
    else:
      from agentcfg.omp_identity import native_identity
      sessions = native_identity(ws.profile, ws.instance).agent_dir / "sessions/fixture-project"
    sessions.mkdir(mode=0o700, parents=True, exist_ok=True)
    targets, old_runs, second_runs, third_runs, references, parents = {}, {}, {}, {}, {}, {}
    for session_id in ids:
      content = marker + "_" + session_id
      target = sessions / ("2026-10-27T00-00-00_" + session_id + ".jsonl")
      target.write_text(json.dumps({"type": "session", "version": 3, "id": session_id,
        "cwd": str(project), "timestamp": "2026-10-27T00:00:00.000Z"}) + "\n" + json.dumps({
        "type": "message", "id": "abcdef12", "parentId": None, "timestamp": "2026-10-27T00:00:01.000Z",
        "message": {"role": "user", "content": [{"type": "text", "text": content}], "timestamp": 1793059201000}}) + "\n")
      targets[session_id] = (target, target.read_bytes())
      child = start_initial(["--no-input", "resume", args.tool, "--local", str(ws.local_path), "--profile", ws.profile,
        "--session", session_id, "--here"])
      run = wait_for(lambda: next((key for key, value in records().items() if value["manager_identity"]["pid"] == child.pid), None), "paired initial run")
      run_sessions[run], run_markers[run] = session_id, content
      wait_for(lambda: observed(run), "paired initial exact session")
      wait_for(lambda: ready(run), "paired initial native ready")
      old_runs[session_id] = run
    confirm_initial_records(list(old_runs.values()))
    batch1 = workflow(list(old_runs.values()), 1, "low")
    for child, _, slave, before, _, _ in terminals:
      code = child.wait(timeout=30)
      evidence.setdefault("initial_cli_exit_codes", []).append(code)
      if code not in ((0, 143) if args.tool == "omp" else (0,)) or termios.tcgetattr(slave) != before:
        raise RuntimeError("paired initial exit/terminal restoration failed")
    context = start_herdr()
    begin_startup_observation()
    result = call("paired-new-tab", restore_tokens(batch1, list(old_runs.values()), "new-tab"), context=context)
    def results(value, expected):
      rows = value.get("results", [])
      if len(rows) != 2 or {row["run_id"] for row in rows} != set(expected) or any(row["exit_code"] != 0 for row in rows):
        raise RuntimeError("batch did not report two successful independent results")
      return {row["run_id"]: row["result"] for row in rows}
    created = results(result, old_runs.values())
    def find_run(session_id, excluded):
      found = []
      for key in records():
        if key in excluded: continue
        previous = run_sessions.get(key)
        run_sessions[key] = session_id
        if observed(key): found.append(key)
        elif previous is None: run_sessions.pop(key, None)
        else: run_sessions[key] = previous
      return found[0] if len(found) == 1 else None
    for session_id in ids:
      run = wait_for(lambda: find_run(session_id, set(old_runs.values())), "paired new tab exact session")
      run_markers[run] = marker + "_" + session_id
      _, active = wait_for(lambda: container(run), "paired resident registration")
      reference = created[old_runs[session_id]]["terminal_ref"]
      if active["terminal_ref"] != reference: raise RuntimeError("paired new tab binding mismatch")
      wait_for(lambda: ready(run, reference), "paired new tab native ready")
      second_runs[session_id], references[session_id], parents[session_id] = run, reference, active["manager_identity"]
      owned.append(active["manager_identity"])
    if len({ref["terminal_id"] for ref in references.values()}) != 2 or len({ref["pane_id"] for ref in references.values()}) != 2:
      raise RuntimeError("batch reused a terminal between items")
    confirm_initial_records(list(second_runs.values()))
    batch2 = workflow(list(second_runs.values()), 2, "medium")
    from agentcfg.lifecycle import observation_guard
    with observation_guard(ws, shared=False), Tree(ws.state_root) as state, instance_lock(state):
      evidence["parked_exclusive_resources_available"] = True
    for session_id, run in second_runs.items():
      _, parked = container(run)
      if parked["manager_identity"] != parents[session_id] or run_owners.observed_process_identity(parents[session_id]["pid"]) != parents[session_id]:
        raise RuntimeError("paired resident parent lost")
      pid = parents[session_id]["pid"]
      baseline = json.loads((ROOT / ("tty-start-" + str(pid) + ".json")).read_text())
      fd = os.open(str(Path("/proc") / str(pid) / "fd/0"), os.O_RDWR | os.O_NOCTTY)
      try:
        actual = json.loads(json.dumps(termios.tcgetattr(fd), default=lambda item: list(item)))
        if actual != baseline: raise RuntimeError("paired parked terminal not restored")
      finally: os.close(fd)
    shadow = ROOT / "work-shadow.py"
    original_source = shadow.read_bytes()
    try:
      shadow.write_bytes(original_source + b"\n# Native source drift probe.\n")
      call("paired-source-drift-rejected", restore_tokens(batch2, second_runs[ids[0]], "original"), expected=5, context=context)
    finally: shadow.write_bytes(original_source)
    begin_startup_observation()
    result = call("paired-original", restore_tokens(batch2, list(second_runs.values()), "original"), context=context)
    restored = results(result, second_runs.values())
    for session_id in ids:
      excluded = set(old_runs.values()) | set(second_runs.values())
      run = wait_for(lambda: find_run(session_id, excluded), "paired original new run")
      run_markers[run] = marker + "_" + session_id
      _, active = wait_for(lambda: container(run), "paired original resident")
      if (active["terminal_ref"] != references[session_id] or active["manager_identity"] != parents[session_id]
          or restored[second_runs[session_id]]["terminal_ref"] != references[session_id]):
        raise RuntimeError("paired original reused the wrong location or parent")
      wait_for(lambda: ready(run, references[session_id]), "paired original native ready")
      third_runs[session_id] = run
    confirm_initial_records(list(third_runs.values()))
    call("paired-repeat-rejected", restore_tokens(batch2, list(second_runs.values()), "original"), expected=4, context=context)
    expected_runs = set(old_runs.values()) | set(second_runs.values()) | set(third_runs.values())
    if len(expected_runs) != 6 or set(records()) != expected_runs: raise RuntimeError("paired replay created an extra run")
    batch3 = workflow(list(third_runs.values()), 3, "low")
    native.stop_owned(server_identity)
    server.wait(timeout=10)
    call("paired-lost-pane-rejected", restore_tokens(batch3, third_runs[ids[0]], "original"), expected=5, context=context)
    for target, original in targets.values():
      if not target.read_bytes().startswith(original): raise RuntimeError("paired synthetic history changed")
    evidence.update(status="passed", batches=[batch1, batch2, batch3], paired_count=2,
      runs_by_phase=[old_runs, second_runs, third_runs], terminal_refs=references, resident_identities=parents,
      final_records=records(), native_host_started=True, parked_terminal_restored=True)
    return 0
  try:
    destination = ws.backend.root(ws, identity)
    if args.tool == "omp":
      asset = lock.metadata["assets"]["linux-x64"]
      if hashlib.sha256(Path("/seed").read_bytes()).hexdigest() != asset["sha256"]:
        raise RuntimeError("OMP official binary digest mismatch")
      downloads = ws.cache / "downloads"
      downloads.mkdir(mode=0o700, parents=True)
      shutil.copyfile("/seed", downloads / asset["sha256"])
      call("initial-setup", ["--no-input", "agent", "--local", str(ws.local_path), "--profile", ws.profile, "setup"], json_output=False)
    elif not args.fresh_sync:
      destination.parent.mkdir(mode=0o700, parents=True)
      shutil.copytree("/seed", destination, symlinks=True)
      if ws.backend.status(ws, identity) != "installed":
        raise RuntimeError("normal backend rejected seed for current candidate")
      evidence["sync"] = ws.backend.sync(ws, lock)
      commands.apply_candidate(ws, lock, ws.candidate(lock.identity))
    else:
      evidence["sync"] = ws.backend.sync(ws, lock)
      commands.apply_candidate(ws, lock, ws.candidate(lock.identity))
    if ws.backend.status(ws, identity) != "installed":
      raise RuntimeError("normal backend installation did not validate")
    evidence["preparation"] = "normal-backend-installed"
    if args.prepare_only:
      if args.tool == "dsh" and Path("/session-seed").is_file():
        with Tree(ws.state_root) as state, instance_lock(state): ws.adapter.prepare_runtime(ws, destination)
        imported = ws.instance / "dsh-home/sessions/--probe-project--" / sid / "session.v4.jsonl.zstd"
        imported.parent.mkdir(mode=0o700, parents=True)
        shutil.copyfile("/session-seed", imported)
        from agentcfg.dsh_sessions import lookup_metadata
        metadata = lookup_metadata(ws, sid)
        if metadata.cwd != str(project): raise RuntimeError("synthetic DSH source cwd changed")
        evidence["prepared_session"] = {"session_id": metadata.ref.native_ref, "cwd": metadata.cwd,
          "source_sha256": hashlib.sha256(imported.read_bytes()).hexdigest(), "host_started": False}
      if args.fresh_sync:
        exported = ROOT / "prepared-runtime"
        shutil.copytree(destination, exported, symlinks=True)
        from agentcfg.pi_runtime_packages import status
        if status(exported, identity) != "installed": raise RuntimeError("exported normal package failed validation")
        evidence["exported_runtime"] = str(exported)
      evidence["status"] = "prepared-no-host-started"
      return 0
    if not args.candidate_digest or source_digest(REPO) != args.candidate_digest:
      raise RuntimeError("formal native validation requires frozen candidate digest")
    if not all(pane_dispatch._admitted(args.tool, identity, location) for location in ("original", "new-tab")):
      raise RuntimeError("candidate exact combinations not admitted for native validation")
    if args.work_entry_only: return work_entry()
    if args.paired: return paired_workflow()
    if args.tool == "dsh":
      with Tree(ws.state_root) as state, instance_lock(state): ws.adapter.prepare_runtime(ws, destination)
      target = ws.instance / "dsh-home/sessions/--probe-project--" / sid / "session.v4.jsonl.zstd"
      target.parent.mkdir(mode=0o700, parents=True)
      shutil.copyfile("/session-seed", target)
    else:
      if args.tool == "pi": sessions = ws.instance / "pi-home/sessions"
      else:
        from agentcfg.omp_identity import native_identity
        sessions = native_identity(ws.profile, ws.instance).agent_dir / "sessions/fixture-project"
      sessions.mkdir(mode=0o700, parents=True, exist_ok=True)
      target = sessions / ("2026-10-27T00-00-00_" + sid + ".jsonl")
      target.write_text(json.dumps({"type": "session", "version": 3, "id": sid, "cwd": str(project),
        "timestamp": "2026-10-27T00:00:00.000Z"}) + "\n" + json.dumps({"type": "message", "id": "abcdef12", "parentId": None,
        "timestamp": "2026-10-27T00:00:01.000Z", "message": {"role": "user", "content": [{"type": "text",
        "text": marker}], "timestamp": 1793059201000}}) + "\n")
    original_history = target.read_bytes()
    first = start_initial(["--no-input", "resume", args.tool, "--local", str(ws.local_path), "--profile", ws.profile,
      "--session", sid, "--here"])
    first_run = wait_for(lambda: next(iter(records()), None), "initial run")
    evidence["initial_session"] = wait_for(lambda: observed(first_run), "initial exact session")
    wait_for(lambda: ready(first_run), "initial native history/raw/control ready")
    confirm_initial_records([first_run])
    batch1 = workflow(first_run, 1, "low")
    code = first.wait(timeout=30)
    evidence["initial_cli_exit_codes"] = [code]
    if code not in ((0, 143) if args.tool == "omp" else (0,)):
      raise RuntimeError("initial CLI exit differs from controlled native stop")
    if termios.tcgetattr(terminals[0][2]) != terminals[0][3]: raise RuntimeError("initial terminal not restored")
    context = start_herdr()
    begin_startup_observation()
    newtab = call("new-tab", restore_tokens(batch1, first_run, "new-tab"), context=context)
    second_run = wait_for(lambda: next((run for run in records() if run != first_run), None), "new tab new run")
    evidence["new_tab_session"] = wait_for(lambda: observed(second_run), "new tab exact session")
    _, active = wait_for(lambda: container(second_run), "new resident registration")
    resident_identity = active["manager_identity"]
    owned.append(resident_identity)
    reference = active["terminal_ref"]
    if reference != newtab["terminal_ref"]: raise RuntimeError("new tab terminal binding mismatch")
    wait_for(lambda: ready(second_run, reference), "new tab native history/raw/control ready")
    confirm_initial_records([second_run])
    batch2 = workflow(second_run, 2, "medium")
    if args.diagnose_stop2:
      evidence["status"] = "diagnostic-completed-not-native-acceptance"
      return 0
    _, parked = wait_for(lambda: found if (found := container(second_run)) and found[1]["state"] == "parked" else None, "parked complete release")
    if parked["child_identity"] is not None or run_owners.observed_process_identity(resident_identity["pid"]) != resident_identity:
      raise RuntimeError("resident did not survive outside single-run resources")
    from agentcfg.lifecycle import observation_guard
    with observation_guard(ws, shared=False), Tree(ws.state_root) as state, instance_lock(state):
      evidence["parked_exclusive_resources_available"] = True
    evidence["parked_fds"] = {path.name: os.readlink(path) for path in (Path("/proc") / str(resident_identity["pid"]) / "fd").iterdir()}
    def resource_sample():
      proc = Path("/proc") / str(resident_identity["pid"])
      fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
      rss = next(line.split(":", 1)[1].strip() for line in (proc / "status").read_text().splitlines() if line.startswith("VmRSS:"))
      return {"cpu_ticks": int(fields[11]) + int(fields[12]), "rss": rss}
    samples = [resource_sample()]
    time.sleep(0.5)
    samples.append(resource_sample())
    evidence["parked_resource_samples"] = samples
    baseline = json.loads((ROOT / ("tty-start-" + str(resident_identity["pid"]) + ".json")).read_text())
    terminal_fd = os.open(str(Path("/proc") / str(resident_identity["pid"]) / "fd/0"), os.O_RDWR | os.O_NOCTTY)
    try:
      # termios 返回含 bytes 的控制字符数组；JSON 往返用于精确同形比较。
      actual = termios.tcgetattr(terminal_fd)
      normalize = lambda value: json.loads(json.dumps(value, default=lambda item: list(item)))
      if normalize(actual) != normalize(baseline): raise RuntimeError("parked terminal attributes not restored")
      evidence["parked_terminal_restored"] = True
    finally:
      os.close(terminal_fd)
    shadow = ROOT / "work-shadow.py"
    original_source = shadow.read_bytes()
    try:
      shadow.write_bytes(original_source + b"\n# Native source drift probe.\n")
      call("source-drift-rejected", restore_tokens(batch2, second_run, "original"), expected=5, context=context)
    finally:
      shadow.write_bytes(original_source)
    begin_startup_observation()
    restored = call("original", restore_tokens(batch2, second_run, "original"), context=context)
    third_run = wait_for(lambda: next((run for run in records() if run not in (first_run, second_run)), None), "same pane new run")
    evidence["original_session"] = wait_for(lambda: observed(third_run), "same pane exact session")
    _, resumed = wait_for(lambda: container(third_run), "same resident new run")
    wait_for(lambda: ready(third_run, reference), "same pane native history/raw/control ready")
    if resumed["manager_identity"] != resident_identity or resumed["terminal_ref"] != reference or restored["terminal_ref"] != reference:
      raise RuntimeError("original pane or parent birth changed")
    confirm_initial_records([third_run])
    call("original-repeat-rejected", restore_tokens(batch2, second_run, "original"), expected=4, context=context)
    if set(records()) != {first_run, second_run, third_run}: raise RuntimeError("duplicate restoration run")
    batch3 = workflow(third_run, 3, "low")
    wait_for(lambda: found if (found := container(third_run)) and found[1]["state"] == "parked" else None, "final parked")
    client.close()
    client = None
    native.stop_owned(server_identity)
    server.wait(timeout=10)
    call("lost-pane-rejected", restore_tokens(batch3, third_run, "original"), expected=5, context=context)
    if set(records()) != {first_run, second_run, third_run}: raise RuntimeError("lost pane spawned a run")
    if args.tool != "dsh" and not target.read_bytes().startswith(original_history): raise RuntimeError("original history not preserved")
    evidence.update(status="passed", runs=[first_run, second_run, third_run], batches=[batch1, batch2, batch3],
      terminal_ref=reference, resident_identity=resident_identity, final_records=records(), native_host_started=True)
    return 0
  except Exception as error:
    import traceback
    evidence.update(status="failed", failure=type(error).__name__ + ":" + str(error), traceback=traceback.format_exc())
    if client is not None:
      if args.work_entry_only:
        try:
          for row in native.native_request(client, ROOT, "pane.list", {})["panes"]:
            pane = native.native_request(client, ROOT, "pane.read", {"pane_id": row["pane_id"],
              "source": "recent", "lines": 200, "strip_ansi": True})
            save("failure-work-pane-" + hashlib.sha256(row["pane_id"].encode()).hexdigest()[:12] + ".json", pane)
        except Exception:
          pass
      for path in (ROOT / "s/rotom/panes").glob("*/container.json"):
        try:
          record = json.loads(path.read_text())
          pane = native.native_request(client, ROOT, "pane.read", {"pane_id": record["terminal_ref"]["pane_id"],
            "source": "recent", "lines": 200, "strip_ansi": True})
          save("failure-pane-" + record["container_id"] + ".json", pane)
        except Exception:
          pass
    return 5
  finally:
    if client is not None: client.close()
    cleanup = []
    if server_identity is not None:
      owned.extend(native.children(server_identity["pid"]))
      cleanup.append({"identity": server_identity, "result": native.stop_owned(server_identity)})
      try: server.wait(timeout=5)
      except subprocess.TimeoutExpired: evidence["cleanup_incomplete"] = True
    for child, master, slave, before, output, thread in terminals:
      if child.poll() is None:
        for identity_value in native.children(child.pid): owned.append(identity_value)
      thread.join(timeout=1)
      (ROOT / "logs/initial-terminal.log").write_bytes(output)
      (ROOT / ("logs/initial-terminal-" + str(child.pid) + ".log")).write_bytes(output)
      evidence.setdefault("initial_children_final", []).append({"manager_pid": child.pid, "exit_code": child.poll()})
      os.close(master)
      os.close(slave)
    for identity_value in {row["pid"]: row for row in owned}.values():
      cleanup.append({"identity": identity_value, "result": native.stop_owned(identity_value)})
    if fixture_server is not None:
      fixture_server.shutdown()
      fixture_server.server_close()
      fixture_thread.join(timeout=2)
      evidence["local_fixture_requests"] = fixture["requests"]
      evidence["local_fixture_error"] = fixture["error"]
    evidence["cleanup"] = cleanup
    save("result.json", evidence)


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--prepare-only", action="store_true")
  parser.add_argument("--work-entry-only", choices=("v1", "v2"), help="仅验收公开work新建Agent默认驻留/停止；不声明会话恢复")
  parser.add_argument("--paired", action="store_true", help="两个不同合成会话的同批次 --all 位置恢复")
  parser.add_argument("--restore-wait-seconds", type=int, default=30, help="位置恢复等待预算秒数（1..300，默认30）")
  parser.add_argument("--diagnose-restore", action="store_true", help="仅restore_child自有agentcfg异常位置，不追踪官方宿主；诊断不算正式通过")
  parser.add_argument("--diagnose-initial", action="store_true", help="仅初始当前终端CLI的自有agentcfg异常位置，不追踪官方宿主；诊断不算正式通过")
  parser.add_argument("--diagnose", action="store_true", help="仅准备时记录仓库自有异常位置；不能替代正常原生验收")
  parser.add_argument("--diagnose-stop2", action="store_true", help="仅第二次控制端stop的自有代码异常追踪；不算原生通过")
  parser.add_argument("--diagnose-stop3", action="store_true", help="仅第三次控制端stop的自有代码异常追踪；不算原生通过")
  parser.add_argument("--diagnose-control", action="store_true", help="仅自身CLI child的可选控制工厂异常与固定返回类别；不追踪宿主")
  parser.add_argument("--tool", choices=("pi", "dsh", "omp"), default="pi")
  parser.add_argument("--profile", choices=("pi-base", "pi-pro"), default="pi-base")
  parser.add_argument("--fresh-sync", action="store_true", help="仅Pi准备时经正常backend从完整锁获取依赖")
  parser.add_argument("--network-prepare", action="store_true", help="仅fresh-sync准备阶段联网；正式运行始终隔离网络")
  parser.add_argument("--root", type=Path)
  parser.add_argument("--node-root", type=Path)
  parser.add_argument("--runtime-source", type=Path)
  parser.add_argument("--session-source", type=Path, help="DSH自有合成历史的官方压缩记录；不接受真实会话")
  parser.add_argument("--session-id")
  parser.add_argument("--herdr", type=Path)
  parser.add_argument("--lock-source", type=Path, help="仅Pi：含manifest.json和两档package文件的公开locks/pi目录，只读覆盖五个固定锁文件")
  parser.add_argument("--pi-base-cursor", action="store_true", help="Pi Base采用已验收的footer+Cursor精确配置；不登录或调用模型")
  parser.add_argument("--candidate-digest")
  parser.add_argument("--candidate-dispatch", type=Path, help="根代理审阅的私人精确门禁候选源码，只读绑定，不修改发行文件")
  parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
  args = parser.parse_args(argv)
  if not 1 <= args.restore_wait_seconds <= 300: parser.error("--restore-wait-seconds requires 1..300")
  if not args.allow_host: parser.error("explicit --allow-host required")
  if args.diagnose and not args.prepare_only: parser.error("--diagnose requires --prepare-only")
  if args.paired and (args.tool == "dsh" or args.diagnose_stop2): parser.error("paired requires Pi/OMP without stop2 diagnostic")
  if (args.fresh_sync or args.network_prepare) and (not args.prepare_only or args.tool != "pi"):
    parser.error("fresh/network preparation requires Pi --prepare-only")
  if args.tool == "dsh" and not args.prepare_only and args.session_source is None and not args.inside and not args.work_entry_only:
    parser.error("DSH formal validation requires own synthetic --session-source")
  if args.work_entry_only and (args.tool == "omp" or args.paired or args.prepare_only):
    parser.error("work entry requires unpaired Pi/DSH native validation")
  if args.pi_base_cursor and (args.tool != "pi" or args.profile != "pi-base"):
    parser.error("--pi-base-cursor requires Pi Base")
  if args.lock_source is not None and args.tool != "pi": parser.error("--lock-source requires Pi")
  if args.inside: return inside(args)
  if (args.root is None or not args.root.is_absolute() or args.root.exists()
      or args.node_root is None or args.runtime_source is None and not args.fresh_sync or args.herdr is None):
    parser.error("unused private absolute --root, locked --node-root/--runtime-source and --herdr required")
  os.umask(0o077)
  args.root.mkdir(mode=0o700)
  if args.tool == "omp": (args.root / "h/.omp").mkdir(mode=0o700, parents=True)
  if args.tool == "omp": (args.root / "h").chmod(0o700)
  shutil.copyfile(REPO / "src/termcfg/work.py", args.root / "work-shadow.py")
  (args.root / "work-shadow.py").chmod(0o600)
  dispatch_binding = []
  if args.candidate_dispatch is not None:
    candidate = args.candidate_dispatch.resolve(strict=True)
    dispatch_binding = ["--ro-bind", str(candidate), str(REPO / "src/rotom/pane_dispatch.py")]
    from termcfg.work import LAUNCH_FILES, source_digest
    names = set(LAUNCH_FILES)
    for package in ("agentcfg", "rotom", "termcfg"):
      names.update(path.relative_to(REPO).as_posix() for path in (REPO / "src" / package).glob("*.py"))
    snapshot = args.root / "candidate-source"
    for name in sorted(names):
      destination = snapshot / name
      destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
      shutil.copyfile(candidate if name == "src/rotom/pane_dispatch.py" else REPO / name, destination)
      destination.chmod(0o600)
    calculated = source_digest(snapshot)
    if args.candidate_digest is not None and args.candidate_digest != calculated:
      raise RuntimeError("candidate source digest changed before namespace startup")
    args.candidate_digest = calculated
    (args.root / "candidate-dispatch-sha256").write_text(hashlib.sha256(candidate.read_bytes()).hexdigest() + "\n")
  lock_binding = []
  if args.lock_source is not None:
    source = args.lock_source.resolve(strict=True)
    lock_hashes = {}
    for name in ("manifest.json", "pi-base/package.json", "pi-base/package-lock.json",
        "pi-pro/package.json", "pi-pro/package-lock.json"):
      file = source / name
      if file.is_symlink() or not file.is_file():
        parser.error("--lock-source requires five regular public lock files")
      lock_binding += ["--ro-bind", str(file), str(REPO / "locks/pi" / name)]
      lock_hashes["locks/pi/" + name] = hashlib.sha256(file.read_bytes()).hexdigest()
    (args.root / "lock-overrides.json").write_text(json.dumps(lock_hashes, indent=2) + "\n")
  venv = (REPO / ".venv").resolve(strict=True)
  network = [] if args.network_prepare else ["--unshare-net"]
  network_inputs = ["--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf", "--ro-bind", "/etc/ssl", "/etc/ssl"] if args.network_prepare else []
  seed = ["--ro-bind", str(args.runtime_source), "/seed"] if args.runtime_source is not None else []
  session_binding = ["--ro-bind", str(args.session_source), "/session-seed"] if args.session_source is not None else []
  native_cache_binding = ["--tmpfs", "/p/h/.omp/natives"] if args.tool == "omp" else []
  project_binding = ["--bind", str(args.root), "/probe"] if args.tool == "dsh" else []
  command = ["/bin/bwrap", "--unshare-user", "--unshare-pid", *network, "--die-with-parent", "--new-session",
    "--tmpfs", "/", "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64",
    "--symlink", "usr/bin", "/bin", "--proc", "/proc", "--dev", "/dev", "--dir", "/tmp",
    "--ro-bind", str(REPO), str(REPO), "--ro-bind", str(venv), str(venv),
    "--ro-bind", str(args.node_root), "/opt/node", "--ro-bind", str(args.herdr), "/opt/herdr",
    *seed, *session_binding, *network_inputs, "--bind", str(args.root), "/p", *project_binding,
    "--tmpfs", "/p/i", "--tmpfs", "/p/cache", *native_cache_binding, "--bind", str(args.root / "work-shadow.py"), str(REPO / "src/termcfg/work.py"),
    *dispatch_binding, *lock_binding, "--chdir", str(REPO), str(venv / "bin/python"), "-B", str(Path(__file__).resolve()),
    "--allow-host", "--inside", "--tool", args.tool, "--profile", args.profile,
    "--restore-wait-seconds", str(args.restore_wait_seconds)]
  if args.prepare_only: command.append("--prepare-only")
  if args.paired: command.append("--paired")
  if args.work_entry_only: command += ["--work-entry-only", args.work_entry_only]
  if args.pi_base_cursor: command.append("--pi-base-cursor")
  if args.diagnose: command.append("--diagnose")
  if args.diagnose_initial: command.append("--diagnose-initial")
  if args.diagnose_restore: command.append("--diagnose-restore")
  if args.diagnose_stop2: command.append("--diagnose-stop2")
  if args.diagnose_stop3: command.append("--diagnose-stop3")
  if args.diagnose_control: command.append("--diagnose-control")
  if args.fresh_sync: command.append("--fresh-sync")
  if args.network_prepare: command.append("--network-prepare")
  if args.session_id: command += ["--session-id", args.session_id]
  if args.candidate_digest: command += ["--candidate-digest", args.candidate_digest]
  (args.root / "argv.json").write_text(json.dumps(command, indent=2) + "\n")
  with (args.root / "driver.stdout").open("wb") as output, (args.root / "driver.stderr").open("wb") as errors:
    completed = subprocess.run(command, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, stdout=output, stderr=errors, timeout=900)
  print(json.dumps({"exit_code": completed.returncode, "evidence": str(args.root)}))
  return completed.returncode


if __name__ == "__main__":
  raise SystemExit(main())
