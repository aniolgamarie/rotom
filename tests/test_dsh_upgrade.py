"""RC2 用户层的离线编解码、逐字段部署和配置边界。"""

import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

from agentcfg import deployment as dep, native
from agentcfg.adapter import Artifact, ManagedTarget, Ownership
from agentcfg.dsh import DshAdapter, OPTIONS
from agentcfg.render import RenderCandidate
from agentcfg.storage import Conflict, Tree, ensure_private


ROOT = Path(__file__).resolve().parents[1]
PATCH = "dsh-home/profiles/agentcfg/cordis.patch.yml"
BINDING = {"machine": "test", "local": "/synthetic/local.toml", "profile": "test"}
LAUNCH = {"lock_identity": "fixture", "shared_files": [PATCH]}


def candidate(value="A", *, with_ui=True):
  artifacts = [Artifact(ManagedTarget(PATCH, Ownership.FIELDS, "cordis-yaml", "/llm-pi-ai/config/providers/agentcfg-fixture/baseURL"), json.dumps(value).encode())]
  if with_ui:
    artifacts.append(Artifact(ManagedTarget(PATCH, Ownership.INITIALIZE, "cordis-yaml", "/dsh-tui/config/whale"), b"false"))
  return RenderCandidate(str((value, with_ui)), tuple(artifacts))


def test_cordis_roundtrip_preserves_unknown_rows_fields_and_inert_js(tmp_path, sentinel_factory):
  sentinel = sentinel_factory(tmp_path)
  raw = b"""- id: custom
  name: arbitrary-plugin
  config:
    dynamic: !!js process.exit(99)
    unknown: {nested: keep}
- insert:
  - name: custom-insert
    config: {dynamic: !!js 'unknownFunction()'}
- id: id-only
"""
  document = dep.parse_native(raw, "cordis-yaml")
  assert document["custom"]["config"]["dynamic"] == native.JS("process.exit(99)")
  assert document["id-only"] == {}
  dep.put_field(document, "/custom/config/managed", dep.encoded(False))
  encoded = dep.encode_native(document, "cordis-yaml")
  restored = dep.parse_native(encoded, "cordis-yaml")
  assert restored == document
  assert restored.rows == document.rows
  assert dep.encode_native(restored, "cordis-yaml") == encoded
  assert restored.rows[1]["insert"][0]["config"]["dynamic"] == native.JS("unknownFunction()")
  sentinel.assert_unchanged()


@pytest.mark.parametrize("raw", [
  "- id: same\n- id: same\n", "- id: ''\n", "- id: row\n  config: {}\n  config: {}\n",
  "- id: row\n  config: !!js []\n", "- id: row\n  config: !!python/object:os.system {}\n",
  "- invalid: row\n", "- insert: invalid\n", "- plain\n", "{row: {config: {}}}\n",
])
def test_cordis_codec_rejects_ambiguous_or_invalid_rows(raw):
  with pytest.raises(Conflict):
    dep.parse_native(raw.encode(), "cordis-yaml")


def test_cordis_managed_parent_cannot_replace_inert_js():
  document = dep.parse_native(b"- id: dsh-tui\n  config: !!js arbitraryConfig()\n", "cordis-yaml")
  with pytest.raises(Conflict, match="原生父字段"):
    dep.put_field(document, "/dsh-tui/config/whale", dep.encoded(False))
  document = dep.parse_native(b"- id: dsh-tui\n", "cordis-yaml")
  document["dsh-tui"]["id"] = "other"
  with pytest.raises(Conflict):
    dep.encode_native(document, "cordis-yaml")


