# Default initializer SDK ABI probe

Default plan tests are inert: own JSON/parser/full-tree receipt helpers only, no official SDK import.

Explicitly authorized native entry uses original SDK1.0.1/pi-ai1.0.2 and original createOfficialRuntimeInitializer. It never replaces ModelRuntime.create, supplies a test SDK facade, registers a faux/native replacement provider, patches prepareRequest or mutates upstream API/classes. Only deployed-style own models.json, fixed managed synthetic environment key and own private auth fixtures are inputs.

Three closed scenes:
- Custom configured openai-completions API-key model: original creation, scope/class/check, unlinked private config FD still held, selected-only directory, getAuth exact managed key, native auth sentinel bytes/atime unchanged. API-key-only uses original InMemoryCredentialStore.
- SDK builtin openai-codex/gpt-5.3-codex-spark: missing native account metadata is empty (model currently still exists in catalog); complete synthetic OAuth record is read at original authPath and returned only as public selected metadata. No OAuth getAuth/refresh/send request; original file unchanged, no copied credential file.
- Incomplete OAuth record is rejected by original initializer before SDK creation with pi-runtime-auth-format/exit2.

No model sending method is invoked, network is disabled, no real account/config/server/deployment. Observed zero-send fields denote no sending calls in this bounded worker, not monkeypatched SDK counters. OAuth format/metadata ABI does not validate real access token, account login, provider connectivity, refresh or model sending. No capability catalog/current lock/installer qualification is implied. The fixed complete SDK tree receipt, twelve current own module hashes and Node/bwrap bytes are verified before imports/execution.
