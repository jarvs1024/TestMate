/** MCP OAuth 同意、用户授权与访问令牌 API。 */
import request from '@/utils/request';

export type McpScope = 'market:read' | 'market:write';

export interface McpAuthorizationQuery {
  client_id: string;
  redirect_uri: string;
  response_type: string;
  scope: string;
  code_challenge: string;
  code_challenge_method: string;
  state?: string;
}

export interface McpAuthorizationPreview {
  client_id: string;
  client_name: string;
  redirect_uri: string;
  scopes: McpScope[];
  response_type: string;
  code_challenge: string;
  code_challenge_method: string;
  state?: string | null;
}

export interface McpAuthorizePayload {
  client_id: string;
  redirect_uri: string;
  scopes: McpScope[];
  response_type: string;
  code_challenge: string;
  code_challenge_method: string;
  state?: string | null;
}

export interface McpGrant {
  id: number;
  client_id: string;
  client_name: string;
  scopes: McpScope[];
  version: number;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface McpToken {
  id: number;
  name: string;
  user_id: number;
  username: string;
  scopes: McpScope[];
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  created_at: string;
  /** 内部工具保留明文，便于随时复制；历史令牌可能为空。 */
  token: string | null;
}

export interface CreateMcpTokenPayload {
  name: string;
  scopes: McpScope[];
  expires_at?: string;
}

export async function previewMcpAuthorization(
  params: McpAuthorizationQuery,
): Promise<McpAuthorizationPreview> {
  return (await request.get('/mcp/authorize/preview', {
    params,
    silent: true,
  })) as McpAuthorizationPreview;
}

export async function authorizeMcp(
  payload: McpAuthorizePayload,
): Promise<{ callback_url: string }> {
  return (await request.post('/mcp/authorize', payload, { silent: true })) as { callback_url: string };
}

export async function listMcpGrants(): Promise<{ items: McpGrant[] }> {
  return (await request.get('/mcp/grants', { silent: true })) as { items: McpGrant[] };
}

export async function revokeMcpGrant(id: number): Promise<void> {
  await request.delete(`/mcp/grants/${id}`, { silent: true });
}

export async function listMcpTokens(): Promise<{ items: McpToken[] }> {
  return (await request.get('/mcp/tokens', { silent: true })) as { items: McpToken[] };
}

export async function listMcpTokenScopes(): Promise<{ scopes: McpScope[] }> {
  return (await request.get('/mcp/tokens/scopes', { silent: true })) as { scopes: McpScope[] };
}

export async function createMcpToken(payload: CreateMcpTokenPayload): Promise<McpToken> {
  return (await request.post('/mcp/tokens', payload, { silent: true })) as McpToken;
}

export async function deleteMcpToken(id: number): Promise<void> {
  await request.delete(`/mcp/tokens/${id}`, { silent: true });
}
