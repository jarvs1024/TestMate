/**
 * File System Access API — 运行时能力检测与写盘辅助.
 *
 * 前端安装通道用: 让用户选一个目录, 把后端给的**明文文件**写进去.
 * 浏览器不能解 zip (DecompressionStream 不支持), 所以解压发生在服务端,
 * 这里只做"写文件".
 *
 * 兼容性: 仅 Chromium 系 (Chrome / Edge / Opera). Firefox / Safari 不支持,
 * 调用方必须先用 supportsFileSystemAccess() 检测并给出降级提示.
 */
import type { FileSystemDirectoryHandle } from '@/types/filesystem';

/** 浏览器是否支持前端安装通道 */
export function supportsFileSystemAccess(): boolean {
  return typeof window !== 'undefined' && typeof window.showDirectoryPicker === 'function';
}

/** 弹出目录选择器 (用户取消会抛 AbortError) */
export async function pickDirectory(): Promise<FileSystemDirectoryHandle> {
  if (!window.showDirectoryPicker) {
    throw new Error('当前浏览器不支持 File System Access API (仅 Chrome / Edge 可用)');
  }
  return window.showDirectoryPicker({ mode: 'readwrite' });
}

/** 在目录句柄里创建多级目录并写入一个文件 */
export async function writeFileInto(
  dir: FileSystemDirectoryHandle,
  relPath: string,
  data: BlobPart,
): Promise<void> {
  const parts = relPath.split('/').filter(Boolean);
  const fileName = parts.pop() as string;
  let cur: FileSystemDirectoryHandle = dir;
  for (const p of parts) {
    cur = await cur.getDirectoryHandle(p, { create: true });
  }
  const fh = await cur.getFileHandle(fileName, { create: true });
  const ws = await fh.createWritable();
  await ws.write(data);
  await ws.close();
}

/** base64 → 可直接写 Blob 的 ArrayBuffer */
export function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr.buffer as ArrayBuffer;
}
