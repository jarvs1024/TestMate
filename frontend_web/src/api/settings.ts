/** 系统设置 API */
import request from '@/utils/request';

export interface SettingItem {
  key: string;
  value: any;
  value_type: 'string' | 'url' | 'secret' | 'bool' | 'int';
  description: string;
  is_secret: boolean;
  is_default: boolean;
  default?: any;        // 默认值 (来自 .env 或代码, 未在 DB 改过)
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
export async function testDify(): Promise<TestResult> {
  return (await request.post('/settings/test/dify')) as TestResult;
}
export async function testPrAgent(): Promise<TestResult> {
  return (await request.post('/settings/test/pr_agent')) as TestResult;
}

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

// ===== 运行时拼 URL: 把 <prefix>.embed_url 拼上 userId (后端取当前用户) + theme (前端传) =====
// 后端按 schema 中的 <prefix>.append_user_id / <prefix>.append_theme 开关决定是否拼
// prefix: 配置项前缀 (search / chat / agent), 不带 .embed_url 后缀
export async function buildEmbedUrl(prefix: string, theme: string): Promise<{ url: string }> {
  return (await request.get(`/settings/embed/${prefix}`, { params: { theme } })) as { url: string };
}
