export function terminalStateSequence(title: string, state: "working" | "blocked" | "idle"): string;
export function terminalHyperlink(target: string): string;
export function terminalClipboard(text: string): string;
export function agentStateClient(runtime: any, context: any, emit?: (value: string) => unknown): { report(state: "working" | "blocked" | "idle"): Promise<void> };
export function declaredRules(): Promise<{ rules: Array<{ id: string; body: string }> }>;
export function readDeclaredSkill(path: string): Promise<string>;
