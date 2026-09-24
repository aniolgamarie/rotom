"""Web 配置只产生明确引用，不访问旧 HOME、账号或网络。"""
import json

import pytest

from agentcfg.adapter import SecretRef
from agentcfg.pi import PiAdapter
from agentcfg.pi_web import configuration, environment_bindings
from agentcfg.schema import ConfigError
from test_pi_adapter import ROOT, pi_data


def setup(tmp_path):
  data = pi_data(tmp_path)
  data["plugins"]["pi-permissions"] = data["adapter_documents"]["plugins"]["plugins"]["pi-permissions"]
  data["profile"]["plugins"].append("pi-permissions")
  data["plugins"]["pi-web"] = data["adapter_documents"]["plugins"]["plugins"]["pi-web"]
  data["profile"]["plugins"].append("pi-web")
  options = data["profile"]["agent_options"]
  options["network"] = {"routes": {"web-direct": {"mode": "direct", "provider_ids": [], "service_ids": ["web:public", "web:brave"]}}}
  options["web"] = {"services": {"public": {"type": "public", "network_route": "web-direct"},
    "brave": {"type": "api", "network_route": "web-direct", "origins": ["https://api.search.brave.com"]}},
    "credentials": {"braveApiKey": "secret:brave"}, "settings": {"provider": "brave"},
    "models": {"summary": "main"}}
  return data


def test_selected_services_render_only_environment_references_and_optional_credentials(tmp_path):
  data = setup(tmp_path); adapter = PiAdapter(ROOT); adapter.validate(data)
  value = configuration(data)
  assert value["web_config"]["braveApiKey"].startswith("${AGENTCFG_PI_CREDENTIAL_")
  assert value["web_config"]["summaryModel"] == "agentcfg-fictional/fictional-chat"
  assert value["web_config"]["autoOpenBrowser"] is False
  bindings = environment_bindings(data)
  assert len(bindings) == 1 and isinstance(bindings[0].value, SecretRef) and bindings[0].required is False
  artifacts = adapter.render(data)
  manifest = json.loads(next(row.content for row in artifacts if row.target.path.endswith("agentcfg-manifest.json")))
  assert manifest["web_services"]["brave"]["network_route"] == "web-direct"
  assert "secret:brave" not in json.dumps(manifest["web_config"])
  launch = adapter.launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime", instance_root=tmp_path / "instance", lock_identity="fixture")
  assert any(row.name == bindings[0].name and row.required is False for row in launch.environment)


@pytest.mark.parametrize("kind", ["unselected", "route", "endpoint", "credential-service", "literal-key", "unknown-setting", "unknown-service", "model", "environment-proxy", "range"])
def test_invalid_or_undeclared_web_bindings_fail_without_falling_back(tmp_path, kind):
  data = setup(tmp_path); web = data["profile"]["agent_options"]["web"]
  if kind == "unselected": data["plugins"].pop("pi-web"); data["profile"]["plugins"].remove("pi-web")
  if kind == "route": web["services"]["brave"]["network_route"] = "absent"
  if kind == "endpoint": web["endpoints"] = {"braveBaseUrl": "https://unselected.example.invalid"}
  if kind == "credential-service": web["credentials"]["exaApiKey"] = "secret:other"
  if kind == "literal-key": web["credentials"]["braveApiKey"] = "synthetic literal key"
  if kind == "unknown-setting": web["settings"]["guess_unknown"] = True
  if kind == "unknown-service": web["services"]["invented"] = {"type": "api", "network_route": "web-direct"}
  if kind == "model": web["models"]["summary"] = "unselected-model"
  if kind == "environment-proxy": web["settings"]["ssrf"] = {"trustEnvProxy": True}
  if kind == "range": web["services"]["public"]["allow_ranges"] = ["0.0.0.0/0"]
  with pytest.raises(ConfigError): PiAdapter(ROOT).validate(data)


def test_no_web_selection_preserves_the_core_profile(tmp_path):
  data = pi_data(tmp_path)
  assert configuration(data) is None and environment_bindings(data) == []
  PiAdapter(ROOT).validate(data)


