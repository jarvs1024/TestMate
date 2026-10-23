/**
 * File System Access API — 运行时能力检测、句柄记忆与写盘辅助.
 *
 * 前端安装通道用: 让用户选一个目录, 把后端给的**明文文件**写进去.
 * 浏览器不能解 zip (DecompressionStream 不支持), 所以解压发生在服务端,
 * 这里只做"写文件".
 *
 * ## 为什么要有"句柄记忆"
 *
 * 浏览器**不暴露用户家目录的绝对路径** (`~` 是 shell 概念, 网页拿不到).
 * 所以"自动装到 ~/qoder-cn/skills"没法靠拼字符串实现, 只能靠**目录句柄**:
 *   1. 用户第一次授权一次**家目录** (或直接授权安装目录), 我们把句柄存进 IndexedDB;
 *   2. 之后每次安装, 用句柄逐级 getDirectoryHandle 派生出目标目录 —— **不再弹选择器**;
 *   3. 派生只用相对路径段, 不碰路径分隔符, Linux / macOS / Windows 同一套逻辑.
 *
 * 兼容性: 仅 Chromium 系 (Chrome / Edge / Opera). Firefox / Safari 不支持,
 * 调用方必须先用 supportsFileSystemAccess() 检测并给出降级提示.
 */
import type {
  FileSystemDirectoryHandle,
  FileSystemPermissionMode,
  FileSystemPermissionState,
} from '@/types/filesystem';

/** 浏览器是否支持前端安装通道 */
export function supportsFileSystemAccess(): boolean {
  return typeof window !== 'undefined' && typeof window.showDirectoryPicker === 'function';
}

// ==================== 句柄记忆 (IndexedDB) ====================

const DB_NAME = 'testmate-fs';
const DB_VERSION = 1;
const STORE = 'dir-handles';

/** 记住的"用户家目录"句柄 —— 用来派生 ~/xxx 的安装目录 */
export const HOME_HANDLE_KEY = 'home';
/** 记住的"安装根目录"句柄 —— 用户手动选过一次之后直接复用 */
export const INSTALL_ROOT_HANDLE_KEY = 'install-root';

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** 记住一个目录句柄 (句柄可以结构化克隆, 能存进 IndexedDB) */
export async function saveDirHandle(
  key: string, handle: FileSystemDirectoryHandle,
): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put(handle, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    db.close();
  } catch {
    // 隐私模式 / 存储被禁用 —— 记住不了就算了, 退回每次手选
  }
}

/** 取回记住的目录句柄 */
export async function loadDirHandle(
  key: string,
): Promise<FileSystemDirectoryHandle | null> {
  try {
    const db = await openDb();
    const val = await new Promise<unknown>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).get(key);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    db.close();
    return (val as FileSystemDirectoryHandle) || null;
  } catch {
    return null;
  }
}

/** 忘掉一个目录句柄 */
export async function forgetDirHandle(key: string): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
    db.close();
  } catch {
    // 忽略
  }
}

// ==================== 权限 ====================

/** 查权限 (不需要用户手势) */
export async function queryPermission(
  handle: FileSystemDirectoryHandle,
  mode: FileSystemPermissionMode = 'readwrite',
): Promise<FileSystemPermissionState> {
  if (!handle.queryPermission) return 'granted';
  try {
    return await handle.queryPermission({ mode });
  } catch {
    return 'prompt';
  }
}

/** 请求权限 (必须在用户手势的调用栈里, 否则浏览器直接拒绝) */
export async function requestPermission(
  handle: FileSystemDirectoryHandle,
  mode: FileSystemPermissionMode = 'readwrite',
): Promise<FileSystemPermissionState> {
  if (!handle.requestPermission) return 'granted';
  try {
    return await handle.requestPermission({ mode });
  } catch {
    return 'denied';
  }
}

// ==================== 目录派生 ====================

/**
 * 在根句柄下逐级派生出一个子目录 (不存在就建).
 *
 * 只用相对路径段 —— 跟操作系统无关, Windows 上 `getDirectoryHandle('qoder-cn')`
 * 一样能用, 不用自己拼 `\` 或 `/`.
 */
export async function deriveDirectory(
  root: FileSystemDirectoryHandle,
  relPath: string[],
): Promise<FileSystemDirectoryHandle> {
  let cur = root;
  for (const seg of relPath) {
    cur = await cur.getDirectoryHandle(seg, { create: true });
  }
  return cur;
}

// ==================== 目录选择 ====================

/**
 * 弹出目录选择器 (用户取消会抛 AbortError).
 *
 * @param startIn 预定位: 传上次的句柄, 选择器直接打开那个位置, 不用从头翻.
 */
export async function pickDirectory(
  startIn?: FileSystemDirectoryHandle | string,
): Promise<FileSystemDirectoryHandle> {
  if (!window.showDirectoryPicker) {
    throw new Error('当前浏览器不支持 File System Access API (仅 Chrome / Edge 可用)');
  }
  const opts: { mode: 'readwrite'; startIn?: FileSystemDirectoryHandle | string } = {
    mode: 'readwrite',
  };
  if (startIn) opts.startIn = startIn;
  return window.showDirectoryPicker(opts);
}

// ==================== 写盘 ====================

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
