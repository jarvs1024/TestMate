export type InstanceType = 'ragflow' | 'dify';

export interface BaseInstance {
  id: string;
  type: InstanceType;
  name: string;
  url: string;
  createdAt: string;
  updatedAt: string;
}

export interface RAGFlowInstance extends BaseInstance {
  type: 'ragflow';
  authToken?: string;
}

export interface DifyInstance extends BaseInstance {
  type: 'dify';
  apiKey?: string;
}

export type Instance = RAGFlowInstance | DifyInstance;

export interface ExportPayload {
  version: 1;
  exportedAt: string;
  instances: Instance[];
}