def test_cordis_deployment_preserves_native_edits_and_conflicts_on_managed_update(tmp_path):
  root, state = tmp_path / "instance", tmp_path / "state"
  dep.apply(root, state, candidate(), BINDING, LAUNCH)
  with Tree(root) as tree:
    document = dep.parse_native(tree.read(PATCH)[0], "cordis-yaml")
    document["dsh-tui"]["config"].update(whale=True, custom=native.JS("runtimeCustom()"))
    document["custom"] = {"config": {"unknown": "keep"}}
    document.rows.append({"insert": [{"name": "native-addon", "config": {"unknown": 1}}]})
    tree.write_state(PATCH, dep.encode_native(document, "cordis-yaml"))
    tree.write_state("dsh-home/settings.yaml", b"legacy-user-data: keep\n")
    tree.write_state("dsh-home/accounts.json", b"synthetic native account data\n")
    tree.write_state("dsh-home/sessions/session.json", b"synthetic session data\n")
  assert dep.apply(root, state, candidate(), BINDING, LAUNCH)["changes"] == 0
  dep.apply(root, state, candidate("B"), BINDING, LAUNCH)
  with Tree(root) as tree:
    current = dep.parse_native(tree.read(PATCH)[0], "cordis-yaml")
    assert current["dsh-tui"]["config"]["whale"] is True
    assert current["dsh-tui"]["config"]["custom"] == native.JS("runtimeCustom()")
    assert current["custom"]["config"]["unknown"] == "keep"
  dep.rollback(root, state, BINDING)
  with Tree(root) as tree:
    current = dep.parse_native(tree.read(PATCH)[0], "cordis-yaml")
    assert current["llm-pi-ai"]["config"]["providers"]["agentcfg-fixture"]["baseURL"] == "A"
    assert current["dsh-tui"]["config"]["whale"] is True
    current["llm-pi-ai"]["config"]["providers"]["agentcfg-fixture"]["baseURL"] = "native-edit"
    tree.write_state(PATCH, dep.encode_native(current, "cordis-yaml"))
  with pytest.raises(Conflict):
    dep.apply(root, state, candidate("C"), BINDING, LAUNCH)
  assert (root / "dsh-home/settings.yaml").read_bytes() == b"legacy-user-data: keep\n"
  assert (root / "dsh-home/accounts.json").read_bytes() == b"synthetic native account data\n"
  assert (root / "dsh-home/sessions/session.json").read_bytes() == b"synthetic session data\n"


def test_cordis_rollback_distinguishes_new_row_from_existing_id_only_row(tmp_path):
  root, state = tmp_path / "instance", tmp_path / "state"
  dep.apply(root, state, candidate(with_ui=False), BINDING, LAUNCH)
  with Tree(root) as tree:
    document = dep.parse_native(tree.read(PATCH)[0], "cordis-yaml")
    document["existing"] = {}
    tree.write_state(PATCH, dep.encode_native(document, "cordis-yaml"))
  extra = [Artifact(ManagedTarget(PATCH, Ownership.FIELDS, "cordis-yaml", f"/{name}/config/managed"), b"true") for name in ("existing", "new")]
  expanded = RenderCandidate("expanded", candidate(with_ui=False).artifacts + tuple(extra))
  dep.apply(root, state, expanded, BINDING, LAUNCH)
  dep.rollback(root, state, BINDING)
  with Tree(root) as tree:
    document = dep.parse_native(tree.read(PATCH)[0], "cordis-yaml")
  assert document["existing"] == {}
  assert "new" not in document


def test_tui_preferences_are_initial_only_and_preserve_runtime_unknown_json(tmp_path):
  adapter = DshAdapter(ROOT)
  root, state = tmp_path / "instance", tmp_path / "state"
  preferences = [Artifact(ManagedTarget("user-home/.dsh-tui/onboarding.json", Ownership.INITIALIZE, "json", selector), json.dumps(value).encode()) for selector, value in (("/completed", True), ("/version", 1))]
  proposal = RenderCandidate("prefs", tuple(preferences))
  dep.apply(root, state, proposal, BINDING, {"lock_identity": "fixture"})
  with Tree(root) as tree:
    tree.write_state("user-home/.dsh-tui/onboarding.json", b'{"completed":false,"version":1,"unknown":"keep"}')
  assert dep.apply(root, state, proposal, BINDING, {"lock_identity": "fixture"})["changes"] == 0
  assert json.loads((root / "user-home/.dsh-tui/onboarding.json").read_bytes()) == {"completed": False, "version": 1, "unknown": "keep"}
  assert adapter.shared_files == (PATCH,)


def test_existing_unowned_preference_is_not_claimed_or_overwritten(tmp_path):
  root, state = tmp_path / "instance", tmp_path / "state"
  ensure_private(root)
  with Tree(root) as tree:
    tree.write_state("user-home/.dsh-tui/onboarding.json", b'{"unknown":"keep"}')
  proposal = RenderCandidate("pref", (Artifact(ManagedTarget("user-home/.dsh-tui/onboarding.json", Ownership.INITIALIZE, "json", "/completed"), b"true"),))
  with pytest.raises(Conflict):
    dep.apply(root, state, proposal, BINDING, {"lock_identity": "fixture"})
  assert (root / "user-home/.dsh-tui/onboarding.json").read_bytes() == b'{"unknown":"keep"}'


