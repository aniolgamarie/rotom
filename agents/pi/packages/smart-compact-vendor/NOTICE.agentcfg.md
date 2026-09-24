# pi-smart-compact in agentcfg

Derived from pi-smart-compact 9.6.0, MIT. Original file identities are recorded in the migration manifest. This fork is 9.6.0-agentcfg.1.

Configuration is read from the selected manifest; private cache, session and backup roots belong to the instance. Only explicitly declared project roots participate in project memory. All model helper calls reuse the current constrained ModelRuntime; configured model references are exact and never fall back when missing. Managed helper requests are refused. Smart compaction owns the session hook when selected; failed/refused compaction cancels rather than invoking a second compactor. Restore checks the shared activity boundary before changing sessions.

Original bundled output is the published source. The derivation patch records changes to dist/index.js and package.json; upstream source maps remain reference artifacts and do not describe the agentcfg modifications.
