/**
 * 软件库上传表单的**取值规则** —— 抽出来是为了能单测 (界面逻辑不写死在组件里).
 *
 * ⚠️ 与「插件·技能·连接」的表单规则**故意不一样**:
 *   市场那边要求 code 以 "dml-" 开头、包名必须是 zip/tar.gz —— 那是给 Agent
 *   装的文本包; 软件库这边是**任意格式的内部软件包** (exe / tar.gz / zip / deb …),
 *   文件名千奇百怪, 不能卡扩展名.
 *   但 code 仍然要严 —— 它会变成**服务端存储目录名** (见后端 software_store).
 */

/** 软件 code 的合法格式 —— 必须跟后端 software_store.CODE_RE 一致 */
export const CODE_PATTERN = /^[a-z0-9][a-z0-9._-]{1,63}$/;

/** 示例 code (表单 placeholder / 报错提示用) */
export const CODE_EXAMPLE = 'ssd-log-doctor';

/** 被系统固定路径占用的 code —— 不能用 */
export const RESERVED_CODES = ['dl', 'config', 'categories', 'path-check'];

/** 适用平台的候选项 (只是标签, 不做平台校验) */
export const PLATFORMS = [
  { value: '', label: '通用 —— 哪个平台都能用' },
  { value: 'windows', label: 'Windows' },
  { value: 'linux', label: 'Linux' },
  { value: 'macos', label: 'macOS' },
];

/** 图标候选 —— 软件库跟资产市场的图标池分开 (两边的东西长得不一样) */
export const ICONS = [
  '🧰', '📦', '💿', '🖴', '🧪', '🔬', '📊', '📈',
  '🛠', '🔧', '⚙', '🔩', '🪛', '🖥', '💻', '⌨',
  '📄', '📑', '📝', '📚', '🧠', '💡', '🔍', '🩺',
  '🚀', '⚡', '🧭', '🗺', '🔐', '🔒', '🏁', '🎯',
];

/**
 * 校验软件 code, 返回空串 = 通过, 否则是给用户看的原因.
 *
 * ⚠️ 规则必须跟后端一致 (app/core/software_store.py 的 CODE_RE) ——
 *   前端不拦的话, 后端会 422, 用户只看到一句没头没尾的报错.
 */
export function validateCode(code: string): string {
  const c = (code || '').trim();
  if (!c) return '软件标识必填';
  if (!CODE_PATTERN.test(c)) {
    return '只能用小写字母/数字/点/下划线/连字符, 且以字母或数字开头 (2-64 位), 如 ' + CODE_EXAMPLE;
  }
  if (RESERVED_CODES.includes(c)) {
    return `软件标识不能叫 "${c}" —— 这个词被系统里的固定路径占用了`;
  }
  return '';
}

/** 校验版本号 —— 空串 = 通过 */
export function validateVersion(version: string): string {
  const v = (version || '').trim();
  if (!v) return '版本号必填';
  if (v.length > 32) return '版本号最长 32 个字符';
  if (/[\\/]/.test(v)) return '版本号里不能有斜杠';
  return '';
}

/** 校验软件名 */
export function validateName(name: string): string {
  const n = (name || '').trim();
  if (!n) return '软件名必填';
  if (n.length > 128) return '软件名最长 128 个字符';
  return '';
}

/**
 * 校验软件包大小 —— 返回空串 = 通过.
 *
 * ⚠️ 前端先拦一道只是**省一次白跑的上传**; 后端必须再拦一道 (前端规则可以被绕过).
 */
export function validateFileSize(size: number, maxBytes: number): string {
  if (!size) return '请选择软件包';
  if (maxBytes > 0 && size > maxBytes) {
    return `文件太大 (${formatSize(size)}), 上限 ${formatSize(maxBytes)}`;
  }
  return '';
}

/** 人类可读的体积 */
export function formatSize(bytes: number): string {
  const b = Number(bytes) || 0;
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`;
  return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

/** 把 "a, b、c" 这样的输入拆成标签数组 (去空去重) */
export function splitTags(raw: string): string[] {
  const parts = (raw || '')
    .split(/[,;、，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  return Array.from(new Set(parts));
}

/** 功能清单: 一行一条 → 数组 */
export function splitFeatures(raw: string): string[] {
  return (raw || '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);
}

/** 功能清单: 数组 → 一行一条 (编辑时回填) */
export function joinFeatures(list: string[]): string {
  return (list || []).filter(Boolean).join('\n');
}
