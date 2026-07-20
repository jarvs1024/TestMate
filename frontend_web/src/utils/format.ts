/** 通用格式化工具 */

/** 把字节数变成人类可读 B / KB / MB / GB */
export function fmtSize(bytes: number): string {
  if (!bytes || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let n = bytes / 1024;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(n >= 100 ? 0 : n >= 10 ? 1 : 2)} ${units[i]}`;
}

/** 把 epoch ms 转 'YYYY-MM-DD HH:mm' */
export function fmtTime(epochMs: number): string {
  if (!epochMs || epochMs < 0) return '—';
  const d = new Date(epochMs);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 文件类型 → emoji icon (用于文档表) */
export function docIcon(type: string): string {
  const t = (type || '').toLowerCase();
  if (t.includes('pdf')) return '📕';
  if (t.includes('word') || t === 'doc' || t === 'docx') return '📘';
  if (t.includes('excel') || t === 'xls' || t === 'xlsx' || t.includes('sheet')) return '📗';
  if (t.includes('powerpoint') || t === 'ppt' || t === 'pptx' || t.includes('presentation')) return '📙';
  if (t.includes('image') || t === 'png' || t === 'jpg' || t === 'jpeg') return '🖼️';
  if (t === 'txt' || t === 'md') return '📄';
  if (t.includes('html')) return '🌐';
  return '📄';
}

/** RAGFlow chunk_method → 中文简短标签 */
export function fmtChunkMethod(m: string): string {
  const map: Record<string, string> = {
    naive: '通用',
    book: '书',
    email: '邮件',
    laws: '法律',
    manual: '手册',
    one: '单段',
    paper: '论文',
    picture: '图片',
    presentation: 'PPT',
    qa: '问答',
    table: '表格',
    tag: '标签',
  };
  return map[m] || m || '—';
}

/** RAGFlow 文档 run 状态 → 颜色 class */
export function runStatusClass(run: string): string {
  switch (run) {
    case 'DONE': return 'run-done';
    case 'RUNNING': return 'run-running';
    case 'UNSTART': return 'run-unstart';
    case 'CANCEL': return 'run-cancel';
    case 'FAIL': return 'run-fail';
    default: return 'run-unstart';
  }
}

export function runStatusLabel(run: string): string {
  switch (run) {
    case 'DONE': return '已完成';
    case 'RUNNING': return '解析中';
    case 'UNSTART': return '待解析';
    case 'CANCEL': return '已取消';
    case 'FAIL': return '失败';
    default: return run || '—';
  }
}

/** 把秒数格式化成 'X分Y秒' / 'Y秒' / 'X.X秒'. < 60 显示秒, < 3600 显示分秒 */
export function fmtDuration(seconds: number): string {
  if (!seconds || seconds < 0) return '';
  if (seconds < 60) return `${seconds.toFixed(1)}秒`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m}分${s}秒`;
  const h = Math.floor(m / 60);
  return `${h}时${m % 60}分`;
}

/** source_type -> 简短中文标签 (用于文档行) */
export function sourceLabel(type: string): string {
  switch ((type || '').toLowerCase()) {
    case 'local': return '本地';
    case 'http': return 'HTTP';
    case 'web': return '网页';
    default: return type || '—';
  }
}

