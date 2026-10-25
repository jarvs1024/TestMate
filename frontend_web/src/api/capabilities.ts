/**
 * 能力 API 客户端。
 *
 * ⚠️ 后端仍叫 `/agents` (表名 / 路径暂不改, 见设计文档 §11),
 *    但前端统一用「能力」的措辞 —— 这层隔离就是为了以后改后端时前端不用动.
 */
import request from '@/utils/request';
import type { CapabilityKind } from '@/constants/capabilityKinds';

export interface Capability {
  id: number;
  code: string;
  name: string;
  icon: string;
  /** 业务域标签 (跟 kind 正交) */
  category: string;
  /** 能力角色: tool 干活 / board 看数 / platform 供料 */
  kind: CapabilityKind;
  /** 卡片自己的动作词 (空 = 前端按角色给默认词) */
  cta?: string | null;
  version: string;
  status: 'draft' | 'alpha' | 'beta' | 'stable' | 'deprecated';
  summary: string;
  use_when: string;
  not_for: string;
  tags: string[];
  /** 后端执行引擎 —— 只有 tool 角色才有意义 */
  engine: string;
  engine_config: Record<string, any>;
  input_schema: AgentInputField[];
  data_sources: string[];
  tools: string[];
  call_count: number;
  last_called_at: string | null;
  is_featured: boolean;
  embed_url?: string | null;
  /** "page:<路由名>" = 跳自定义页; 空 = 走工具型运行页 */
  route?: string | null;
}

export interface AgentInputField {
  key: string;
  label: string;
  type:
    | 'text' | 'number' | 'textarea' | 'select' | 'file'
    | 'machine_select' | 'machine_multi_select';
  required?: boolean;
  default?: any;
  options?: string[];
  placeholder?: string;
  accept?: string;
  min?: number;
  max?: number;
}

export interface CapabilityListResp {
  items: Capability[];
  total: number;
}

/** 能力列表 —— 首页能力墙 / 侧栏导航器共用 */
export async function listCapabilities(params?: {
  category?: string;
  status?: string;
  kind?: string;
  featured_only?: boolean;
}): Promise<CapabilityListResp> {
  return (await request.get('/agents', { params })) as CapabilityListResp;
}

/** 单项能力详情 */
export async function getCapability(code: string): Promise<Capability> {
  return (await request.get(`/agents/${encodeURIComponent(code)}`)) as Capability;
}
