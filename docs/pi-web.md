# Pi Web integration

The derived Web package is declared for four Pi profiles. This page describes implemented configuration and execution boundaries. It does not establish native loading, real accounts, or live services. Current Pi 0.84.4 has a pre-existing stale lock; historical native/cold results belong to a different candidate. See [testing](testing.md) and [known issues](known-issues.md).

## Configuration, requests, and models

Configuration comes from the current instance manifest; credentials resolve only the plugin's declared SecretRefs. Literal `$` or `!` in secrets never expands or executes. Each HTTP service declares origins and a network route. Public-page requests validate DNS/address ranges and pin the actual connection address. Proxy failure ends that operation without direct fallback.

The four Web tools, commands, and shortcuts use instance-bound entry points. Tool-name collision checks are shared with MCP and cannot overwrite ordinary file tools or ReadSeek. HTTP, background fetch, and shutdown retain same-process resources in the existing AgentManager. Foreground return does not release session protection while background work remains.

Summaries, query rewriting, and page answers use constrained instance ModelRuntime selections with zero model retries. They never scan old accounts or rotate fallback models. An unfinished timed-out model request retains an active record. Availability checks explicit service selection first. Gemini ADC uses JSON in a SecretRef, not global gcloud files; parse errors do not expose credential bodies.

## Curator

Explicit `web.curator.enabled` with `browser_network="user-browser"` enables the loopback UI code path. Ports and maximum lifetime can be configured. Default workflow is none; summary-review without enabled curator fails validation.

The listener shares existing-manager lifecycle with MCP and separately tracks Web requests. Shutdown aborts and waits for requests. Pages use marked 18.0.5 from the frozen package, without CDN assets or remote fonts. Users open the displayed link; the plugin does not launch desktop commands or discover global npm.

`web.curator.bind` selects the listening IP. A nondefault loopback binding requires `advertised_origin`, allowing an explicitly supplied HTTPS reverse proxy. Host/Origin checks accept that entry only and links come from the binding. Reverse proxy setup is the machine's responsibility; hostnames are not discovered. Real local/remote browser connectivity requires native validation.

## Authenticated fetch and GitHub API

`web.auth_fetch.<profile>` references `cookie_ref` and allowed HTTPS origins, which must also be in explicitly routed `web.services.authenticated.origins`. Model input cannot replace cookies/authentication headers or perform writes through this entry. Redirects recheck the profile's exact origins. Instead of cookie_ref, a fetch profile can select an explicit browser profile below.

GitHub size, default branch, tree, README, and single-file reads use `web.services.github` controlled HTTP and optional `githubToken`; neither gh CLI nor global accounts are needed. Truncated trees are marked. PR/issue details use fixed read-only GraphQL/REST queries, preserving comments, reviews, commits, checks, and linked records, with connections over 100 marked incomplete. Fields follow GitHub's official [pull request](https://docs.github.com/en/graphql/reference/objects#pullrequest), [issue](https://docs.github.com/en/graphql/reference/objects#issue), and [commit](https://docs.github.com/en/graphql/reference/objects#commit) schema. Schema review is not a real-account query pass.

## Explicit browser profiles

`web.browser_profiles.<id>` declares `root_ref`, one `profile` directory, `browser`, `password_ref`, and `allowed_hosts`, with optional total database/sidecar size limits. `web.gemini_browser_profile` selects one for Gemini Web; `web.auth_fetch.<name>.browser_profile` selects one for authenticated pages and is mutually exclusive with cookie_ref.

The root must be a declared read root. It becomes a hard deny for ordinary tools without rewriting source configuration. Missing password values prevent database reading. The supervisor verifies DB/WAL/SHM identities, rejecting links, excessive write permissions, size excess, and concurrent change. Copies and SQLite work files remain in protected authentication cache, not global temporary cookie files.

Only fixed Node/Bun `node:sqlite` is used, with the password from its SecretRef. There is no discovery of other profiles, OS keychain, secret-tool, global sqlite3, or Python fallback. Completed copies are explicitly released; generation-aware cleanup after restart reclaims only marked, expired copies owned by this instance.

Upstream POSIX presets cover Chrome/Chromium on Linux and Chrome/Brave/Helium/Arc on macOS; other combinations fail explicitly. Synthetic database checks do not establish actual browser versions, accounts, filesystem timing, or platform support.

## Local media and network media tools