@pytest.mark.parametrize("options", [
  {"cursor_port": 8318},
  {"provider_options": {"fixture": {"retryPolicy": {"mode": "always"}}}},
  {"provider_options": {"fixture": {"retryPolicy": {"mode": "normal", "maxRetries": 3}}}},
  {"provider_options": {"fixture": {"retryPolicy": {"mode": "normal", "maxRetries": -1}}}},
])
def test_retired_cursor_port_and_unbounded_retry_configuration_are_rejected(options):
  with pytest.raises(ValidationError):
    validate({"preset": "standard", "theme": "rotom-poimandres", "terminal_images": False, **options}, OPTIONS)


@pytest.mark.parametrize("retries", [None, 0, 1, 2])
def test_provider_retry_is_bounded_and_reasoning_is_not_forced(retries):
  provider_options = {} if retries is None else {"retryPolicy": {"mode": "normal", "maxRetries": retries}}
  validate({"preset": "standard", "theme": "rotom-poimandres", "terminal_images": False,
    "provider_options": {"fixture": provider_options}}, OPTIONS)
  data = {"providers": {"fixture": {"auth_kind": "api-key", "base_url": "https://fixture.invalid/v1", "protocol": "openai-compatible"}},
    "models": {"fixture": {"provider": "fixture", "remote_id": "fixture-model", "input": ["text"]}},
    "profile": {"agent_options": {"provider_options": {"fixture": provider_options}}},
    "adapter_documents": {"bindings": {"protocols": {"openai-compatible": "openai-completions"}}}}
  fields = dict(DshAdapter(ROOT)._api_fields(data))
  assert fields["/llm-pi-ai/config/providers/agentcfg-fixture/retryPolicy"] == {"mode": "normal", "maxRetries": retries or 0}
  assert all(not path.endswith("/reasoning") for path in fields)


@pytest.mark.parametrize("legacy_path", ["env-guard.mjs", "dsh-home/settings.yaml"])
@pytest.mark.parametrize("pending", [False, True])
def test_legacy_deployment_guard_preserves_state_accounts_and_sessions(tmp_path, sentinel_factory, legacy_path, pending):
  root, state = tmp_path / "instance", tmp_path / "state"
  old = RenderCandidate("legacy", (Artifact(ManagedTarget(legacy_path, Ownership.FILE, "bytes"), b"legacy owned asset"),))
  dep.apply(root, state, old, BINDING, {"lock_identity": "old"})
  with Tree(root) as tree:
    tree.write_state("dsh-home/account.json", b"synthetic native account")
    tree.write_state("dsh-home/session.json", b"synthetic native session")
  if pending:
    with Tree(state) as tree:
      saved = dep.read_state(tree)
      tree.write_state("pending.json", dep.json_bytes({"after_state": saved, "changes": []}))
  before_root, before_state = sentinel_factory(root), sentinel_factory(state)
  with pytest.raises(Conflict, match="迁移验收"):
    dep.apply(root, state, candidate(), BINDING, LAUNCH, state_guard=DshAdapter(ROOT).validate_deployment_state)
  from types import SimpleNamespace
  from agentcfg.commands import current_plan
  workspace = SimpleNamespace(instance=root, state_root=state, adapter=DshAdapter(ROOT))
  with pytest.raises(Conflict, match="迁移验收"):
    current_plan(workspace, None, None)
  before_root.assert_unchanged()
  before_state.assert_unchanged()


def test_current_generation_allows_future_locks_and_rollback(tmp_path):
  root, state = tmp_path / "instance", tmp_path / "state"
  guard = DshAdapter(ROOT).validate_deployment_state
  dep.apply(root, state, candidate(), BINDING, LAUNCH, state_guard=guard)
  dep.apply(root, state, candidate("B"), BINDING, {**LAUNCH, "lock_identity": "future"}, state_guard=guard)
  dep.rollback(root, state, BINDING)
  with Tree(root) as tree:
    assert dep.parse_native(tree.read(PATCH)[0], "cordis-yaml")["llm-pi-ai"]["config"]["providers"]["agentcfg-fixture"]["baseURL"] == "A"


