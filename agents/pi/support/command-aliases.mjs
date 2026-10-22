export default function commandAliases(pi) {
  pi.registerCommand("exit", {
    description: "Exit Pi gracefully (waits for active work to finish)",
    handler: async (_args, ctx) => {
      ctx.shutdown();
    },
  });
}
