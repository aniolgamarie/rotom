import importlib.util
import json
from pathlib import Path
import stat

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "omp-command-history.py"
spec = importlib.util.spec_from_file_location("command_history", SCRIPT)
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


def tool(command, name="bash"):
  return {"type": "message", "message": {"role": "assistant", "content": [{"type": "toolCall", "name": name, "arguments": {"command": command}}]}}


def codex(command, name="exec_command"):
  return {"type": "response_item", "payload": {"type": "function_call", "name": name, "arguments": json.dumps({"command" if name == "shell" else "cmd": command})}}


def write_log(path, events):
  path.write_text("\n".join(json.dumps(event) for event in events) + "\n")
  return path


def run(tmp_path, inputs, capsys):
  output = tmp_path / "private" / "history.json"
  args = ["--output", str(output)]
  for source, log in inputs.items():
    args.extend([f"--{source}-root", str(log)])
  assert history.main(args) == 0
  captured = capsys.readouterr()
  return json.loads(output.read_text()), output, captured


def test_three_shapes_deduplicate_and_preserve_shell(tmp_path, capsys):
  command = "printf '%s\\n' 'quoted words'\nrg \"a|b\" *.py > result.txt && cat < result.txt"
  logs = {
    "pi": write_log(tmp_path / "pi.jsonl", [tool(command)]),
    "omp": write_log(tmp_path / "omp.jsonl", [tool(command, "permission_bash")]),
    "codex": write_log(tmp_path / "codex.jsonl", [codex(["/bin/bash", "-lc", command], "shell")]),
  }
  before = {path: path.read_bytes() for path in logs.values()}
  artifact, output, captured = run(tmp_path, logs, capsys)
  assert len(artifact["records"]) == 1
  record = artifact["records"][0]
  assert record["command"] == command
  assert record["sources"] == ["pi", "codex", "omp"]
  assert record["occurrences"] == 3
  assert len(record["id"]) == 64
  assert set(record) == {"id", "command", "sources", "occurrences"}
  assert artifact["publication"] == "private-review-required"
  assert artifact["schemaVersion"] == 1
  assert artifact["redactionVersion"] == 2
  assert stat.S_IMODE(output.stat().st_mode) == 0o600
  assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
  assert command not in captured.out
  assert all(path.read_bytes() == before[path] for path in logs.values())


@pytest.mark.parametrize("command", [
  "API_TOKEN=SecretSentinel123 curl --password 'PasswordSentinel123' --api-key=KeySentinel123",
  "curl -H 'Authorization: Bearer HeaderSentinel123' https://u:UrlSentinel123@example.test/a?token=QuerySentinel123&name=QueryNameSentinel123",
  "mysql -pDbSentinel123; redis-cli -a 'RedisSentinel123'; sqlcmd -P SqlSentinel123",
  "PGPASSWORD=PgSentinel123 psql; echo password=PlainSentinel123",
  "echo '{\"password\": \"JsonSentinel123\"}'; echo Bearer BearerSentinel123",
  "echo sk-KnownSentinel123456789abc",
])
def test_secrets_never_leave_memory(tmp_path, capsys, command):
  log = write_log(tmp_path / "secret.jsonl", [tool(command)])
  artifact, output, captured = run(tmp_path, {"pi": log}, capsys)
  assert artifact["records"]
  external = output.read_text() + captured.out + captured.err
  assert "Sentinel123" not in external
  assert "private-review-required" in external


def test_personal_locations_addresses_redacted(tmp_path, capsys):
  command = "cat '/home/alice/private/file' /data/1/alice/repo/*.py; echo alice@example.test 192.168.1.20 2001:db8::12"
  artifact, output, captured = run(tmp_path, {"omp": write_log(tmp_path / "omp.jsonl", [tool(command)])}, capsys)
  external = output.read_text() + captured.out + captured.err
  for secret in ("alice", "192.168.1.20", "2001:db8::12"):
    assert secret not in external
  safe = artifact["records"][0]["command"]
  assert "'" in safe and "*.py" in safe and ";" in safe


