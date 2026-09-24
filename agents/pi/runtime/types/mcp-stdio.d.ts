export class BoundStdioTransport {
  constructor(runtime: any, serverName: string, options?: { pause?: (milliseconds: number) => Promise<void>; pollMilliseconds?: number });
  onclose?: () => void;
  onerror?: (error: Error) => void;
  onmessage?: (message: any) => void;
  start(): Promise<void>;
  send(message: any): Promise<void>;
  close(): Promise<void>;
}
