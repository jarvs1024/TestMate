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