def test_github_clone_requires_output_tool_and_github_https_origin(tmp_path):
  data = setup(tmp_path); options = data["profile"]["agent_options"]; web = options["web"]
  assert configuration(data)["web_config"]["githubClone"]["enabled"] is False
  options.setdefault("paths", {}).setdefault("roots", {})["clones"] = {"path": str(tmp_path / "clones"), "purpose": "write"}
  options.setdefault("external_tools", {})["git"] = {"executable": "/fictional/git", "version": "fixture"}
  web["github_clone"] = {"root_ref": "clones", "git_tool_ref": "git", "max_repo_size_mb": 123}
  with pytest.raises(ConfigError, match="pi-web-github-origin"): configuration(data)
  web["services"]["github"] = {"type": "api", "origins": ["https://github.com", "https://api.github.com"], "network_route": "web-direct"}
  options["network"]["routes"]["web-direct"]["service_ids"].append("web:github")
  assert configuration(data)["web_config"]["githubClone"] == {"enabled": True, "maxRepoSizeMB": 123}
  PiAdapter(ROOT).validate(data)
  options["paths"]["roots"]["clones"]["purpose"] = "read"
  with pytest.raises(ConfigError, match="pi-web-github-output-root"): configuration(data)


def test_remaining_web_settings_are_typed_and_explicit_routes_cannot_name_unselected_services(tmp_path):
  data = setup(tmp_path); web = data["profile"]["agent_options"]["web"]
  web["settings"].pop("provider")
  web["settings"].update(searchRouting={"providers": ["brave"], "fallbackOn": ["transient", "quota"]},
    fetchRouting={"providers": ["http"], "allowRemoteHostedProviders": False}, fetch={"timeout": 12.5},
    youtube={"enabled": False}, pdf={"enabled": True, "provider": "unpdf", "maxPages": 10},
    toolNames={"fetchContent": "selected_fetch"}, firecrawlApiVersion="v2", firecrawlFreshScrape=True,
    brightdataSerpZone="search_zone", serpdiveModel="mako", datalabMode="accurate", datalabProcessingLocation="eu")
  PiAdapter(ROOT).validate(data)
  assert configuration(data)["web_config"]["fetch"]["timeout"] == 12.5
  web["settings"]["fetchRouting"]["providers"].append("tinyfish")
  with pytest.raises(ConfigError, match="pi-web-fetch-provider-not-selected"): configuration(data)
  web["settings"]["fetchRouting"]["providers"].pop()
  web["settings"]["provider"] = "brave"
  with pytest.raises(ConfigError, match="pi-web-routing-conflict"): configuration(data)
  web["settings"].pop("provider"); web["settings"]["pdf"]["provider"] = "datalab"
  with pytest.raises(ConfigError, match="pi-web-pdf-provider-not-selected"): configuration(data)


def test_searxng_header_credentials_are_only_generated_references(tmp_path):
  data = setup(tmp_path); options = data["profile"]["agent_options"]; web = options["web"]
  web["services"]["searxng"] = {"type": "api", "origins": ["https://search.invalid"], "network_route": "web-direct"}
  options["network"]["routes"]["web-direct"]["service_ids"].append("web:searxng")
  web["header_credentials"] = {"searxng": {"CF-Access-Client-Secret": "secret:search-gate"}}
  PiAdapter(ROOT).validate(data)
  native = configuration(data)
  assert native["web_config"]["searxngHeaders"]["CF-Access-Client-Secret"].startswith("${AGENTCFG_PI_CREDENTIAL_")
  assert "secret:search-gate" not in json.dumps(native)
  assert len(environment_bindings(data)) == 2
  web["header_credentials"]["searxng"]["Host"] = "secret:host"
  with pytest.raises(ConfigError, match="pi-web-header-name"): configuration(data)