def test_unsupported_malformed_noncommands_and_quarantine(tmp_path, capsys):
  events = [
    {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "functions.exec", "input": "await tools.exec_command(...)"}},
    codex(["echo", "hello"], "shell"),
    {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "arguments": "{broken"}},
    {"type": "response_item", "payload": {"type": "function_call", "name": "read_file", "arguments": "{}"}},
    codex("echo $(secret-command)"),
    codex("python -c 'print(1)\nprint(2)'"),
    codex("echo -----BEGIN RSA PRIVATE KEY-----"),
    codex("echo q8WeR7tYu6IoP5aSd4FgH3jKl2ZxCvBnM"),
  ]
  log = write_log(tmp_path / "codex.jsonl", events)
  with log.open("a") as handle:
    handle.write("invalid JSON SecretSentinel123\n")
  artifact, output, captured = run(tmp_path, {"codex": log}, capsys)
  counters = artifact["statistics"]["codex"]
  assert counters["events"] == 9
  assert counters["unsupportedCommandCarrier"] == 2
  assert counters["malformed"] == 2
  assert counters["nonCommand"] == 1
  assert counters["redactionSkipped"] == 4
  assert artifact["records"] == []
  assert "SecretSentinel123" not in output.read_text() + captured.out + captured.err


def test_does_not_execute_commands(tmp_path, capsys, monkeypatch):
  sentinel = tmp_path / "executed"
  def fail(*args, **kwargs):
    pytest.fail("history command was executed")
  monkeypatch.setattr(history.os, "system", fail)
  artifact, _, _ = run(tmp_path, {"pi": write_log(tmp_path / "pi.jsonl", [tool(f"touch '{sentinel}'")])}, capsys)
  assert artifact["records"]
  assert not sentinel.exists()


def test_existing_output_and_symlinks_refused(tmp_path, capsys):
  log = write_log(tmp_path / "pi.jsonl", [tool("echo safe")])
  private = tmp_path / "private"
  private.mkdir(mode=0o700)
  output = private / "history.json"
  output.write_text("original")
  assert history.main(["--pi-root", str(log), "--output", str(output)]) == 2
  assert output.read_text() == "original"
  output.unlink()
  output.symlink_to(log)
  assert history.main(["--pi-root", str(log), "--output", str(output)]) == 2
  link = tmp_path / "link"
  link.symlink_to(private, target_is_directory=True)
  assert history.main(["--pi-root", str(log), "--output", str(link / "new.json")]) == 2
  assert not (private / "new.json").exists()
  assert "pi.jsonl" not in capsys.readouterr().err


def test_explicit_roots_and_public_destination_required(tmp_path, capsys):
  assert history.main(["--output", str(tmp_path / "private" / "result.json")]) == 2
  log = write_log(tmp_path / "pi.jsonl", [tool("echo safe")])
  public = SCRIPT.parents[1] / "tests" / "fixtures" / "should-not-exist.json"
  assert history.main(["--pi-root", str(log), "--output", str(public)]) == 2
  assert not public.exists()
  assert not capsys.readouterr().out


def test_safe_literal_dynamic_shapes_kept_and_unsafe_heredoc_skipped(tmp_path, capsys):
  commands = ["echo $(pwd)", "cat <<'EOF'\nexample\nEOF", "cat <<EOF\n$SECRET\nEOF"]
  artifact, _, _ = run(tmp_path, {"pi": write_log(tmp_path / "pi.jsonl", [tool(command) for command in commands])}, capsys)
  assert [record["command"] for record in artifact["records"]] == commands[:2]
  assert artifact["statistics"]["pi"]["redactionSkipped"] == 1
  assert artifact["statistics"]["pi"]["dynamicCommandSkipped"] == 1


def test_database_nonpassword_option_preserved(tmp_path, capsys):
  command = "mysql --port=3306 -pSecretSentinel123"
  artifact, _, _ = run(tmp_path, {"pi": write_log(tmp_path / "pi.jsonl", [tool(command)])}, capsys)
  assert artifact["records"][0]["command"] == "mysql --port=3306 -pREDACTED"


