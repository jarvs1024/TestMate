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

// ===== 软件包文件名 (2026-10-28) =====

/**
 * **软件包文件名**的合法格式 —— 必须跟后端 software_store.FILE_NAME_RE 一致.
 *
 * ⚠️ 比 code 严: 文件名会原样落到 ``<root>/<code>/<version>/<file_name>``,
 *   也是下载回来时给用户的那个名字. 带中文/空格/括号的话, 在别人机器上
 *   (curl / unzip / Windows 资源管理器) 很容易变成乱码或转义不一致.
 *   所以**上架时当场校验并拒绝**, 而不是静默改名 (静默改名用户不知道).
 */
export const FILE_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$/;

/** 校验软件包文件名 —— 返回空串 = 通过, 否则是给用户看的原因 */
export function validateFileName(name: string): string {
  const n = (name || '').trim();
  if (!n) return '软件包文件名不能为空';
  if (!FILE_NAME_PATTERN.test(n)) {
    return `文件名「${n}」不合规 —— 只能用英文字母、数字、点(.)、下划线(_)、连字符(-), `
      + '且必须以字母或数字开头 (不能有中文、空格、括号等)';
  }
  return '';
}

/**
 * 从**软件包文件名**派生软件标识 (code) —— 不用用户填.
 *
 * ⚠️ 规则必须跟后端 software_store.code_from_file_name **一字不差**:
 *   前端显示的 code 跟后端存的不一样, 用户在服务器上就找不到自己的目录.
 *
 * 规则:
 *   · 去掉扩展名 (``dify-web-entrypoint.sh`` → ``dify-web-entrypoint``)
 *   · 转小写
 *   · 非法字符 → ``-``
 *   · 合并连续的 ``-``, 去掉首尾的 ``-._``
 *   · 最多 64 位; 太短补齐到 2 位
 *
 * ⚠️ 派生结果**仍可能撞名** —— 真正的唯一性由后端加序号保证 (xxx2 / xxx3).
 */
export function codeFromFileName(fileName: string): string {
  let base = ((fileName || '').trim().replace(/\\/g, '/').split('/').pop()) || '';
  // 去掉扩展名 (只去最后一段, `a.tar.gz` → `a.tar`)
  if (base.includes('.')) base = base.slice(0, base.lastIndexOf('.'));
  base = base.toLowerCase();
  base = base.replace(/[^a-z0-9._-]+/g, '-');
  base = base.replace(/-{2,}/g, '-').replace(/^[-._]+/, '').replace(/[-._]+$/, '');
  if (!base) base = 'software';
  base = base.slice(0, 64).replace(/^[-._]+/, '').replace(/[-._]+$/, '');
  if (base.length < 2) base = (base || 'so').slice(0, 2).padEnd(2, '0');
  return base;
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
