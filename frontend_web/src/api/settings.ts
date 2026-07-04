/** 系统设置 API */
import request from '@/utils/request';

export interface SettingItem {
  key: string;
  value: any;
  value_type: 'string' | 'url' | 'secret' | 'bool' | 'int';
  description: string;
  is_secret: boolean;
  is_default: boolean;
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
