/** 智能体 API 客户端。 */
import request from '@/utils/request';

export interface AgentSummary {
  id: number;
  code: string;
  name: string;
  icon: string;
  category: string;
  version: string;
  status: 'draft' | 'alpha' | 'beta' | 'stable' | 'deprecated';
  summary: string;
  use_when: string;
  not_for: string;
  tags: string[];
  engine: string;
  engine_config: Record<string, any>;
  input_schema: AgentInputField[];
  data_sources: string[];
  tools: string[];
  call_count: number;
  last_called_at: string | null;
  is_featured: boolean;
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

export interface AgentListResp {
  items: AgentSummary[];
  total: number;
}

export async function listAgents(params?: {
  category?: string;
  status?: string;
  featured_only?: boolean;
}): Promise<AgentListResp> {
  return (await request.get('/agents', { params })) as AgentListResp;
}

export async function getAgent(code: string): Promise<AgentSummary> {
  return (await request.get(`/agents/${code}`)) as AgentSummary;
}
