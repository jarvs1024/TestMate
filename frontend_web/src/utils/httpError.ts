/**
 * HTTP 状态码 → 人话.
 *
 * ⚠️ 为什么要单独一个模块: axios 的原始报文是
 *    "Request failed with status code 502" —— 对用户等于天书.
 *
 *    尤其 502 特别常见, 而且**极具迷惑性**: nginx 活着、前端页面能打开,
 *    但它反代的后端没在跑. 典型场景是本地部署跑着, 而 Docker 模式的后端容器停了 ——
 *    这时页面看起来一切正常, 只有接口全挂, 不翻译的话用户只会以为"平台坏了".
 *
 *    译文要说清"问题在哪一环", 否则用户还是不知道该去看后端.
 */

/** 后端自己给了人话 (detail 字段) 就用它 —— 那是更精确的信息 */
function detailText(detail: unknown): string {
  if (typeof detail === 'string' && detail.trim()) return detail.trim();
  if (detail && typeof detail === 'object') {
    const msg = (detail as { message?: unknown }).message;
    if (typeof msg === 'string' && msg.trim()) return msg.trim();
  }
  return '';
}

/**
 * 把一次失败翻译成能直接给人看的句子.
 *
 * @param status HTTP 状态码 (没拿到响应就是 undefined)
 * @param detail 后端返回的 detail 字段 (可能是字符串或 { message })
 * @param fallback 连状态码都没有时的兜底文案
 */
export function httpErrorText(
  status?: number | null,
  detail?: unknown,
  fallback = '未知错误',
): string {
  const d = detailText(detail);
  if (d) return d;

  switch (status) {
    case 502:
      return '后端服务连不上 (502) —— 页面能打开, 但后端没在跑. 请检查后端服务状态';
    case 503:
      return '服务暂时不可用 (503) —— 后端可能正在启动, 或数据库 / Redis 没连上';
    case 504:
      // ⚠️ nginx 在上游不可达时有时返 504 而不是 502 (连接挂起等到超时) ——
      //    所以 504 也可能是"后端根本没在跑", 不能只说"慢".
      return '后端没在时限内回话 (504) —— 可能后端没在跑, 也可能它卡住了';
    case 500:
      return '服务端内部错误 (500)';
    case 404:
      return '接口不存在 (404)';
    case 403:
      return '没有权限 (403)';
    case 401:
      return '登录态已失效 (401)';
    case 429:
      return '请求太频繁 (429), 稍后再试';
    default:
      break;
  }
  if (typeof status === 'number') return `请求失败 (HTTP ${status})`;
  return fallback;
}

/**
 * 从 axios 错误对象里取状态码 (axios 的错误形状不稳定, 各处都写一遍容易漏).
 */
export function errorStatus(e: unknown): number | null {
  const s = (e as { response?: { status?: number } } | null)?.response?.status;
  return typeof s === 'number' ? s : null;
}

/**
 * 从 axios 错误对象里取 detail 字段.
 */
export function errorDetail(e: unknown): unknown {
  return (e as { response?: { data?: { detail?: unknown } } } | null)?.response?.data?.detail;
}
