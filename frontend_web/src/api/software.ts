/** 软件库 API —— 后端 /api/v1/software/*.
 *
 * ⚠️ 与「插件·技能·连接」(api/assets.ts) 的分工:
 *    那边传的是**文本包**(FormData/multipart), 真身在 GitLab;
 *    这边传的是**任意格式的二进制软件包**(原始字节流), 真身在服务端磁盘.
 *
 * ⚠️ 为什么上传要**另开一个 axios 实例**:
 *    1. 公共实例的 timeout 是 30s —— 5G 的包在内网也要传好几分钟, 必须 timeout: 0;
 *    2. 上传要用原始字节流 (body 直接传 File), 不能让 axios 走 multipart;
 *    3. 上传要拿 onUploadProgress 做进度条.
 */
import axios from 'axios';
import request from '@/utils/request';
import { nativeDownload } from '@/utils/download';
import { useUserStore } from '@/stores/user';

export type SoftwareSort = 'hot' | 'new' | 'name';

/** 一个版本 (= 一个文件) */
export interface SoftwareVersion {
  id: number;
  version: string;
  /** 发布与更新说明 */
  release_notes: string;
  /** 变体标签 (选填) —— 如「Windows版」「LTS版」. 两个版本并存时靠它区分. */
  variant: string;
  /** 是否是**推荐下载**的版本 —— 头部那个「⬇ 下载」按钮下的是它. */
  is_default: boolean;
  file_name: string;
  file_size: number;
  sha256: string;
  /** awaiting_file(在等文件) / uploading(正在传) / ready(可下载) / failed(传失败) */
  status: string;
  /** 上次失败的原因 (status=failed 时有值) */
  last_error: string;
  author: string;
  download_count: number;
  created_at: string | null;
}

/** 一个软件条目 (= 卡片) */
export interface SoftwareItem {
  code: string;
  name: string;
  icon: string;
  version: string;
  summary: string;
  description: string;
  /** 展示功能 */
  features: string[];
  /** 适用场景 / 不适合的场景 */
  use_when: string;
  not_for: string;
  /** 安装说明 (选填) —— 怎么装、怎么跑起来 */
  install_steps: string;
  /** 注意事项 (选填) —— 坑、副作用、别乱用的地方 */
  caveats: string;
  platform: string;
  category: string;
  tags: string[];
  keywords: string[];
  author: string;
  download_count: number;
  /** awaiting_file / published / hidden */
  publish_status: string;
  created_at: string | null;
  updated_at: string | null;
  /** 当前用户能不能改这个条目 */
  can_edit: boolean;
  /** 当前**可下载**的版本号 (空 = 还没有能下的文件) */
  download_version: string;
}

export interface SoftwareDetail extends SoftwareItem {
  versions: SoftwareVersion[];
}

export interface SoftwareListResp {
  items: SoftwareItem[];
  total: number;
}

export interface SoftwareConfig {
  /** 单个软件包上限 (字节) */
  max_bytes: number;
  can_publish: boolean;
  is_admin: boolean;
  public_download: boolean;
  /** 存储根目录 (仅管理员可见) */
  storage_root: string;
  /** 根目录是哪来的: setting(设置项) / env(环境变量) / default(兜底) */
  storage_source: string;
  /** 存储根是否可用 (仅管理员) */
  path_ok: boolean;
  used_bytes: number;
  free_bytes: number;
  /** 已被占用的图标: { emoji: 软件名 } —— 图标不能跟别的软件重复 */
  used_icons?: Record<string, string>;
}

