export class ManagedHttpTransport {
  constructor(options: Record<string, unknown>);
  readonly api: "openai-completions";
  readonly certified: boolean;
  readonly model_digest: string;
  readonly route_id: string;
  observed_model: { provider_id: string; model_id: string } | null;
  readonly budgetExhausted: boolean;
  bind(runtime: unknown, options: unknown): Promise<{ finish(): Promise<void>; close(): Promise<void> }>;
  finish(): Promise<void>;
}
