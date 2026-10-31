/** 系统设置 API */
import request from '@/utils/request';

export interface SettingItem {
  key: string;
  value: any;
  value_type: 'string' | 'url' | 'secret' | 'bool' | 'int';
  description: string;
  is_secret: boolean;
  is_default: boolean;
  /**
   * 默认值 (来自 .env 或代码, 未在 DB 改过).
   *
   * ⚠️ 类型是 `any` 而不是 string —— 后端的 default 跟着 value_type 走:
   *   int 项的 default 是 "5120" (字符串), 但 bool 项是 "false" (字符串),
   *   而**当前值**是真正的 int / bool. 前端拿它做 placeholder
   *   (「默认 5120」), 所以得能原样插值.
   */
  default?: any;
  category?: string;
}
export interface SettingGroup {
  category: string;
  label: string;
  items: SettingItem[];
}
export interface SchemaResp {
  groups: SettingGroup[];
  total: number;
}

export async function getSchema(): Promise<SchemaResp> {
  return (await request.get('/settings/schema')) as SchemaResp;
}

export async function updateSetting(key: string, value: any, updateSecret = true): Promise<void> {
  await request.put(`/settings/${key}`, { value, update_secret: updateSecret });
}

export interface TestResult {
  ok: boolean;
  status: 'ok' | 'warn' | 'off';
  message: string;
  detail: any;
}
export async function testRagflow(): Promise<TestResult> {
  return (await request.post('/settings/test/ragflow')) as TestResult;
}

// ⚠️ testPrAgent 已删 —— PR-Agent 服务下线了, 这个测试接口没有调用方了.

export async function testReviewAgent(): Promise<TestResult> {
  return (await request.post('/settings/test/review_agent')) as TestResult;
}

/**
 * 真发一条钉钉消息 (验证 webhook / 关键词 / 加签是否配对)
 *
 * ⚠️ 两个频道各配各的: market(市场群: 上架/更新/彻底下架) / review(审核群: 待审核/驳回/删除)
 */
export async function testDingTalk(channel: 'market' | 'review' = 'market'): Promise<TestResult> {
  return (await request.post('/settings/test/dingtalk', null, { params: { channel } })) as TestResult;
}

/** 探当前配置的 GitLab 仓库能不能连上 (SSH 鉴权 + 分支是否存在) */
export async function testGitLab(): Promise<TestResult> {
  return (await request.post('/settings/test/gitlab')) as TestResult;
}

/**
 * 体检**软件库存储根目录** —— 能不能写、剩多少空间、哪些版本的文件丢了.
 *
 * ⚠️ admin only (后端会拒) —— 存储根目录是服务端路径, 不该让普通用户知道.
 * ⚠️ 改了存储路径后一定要点一下 —— 换根目录**不会**自动搬文件,
 *    缺哪些文件这个端点会一次列全.
 */
export async function testSoftwareStorage(): Promise<TestResult> {
  return (await request.post('/settings/test/software_storage')) as TestResult;
}

// ===== 运行时拼 URL: 把 <prefix>.embed_url 拼上 userId (后端取当前用户) + theme (前端传) =====
// 后端按 schema 中的 <prefix>.append_user_id / <prefix>.append_theme 开关决定是否拼
// prefix: 配置项前缀 (search / chat / agent), 不带 .embed_url 后缀
export async function buildEmbedUrl(prefix: string, theme: string): Promise<{ url: string }> {
  return (await request.get(`/settings/embed/${prefix}`, { params: { theme } })) as { url: string };
}

// ===== 平台信息 (副标题 + 版本号 · 页头/登录页显示) =====

/** 平台对外信息 —— 后端从设置项里读 (general.platform_name / .platform_tagline / .platform_version) */
export interface PlatformInfo {
  /** 平台显示名 (如 TestMate) */
  name: string;
  /** 版本号, 不带 "v" 前缀 (如 1.0.0) */
  version: string;
  /** 副标题 (如 智能测试辅助平台) */
  tagline: string;
}

/** ⚠️ 缓存 30 秒 —— 管理员改完设置刷新页面就该看到, 但别每翻一页都打一次接口 */
const PLATFORM_INFO_TTL = 30_000;
let platformInfoCache: PlatformInfo | null = null;
let platformInfoAt = 0;

/**
 * 读平台信息 (版本号 + 副标题).
 *
 * ⚠️ **公开接口** (`GET /api/v1/platform/info`) —— 匿名用户也要看得到页头那行字,
 *    所以它不走要登录的 `/settings/schema`.
 *
 * ⚠️ 取不到就返回空串, **调用方自己兜底** —— 页头不能因为接口挂了就显示空白.
 */
export async function getPlatformInfo(): Promise<PlatformInfo> {
  if (platformInfoCache && Date.now() - platformInfoAt < PLATFORM_INFO_TTL) {
    return platformInfoCache;
  }
  try {
    const r = (await request.get('/platform/info', { silent: true })) as Partial<PlatformInfo>;
    const info: PlatformInfo = {
      name: String(r?.name || ''),
      version: String(r?.version || ''),
      tagline: String(r?.tagline || ''),
    };
    // ⚠️ 只缓存**成功**的结果 —— 失败要留机会下次再探 (后端可能只是暂时挂了)
    if (info.name || info.version || info.tagline) {
      platformInfoCache = info;
      platformInfoAt = Date.now();
    }
    return info;
  } catch {
    return { name: '', version: '', tagline: '' };
  }
}

// ===== 后端版本号 (页头显示) =====

/** 已经探到的版本号 —— 一次会话只探一次, 别每页都发一遍请求 */
let versionCache: string | null = null;

/**
 * 探后端版本号.
 *
 * ⚠️ 探两个地方, 谁先给 version 用谁:
 *   ① GET /api/v1/health —— 公开存活探针, 带上 version 就直接用;
 *   ② GET / (根路径返回 { name, version, docs }) —— 注意要**覆盖 baseURL**,
 *      不然 '/api/v1' + '/' 会打到 /api/v1/ 而不是根路径.
 * 两者都取不到就返回空串 —— 调用方保留自己的默认版本号,
 * 页头**不能**因为接口挂了就显示空白.
 */
async function probeVersion(): Promise<string> {
  try {
    const r = (await request.get('/health', { silent: true })) as { version?: string };
    if (r?.version) return String(r.version);
  } catch {
    /* 探不到就试下一个 */
  }
  try {
    const r = (await request.get('/', { baseURL: '/', silent: true })) as { version?: string };
    if (r?.version) return String(r.version);
  } catch {
    /* 取不到就回退默认值 */
  }
  return '';
}

/** 后端版本号 —— 取不到返回空串 (调用方自己回退默认值) */
export async function getBackendVersion(): Promise<string> {
  if (versionCache) return versionCache;
  const v = await probeVersion();
  // ⚠️ 只缓存**成功**的结果 —— 失败要留机会下次再探 (后端可能只是暂时挂了)
  if (v) versionCache = v;
  return v;
}