def test_legacy_owner_remains_blocked_after_first_deployment_rollback(tmp_path, sentinel_factory):
  root, state = tmp_path / "instance", tmp_path / "state"
  path = "dsh-home/settings.yaml"
  legacy = RenderCandidate("legacy", (Artifact(ManagedTarget(path, Ownership.FILE, "bytes"), b"legacy settings"),))
  dep.apply(root, state, legacy, BINDING, {"lock_identity": "old", "shared_files": [path]})
  dep.rollback(root, state, BINDING)
  with Tree(state) as tree:
    assert dep.read_state(tree)["current"] is None
  with Tree(root) as tree:
    tree.write_state(path, b"native legacy settings")
    tree.write_state("dsh-home/account.json", b"synthetic account retained after rollback")
    tree.write_state("dsh-home/session.json", b"synthetic session retained after rollback")
  before_root, before_state = sentinel_factory(root), sentinel_factory(state)
  with pytest.raises(Conflict, match="迁移验收"):
    dep.apply(root, state, candidate(), BINDING, LAUNCH, state_guard=DshAdapter(ROOT).validate_deployment_state)
  before_root.assert_unchanged()
  before_state.assert_unchanged()


def test_current_generation_owner_allows_apply_after_first_rollback(tmp_path):
  root, state = tmp_path / "instance", tmp_path / "state"
  guard = DshAdapter(ROOT).validate_deployment_state
  dep.apply(root, state, candidate(), BINDING, LAUNCH, state_guard=guard)
  dep.rollback(root, state, BINDING)
  dep.apply(root, state, candidate("B"), BINDING, LAUNCH, state_guard=guard)
  with Tree(root) as tree:
    assert dep.parse_native(tree.read(PATCH)[0], "cordis-yaml")["llm-pi-ai"]["config"]["providers"]["agentcfg-fixture"]["baseURL"] == "B"


def test_theme_is_an_initial_preference_and_not_forced_by_environment():
  adapter = DshAdapter(ROOT)
  data = {"providers": {}, "models": {}, "mcp": {},
    "profile": {"roles": {}, "agent_options": {"theme": "rotom-poimandres", "terminal_images": False, "preset": "standard"}}}
  theme = next(a for a in adapter._field_artifacts(data) if a.target.path == "user-home/.dsh-tui/theme.json")
  assert theme.target.ownership is Ownership.INITIALIZE and theme.target.selector == "/theme"
  spec = adapter.launch_spec(data, cwd=Path("/project"), runtime_root=Path("/runtime"), instance_root=Path("/instance"), lock_identity="fixture")
  assert "DSH_TUI_THEME" not in {binding.name for binding in spec.environment}


def test_welcome_default_and_visual_preferences_use_public_configuration():
  import tomllib
  defaults = tomllib.loads((ROOT / "agents/dsh/agent.toml").read_text())["defaults"]["agent_options"]
  assert defaults["theme"] == "rotom-catppuccin" and defaults["show_welcome"] is True
  adapter = DshAdapter(ROOT)
  data = {"providers": {}, "models": {}, "mcp": {}, "profile": {"roles": {}, "agent_options": defaults}}
  fields = {path: (value, owner) for path, value, owner in adapter._tui_fields(data)}
  targets = {target.path for target in adapter.managed_targets(data)}
  assert {"user-home/.dsh-tui/themes/rotom-catppuccin.json", "user-home/.dsh-tui/themes/rotom-poimandres.json"} <= targets
  assert fields["/dsh-tui/config/whale"] == (True, Ownership.INITIALIZE)
  assert fields["/dsh-tui/config/whaleIdle"] == (False, Ownership.INITIALIZE)
  assert fields["/dsh-tui/config/minimal"] == (False, Ownership.INITIALIZE)
  assert fields["/dsh-tui/config/sidePanel/open"] == (False, Ownership.INITIALIZE)
  for welcome in (True, False):
    data["profile"]["agent_options"] = {**defaults, "show_welcome": welcome}
    spec = adapter.launch_spec(data, cwd=Path("/project"), runtime_root=Path("/runtime"), instance_root=Path("/instance"), lock_identity="fixture")
    assert next(binding.value for binding in spec.environment if binding.name == "DSH_TUI_NO_LAUNCHPAD") == ("0" if welcome else "1")


