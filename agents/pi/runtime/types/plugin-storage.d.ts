export function privatePluginStore(capability: string, namespace: string): {
  read(account: string): string | undefined;
  write(account: string, value: string): void;
  remove(account: string): void;
};
