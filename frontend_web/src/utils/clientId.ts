/**
 * 本机唯一标识 (client_id).
 *
 * 为什么需要: `asset_installs` 记录的是"哪台机器/哪个浏览器装了哪个资产".
 * 之前硬编码成 'web', 团队多人用同一个 TestMate 时所有人的安装记录会串成一条,
 * 导致 "谁装的" / "谁该收到更新提示" 全乱.
 *
 * 存在 localStorage, 首次访问生成 UUID4, 之后一直复用.
 */
const KEY = 'testmate.client_id';

function uuid4(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  // 兜底 (老浏览器 / 非安全上下文)
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function getClientId(): string {
  try {
    let id = localStorage.getItem(KEY);
    if (!id) {
      id = uuid4();
      localStorage.setItem(KEY, id);
    }
    return id;
  } catch {
    // 隐私模式 / localStorage 不可用 → 退化成会话级 id
    return 'anon-' + uuid4().slice(0, 8);
  }
}