/** 新建软件时填的元数据 */
export interface SoftwareCreateForm {
  code: string;
  name: string;
  icon: string;
  version: string;
  summary: string;
  features: string[];
  use_when: string;
  /** 安装说明 (选填) */
  install_steps: string;
  /** 注意事项 (选填) */
  caveats: string;
  platform: string;
  category: string;
  tags: string[];
  keywords: string[];
  file_name: string;
  file_size: number;
  release_notes: string;
  /** 变体标签 (选填) —— 如「Windows版」 */
  variant: string;
  // ⚠️ 2026-10-28: `description`(详情) 和 `not_for`(不适合的场景) **不再要求填** ——
  //    上架页没有这两个输入框了. 老条目里已有的值照常显示 (详情页是条件渲染).
  //    后端两个字段都是 nullable=False + default="", 不传就是空串.
  description?: string;
  not_for?: string;
}

// ---------- 类型收敛的请求封装 ----------

async function apiGet<T>(
  url: string,
  params?: Record<string, unknown>,
  config?: { silent?: boolean },
): Promise<T> {
  return (await request.get(url, { params, ...config })) as unknown as T;
}
async function apiPost<T>(url: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
  return (await request.post(url, body, { params })) as unknown as T;
}
async function apiPut<T>(url: string, body?: unknown): Promise<T> {
  return (await request.put(url, body)) as unknown as T;
}
async function apiPatch<T>(url: string, body?: unknown): Promise<T> {
  return (await request.patch(url, body)) as unknown as T;
}
async function apiDelete<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return (await request.delete(url, { params })) as unknown as T;
}

// ---------- 读 ----------

export async function listSoftware(params: {
  q?: string; category?: string; platform?: string; sort?: SoftwareSort;
  status?: string; limit?: number; offset?: number;
} = {}, opts: { silent?: boolean } = {}): Promise<SoftwareListResp> {
  return apiGet<SoftwareListResp>('/software', params, opts);
}

export async function listSoftwareCategories(): Promise<{
  items: { name: string; total: number }[];
  total: number;
}> {
  return apiGet('/software/categories');
}

export async function getSoftwareConfig(): Promise<SoftwareConfig> {
  return apiGet<SoftwareConfig>('/software/config');
}

export async function getSoftware(code: string): Promise<SoftwareDetail> {
  return apiGet<SoftwareDetail>(`/software/${encodeURIComponent(code)}`);
}

/** 管理员的「检查路径」—— 换存储根目录后, 看看缺哪些文件 */
export async function checkSoftwarePath(): Promise<{
  root: string; exists: boolean; writable: boolean;
  used_bytes: number; free_bytes: number;
  missing: { code: string; version: string }[];
  missing_count: number;
}> {
  return apiGet('/software/path-check');
}

// ---------- 写 ----------

export async function createSoftware(form: SoftwareCreateForm): Promise<{
  ok: boolean; code: string; version: string; upload_path: string;
}> {
  return apiPost('/software', form);
}

export async function createSoftwareVersion(code: string, payload: {
  version: string; release_notes: string; file_name: string; file_size: number;
  /** 变体标签 (选填) —— 如「Windows版」 */
  variant?: string;
  /** 是否把这个版本设成推荐下载的那个 (默认 true) */
  is_default?: boolean;
}): Promise<{ ok: boolean; code: string; version: string; upload_path: string }> {
  return apiPost(`/software/${encodeURIComponent(code)}/versions`, payload);
}

/**
 * 改某个版本的元信息 —— **变体标签** / **推荐标记** (不动文件).
 *
 * ⚠️ 把 is_default 设成 true 时, 同条目的其他版本会被摘掉推荐 ——
 *    "推荐哪个" 必须唯一, 前端才知道头部按钮该指哪.
 */
export async function updateSoftwareVersion(
  code: string,
  version: string,
  payload: { variant?: string; is_default?: boolean },
): Promise<SoftwareVersion> {
  return apiPatch<SoftwareVersion>(
    `/software/${encodeURIComponent(code)}/versions/${encodeURIComponent(version)}`,
    payload,
  );
}

/**
 * **下架单个版本** —— 只删这一个版本的文件, 其他版本不受影响.
 *
 * ⚠️ 删掉最后一个能下载的版本 → 整个条目一起下架 (后端行为).
 */
