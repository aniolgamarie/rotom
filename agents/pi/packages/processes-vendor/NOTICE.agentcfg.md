# agentcfg adaptation source notice

Source: `@aliou/pi-processes@0.11.1`, npm integrity recorded in `agents/pi/migration/processes-manifest.json`.
The npm package and README identify the license as MIT. Neither the published archive nor repository tree at
`9508f08fc5427c3f445d55a5f0d728e3e9c8b95d` includes a standalone license text file.
The original package.json, README, source files and their notices are retained without substituting invented copyright information.
The build recipe must include the upstream package.json and README as license evidence.

The default runtime is adapted to agentcfg's bound command executor and existing
AgentManager. All three extensions and the complete skill remain packaged.
Settings use explicit instance options; the original global/local configuration
and automatic legacy state import are not used by the managed runtime.
`SOURCE.json` records original file hashes and
`agents/pi/build/processes-supervisor.patch` records the derived source changes.
Mock validation and isolated package installation have passed; native host and
terminal-service acceptance remain separate and have not been run.