def test_redaction_preserves_path_shell_structure_and_rejects_dynamic_secrets(tmp_path, capsys):
  safe = "echo /home/alice/$(pwd)/{a,b} /home/alice/file\\ name"
  unsafe = ["TOKEN=$SECRET echo hi", "curl --token '$SECRET'", "curl -H \"Authorization: $SECRET\""]
  artifact, _, _ = run(tmp_path, {"pi": write_log(tmp_path / "pi.jsonl", [tool(safe)] + [tool(command) for command in unsafe])}, capsys)
  assert len(artifact["records"]) == 1
  result = artifact["records"][0]["command"]
  assert "$(pwd)/{a,b}" in result
  assert "\\ name" in result
  assert "alice" not in result
  assert artifact["statistics"]["pi"]["redactionSkipped"] == 3


def test_object_arguments_and_missing_pi_tool_type(tmp_path, capsys):
  event = codex("echo object")
  event["payload"]["arguments"] = {"cmd": "echo object"}
  missing_type = tool("echo should-not-extract")
  del missing_type["message"]["content"][0]["type"]
  artifact, _, _ = run(tmp_path, {"codex": write_log(tmp_path / "codex.jsonl", [event]), "pi": write_log(tmp_path / "pi.jsonl", [missing_type])}, capsys)
  assert [record["command"] for record in artifact["records"]] == ["echo object"]
  assert artifact["statistics"]["pi"]["unsupportedCommandCarrier"] == 1


def test_unclosed_secret_quote_and_escaped_value_quarantined(tmp_path, capsys):
  commands = ["TOKEN='QuoteSentinel123", "curl --token SecretSentinel123\\ value"]
  artifact, output, captured = run(tmp_path, {"pi": write_log(tmp_path / "pi.jsonl", [tool(command) for command in commands])}, capsys)
  assert artifact["records"] == []
  assert artifact["statistics"]["pi"]["redactionSkipped"] == 2
  assert "Sentinel123" not in output.read_text() + captured.out + captured.err


def test_custom_noncommand_tools_do_not_inflate_unsupported_statistics(tmp_path, capsys):
  def custom(name, value):
    return {"type": "response_item", "payload": {"type": "custom_tool_call", "name": name, "input": value}}
  events = [
    custom("apply_patch", "*** Begin Patch\n+cmd: fixture-value\n*** End Patch"),
    custom("functions.apply_patch", {"command": "documentation example"}),
    custom("read_file", {"path": "example.txt"}),
    custom("unknown_tool", {"path": "example.txt"}),
    custom("unknown_tool", {"cmd": "echo should-not-extract"}),
    custom("unknown_tool", json.dumps({"command": "echo should-not-extract"})),
    custom("unknown_tool", "tool({cmd: 'echo should-not-extract'})"),
    custom("exec", "await tools.exec_command(...)"),
    custom("functions.exec", "await tools.exec_command(...)"),
    custom("functions.shell", {"command": ["bash", "-c", "echo should-not-extract"]}),
  ]
  artifact, _, captured = run(tmp_path, {"codex": write_log(tmp_path / "codex.jsonl", events)}, capsys)
  counters = artifact["statistics"]["codex"]
  assert counters["unsupportedCommandCarrier"] == 6
  assert counters["nonCommand"] == 4
  assert counters["events"] == 10
  assert counters["extracted"] == 0
  assert artifact["records"] == []
  assert "should-not-extract" not in captured.out + captured.err


class FakeParserProcess:
  def __init__(self, responses, *, blocked=False, wait_timeout=False):
    # 真管道仅传输合成字节，不创建或执行子进程。
    import os
    reader, writer = os.pipe()
    self.request_reader = os.fdopen(reader, "rb")
    self.stdin = os.fdopen(writer, "wb")
    reader, writer = os.pipe()
    self.stdout = os.fdopen(reader, "rb")
    self.response_writer = os.fdopen(writer, "wb")
    for response in responses:
      raw = response if isinstance(response, str) else json.dumps(response)
      self.response_writer.write((raw + "\n").encode())
    self.response_writer.flush()
    if not blocked:
      self.response_writer.close()
    self.wait_timeout = wait_timeout
    self.terminated = False
    self.killed = False
    self.waited = False
    self.requests = []

  def wait(self, timeout):
    if self.wait_timeout and not self.terminated:
      raise history.subprocess.TimeoutExpired("fixed-parser", timeout)
    self.waited = True
    if not self.request_reader.closed:
      self.requests = [json.loads(line) for line in self.request_reader.read().splitlines()]
      self.request_reader.close()
    self.response_writer.close()
    return 0

  def terminate(self):
    self.terminated = True

  def kill(self):
    self.killed = True