/** 把 ISO 8601 字符串 / epoch ms 转 'YYYY-MM-DD HH:mm' (无时区 → 当本地时间) */
export function fmtIso(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—';
  const d = typeof v === 'number' ? new Date(v) : new Date(v);
  const t = d.getTime();
  if (Number.isNaN(t)) return '—';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 0-1 小数 → 百分比字符串 'xx.x%' */
export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${(v * 100).toFixed(1)}%`;
}

/** ms 时长 → '1.2s' / '456ms' */
export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** 长错误信息抽取摘要: { head, root, traceback, short }
 * - head: 截断在 Traceback 段前的可读消息 (一般是 Exception: + Last error 简介)
 * - root: " -> " 链最后一节 (HTTPStatusError: 401 ...), 没有链就 null
 * - traceback: 完整 stack trace 段 (含 Traceback 头), 没有就 null
 * 短错误 (<200 字): traceback=null, head=原全文
 *
 * 支持 3 种 pr-agent 错误格式:
 * 1) Python 标准 traceback: "Traceback (most recent call last):\n  File ..." (带括号)
 * 2) 单行 traceback 头:    "Traceback: ..." (冒号紧贴, 老式)
 * 3) 纯 chain (无 traceback): "A: msg1 -> B: msg2 -> C: msg3" (pr-agent format_exception_chain)
 */
export function summarizeError(raw: string | null | undefined): { head: string; root: string | null; traceback: string | null; short: boolean } {
  if (!raw) return { head: '', root: null, traceback: null, short: true };
  // 找 traceback 起始位置: 支持 "Traceback:" 和 "Traceback (most recent call last):"
  const m = raw.match(/Traceback\s*(?::|\(most recent call last\))/i);
  if (m && m.index !== undefined) {
    const tbIdx = m.index;
    const head = raw.slice(0, tbIdx).trim();
    const tbBlock = raw.slice(tbIdx);
    // 优先级: tbBlock 的 -> 链 → head 的 -> 链 → head 的 "Last error: ..." 段
    const root = pickChainRoot(tbBlock) ?? pickChainRoot(head) ?? pickLastErrorRoot(head);
    return { head, root, traceback: tbBlock, short: false };
  }
  // 无 traceback: 走纯 chain 解析 + Last error 兜底
  const head = raw.trim();
  const root = pickChainRoot(head) ?? pickLastErrorRoot(head);
  return { head, root, traceback: null, short: raw.length < 200 };
}

/** 从 " -> " 链里挑最后一节作为根因 (符合 ErrorType: 格式才算).
 *  例: "A: x -> B: y -> HTTPStatusError: 401" → root="HTTPStatusError: 401"
 *  注意: 跳过纯链节本身 (length<=1) 和不像 error 总结的最后节 (例如纯路径含 "->")
 */
function pickChainRoot(block: string): string | null {
  const parts = block.split(' -> ');
  if (parts.length <= 1) return null;
  const last = parts[parts.length - 1].trim();
  if (/^[A-Z][A-Za-z._]+(?:Error|Exception|Warning):/.test(last)) return last;
  return null;
}

/** 从 pr-agent 风格的 "Last error: TypeName: msg" 抽根因.
 *  pr-agent 把 format_exception_chain 的结果存到 _run_status["error"], 但实际只存了
 *  最后一节 (没有 " -> " 前缀) 加上 "Last error: " 前缀. 例:
 *    "Exception: Failed to ...\nLast error: RateLimitError: too many"
 *  → 抽 "RateLimitError: too many" 作为根因展示.
 *  也兼容 "RateLimitError: litellm.X: y" 这种嵌套: 拿最后那段 (litellm.X: y).
 */
function pickLastErrorRoot(head: string): string | null {
  // 1) 找 "Last error: " 段
  const m = head.match(/Last error:\s*(.+?)(?:\n|$)/i);
  if (!m) return null;
  const tail = m[1].trim();
  // 2) 嵌套的 "TypeA: msg1 TypeB: msg2" 里挑最像 error 总结的一段 (按 ":" 切, 倒序遍历)
  //    例: "RateLimitError: litellm.RateLimitError: OpenAIException - 已达... (2062)"
  //    切: ["RateLimitError", "litellm.RateLimitError", "OpenAIException - 已达... (2062)"]
  //    最后一段 "OpenAIException - ..." 是真正的根因.
  const parts = tail.split(/(?<=\S):\s+/);
  for (let i = parts.length - 1; i >= 0; i--) {
    const p = parts[i].trim();
    if (i === parts.length - 1) return p;  // 最后一段就是根因
    // 中间段必须像 TypeName (大写开头 + 字母/点) 才能算
    if (/^[A-Z][A-Za-z._]*$/.test(p)) return parts.slice(i).join(': ');
  }
  return tail;  // fallback: 整段
}

/** 智能识别错误类别 — 给 ErrorView 一个友好标签 (限流 / 鉴权 / 超时 等) */
export type ErrCategory = 'rate_limit' | 'auth' | 'server' | 'timeout' | 'network' | 'unknown';
export interface ErrMeta {
  category: ErrCategory;
  httpStatus: number | null;
  rootType: string | null;   // 错误类名 (e.g. "HTTPStatusError", "AuthenticationError")
  icon: string;
  label: string;
}
const ERR_META: Record<ErrCategory, Omit<ErrMeta, 'httpStatus' | 'rootType'>> = {
  rate_limit: { category: 'rate_limit', icon: '🚦', label: '限流' },
  auth:       { category: 'auth',       icon: '🔑', label: '鉴权失败' },
  server:     { category: 'server',     icon: '💥', label: '服务端错误' },
  timeout:    { category: 'timeout',    icon: '⏱️', label: '超时' },
  network:    { category: 'network',    icon: '🌐', label: '网络错误' },
  unknown:    { category: 'unknown',    icon: '❗', label: '错误' },
};
export function categorizeError(head: string, root: string | null): ErrMeta {
  const text = `${root || ''}\n${head}`.toLowerCase();
  // 抽 HTTP 状态码: 4xx 客户端错 (401/403/404/429), 5xx 服务端错 (500-599).
  // 兼容 "Error code: 500" / "'429 Too Many Requests'" / "status=502" 等格式.
  const HTTP4XX = '(?:400|401|403|404|429)';
  const HTTP5XX = '(?:5\\d{2})';
  const statusMatch = text.match(new RegExp(`(?:^|[^\\d])(${HTTP4XX}|${HTTP5XX})(?=[^\\d]|$)`, 'i'));
  const httpStatus = statusMatch ? Number(statusMatch[1]) : null;
  // 类型名: 先看 root (可能是 "HTTPStatusError: 401" 或 "OpenAIException - msg"),
  // root 拿不到 "大写开头标识符:" 就 fallback 到 head (例: "Exception: ...").
  // 覆盖 "Exception:" 裸异常 和 "ValueError: ..." 带后缀, 也覆盖 root 是无 ":" 描述的情况.
  function pickType(s: string | null): string | null {
    if (!s) return null;
    const m = s.match(/^([A-Z][A-Za-z._]+?)\s*:/);
    return m && /^[A-Z][A-Za-z._]+$/.test(m[1]) ? m[1] : null;
  }
  const rootType = pickType(root) ?? pickType(head);
  // 类别判定
  let category: ErrCategory = 'unknown';
  if (httpStatus === 429) category = 'rate_limit';
  else if (httpStatus === 401 || httpStatus === 403) category = 'auth';
  else if (httpStatus && httpStatus >= 500) category = 'server';
  else if (/ratelimit|rate.?limit|too.?many.?requests|quota/i.test(text)) category = 'rate_limit';
  else if (/authentication|invalid.?api.?key|unauthorized|forbidden/i.test(text)) category = 'auth';
  else if (/connect.?timeout|read.?timeout|timeout/i.test(text)) category = 'timeout';
  else if (/connection.?error|connection.?refused|connection.?reset|network|httpx|httperror/i.test(text)) category = 'network';
  else if (rootType && /(Error|Exception)/.test(rootType) && httpStatus === null) category = 'unknown';
  return { ...ERR_META[category], httpStatus, rootType };
}
