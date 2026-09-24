# pi-btw in agentcfg

Derived from @narumitw/pi-btw 0.55.3, MIT; the migration manifest records original npm file identities. This fork is 0.55.3-agentcfg.1 and loads src/index.ts.

Settings come from the selected agentcfg manifest. Model helpers use the current constrained ModelRuntime with zero nested retries and reject managed request contexts. Link and clipboard UI actions use terminal OSC 8 / OSC 52: click the displayed link to open it, and enable clipboard support in the terminal when copying. They do not launch desktop child processes. Upstream dist files are source history and are excluded from the runtime archive.