def parser_args(tmp_path):
  bun = tmp_path / "locked-bun"
  module = tmp_path / "parser.js"
  bun.write_text("synthetic executable path; never launched")
  module.write_text("synthetic module path; never loaded")
  return ["--bun", str(bun), "--js-parser-module", str(module)]


def test_js_parser_protocol_reuses_process_redacts_and_closes(tmp_path, capsys, monkeypatch):
  responses = [
    {"commands": ["TOKEN=SecretSentinel123 echo safe"], "unsupported": 2, "malformed": False},
    {"commands": ["echo second"], "unsupported": 0, "malformed": False},
    {"commands": [], "unsupported": 0, "malformed": True},
  ]
  process = FakeParserProcess(responses)
  launches = []
  def launch(argv, **kwargs):
    launches.append((argv, kwargs))
    return process
  monkeypatch.setattr(history.subprocess, "Popen", launch)
  scripts = ["throw new Error('RawSentinel123');", "await tools.exec_command({cmd:'echo second'})", "malformed JS RawSentinel123"]
  events = [{"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": script}} for script in scripts]
  log = write_log(tmp_path / "codex.jsonl", events)
  output = tmp_path / "private" / "history.json"
  extra = parser_args(tmp_path)
  assert history.main(["--codex-root", str(log), "--output", str(output)] + extra) == 0
  artifact = json.loads(output.read_text())
  counters = artifact["statistics"]["codex"]
  assert counters["jsScripts"] == 3
  assert counters["jsLiteralCommands"] == 2
  assert counters["jsUnresolvedCalls"] == 2
  assert counters["jsMalformedScripts"] == counters["malformed"] == 1
  assert counters["unsupportedCommandCarrier"] == 1
  assert len(launches) == 1
  assert launches[0][0] == [extra[1], str(SCRIPT.parent / "extract-omp-history-js.ts"), "--parser-module", extra[3]]
  assert launches[0][1]["stderr"] == history.subprocess.DEVNULL
  assert process.requests == [{"script": script} for script in scripts]
  assert process.stdin.closed and process.stdout.closed and process.waited
  assert not process.terminated
  captured = capsys.readouterr()
  external = output.read_text() + captured.out + captured.err
  assert "Sentinel123" not in external
  for source in ("pi", "omp"):
    assert artifact["statistics"][source]["jsScripts"] == 0