def test_service_only_proxy_credentials_do_not_bind_a_model_provider(tmp_path):
  data = setup(tmp_path); options = data["profile"]["agent_options"]
  route = options["network"]["routes"]["web-direct"]
  assert route["provider_ids"] == []
  route.update(mode="proxy", proxy_url="http://127.0.0.1:8123", credential_ref="secret:proxy-key")
  adapter = PiAdapter(ROOT); adapter.validate(data)
  launch = adapter.launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime", instance_root=tmp_path / "instance", lock_identity="fixture")
  assert any(row.name.startswith("AGENTCFG_PI_ROUTE_CREDENTIAL_") and isinstance(row.value, SecretRef) for row in launch.environment)


def test_multiple_search_providers_have_a_typed_source_and_conflicting_sources_fail(tmp_path):
  data = setup(tmp_path); web = data["profile"]["agent_options"]["web"]
  web["settings"].pop("provider"); web["providers"] = ["brave"]
  PiAdapter(ROOT).validate(data)
  assert configuration(data)["web_config"]["searchProvider"] == ["brave"]
  web["settings"]["provider"] = "brave"
  with pytest.raises(ConfigError, match="pi-web-provider-conflict"): PiAdapter(ROOT).validate(data)
  web.pop("providers"); web["settings"]["searchProvider"] = "auto"
  with pytest.raises(ConfigError, match="pi-web-provider-conflict"): PiAdapter(ROOT).validate(data)


def test_web_provider_names_exclude_non_search_service_bindings(tmp_path):
  data = setup(tmp_path); web = data["profile"]["agent_options"]["web"]
  for name in ("public", "github", "gemini-auth", "jina-reader"):
    web["settings"]["provider"] = name
    with pytest.raises(ConfigError): PiAdapter(ROOT).validate(data)


def test_curator_browser_work_requires_explicit_selection_and_disabled_needs_no_browser(tmp_path):
  data = setup(tmp_path); web = data["profile"]["agent_options"]["web"]
  web["curator"] = {"enabled": False}
  PiAdapter(ROOT).validate(data)
  web["settings"]["workflow"] = "summary-review"
  with pytest.raises(ConfigError, match="pi-web-curator-required"): PiAdapter(ROOT).validate(data)
  web["curator"]["enabled"] = True
  with pytest.raises(ConfigError, match="pi-web-curator-browser-binding"): PiAdapter(ROOT).validate(data)
  web["curator"]["browser_network"] = "user-browser"
  PiAdapter(ROOT).validate(data)


def test_authenticated_fetch_projects_a_profile_scoped_secret_and_exact_https_origins(tmp_path):
  data = setup(tmp_path); options = data["profile"]["agent_options"]; web = options["web"]
  options["network"]["routes"]["web-direct"]["service_ids"].append("web:authenticated")
  web["services"]["authenticated"] = {"type": "api", "network_route": "web-direct", "origins": ["https://docs.example.invalid"]}
  web["auth_fetch"] = {"docs": {"origins": ["https://docs.example.invalid"], "cookie_ref": "secret:docs-cookie"}}
  PiAdapter(ROOT).validate(data); projected = configuration(data)
  assert projected["web_config"]["authFetch"]["docs"] == {"hosts": ["docs.example.invalid"], "redirects": "same-origin", "cache": "off"}
  assert projected["web_auth_fetch"]["docs"]["cookie_reference"].startswith("${AGENTCFG_PI_CREDENTIAL_")
  assert "secret:docs-cookie" not in json.dumps(projected)
  assert len(environment_bindings(data)) == 2
  web["auth_fetch"]["docs"]["origins"] = ["https://other.example.invalid"]
  with pytest.raises(ConfigError, match="pi-web-auth-fetch-origin"): PiAdapter(ROOT).validate(data)
  web["services"]["authenticated"]["origins"] = ["http://docs.example.invalid"]
  web["auth_fetch"]["docs"]["origins"] = ["http://docs.example.invalid"]
  with pytest.raises(ConfigError, match="pi-web-auth-fetch-origin"): PiAdapter(ROOT).validate(data)


