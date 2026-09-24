export class PermissionAccess {
  constructor(context: any);
  require(): any;
  state(sessionId: string): any;
  setMode(sessionId: string, mode: string, cwd: string): any;
  yolo(sessionId: string, cwd: string): boolean;
  parentSnapshot(source?: unknown, options?: unknown): any;
  check(event: any, ctx: any): Promise<any>;
  approve(event: any, checked: any, ctx: any): void;
  take(toolCallId: string, toolName: string, input: unknown, ctx: any): any;
}
