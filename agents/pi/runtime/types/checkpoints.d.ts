export function checkpointClient(runtime: any, context: any): {
  capture(entryId?: string): Promise<any>;
  list(entryId?: string): Promise<any>;
  preview(checkpointId: string): Promise<any>;
  restore(preview: any): Promise<any>;
};
