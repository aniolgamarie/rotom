# Superpowers in agentcfg

Source: obra/superpowers at b36e0829c6d0140e93cfef2ca599b1b07d4a7797 (6.3.0), MIT; see LICENSE and SOURCE.json.

All 14 skill directories and supporting files retain the upstream contents and executable modes, except the Pi tool mapping. The Pi extension uses explicit resource discovery and only injects bootstrap context into the parent. Its mapping follows agentcfg routing, permissions and service bindings. The package manifest identifies this fork. The corresponding derivation is `agents/pi/build/superpowers-agentcfg.patch` in the agentcfg repository.

Other harness integrations, upstream development tests and the repository-level AGENTS.md symlink are not runtime inputs. No installation, browser, shell or background service is started when these resources are packaged or discovered.
