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

/** 长错误信息抽取摘要: { head, root, traceback }
 * - head: 截断在 Traceback: 前的可读消息 (一般是 Exception: + Last error 简介)
 * - root: " -> " 链最后一节 (HTTPStatusError: 401 ...), 没有链就 null
 * - traceback: 完整 stack trace 段 (含 Traceback: 头), 没有就 null
 * 短错误 (<10 行 or <200 字): traceback=null, head=原全文 */
export function summarizeError(raw: string | null | undefined): { head: string; root: string | null; traceback: string | null; short: boolean } {
  if (!raw) return { head: '', root: null, traceback: null, short: true };
  const tbIdx = raw.indexOf('Traceback:');
  if (tbIdx < 0) return { head: raw.trim(), root: null, traceback: null, short: raw.length < 200 };
  const head = raw.slice(0, tbIdx).trim();
  const tbBlock = raw.slice(tbIdx);
  // " -> " 链末节 = 根因 (HTTPStatusError / AuthenticationError 这类最后一条)
  const parts = tbBlock.split(' -> ');
  let root: string | null = null;
  if (parts.length > 1) {
    const last = parts[parts.length - 1].trim();
    // 只在最后一段看起来是 error 总结时拿来用 (例如 "HTTPStatusError: Client error '401' ...")
    if (/^[A-Z][A-Za-z]+(?:Error|Exception|Warning):/.test(last)) root = last;
  }
  return { head, root, traceback: tbBlock, short: false };
}
