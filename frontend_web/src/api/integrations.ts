/** 外部系统凭据 API（PingCode / PLM）。 */
import request from '@/utils/request';

export interface IntegrationProvider {
  id: number | null;
  code: string;
  name: string;
  enabled: boolean;
  bound: boolean;
  username: string | null;
  status: 'unbound' | 'ok' | 'reauth_required';
  last_login_at: string | null;
  last_error: string | null;
}

export interface IntegrationTestResult {
  display_name: string;
  team_name: string;
  login_at: string;
}

export async function listIntegrationProviders(): Promise<{ items: IntegrationProvider[] }> {
  return (await request.get('/integrations/providers', { silent: true })) as {
    items: IntegrationProvider[];
  };
}

export async function getIntegrationPublicKey(): Promise<{
  algorithm: string;
  public_key: string;
}> {
  return (await request.get('/integrations/crypto/public-key', { silent: true })) as {
    algorithm: string;
    public_key: string;
  };
}

export async function saveIntegrationCredentials(
  providerCode: string,
  payloadEncrypted: string,
): Promise<IntegrationProvider> {
  return (await request.put(
    `/integrations/${providerCode}/credentials`,
    { payload_encrypted: payloadEncrypted },
    { silent: true },
  )) as IntegrationProvider;
}

export async function testIntegrationConnection(
  providerCode: string,
): Promise<IntegrationTestResult> {
  return (await request.post(
    `/integrations/${providerCode}/test`,
    null,
    { silent: true },
  )) as IntegrationTestResult;
}

export async function deleteIntegrationCredentials(providerCode: string): Promise<void> {
  await request.delete(`/integrations/${providerCode}/credentials`, { silent: true });
}
