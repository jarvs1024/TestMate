/**
 * 账号管理区块 (UserManage) —— 2026-10-25.
 *
 * 这是**唯一的建号入口**: 登录页只认这里建出来的号.
 * 盯住这几件事:
 *   ① 建号: 短名 / 全邮箱都提交原样 (后端负责补域名), 角色和密码一起带上;
 *   ② 建号失败 → 把后端的话显示出来 (比如"普通用户必须是公司邮箱"), 不吞掉;
 *   ③ 列表: 用户名 / 角色 / 登录方式 (免密 vs 需密码) / 停用状态;
 *   ④ 停用 / 启用 / 改角色 / 重置密码 → 各自打对应的接口, 改完 emit('changed');
 *      停用是**立刻生效**的破坏性操作 → 必须**二次确认** (2026-10-30);
 *   ⑤ 选「管理员」角色时**不显示** @twsc.com.cn 后缀 (管理员是账号名, 不是邮箱);
 *   ⑥ 管理员账号没设密码 → 禁用「创建账号」, 错误**贴在密码框下面** (字段级).
 *   ⑦ 删除账号 (2026-10-31) → 不可逆, 必须**手打账号名**确认并把后果写清楚;
 *      **当前登录的账号不能删** (按钮禁用), 别的管理员账号照常能删.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus';
import UserManage from '../UserManage.vue';
import { useUserStore, type UserInfo } from '@/stores/user';
import type { ManagedUser } from '@/api/users';

const api = vi.hoisted(() => ({
  listUsers: vi.fn(async () => [] as ManagedUser[]),
  createUser: vi.fn(async (p: any) => ({
    id: 99, username: 'zhangsan@twsc.com.cn', role: p.role,
    is_active: true, password_required: !!p.password, created_at: '2026-10-25T10:00:00',
  })),
  updateUser: vi.fn(async (_id: number, p: any) => ({
    id: 1, username: 'zhangsan@twsc.com.cn', role: 'tester',
    is_active: p.is_active ?? true, password_required: !!p.password, created_at: '2026-10-25T10:00:00',
  })),
  // ⚠️ 删除 = 204 无响应体 —— 没有返回值, 调用方只看成功/失败
  deleteUser: vi.fn(async (_id: number) => undefined),
}));

vi.mock('@/api/users', () => api);

function user(over: Partial<ManagedUser> = {}): ManagedUser {
  return {
    id: 1,
    username: 'zhangsan@twsc.com.cn',
    role: 'tester',
    is_active: true,
    password_required: false,
    created_at: '2026-10-25T10:00:00',
    ...over,
  };
}

/**
 * 挂组件.
 *
 * ⚠️ 必须起一个 pinia —— 组件里要读 user store 判断"当前登录的是哪个账号"
 *    (「删除自己」那个按钮要禁用). 不给 pinia 的话组件读不到当前用户,
 *    那个断言就没法测了.
 *
 * @param me 当前登录的账号 (不给 = 未登录/不知道是谁 → 删除按钮不禁用)
 */
async function mountComp(
  users: ManagedUser[] = [],
  me?: { id: number; username: string; role: UserInfo['role'] },
) {
  const pinia = createPinia();
  setActivePinia(pinia);
  if (me) {
    const store = useUserStore(pinia);
    store.user = { id: me.id, username: me.username, role: me.role };
  }
  const w = mount(UserManage, {
    props: { users },
    global: { plugins: [ElementPlus, pinia] },
  });
  await flushPromises();
  return w;
}

/** 找账号行里的「删除」按钮 (按文案精确找, 免得跟「重置密码」串了) */
function deleteBtn(w: any, index = 0) {
  return w.findAll('button').filter((b: any) => b.text().trim() === '删除')[index];
}

beforeEach(() => {
  api.createUser.mockClear();
  api.updateUser.mockClear();
  api.listUsers.mockClear();
  api.deleteUser.mockClear();
  // ⚠️ user store 的初始状态是从 localStorage 读的 —— 别让上一条用例的残留影响下一条
  localStorage.clear();
});

