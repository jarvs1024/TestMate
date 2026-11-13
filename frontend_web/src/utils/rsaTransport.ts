/**
 * 凭据传输加密（RSA-PKCS1v15 + 后端下发的公钥）。
 *
 * ⚠️ WebCrypto 的 RSA 只支持 OAEP，后端用的是 PKCS1v15，所以这里用 jsencrypt。
 * 明文只在内存里存在几毫秒，页面不落任何存储。
 */
import { JSEncrypt } from 'jsencrypt';

export async function encryptForTransport(plaintext: string, publicKeyPem: string): Promise<string> {
  const encryptor = new JSEncrypt();
  encryptor.setPublicKey(publicKeyPem);
  const encrypted = encryptor.encrypt(plaintext);
  if (!encrypted) throw new Error('凭据加密失败，请刷新页面后重试');
  return encrypted;
}
