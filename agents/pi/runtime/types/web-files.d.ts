export interface WebLocalFile {
  file_id: string;
  directory: string;
  path: string;
  size: number;
  sha256: string;
  snapshot_path: string;
  bytes(): Buffer;
}
export function webLocalFile(path: string): Promise<WebLocalFile>;
export function webReadLocalFile(path: string): Promise<Buffer>;