@pytest.mark.parametrize("theme", ["rotom-catppuccin", "rotom-poimandres", "claude-dark", "claude-paper", "codex-lavender", "codex-paper"])
def test_declared_native_and_custom_themes_are_captureable(theme):
  assert DshAdapter(ROOT).capture({"theme": {"theme": theme}}) == {"agent_options": {"theme": theme}}


def test_unknown_custom_theme_is_rejected():
  from agentcfg.schema import ConfigError
  with pytest.raises(ConfigError, match="capture-theme-not-supported"):
    DshAdapter(ROOT).capture({"theme": {"theme": "foreign-custom"}})


def test_catppuccin_covers_selected_tui_theme_contract_and_official_mocha():
  colors = json.loads((ROOT / "agents/dsh/templates/theme-catppuccin.json").read_bytes())["colors"]
  # TUI 0.14.0 的现行 Theme 字段；防止静默继承雾蓝或写入不生效的别名。
  fields = set("""autoAccept bashBorder accent toolNameMutate toolNameExec accentShimmer activity activityShimmer
    permission permissionShimmer planMode ide promptBorder promptBorderShimmer text inverseText inactive inactiveShimmer
    subtle suggestion remember background success error warning merged warningShimmer diffAdded diffRemoved
    diffAddedDimmed diffRemovedDimmed diffAddedWord diffRemovedWord toolCardBackground toolCardBackgroundDim
    toolDotExec toolDotRead toolDotWrite toolDotWeb toolDotTask syntaxKeyword syntaxString syntaxComment syntaxNumber
    syntaxFunction syntaxType syntaxVariable syntaxOperator syntaxPunctuation syntaxConstant professionalBlue chromeYellow
    contextBarSystem contextBarPrompt contextBarAssistant contextBarThinking contextBarTools ignition ignitionDim cursor
    mascotBody inputBackground userMessageBackground userMessageBackgroundHover messageActionsBackground selectionBg
    bashMessageBackgroundColor memoryBackgroundColor rate_limit_fill rate_limit_empty fastMode fastModeShimmer userPromptLabel
    subagentBullet subagentDescription subagentModel subagentElapsed subagentToolName subagentStatusRunning
    subagentStatusCompleted subagentStatusFailed""".split())
  assert set(colors) == fields and colors["cursor"] == ""
  # 官方 Mocha 26 色；Diff 行衬底另按 Neovim 算法由原色推导。
  mocha = set("""#f5e0dc #f2cdcd #f5c2e7 #cba6f7 #f38ba8 #eba0ac #fab387 #f9e2af #a6e3a1 #94e2d5
    #89dceb #74c7ec #89b4fa #b4befe #cdd6f4 #bac2de #a6adc8 #9399b2 #7f849c #6c7086 #585b70
    #45475a #313244 #1e1e2e #181825 #11111b""".split())
  backgrounds = {"diffAdded", "diffRemoved", "diffAddedDimmed", "diffRemovedDimmed"}
  assert all(value in mocha for key, value in colors.items() if key not in backgrounds | {"cursor"})
  def blend(foreground, alpha):
    return "#" + "".join(f"{int(int(foreground[index:index + 2], 16) * alpha + int(colors['inputBackground'][index:index + 2], 16) * (1 - alpha) + 0.5):02x}"
      for index in (1, 3, 5))
  for tone in ("Added", "Removed"):
    assert colors["diff" + tone] == blend(colors["diff" + tone + "Word"], 0.18)
    assert colors["diff" + tone + "Dimmed"] == blend(colors["diff" + tone + "Word"], 0.09)


def test_catppuccin_semantic_fills_keep_text_legible():
  colors = json.loads((ROOT / "agents/dsh/templates/theme-catppuccin.json").read_bytes())["colors"]
  def luminance(hex_color):
    channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
  for foreground, background in (("text", "inputBackground"), ("text", "toolCardBackground"), ("text", "selectionBg"),
      ("inverseText", "background"), ("inverseText", "accent"), ("text", "diffAdded"), ("text", "diffRemoved"),
      ("diffAddedWord", "diffAddedDimmed"), ("diffRemovedWord", "diffRemovedDimmed")):
    light, dark = sorted((luminance(colors[foreground]), luminance(colors[background])), reverse=True)
    assert (light + 0.05) / (dark + 0.05) >= 4.5, (foreground, background)