@pytest.mark.parametrize("response", [
  "not JSON RawSentinel123",
  {"commands": ["echo RawSentinel123"], "unsupported": True, "malformed": False},
  {"commands": ["echo RawSentinel123"], "unsupported": 0, "malformed": True},
  {"commands": [], "unsupported": 0, "malformed": False, "raw": "RawSentinel123"},
])
def test_js_invalid_protocol_fails_without_secret_or_artifact(tmp_path, capsys, monkeypatch, response):
  process = FakeParserProcess([response])
  monkeypatch.setattr(history.subprocess, "Popen", lambda *args, **kwargs: process)
  event = {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": "RawSentinel123"}}
  log = write_log(tmp_path / "codex.jsonl", [event])
  output = tmp_path / "private" / "history.json"
  assert history.main(["--codex-root", str(log), "--output", str(output)] + parser_args(tmp_path)) == 2
  assert not output.exists()
  assert process.stdin.closed and process.stdout.closed and process.waited
  captured = capsys.readouterr()
  assert "RawSentinel123" not in captured.out + captured.err
  assert not captured.out


def test_js_timeout_terminates_only_created_parser(tmp_path, capsys, monkeypatch):
  process = FakeParserProcess([], blocked=True, wait_timeout=True)
  monkeypatch.setattr(history.subprocess, "Popen", lambda *args, **kwargs: process)
  monkeypatch.setattr(history.JsExtractor, "TIMEOUT", 0.01)
  event = {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": "RawSentinel123"}}
  log = write_log(tmp_path / "codex.jsonl", [event])
  output = tmp_path / "private" / "history.json"
  assert history.main(["--codex-root", str(log), "--output", str(output)] + parser_args(tmp_path)) == 2
  assert process.terminated and process.waited
  assert process.stdin.closed and process.stdout.closed
  assert not output.exists()
  assert "RawSentinel123" not in capsys.readouterr().err


def test_js_flags_are_paired_and_process_launch_is_lazy(tmp_path, capsys, monkeypatch):
  def unexpected_launch(*args, **kwargs):
    pytest.fail("parser was launched without an exec script")
  monkeypatch.setattr(history.subprocess, "Popen", unexpected_launch)
  log = write_log(tmp_path / "codex.jsonl", [codex("echo direct")])
  extra = parser_args(tmp_path)
  for flags in (extra[:2], extra[2:]):
    assert history.main(["--codex-root", str(log), "--output", str(tmp_path / "private" / "missing.json")] + flags) == 2
  output = tmp_path / "private" / "direct.json"
  assert history.main(["--codex-root", str(log), "--output", str(output)] + extra) == 0
  assert json.loads(output.read_text())["records"][0]["command"] == "echo direct"
  capsys.readouterr()


@pytest.mark.parametrize("flag, expected", [
  ("-u user:BasicSentinel123", "-u REDACTED"),
  ("-uuser:BasicSentinel123", "-uREDACTED"),
  ("-U user:BasicSentinel123", "-U REDACTED"),
  ("-Uuser:BasicSentinel123", "-UREDACTED"),
  ('-U "user:BasicSentinel123"', '-U "REDACTED"'),
  ("--oauth2-bearer BasicSentinel123", "--oauth2-bearer REDACTED"),
  ("--oauth2-bearer=BasicSentinel123", "--oauth2-bearer=REDACTED"),
  ("--oauth2-bearer='BasicSentinel123'", "--oauth2-bearer='REDACTED'"),
  ("--user user:BasicSentinel123", "--user REDACTED"),
  ("--user=user:BasicSentinel123", "--user=REDACTED"),
  ("--proxy-user user:BasicSentinel123", "--proxy-user REDACTED"),
  ("--proxy-user='user:BasicSentinel123'", "--proxy-user='REDACTED'"),
  ('-u "user:BasicSentinel123"', '-u "REDACTED"'),
])
def test_curl_basic_auth_preserves_flags_quotes_and_other_shell(tmp_path, capsys, flag, expected):
  suffix = " https://example.test/*.txt > result.txt && echo done\n"
  command = "curl " + flag + suffix
  artifact, output, captured = run(tmp_path, {"pi": write_log(tmp_path / "pi.jsonl", [tool(command)])}, capsys)
  assert artifact["records"][0]["command"] == "curl " + expected + suffix
  assert "BasicSentinel123" not in output.read_text() + captured.out + captured.err


@pytest.mark.parametrize("auth", [
  "-u user:$BasicSentinel123",
  "-U user:$BasicSentinel123",
  "-U user:BasicSentinel123\\ value",
  '--oauth2-bearer="$BasicSentinel123"',
  "--oauth2-bearer BasicSentinel123\\ value",
  "--oauth2-bearer=\"BasicSentinel123\"suffix",
  '--user="user:$BasicSentinel123"',
  "--proxy-user 'user:BasicSentinel123\\ value'",
  "-u user:BasicSentinel123\\ value",
  "-u user:'BasicSentinel123'",
  "--user=\"user:BasicSentinel123\"suffix",
  "--user -v",
])
def test_curl_dynamic_or_ambiguous_auth_is_quarantined(tmp_path, capsys, auth):
  command = "curl " + auth + " https://example.test"
  artifact, output, captured = run(tmp_path, {"pi": write_log(tmp_path / "pi.jsonl", [tool(command)])}, capsys)
  assert artifact["records"] == []
  assert artifact["statistics"]["pi"]["redactionSkipped"] == 1
  assert "BasicSentinel123" not in output.read_text() + captured.out + captured.err


def test_curl_unix_socket_option_is_not_basic_auth(tmp_path, capsys):
  command = "curl --unix-socket socket https://example.test"
  artifact, _, _ = run(tmp_path, {"pi": write_log(tmp_path / "pi.jsonl", [tool(command)])}, capsys)
  assert artifact["records"][0]["command"] == command


def test_system_temporary_root_is_canonical_and_requires_private_subdirectory(tmp_path, capsys, monkeypatch):
  temporary = tmp_path / "platform-temp"
  temporary.mkdir(mode=0o700)
  alias = tmp_path / "platform-temp-alias"
  alias.symlink_to(temporary, target_is_directory=True)
  monkeypatch.setattr(history.tempfile, "gettempdir", lambda: str(alias))
  log = write_log(tmp_path / "pi.jsonl", [tool("echo safe")])
  direct = alias / "direct.json"
  assert history.main(["--pi-root", str(log), "--output", str(direct)]) == 2
  assert not direct.exists()
  output = alias / "private" / "result.json"
  assert history.main(["--pi-root", str(log), "--output", str(output)]) == 0
  canonical = temporary / "private" / "result.json"
  assert canonical.exists()
  assert stat.S_IMODE(canonical.stat().st_mode) == 0o600
  assert stat.S_IMODE(canonical.parent.stat().st_mode) == 0o700
  assert stat.S_IMODE(temporary.stat().st_mode) == 0o700
  nested_alias = temporary / "nested-link"
  nested_alias.symlink_to(canonical.parent, target_is_directory=True)
  assert history.main(["--pi-root", str(log), "--output", str(alias / "nested-link" / "blocked.json")]) == 2
  assert not (canonical.parent / "blocked.json").exists()
  capsys.readouterr()


def test_system_temp_root_cannot_authorize_public_repository_output(tmp_path, capsys, monkeypatch):
  repo = tmp_path / "synthetic-repo"
  monkeypatch.setattr(history, "__file__", str(repo / "scripts" / "omp-command-history.py"))
  public = repo / "tests" / "fixtures"
  monkeypatch.setattr(history.tempfile, "gettempdir", lambda: str(public))
  log = write_log(tmp_path / "pi.jsonl", [tool("echo safe")])
  output = public / "private" / "history.json"
  assert history.main(["--pi-root", str(log), "--output", str(output)]) == 2
  assert not public.exists()
  cache_output = repo / ".cache" / "private" / "history.json"
  assert history.main(["--pi-root", str(log), "--output", str(cache_output)]) == 0
  assert cache_output.exists()
  capsys.readouterr()


@pytest.mark.parametrize("command", [
  "TOKEN='HeadSentinel123'\"TailSentinel123\" echo safe",
  "TOKEN=\"HeadSentinel123\"TailSentinel123 echo safe",
  "cli --password 'HeadSentinel123'TailSentinel123",
  "mysql -p'HeadSentinel123'\"TailSentinel123\"",
  "mysql -p\"HeadSentinel123\"TailSentinel123",
  "redis-cli -a 'HeadSentinel123'TailSentinel123",
  "curl -H 'Authorization: HeadSentinel123'\"TailSentinel123\"",
  "echo Bearer 'HeadSentinel123'TailSentinel123",
])
def test_adjacent_quoted_credentials_are_quarantined(tmp_path, capsys, command):
  artifact, output, captured = run(tmp_path, {"pi": write_log(tmp_path / "pi.jsonl", [tool(command)])}, capsys)
  assert artifact["records"] == []
  assert artifact["statistics"]["pi"]["redactionSkipped"] == 1
  assert "Sentinel123" not in output.read_text() + captured.out + captured.err


@pytest.mark.parametrize("command, expected", [
  ("TOKEN=Head'Sentinel123' echo safe", "TOKEN=REDACTED echo safe"),
  ("echo Bearer 'BearerSentinel123'", "echo Bearer 'REDACTED'"),
  ("printf '%s' 'normal'\"concat\"suffix", "printf '%s' 'normal'\"concat\"suffix"),
  ("mysql -pHead'Sentinel123'", "mysql -pREDACTED"),
])
def test_literal_concatenation_and_credential_boundaries(command, expected):
  assert history.redact(command) == expected
  assert history.redaction_findings(expected) == set()


@pytest.mark.parametrize("command, expected", [
  ("curl 'https://AccountSentinel123:PassSentinel123@example.test/a?x=ValueSentinel123&ShortSentinel123#FragmentSentinel123' && echo done", "curl 'https://REDACTED@example.test/a?x=REDACTED&REDACTED#REDACTED' && echo done"),
  ("curl https://AccountSentinel123@example.test/a?ShortSentinel123&echo done", "curl https://REDACTED@example.test/a?REDACTED&echo done"),
  ("curl https://example.test/a?x=ValueSentinel123&y=OtherSentinel123& echo done", "curl https://example.test/a?x=REDACTED&y=REDACTED& echo done"),
  ("curl https://example.test/a&&echo done", "curl https://example.test/a&&echo done"),
  ("echo MailSentinel123@example.test; curl https://example.test/a", "echo REDACTED_EMAIL; curl https://example.test/a"),
])
def test_url_credentials_queries_and_shell_controls(command, expected):
  safe = history.redact(command)
  assert safe == expected
  assert "Sentinel123" not in safe
  assert history.redaction_findings(safe) == set()


@pytest.mark.parametrize("root", ["/var/tmp", "/opt", "/workspace", "/workspaces", "/private", "/home", "/Users", "/root"])
def test_personal_path_roots_and_scp_colon(root):
  command = f"scp host:{root}/PathSentinel123/*.txt {root}/OtherSentinel123; rm -rf / > /dev/null"
  expected = "scp host:/REDACTED_PATH*.txt /REDACTED_PATH; rm -rf / > /dev/null"
  assert history.redact(command) == expected
  assert history.redaction_findings(expected) == set()


def test_identity_terms_are_literal_case_sensitive_and_private(tmp_path, capsys):
  command = "echo Name.Sentinel123 name.sentinel123 Team+Sentinel123"
  identities = ("Name.Sentinel123", "Team+Sentinel123")
  assert history.redact(command, identities) == "echo REDACTED_IDENTITY name.sentinel123 REDACTED_IDENTITY"
  log = write_log(tmp_path / "pi.jsonl", [tool(command)])
  output = tmp_path / "private" / "history.json"
  args = ["--pi-root", str(log), "--output", str(output)]
  for identity in identities:
    args.extend(["--identity-term", identity])
  assert history.main(args) == 0
  captured = capsys.readouterr()
  external = output.read_text() + captured.out + captured.err
  assert all(identity not in external for identity in identities)
  assert "identity-term" not in external
  assert json.loads(output.read_text())["records"][0]["command"] == history.redact(command, identities)
  assert history.main(args) == 2
  captured = capsys.readouterr()
  assert all(identity not in captured.out + captured.err for identity in identities)


@pytest.mark.parametrize("command, category", [
  ("echo sk-KnownSentinel123456789abc", "known-key"),
  ("echo -----BEGIN RSA PRIVATE KEY-----", "pem"),
  ("echo EmailSentinel123@example.test", "email"),
  ("echo 192.0.2.10", "ip"),
  ("echo 2001:db8::12", "ip"),
  ("cat /opt/PathSentinel123", "personal-path"),
  ("echo IdentitySentinel123", "identity"),
  ("TOKEN=ValueSentinel123", "credential"),
  ("mysql -pValueSentinel123", "credential"),
  ("TOKEN='REDACTED'TailSentinel123", "credential-tail"),
  ("curl https:REDACTED_EMAIL/a", "url-marker"),
  ("curl https://UserSentinel123@example.test/a", "url-credential"),
  ("curl https://example.test/a?ShortSentinel123", "url-query"),
])
def test_independent_scanner_reports_only_categories(command, category):
  findings = history.redaction_findings(command, ("IdentitySentinel123",))
  assert category in findings
  assert isinstance(findings, set)
  assert "Sentinel123" not in str(findings)


def test_second_scan_blocks_injected_first_pass_failure(tmp_path, capsys, monkeypatch):
  monkeypatch.setattr(history, "redact", lambda command, identities=(): command)
  command = "TOKEN=ShortSentinel123 echo safe"
  artifact, output, captured = run(tmp_path, {"pi": write_log(tmp_path / "pi.jsonl", [tool(command), tool("echo safe")])}, capsys)
  assert [record["command"] for record in artifact["records"]] == ["echo safe"]
  assert artifact["statistics"]["pi"]["secondPassSkipped"] == 1
  assert artifact["statistics"]["pi"]["redactionSkipped"] == 1
  assert artifact["statistics"]["pi"]["extracted"] == 1
  assert "ShortSentinel123" not in output.read_text() + captured.out + captured.err


@pytest.mark.parametrize("command", [
  "TOKEN=Head'Hidden Sentinel123' echo safe",
  "mysql -pHead\"Hidden Sentinel123\"",
  "echo Bearer Head'Hidden Sentinel123'",
  "curl -H Head'Hidden Sentinel123'",
  "curl https://User:'Url Sentinel123'@example.test/a",
  "curl 'https://User:UrlSentinel123@example.test/a'TailSentinel123",
])
def test_embedded_quote_spaces_and_url_concat_do_not_leak(tmp_path, capsys, command):
  artifact, output, captured = run(tmp_path, {"pi": write_log(tmp_path / "pi.jsonl", [tool(command)])}, capsys)
  assert artifact["records"] == []
  assert "Sentinel123" not in output.read_text() + captured.out + captured.err


def test_second_scan_exception_fails_without_artifact_or_secret(tmp_path, capsys, monkeypatch):
  def fail_scan(command, identities=()):
    raise ValueError("ScannerSentinel123")
  monkeypatch.setattr(history, "redaction_findings", fail_scan)
  log = write_log(tmp_path / "pi.jsonl", [tool("echo safe")])
  output = tmp_path / "private" / "history.json"
  assert history.main(["--pi-root", str(log), "--output", str(output), "--identity-term", "IdentitySentinel123"]) == 2
  assert not output.exists()
  captured = capsys.readouterr()
  assert "Sentinel123" not in captured.out + captured.err
  assert not captured.out


@pytest.mark.parametrize("spelling", [
  "Identity''Sentinel123",
  'Identity""Sentinel123',
  "'Identity'Sentinel123",
  'Identity"Sentinel123"',
  "'Identity'\"Sentinel123\"",
  "Iden\\titySentinel123",
  "IdentitySentinel12\\3",
  "prefixIdentity''Sentinel123suffix",
])
def test_shell_cooked_identity_is_quarantined_and_independently_found(tmp_path, capsys, spelling):
  identity = "IdentitySentinel123"
  command = "echo " + spelling
  assert identity not in command
  assert history.redact(command, (identity,)) is None
  assert history.redaction_findings(command, (identity,)) == {"identity"}
  log = write_log(tmp_path / "pi.jsonl", [tool(command)])
  output = tmp_path / "private" / "history.json"
  assert history.main(["--pi-root", str(log), "--output", str(output), "--identity-term", identity]) == 0
  captured = capsys.readouterr()
  artifact = json.loads(output.read_text())
  assert artifact["records"] == []
  assert artifact["statistics"]["pi"]["redactionSkipped"] == 1
  assert spelling not in output.read_text() + captured.out + captured.err
  assert identity not in output.read_text() + captured.out + captured.err


@pytest.mark.parametrize("command", [
  "echo Identity''Sentinel123",
  "echo identity''sentinel123",
  "echo 'Identity' 'Sentinel123'",
])
def test_cooked_identity_checks_preserve_ordinary_concat_case_and_word_boundaries(command):
  assert history.redact(command) == command
  assert history.redaction_findings(command) == set()
  if command != "echo Identity''Sentinel123":
    assert history.redact(command, ("IdentitySentinel123",)) == command
    assert history.redaction_findings(command, ("IdentitySentinel123",)) == set()


def test_second_scan_catches_cooked_identity_after_injected_redactor_failure(tmp_path, capsys, monkeypatch):
  monkeypatch.setattr(history, "redact", lambda command, identities=(): command)
  command = "echo Identity''Sentinel123"
  log = write_log(tmp_path / "pi.jsonl", [tool(command)])
  output = tmp_path / "private" / "history.json"
  assert history.main(["--pi-root", str(log), "--output", str(output), "--identity-term", "IdentitySentinel123"]) == 0
  artifact = json.loads(output.read_text())
  assert artifact["records"] == []
  assert artifact["statistics"]["pi"]["secondPassSkipped"] == 1
  assert command not in output.read_text() + capsys.readouterr().out
