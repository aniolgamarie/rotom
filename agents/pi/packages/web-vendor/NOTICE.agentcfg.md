# agentcfg Web adaptation

Derived from pi-web-access 0.27.0 (MIT). The original license, README,
changelog and media remain included. SOURCE.json and the migration manifest
record the original npm archive integrity and all 73 original file hashes.
The rebuildable upstream-to-derived patch is agents/pi/build/web-agentcfg.patch.

Configuration, service origins, routes, credentials, models, browser profiles,
commands and artifact roots come from the selected agentcfg instance. Global
settings, account discovery, environment aliases and executable credential
commands are not consulted. Backend model selection and original provider APIs
remain subject to the declared instance bindings.

Web operations and background requests share the existing AgentManager. HTTP
uses owned transports. Git and media CLIs use the same execution supervisor,
file policy and physical termination evidence as other ordinary commands. Their
isolated loopback relay connects only to a private authenticated Unix proxy.
Git artifacts require an explicit writable root in a verifiable Git worktree;
content reads use the ordinary FilePolicy. PDF content is returned inline unless
an explicit output root is selected. Original media and browser DB inputs are
copied into private, bounded snapshots with persistent cleanup ownership.

The curator uses a declared listener and local locked UI assets. Browser launch
is a user action. Search caches belong to the active instance, and session
transitions await closure of preceding Web activity.

This derived package registration and its isolated tests are software evidence.
They do not establish native Pi, CLI, browser, account, or other-platform support.
External Git, FFmpeg/ffprobe, yt-dlp and JavaScript tools require explicit versioned
machine bindings and read-only dependencies. No installation script is executed
implicitly, and missing bindings are reported rather than discovered on PATH.
