/**
 * File System Access API 的**类型**声明 (TS DOM lib 里还没有).
 *
 * 仅 Chromium 系支持 (Chrome / Edge / Opera). Firefox / Safari 不支持,
 * 运行时必须做能力检测 (见 utils/fileSystemAccess.ts), 不支持时禁用前端安装通道.
 *
 * 这里只放类型; 运行时能力检测与写盘辅助放在 utils/fileSystemAccess.ts
 * (vite 无法把 .d.ts 当运行时模块解析).
 */

export interface FileSystemHandle {
  readonly kind: 'file' | 'directory';
  readonly name: string;
  isSameEntry(other: FileSystemHandle): Promise<boolean>;
}

/** 权限状态 —— 记住的目录句柄可能被用户撤销授权 */
export type FileSystemPermissionMode = 'read' | 'readwrite';
export type FileSystemPermissionState = 'granted' | 'denied' | 'prompt';

export interface FileSystemDirectoryHandle extends FileSystemHandle {
  readonly kind: 'directory';
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<FileSystemDirectoryHandle>;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<FileSystemFileHandle>;
  removeEntry(name: string, options?: { recursive?: boolean }): Promise<void>;
  entries(): AsyncIterableIterator<[string, FileSystemHandle]>;
  values(): AsyncIterableIterator<FileSystemHandle>;
  [Symbol.asyncIterator](): AsyncIterableIterator<[string, FileSystemHandle]>;
  /** 查当前授权状态 (不需要用户手势) */
  queryPermission?(descriptor?: { mode?: FileSystemPermissionMode }): Promise<FileSystemPermissionState>;
  /** 请求授权 (必须在用户手势的调用栈里) */
  requestPermission?(descriptor?: { mode?: FileSystemPermissionMode }): Promise<FileSystemPermissionState>;
}

export interface FileSystemFileHandle extends FileSystemHandle {
  readonly kind: 'file';
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
  /** 预定位: 传句柄或已知目录名 ('desktop' | 'documents' | 'downloads' | …) */
  startIn?: FileSystemHandle | string;
}

declare global {
  interface Window {
    showDirectoryPicker?: (options?: DirectoryPickerOptions) => Promise<FileSystemDirectoryHandle>;
  }
}
