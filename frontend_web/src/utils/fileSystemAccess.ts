/**
 * File System Access API — 能力检测与写盘辅助.
 *
 * 前端安装通道用: 让用户选一个目录, 把后端给的**明文文件**写进去.
 * 浏览器不能解 zip (DecompressionStream 不支持), 所以解压发生在服务端,
 * 这里只做"写文件".
 *
 * ⚠️ 浏览器**不会记住**授权的目录 —— 每次安装都要用户重新选一次.
 *    这是安全模型决定的 (网页拿不到用户家目录的绝对路径), 绕不过去.
 *    所以安装流程是"选目录 → 写盘", 手动一步到位, 不做自动定位.
 *
 * 兼容性: 仅 Chromium 系 (Chrome / Edge / Opera). Firefox / Safari 不支持,
 * 调用方必须先用 supportsFileSystemAccess() 检测并给出降级提示
 * (降级路径 = 下载安装包自行解压).
 */
import type { FileSystemDirectoryHandle } from '@/types/filesystem';

/** 浏览器是否支持前端安装通道 */
export function supportsFileSystemAccess(): boolean {
  return typeof window !== 'undefined' && typeof window.showDirectoryPicker === 'function';
}

/**
 * 弹出目录选择器 (用户取消会抛 AbortError).
 *
 * 用户应该选**安装根目录** (如 ~/.qoder-cn/skills) —— 资产自己的子目录
 * (skill 是 <code>/, plugin 是 <code>/<version>/) 由代码自动创建.
 */
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

/**
 * 触发浏览器下载一个 blob.
 *
 * 下载端点要带 token (Authorization 头), 所以不能直接开新窗口 ——
 * 得先 fetch 下来再由前端触发保存.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // 立刻 revoke 会让部分浏览器来不及开始下载, 延后释放
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
