# Main auth / selected-model public SDK probe

Default `plan.test.mjs` imports only own plan code and receipt checker. It never loads the SDK.

The explicitly authorized native worker uses readonly SDK 1.0.1 / pi-ai 1.0.2, fixed Node24, twelve pinned current own modules, a complete candidate inventory receipt, empty parent environment, disabled network and a fresh private writable `/tmp` workroot.

Closed scenes:

1. Public session.setModel to selected alternate, then actual session.prompt: the original synthetic provider sees exactly alternate and sends once.
2. Public selected switch then outside setModel/prompt: original synthetic provider sends zero times.
3. Original public ModelRuntime.login via own scope, selected `oauth` / `pi-native` provider, own synthetic interaction and original InMemoryCredentialStore: one login with original OAuth receiver, unrelated existing native credential unchanged, filtered credential metadata, getAuth consumption then one actual completeSimple sender and zero refresh.

All credentials are deliberately synthetic and stay private except fixed boolean/count observations. The memory store is not persistence qualification. No real account, real OAuth endpoint, real human TUI, model network, deployment, SDK patch, private import or namespace mutation is involved. Old Main SDK8 artifacts remain separate. An observed probe is component public ABI evidence, not current product qualification.