describe('账号管理 · 建号', () => {
  it('填用户名 + 选角色 → 调 createUser', async () => {
    const w = await mountComp();
    await w.find('input[placeholder="zhangsan"]').setValue('zhangsan');
    await w.find('select').setValue('viewer');
    await w.find('.create-btn').trigger('click');
    await flushPromises();
    expect(api.createUser).toHaveBeenCalledWith({
      username: 'zhangsan',
      password: '',
      role: 'viewer',
    });
    w.unmount();
  });

  it('建号成功 → 清空表单 + 通知父组件刷新', async () => {
    const w = await mountComp();
    await w.find('input[placeholder="zhangsan"]').setValue('zhangsan');
    await w.find('.create-btn').trigger('click');
    await flushPromises();
    expect((w.find('input[placeholder="zhangsan"]').element as HTMLInputElement).value).toBe('');
    expect(w.emitted('changed')).toBeTruthy();
    w.unmount();
  });

  it('建号失败 → 把后端给的错误显示出来 (不吞掉)', async () => {
    api.createUser.mockRejectedValueOnce({
      response: { data: { detail: '普通用户必须是公司邮箱 (如 zhangsan@twsc.com.cn)' } },
    });
    const w = await mountComp();
    await w.find('input[placeholder="zhangsan"]').setValue('someone@other.com');
    await w.find('.create-btn').trigger('click');
    await flushPromises();
    // ⚠️ 2026-10-30: 错误改成**按字段定位** —— 说的是用户名, 就贴在用户名框下面
    expect(w.find('.field-err').text()).toContain('公司邮箱');
    w.unmount();
  });

  it('选「管理员」+ 密码留空 → 禁用「创建账号」, 错误贴在密码框下', async () => {
    const w = await mountComp();
    await w.find('input[placeholder="zhangsan"]').setValue('opsadmin');
    await w.find('select').setValue('admin');
    await flushPromises();
    // 按钮禁用 —— 不用等后端往返才知道建不了
    expect((w.find('.create-btn').element as HTMLButtonElement).disabled).toBe(true);
    // 错误贴着密码字段
    expect(w.find('.field-err').text()).toContain('管理员账号必须设置密码');
    expect(api.createUser).not.toHaveBeenCalled();
    w.unmount();
  });

  it('选「管理员」→ 不显示 @twsc.com.cn 后缀 (账号名不带 @)', async () => {
    const w = await mountComp();
    expect(w.find('.suffix').exists()).toBe(true);
    await w.find('select').setValue('admin');
    await flushPromises();
    expect(w.find('.suffix').exists()).toBe(false);
    w.unmount();
  });
});

describe('账号管理 · 列表', () => {
  it('显示用户名 / 角色 / 登录方式', async () => {
    const w = await mountComp([
      user(),
      user({ id: 2, username: 'opsadmin', role: 'admin', password_required: true }),
    ]);
    const txt = w.text();
    expect(txt).toContain('zhangsan@twsc.com.cn');
    expect(txt).toContain('opsadmin');
    expect(txt).toContain('测试者');
    expect(txt).toContain('管理员');
    expect(txt).toContain('免密');
    expect(txt).toContain('需密码');
    w.unmount();
  });

  it('停用的账号显示「已停用」', async () => {
    const w = await mountComp([user({ is_active: false })]);
    expect(w.text()).toContain('已停用');
    w.unmount();
  });

  it('一个账号都没有 → 给一句人话, 不留白板', async () => {
    const w = await mountComp([]);
    expect(w.find('.empty').exists()).toBe(true);
    w.unmount();
  });
});

describe('账号管理 · 改账号', () => {
  it('点「停用」→ 先弹确认框, 确认后才调 updateUser(is_active=false)', async () => {
    // ⚠️ 2026-10-30: 停用是立刻生效的破坏性操作, 现在**必须二次确认**
    const spy = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as any);
    const w = await mountComp([user()]);
    const btn = w.findAll('button').find((b: any) => b.text().includes('停用'))!;
    await btn.trigger('click');
    await flushPromises();
    expect(spy).toHaveBeenCalled();
    expect(api.updateUser).toHaveBeenCalledWith(1, { is_active: false });
    expect(w.emitted('changed')).toBeTruthy();
    spy.mockRestore();
    w.unmount();
  });

  it('停用确认框里取消 → 不调接口', async () => {
    const spy = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel' as any);
    const w = await mountComp([user()]);
    const btn = w.findAll('button').find((b: any) => b.text().includes('停用'))!;
    await btn.trigger('click');
    await flushPromises();
    expect(api.updateUser).not.toHaveBeenCalled();
    spy.mockRestore();
    w.unmount();
  });

  it('已停用的账号 → 按钮变成「启用」', async () => {
    const w = await mountComp([user({ is_active: false })]);
    const btn = w.findAll('button').find((b: any) => b.text().includes('启用'))!;
    await btn.trigger('click');
    await flushPromises();
    expect(api.updateUser).toHaveBeenCalledWith(1, { is_active: true });
    w.unmount();
  });

  it('改角色 → 调 updateUser(role)', async () => {
    const w = await mountComp([user()]);
    await w.find('.role-sel').setValue('admin');
    await flushPromises();
    expect(api.updateUser).toHaveBeenCalledWith(1, { role: 'admin' });
    w.unmount();
  });

  it('重置密码 → 确认框里拿到值后调 updateUser(password)', async () => {
    const spy = vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: 'NewPwd@2026' } as any);
    const w = await mountComp([user()]);
    const btn = w.findAll('button').find((b: any) => b.text().includes('重置密码'))!;
    await btn.trigger('click');
    await flushPromises();
    expect(api.updateUser).toHaveBeenCalledWith(1, { password: 'NewPwd@2026' });
    spy.mockRestore();
    w.unmount();
  });

  it('重置密码时用户取消 → 不调接口', async () => {
    const spy = vi.spyOn(ElMessageBox, 'prompt').mockRejectedValue('cancel' as any);
    const w = await mountComp([user()]);
    const btn = w.findAll('button').find((b: any) => b.text().includes('重置密码'))!;
    await btn.trigger('click');
    await flushPromises();
    expect(api.updateUser).not.toHaveBeenCalled();
    spy.mockRestore();
    w.unmount();
  });
});

