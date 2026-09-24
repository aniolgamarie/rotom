"""doctor 的配置、依赖、加载、认证和执行证据互不冒充。"""
from copy import deepcopy
import json
from types import SimpleNamespace

from agentcfg.pi import PiAdapter
from agentcfg.pi_evidence import identity_for
from test_pi_adapter import pi_data, ROOT
from test_pi_release_gate import passed, save


def projection(tmp_path):
  return {"data": pi_data(tmp_path), "deployed": False, "dependencies": "sync-required", "lock_identity": "a" * 64,
    "runtime_identity": "b" * 64, "platform": {"os": "linux", "architecture": "x86_64", "engine": "node"}}


def test_doctor_layers_missing_packages_and_unselected_capabilities_without_secret_inspection(tmp_path):
  p = projection(tmp_path)
  rows = PiAdapter(ROOT).capability_diagnostics(p)
  host = next(row for row in rows if row["id"] == "pi-host")
  assert host["configured"] and not host["deployed"] and host["dependencies"] == "sync-required"
  assert host["load_evidence"] == host["execution_evidence"] == "not-run"
  assert host["authentication"] == "not-inspected" and "PI_DEPENDENCIES_MISSING" in host["blockers"]
  assert host["location_id"].startswith("capability:")
  codex = next(row for row in rows if row["id"] == "model-delegate:codex")
  assert not codex["selected"] and codex["blockers"] == [] and codex["authentication"] == "not-required"


def test_bootstrap_does_not_claim_a_bound_model(tmp_path):
  p = projection(tmp_path); p["data"]["profile"]["roles"] = {}
  host = PiAdapter(ROOT).capability_diagnostics(p)[0]
  assert not host["configured"] and "PI_MODEL_UNBOUND" in host["blockers"]


def test_matching_observations_are_dated_and_policy_changes_invalidate_them(tmp_path):
  from agentcfg.pi_diagnostics import diagnostic_identity
  p = projection(tmp_path); p.update(deployed=True, dependencies="installed")
  p["data"]["profile"]["agent_options"]["diagnostics"] = {"evidence_root": str(tmp_path), "evidence_paths": ["load.json", "auth.json", "execute.json"]}
  identity = diagnostic_identity(p)
  for name, stage in (("load", "load"), ("auth", "authentication"), ("execute", "execution")):
    save(tmp_path, name + ".json", passed("native", capability_id="pi-host", test_case_id=stage, identity=identity))
  row = PiAdapter(ROOT).capability_diagnostics(p)[0]
  assert row["load_evidence"] == row["execution_evidence"] == "verified"
  assert row["authentication"] == "observed-ready" and row["observed_at"]["authentication"]
  p["data"]["profile"]["agent_options"]["permissions"] = {"policy_ref": "project-default"}
  row = PiAdapter(ROOT).capability_diagnostics(p)[0]
  assert row["load_evidence"] == row["execution_evidence"] == "stale"
  assert row["authentication"] == "not-inspected"


def test_authentication_not_run_can_report_pending_login_without_reading_credentials(tmp_path):
  from agentcfg.pi_diagnostics import diagnostic_identity
  p = projection(tmp_path)
  p["data"]["profile"]["agent_options"]["diagnostics"] = {"evidence_root": str(tmp_path), "evidence_paths": ["observation.json"]}
  save(tmp_path, "observation.json", passed("native", capability_id="pi-host", test_case_id="authentication", identity=diagnostic_identity(p),
    status="not-run", started_at=None, finished_at=None, command=[], reason="authentication-required"))
  row = PiAdapter(ROOT).capability_diagnostics(p)[0]
  assert row["authentication"] == "pending-login"
  assert "PI_AUTHENTICATION_PENDING" in row["blockers"]


def test_missing_required_runtime_sets_dependency_exit_code_without_changing_dsh(tmp_path):
  from agentcfg.adapter import Adapter
  p = projection(tmp_path); adapter = PiAdapter(ROOT)
  assert adapter.diagnostic_exit_code(adapter.capability_diagnostics(p)) == 5
  p["dependencies"] = "installed"
  assert adapter.diagnostic_exit_code(adapter.capability_diagnostics(p)) == 0
  assert Adapter.diagnostic_exit_code(object(), None) == 0


def test_live_reachability_requires_explicit_routes_and_does_not_read_auth(tmp_path, monkeypatch):
  from agentcfg import pi_diagnostics
  p = projection(tmp_path)
  calls = []
  monkeypatch.setattr(pi_diagnostics, "probe_endpoint", lambda *args: calls.append(args) or {"status": "reachable"})
  rows = PiAdapter(ROOT).live_diagnostics(p["data"])
  assert rows and all(row["reason"] == "explicit-route-required" for row in rows)
  assert calls == []
  providers = list(p["data"]["providers"])
  route = {"mode": "proxy", "proxy_url": "http://proxy.invalid:8080", "provider_ids": providers}
  p["data"]["profile"]["agent_options"]["network"] = {"routes": {"explicit-proxy": route}}
  rows = PiAdapter(ROOT).live_diagnostics(p["data"])
  assert all(row["status"] == "reachable" for row in rows)
  assert calls and all(call[1] == route for call in calls)