Local video metadata/upload reads use ordinary read permission and stream into private readonly copies. A Web operation reuses one digest-checked content version rather than guessing similar filenames. The default input cap is 128 MiB via `web.media.max_file_bytes`; native `video.maxSizeMB` also limits uploads. Gemini API/Web requests default to 64 MiB unless the selected HTTP service explicitly overrides it.

`web.media.ffmpeg_tool_ref` and `ffprobe_tool_ref` bind local frame/duration tools with command permission. Execution has no network, project mount, or write roots, only the authorized copy, under the same manager/supervisor. Inputs remain until all associated processes are proven terminated. Nonzero exit, truncation, or missing/mismatched proof cannot return successful frames.

`web.media.yt_dlp_tool_ref` and `javascript_tool_ref` explicitly bind yt-dlp and Node; ffmpeg also handles remote extraction. Tools need `bash/execute` permission and explicit `external_tools.<id>.read_roots` for actual dependencies, certificates, and dynamic libraries. No PATH substitutes, machine proxies, or accounts are inherited.

Network media commands use a first-party loopback relay to a private Unix proxy and the declared `web.services.public` route. Linux keeps an independent network namespace. macOS projects one loopback port/private Unix socket and requires native verification. The proxy validates targets/addresses and enforces connection/byte limits; upstream-proxy failure never falls back direct. Revocation closes channels, while actual process termination still requires the supervisor's proof.

yt-dlp disables global configuration, extra plugins, and dynamically downloaded JavaScript components. The selected distribution must include needed components and explicitly selected Node. Remote extraction accepts HTTPS video only, disabling local file protocols. Mock success does not establish installed tools or YouTube availability; truncated/nonzero/unproven results fail.

## GitHub clone artifacts

`web.github_clone` requires `git_tool_ref` and `root_ref`. The latter references a `purpose="write"` root within a verifiable Git worktree, as required by shared write leases. Each artifact uses a new `clone-<random-id>` directory and needs ordinary `write/create` plus Git command permission. Listing/reading requires `ls/list` and `read/read`, including deny rules; plugin reads do not bypass them.

Declare `https://github.com` in the GitHub service; API reads additionally need `https://api.github.com`. Private clones use only declared `githubToken`, passed through that child's temporary Git environment rather than argv or cloned `.git/config`. Global Git config, credential helpers, hooks, templates, recursive submodules, and non-HTTPS protocols are disabled. Clone processes use the same relay/supervisor as media.

Successful and started partial clones remain as artifacts in the explicit write root. Session changes do not delete them or subsequent user edits. In-memory cache is runtime-bound. Private driver inputs, including short-lived proxy tokens and declared authentication, are removed only after termination. Restart cleanup reclaims only marked expired inputs whose leases are no longer protected; raw media copies follow persistent leases too. Unknown activity is preserved.

## PDF output and settings projection

Without an output root, PDF extraction returns Markdown. `web.pdf_output_root_ref` enables ordinary writes of separate files to an explicit write root meeting Git-workspace lease requirements, with the ordinary 1 MiB write limit. There is no implicit `/tmp/pi-web-pdf`. An explicitly selected Gemini/Datalab backend that is missing or fails cannot masquerade as another successful backend.

`web.settings` supports tool naming, searchRouting, fetchRouting, fetch.timeout, YouTube/PDF switches and limits, Bright Data zone, Firecrawl version/fresh scrape, SERPdive model, and Datalab mode/region. Routes cannot reference unselected services; provider and searchRouting are mutually exclusive.

SearXNG private headers use `web.header_credentials.searxng.<header>="secret:<id>"` and project only generated references. Host, proxy authentication, and HTTP-framing overrides are prohibited. `web.endpoints.datalabApiBase` must remain within declared service origins.

| Native setting | Managed binding |
| --- | --- |
| summaryModel | `web.models.summary` |
| fetch.answerProvider/answerModel | `web.models.answer` |
| searchModel, video/YouTube preferredModel | `web.models.gemini` |
| OpenAI/xAI search model | `web.models.openai` / `web.models.xai` |
| proxy | Explicit network routes |
| curatorRemote | `web.curator` |
| clonePath | `web.github_clone.root_ref` |

One explicit model binding replaces openaiSearchProviders iteration. Full dependency preparation, final-identity host discovery, real browser/media tools, and live-service acceptance remain separate verification work; see [roadmap](roadmap.md).