export async function deleteSoftwareVersion(
  code: string,
  version: string,
): Promise<{ ok: boolean; code: string; deleted_files: number }> {
  return apiDelete(`/software/${encodeURIComponent(code)}/versions/${encodeURIComponent(version)}`);
}

export async function updateSoftware(code: string, payload: Partial<SoftwareItem>): Promise<SoftwareItem> {
  return apiPut<SoftwareItem>(`/software/${encodeURIComponent(code)}`, payload);
}

export async function deleteSoftware(code: string): Promise<{ ok: boolean; code: string }> {
  return apiDelete(`/software/${encodeURIComponent(code)}`);
}

/** 彻底清理 (记录 + 磁盘文件) —— 仅管理员 */
export async function purgeSoftware(code: string): Promise<{ ok: boolean; code: string; deleted_files: number }> {
  return apiDelete(`/software/${encodeURIComponent(code)}/purge`);
}

// ---------- 上传 (独立 axios 实例) ----------

/**
 * 上传用的 axios 实例.
 *
 * ⚠️ timeout: 0 = 不超时 —— 5G 的包在内网也要传好几分钟, 用公共实例的 30s 必断.
 * ⚠️ 不用公共实例的另一个原因: 上传走**原始字节流**, 不能让 axios 走 multipart
 *    (starlette 会把文件先 spool 到系统临时目录, 5G 在临时目录再存一份).
 */
const uploadClient = axios.create({
  baseURL: '/api/v1',
  timeout: 0,
});

/**
 * 传软件包 —— 原始字节流, 边传边报进度.
 *
 * @param onProgress 百分比 (0~100)
 */
export async function uploadSoftwareFile(
  code: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<{ ok: boolean; code: string; version: string; size: number; sha256: string }> {
  const userStore = useUserStore();
  const headers: Record<string, string> = {
    'Content-Type': 'application/octet-stream',
    // 文件名走 URL 编码 —— 原始文件名可能带中文/空格
    'X-File-Name': encodeURIComponent(file.name),
    // 声明大小 —— 后端拿它跟实收字节数比对, 对不上就判"传输中断"
    'X-File-Size': String(file.size),
  };
  if (userStore.token) headers.Authorization = `Bearer ${userStore.token}`;

  const resp = await uploadClient.put(
    `/software/${encodeURIComponent(code)}/file`,
    file,
    {
      headers,
      onUploadProgress: (e) => {
        if (!onProgress) return;
        const total = e.total ?? file.size;
        onProgress(total > 0 ? Math.min(100, Math.round((e.loaded / total) * 100)) : 0);
      },
    },
  );
  return resp.data as { ok: boolean; code: string; version: string; size: number; sha256: string };
}

// ---------- 下载 ----------

/**
 * 下载软件包 —— **短时票据 + 浏览器原生下载器**.
 *
 * ⚠️ 为什么不走 blob (像 downloadAssetPackage 那样):
 *    5G 的包读成 blob 会把浏览器内存打爆 —— 必须让浏览器自己流式落盘.
 * ⚠️ 为什么不直接把登录 token 拼进 URL:
 *    长期 token 落 URL 会进 nginx access_log 和浏览器历史 —— 谁都能捡走.
 *    所以后端签一张 10 分钟有效的短时票.
 */
export async function downloadSoftware(code: string, version?: string): Promise<void> {
  const ticket = await apiPost<{ url: string; expires_in: number }>(
    `/software/${encodeURIComponent(code)}/download-ticket`,
    undefined,
    version ? { version } : undefined,
  );
  // 交给浏览器原生下载器 —— 内存恒定, 断了能续 (取决于浏览器)
  // ⚠️ 走 utils/download 的 nativeDownload —— jsdom 里 location 是 unforgeable 的,
  //    直接写 href 既触发 "Not implemented: navigation", 单测里也 spy 不了.
  nativeDownload(ticket.url);
}