describe('账号管理 · 删除账号', () => {
  it('每个账号行都有「删除」按钮', async () => {
    const w = await mountComp([
      user(),
      user({ id: 2, username: 'opsadmin', role: 'admin', password_required: true }),
    ]);
    expect(w.findAll('button').filter((b: any) => b.text().trim() === '删除').length).toBe(2);
    w.unmount();
  });

  it('点「删除」→ 先弹**要手打账号名**的二次确认 (后果写清楚), 确认前不发请求', async () => {
    const spy = vi.spyOn(ElMessageBox, 'prompt').mockReturnValue(new Promise(() => {}) as any);
    const w = await mountComp([user()]);
    await deleteBtn(w).trigger('click');
    await flushPromises();
    expect(spy).toHaveBeenCalled();
    const [msg, title, opts] = (spy as any).mock.calls[0];
    expect(title).toBe('删除账号');
    expect(opts.type).toBe('warning');
    expect(opts.confirmButtonText).toBe('永久删除');
    expect(opts.cancelButtonText).toBe('取消');
    // ⚠️ 删除**不可逆** —— 提示里必须写清楚"无法恢复"和"资产的作者名还留着"
    expect(msg).toContain('zhangsan@twsc.com.cn');
    expect(msg).toContain('无法恢复');
    expect(msg).toContain('资产');
    // ⚠️ 二次确认必须**加强**: 要把账号名原样敲出来才放行 (不能只点一下"确定")
    expect(opts.inputPlaceholder).toBe('zhangsan@twsc.com.cn');
    expect(typeof opts.inputValidator).toBe('function');
    // 名字对不上 → 拦下
    expect(opts.inputValidator('随便写点什么')).toContain('账号名对不上');
    expect(opts.inputValidator('zhangsan@twsc.com.cn')).toBe(true);
    // 确认之前不能真删
    expect(api.deleteUser).not.toHaveBeenCalled();
    spy.mockRestore();
    w.unmount();
  });

  it('确认 → 调 deleteUser(id) + 通知父组件刷新', async () => {
    const spy = vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: 'zhangsan@twsc.com.cn' } as any);
    const w = await mountComp([user()]);
    await deleteBtn(w).trigger('click');
    await flushPromises();
    expect(api.deleteUser).toHaveBeenCalledWith(1);
    expect(w.emitted('changed')).toBeTruthy();
    spy.mockRestore();
    w.unmount();
  });

  it('取消 → 不调接口', async () => {
    const spy = vi.spyOn(ElMessageBox, 'prompt').mockRejectedValue('cancel' as any);
    const w = await mountComp([user()]);
    await deleteBtn(w).trigger('click');
    await flushPromises();
    expect(api.deleteUser).not.toHaveBeenCalled();
    spy.mockRestore();
    w.unmount();
  });

  it('删除失败 → 把后端的话弹出来 (不吞掉)', async () => {
    const spy = vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: 'zhangsan@twsc.com.cn' } as any);
    const errSpy = vi.spyOn(ElMessage, 'error').mockImplementation((() => undefined) as any);
    api.deleteUser.mockRejectedValueOnce({
      response: { data: { detail: '系统至少要保留一个可用的管理员账号' } },
    });
    const w = await mountComp([user()]);
    await deleteBtn(w).trigger('click');
    await flushPromises();
    expect(errSpy).toHaveBeenCalled();
    expect(String(errSpy.mock.calls[0][0])).toContain('保留一个可用的管理员');
    spy.mockRestore();
    errSpy.mockRestore();
    w.unmount();
  });

  it('当前登录的账号 → 「删除」禁用; 别的管理员账号照常能删', async () => {
    // ⚠️ 短名 admin 登录, 列表里既有别的管理员 (opsadmin) 也有自己 (admin)
    const w = await mountComp(
      [
        user({ id: 2, username: 'opsadmin', role: 'admin', password_required: true }),
        user({ id: 3, username: 'admin', role: 'admin', password_required: true }),
      ],
      { id: 99, username: 'admin', role: 'admin' },
    );
    // 别的管理员 → 能删 (后端只保证"至少留一个可用管理员")
    expect((deleteBtn(w, 0).element as HTMLButtonElement).disabled).toBe(false);
    // 自己 → 禁用 (后端也会拦 400, 但别让人白点一次)
    expect((deleteBtn(w, 1).element as HTMLButtonElement).disabled).toBe(true);
    expect(deleteBtn(w, 1).attributes('title')).toContain('不能删除当前登录的账号');
    w.unmount();
  });
});