def test_browser_profiles_use_explicit_roots_and_are_denied_to_ordinary_tools(tmp_path):
  data = setup(tmp_path); options = data["profile"]["agent_options"]; web = options["web"]
  options["paths"] = {"roots": {"browser": {"path": str(tmp_path / "browser"), "purpose": "read"}}}
  web["browser_profiles"] = {"work": {"root_ref": "browser", "browser": "chrome", "profile": "Default",
    "password_ref": "secret:browser-password", "allowed_hosts": ["gemini.google.com", "accounts.google.com", "www.google.com"]}}
  web["services"]["gemini-web"] = {"type": "api", "origins": ["https://gemini.google.com"], "network_route": "web-direct"}
  options["network"]["routes"]["web-direct"]["service_ids"].append("web:gemini-web")
  web["gemini_browser_profile"] = "work"
  adapter = PiAdapter(ROOT); adapter.validate(data)
  projected = configuration(data)
  assert projected["web_config"]["browserCookies"] == {"browser": "chrome", "profile": "Default"}
  assert projected["web_config"]["agentcfgBrowserProfile"] == "work"
  assert "secret:browser-password" not in json.dumps(projected)
  manifest = json.loads(next(row.content for row in adapter.render(data) if row.target.path.endswith("agentcfg-manifest.json")))
  assert "browser" in manifest["options"]["permissions"]["denied_roots"]
  assert "browser" not in options.get("permissions", {}).get("denied_roots", [])
  assert len(environment_bindings(data)) == 2
  web["browser_profiles"]["work"]["root_ref"] = "unselected"
  with pytest.raises(ConfigError, match="pi-web-browser-root"): adapter.validate(data)


def test_auth_fetch_can_bind_a_browser_profile_without_a_literal_cookie(tmp_path):
  data = setup(tmp_path); options = data["profile"]["agent_options"]; web = options["web"]
  options["paths"] = {"roots": {"browser": {"path": str(tmp_path / "browser"), "purpose": "read"}}}
  web["browser_profiles"] = {"work": {"root_ref": "browser", "browser": "chrome", "profile": "工作档案",
    "password_ref": "secret:browser-password", "allowed_hosts": ["localhost"]}}
  web["services"]["authenticated"] = {"type": "api", "network_route": "web-direct", "origins": ["https://localhost"]}
  options["network"]["routes"]["web-direct"]["service_ids"].append("web:authenticated")
  web["auth_fetch"] = {"docs": {"origins": ["https://localhost"], "browser_profile": "work"}}
  PiAdapter(ROOT).validate(data)
  assert configuration(data)["web_auth_fetch"]["docs"]["browser_profile"] == "work"
  assert len(environment_bindings(data)) == 2
  web["auth_fetch"]["docs"]["cookie_ref"] = "secret:unexpected"
  with pytest.raises(ConfigError, match="pi-web-auth-fetch-source"): PiAdapter(ROOT).validate(data)


def test_remote_curator_is_an_explicit_machine_binding(tmp_path):
  data = setup(tmp_path); web = data["profile"]["agent_options"]["web"]
  web["curator"] = {"enabled": True, "browser_network": "user-browser", "bind": "0.0.0.0"}
  with pytest.raises(ConfigError, match="pi-web-curator-origin-required"): PiAdapter(ROOT).validate(data)
  web["curator"]["advertised_origin"] = "https://curator.example.invalid"
  PiAdapter(ROOT).validate(data)
  web["curator"]["advertised_origin"] += "/unselected/path"
  with pytest.raises(ConfigError, match="pi-web-url"): PiAdapter(ROOT).validate(data)


def test_media_helpers_require_declared_noninteractive_tools(tmp_path):
  data = setup(tmp_path); options = data["profile"]["agent_options"]
  options["web"]["media"] = {"ffmpeg_tool_ref": "frames"}
  with pytest.raises(ConfigError, match="pi-web-media-tool-binding"): PiAdapter(ROOT).validate(data)
  options["external_tools"] = {"frames": {"executable": "/fixture/ffmpeg", "version": "fixture"}}
  PiAdapter(ROOT).validate(data)
  options["external_tools"]["frames"]["args"] = ["--unselected"]
  with pytest.raises(ConfigError, match="pi-web-media-tool-binding"): PiAdapter(ROOT).validate(data)
