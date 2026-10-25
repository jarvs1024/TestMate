/**
 * 账号管理 API —— 设置页「👥 用户管理」区块专用 (仅 admin).
 *
 * ⚠️ 账号口径 (跟后端 app/core/identity.py 一致):
 *   · 普通用户 = 公司邮箱 (后缀由后端的 AUTH_EMAIL_DOMAIN 决定), 建号时填前缀或全邮箱都行
 *   · 管理员   = 不含 @ 的账号名, 一律要密码
 *   · 建号时**没给密码** → 免密账号 (填用户名就能进)
 *   · 建号时**给了密码** → 必须输密码
 */
import request from '@/utils/request';

export type UserRole = 'admin' | 'tester' | 'viewer';

export interface ManagedUser {
  id: number;
  username: string;
  role: UserRole;
  is_active: boolean;
  password_required: boolean;
  created_at: string;
}

export interface CreateUserPayload {
  username: string;
  password?: string;
  role: UserRole;
  password_required?: boolean;
}

export interface UpdateUserPayload {
  is_active?: boolean;
  role?: UserRole;
  password?: string;
  password_required?: boolean;
}

/**
 * 账号列表 (admin)
 *
 * @param opts.silent 失败时不弹全局错误 (调用方自己在页面里显示错误态)
 */
export async function listUsers(opts: { silent?: boolean } = {}): Promise<ManagedUser[]> {
  return (await request.get('/auth/users', { silent: opts.silent })) as ManagedUser[];
}

/**
 * 公开的认证配置 (不需要登录) —— 公司邮箱后缀等.
 *
 * ⚠️ 邮箱后缀的真源是后端的 AUTH_EMAIL_DOMAIN (可配) —— 前端写死的话,
 *    后端换了域名, 登录页/建号页还显示旧后缀, 用户按旧后缀填就登不进去.
 *    取不到时前端回退默认常量 (只是"显示"用的, 真正补后缀在后端).
 */
export async function getAuthConfig(): Promise<{ email_domain: string }> {
  // ⚠️ silent: 取不到就回退默认, 不该弹全局错误 (登录页也会调它)
  return (await request.get('/auth/config', { silent: true })) as { email_domain: string };
}

/** 建号 (admin) */
export async function createUser(payload: CreateUserPayload): Promise<ManagedUser> {
  return (await request.post('/auth/users', payload)) as ManagedUser;
}

/** 改账号: 停用/启用、改角色、重置密码、切换要不要密码 (admin) */
export async function updateUser(id: number, payload: UpdateUserPayload): Promise<ManagedUser> {
  return (await request.patch(`/auth/users/${id}`, payload)) as ManagedUser;
}
