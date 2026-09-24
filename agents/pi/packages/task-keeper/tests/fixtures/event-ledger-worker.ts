import { Store } from "../../src/store/database.ts";
const store = new Store(process.argv[2]);
process.send?.({ ready: true });
process.on("message", (input: any) => {
  try {
    const result = input.kind === "append" ? store.append(input.event)
      : store.prepare(input.owner, input.intentId, "continue", {});
    process.send?.({ id: input.id, result });
  } catch (error) { process.send?.({ id: input.id, error: (error as {code?:string}).code ?? String(error) }); }
});
