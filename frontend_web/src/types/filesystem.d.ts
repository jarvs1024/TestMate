/**
 * File System Access API 的**类型**声明 (TS DOM lib 里还没有).
 *
 * 仅 Chromium 系支持 (Chrome / Edge / Opera). Firefox / Safari 不支持,
 * 运行时必须做能力检测 (见 utils/fileSystemAccess.ts), 不支持时禁用前端安装通道.
 *
 * 这里只放类型; 运行时能力检测与写盘辅助放在 utils/fileSystemAccess.ts
 * (vite 无法把 .d.ts 当运行时模块解析).
 */

export interface FileSystemDirectoryHandle {
  readonly kind: 'directory';
  readonly name: string;
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<FileSystemDirectoryHandle>;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<FileSystemFileHandle>;
  removeEntry(name: string, options?: { recursive?: boolean }): Promise<void>;
  entries(): AsyncIterableIterator<[string, FileSystemHandle]>;
  values(): AsyncIterableIterator<FileSystemHandle>;
  [Symbol.asyncIterator](): AsyncIterableIterator<[string, FileSystemHandle]>;
}

export interface FileSystemFileHandle {
  readonly kind: 'file';
  readonly name: string;
  getFile(): Promise<File>;
  createWritable(options?: { keepExistingData?: boolean }): Promise<FileSystemWritableFileStream>;
}

export interface FileSystemWritableFileStream extends WritableStream {
  write(data: BufferSource | Blob | string): Promise<void>;
  close(): Promise<void>;
}

export interface DirectoryPickerOptions {
  id?: string;
  mode?: 'read' | 'readwrite';
}

declare global {
  interface Window {
    showDirectoryPicker?: (options?: DirectoryPickerOptions) => Promise<FileSystemDirectoryHandle>;
  }
}
