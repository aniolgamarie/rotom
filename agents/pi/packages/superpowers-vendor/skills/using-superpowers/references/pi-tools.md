# Pi / agentcfg Tool Mapping

The current agentcfg instructions and selected tools govern every workflow below. A skill does not grant additional tools, write permissions, model access, or permission to launch a service.

| Requested action | Available agentcfg route |
| --- | --- |
| Read another skill | Read the selected `SKILL.md` at its discovered path, or use `/skill:name` |
| Investigate or independently review code | Dispatch an explicitly bound read-only `scout` or fresh `reviewer` through the current `Agent` tool |
| Implement an ordinary change | The parent implements; a fresh reviewer checks the result |
| Run a managed implementation | Use `kernel_task` with the configured Task Keeper roles and checks |
| Delegate to an external backend | Use `model_delegate` with an explicit `pi` or `codex` backend and preset |
| Track tasks | Use a selected task tool or a plan file in the authorized project |

Only the installed `@tintinweb/pi-subagents` manager owns child execution. Do not install another manager, invent unavailable tool names, enable nested workflows, or bypass its queue. Ordinary child roles are read-only. External writes require the explicit write workflow and its candidate worktree; a skill's implementer prompt cannot turn a read-only child into a writer.

Superpowers scripts and relative reference files are preserved. Execute scripts only through configured command bindings and the supervisor. For visual companion servers use an explicitly bound foreground service with its own state and endpoint; do not launch an untracked background server or run the browser opener automatically. If that service is not configured, report the missing binding and continue with the text workflow where applicable.

Skills and rules are managed in repository sources and machine overrides. Update those sources and redeploy through agentcfg; do not edit generated instance files or install into global home directories. Worktree creation and cleanup must respect active workspace leases and the Task Keeper candidate owner.
