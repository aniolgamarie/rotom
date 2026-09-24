import { EventEmitter } from "node:events";
export class SupervisedScriptWorker extends EventEmitter {
  constructor(code: string, timeoutMs: number);
  postMessage(message: unknown): void;
  terminate(): Promise<number>;
}