def test_head_probe_has_no_environment_proxy_fallback_or_authorization(monkeypatch):
  import http.client
  from agentcfg.pi_diagnostics import probe_endpoint
  events = []
  class Connection:
    def __init__(self, *args, **kwargs): events.append((args, kwargs))
    def set_tunnel(self, *args): events.append(("tunnel", args))
    def request(self, *args, **kwargs): events.append((args, kwargs))
    def getresponse(self): return SimpleNamespace(status=401)
    def close(self): events.append("closed")
  monkeypatch.setattr(http.client, "HTTPSConnection", Connection)
  monkeypatch.setenv("HTTPS_PROXY", "http://ambient.invalid")
  monkeypatch.setenv("NO_PROXY", "*")
  result = probe_endpoint("https://service.invalid/v1", {"mode": "proxy", "proxy_url": "http://bound.invalid:8888"})
  assert result == {"status": "reachable", "http_status": 401}
  assert events[0] == (("bound.invalid", 8888), {"timeout": 5})
  assert events[1] == ("tunnel", ("service.invalid", 443))
  assert events[2] == (("HEAD", "/v1"), {"headers": {"User-Agent": "agentcfg-doctor"}})
  assert events[3] == "closed"


def test_codex_diagnostics_report_restricted_support_without_probing_auth(tmp_path, monkeypatch):
  from agentcfg import pi_codex_admission
  p = projection(tmp_path)
  p["data"]["plugins"]["model-delegate"] = p["data"]["adapter_documents"]["plugins"]["plugins"]["model-delegate"]
  p["data"]["profile"]["plugins"].append("model-delegate")
  p["data"]["profile"]["agent_options"]["model_delegate"] = {"enabled": True, "backends": ["codex"],
    "codex": {"model": "fictional-model", "mode": "readonly", "network_route": "direct", "native_execution": {"allow_shell": True, "tool_network": "none"}}}
  monkeypatch.setattr(pi_codex_admission, "admit_codex_execution", lambda *args: (_ for _ in ()).throw(AssertionError("doctor must not inspect auth")))
  row = next(row for row in PiAdapter(ROOT).capability_diagnostics(p) if row["id"] == "model-delegate:codex")
  assert row["selected"] and row["configuration_admission"]["status"] == "not-inspected"
  assert row["configuration_admission"]["atomic_config_binding"] is False
  assert "organization-or-unknown-account-not-supported" in row["configuration_admission"]["limitations"]


def test_public_oauth_mcp_still_requires_authentication_without_a_client_secret(tmp_path):
  p = projection(tmp_path); data = p["data"]
  for name in ("pi-permissions", "pi-mcp"):
    data["plugins"][name] = data["adapter_documents"]["plugins"]["plugins"][name]
    data["profile"]["plugins"].append(name)
  data["mcp"] = {"fixture": {"transport": "streamable-http", "url": "https://service.invalid/mcp"}}
  data["profile"]["mcp"] = ["fixture"]
  data["profile"]["agent_options"]["mcp"] = {"servers": {"fixture": {"transport": "streamable-http", "network_route": "mcp",
    "authentication": "oauth", "oauth": {"grant_type": "authorization_code", "redirect_uri": "http://localhost:8765/callback", "allowed_origins": ["https://auth.invalid"]}}}}
  data["profile"]["agent_options"]["network"] = {"routes": {"mcp": {"mode": "direct", "provider_ids": [], "service_ids": ["mcp:fixture"]}}}
  row = next(row for row in PiAdapter(ROOT).capability_diagnostics(p) if row["id"] == "pi-mcp")
  assert row["selected"] and row["authentication"] == "not-inspected"


def test_web_service_reachability_uses_declared_origins_and_never_guesses_public_targets(tmp_path, monkeypatch):
  from agentcfg import pi_diagnostics
  from test_pi_web import setup
  data = setup(tmp_path); calls = []
  data["profile"]["agent_options"]["network"]["routes"]["web-direct"].pop("provider_ids", None)
  monkeypatch.setattr(pi_diagnostics, "probe_endpoint", lambda *args: calls.append(args) or {"status": "reachable"})
  rows = pi_diagnostics.service_reachability(data)
  assert len(calls) == 1 and calls[0][0] == "https://api.search.brave.com"
  assert any(row.get("reason") == "public-target-not-selected" for row in rows)
  assert "secret:brave" not in json.dumps(rows)
  data["profile"]["agent_options"]["network"]["routes"]["web-direct"]["service_ids"] = []
  calls.clear(); rows = pi_diagnostics.service_reachability(data)
  assert calls == [] and all(row["reason"] == "explicit-route-required" for row in rows)


def test_public_only_web_does_not_claim_an_account_requirement(tmp_path):
  from test_pi_web import setup
  p = projection(tmp_path); p["data"] = setup(tmp_path)
  web = p["data"]["profile"]["agent_options"]["web"]
  web["services"].pop("brave"); web["credentials"] = {}; web["settings"] = {}
  p["data"]["profile"]["agent_options"]["network"]["routes"]["web-direct"]["service_ids"] = ["web:public"]
  row = next(row for row in PiAdapter(ROOT).capability_diagnostics(p) if row["id"] == "pi-web")
  assert row["authentication"] == "not-required"
