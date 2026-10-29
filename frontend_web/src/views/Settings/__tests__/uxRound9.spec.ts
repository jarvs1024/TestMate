/**
 * 第 9 轮 UX 整改 —— 回归护栏 (2026-10-30).
 *
 * 这一轮修的坑 (每条都要有护栏, 免得哪天改回去):
 *   ① 设置页首次进入的**加载态** —— 以前立刻渲染空目录树, 满屏「0 项」,
 *      跟"平台上没有配置项"长得一模一样;
 *   ② 停用账号的**二次确认** —— 以前一点即生效, 当场把人踢下线;
 *   ③ 路由 afterEach 设 **document.title** —— 以前标签页永远是「TestMate」;
 *   ④ 登录页「探测失败」的文案 —— 以前误报成「账号需管理员提前开通」;
 *   ⑤ ToolRunner 运行中「重置」按钮**禁用** —— 以前点了不停运行, 事件还冒回来;
 *   ⑥ BoardView 的**表格**套 .tbl-wrap —— 以前窄屏撑破卡片边框;
 *   ⑦ BoardView 的统计卡**可聚焦** —— 以前键盘用户打不开周报.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { ElMessageBox } from 'element-plus';
import { useUserStore } from '@/stores/user';
import router from '@/router';

// ===== 打桩 (照抄本仓库其它 spec 的写法: vi.hoisted + vi.mock) =====
// ⚠️ 这里全部用不带实现的 vi.fn() —— 默认实现统一放 beforeEach 里设.
//    带实现的 vi.fn(async () => ...) 会被推断成**固定参数**的签名,
//    下面 vi.mock 工厂里的 `(...a: any[]) => h.getX(...a)` 就没法展开 (TS2556).
const h = vi.hoisted(() => ({
  getSchema: vi.fn(),
  updateSetting: vi.fn(),
  getBackendVersion: vi.fn(),
  listUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  getAuthConfig: vi.fn(),
  getAccountHint: vi.fn(),
  getCapability: vi.fn(),
  listCapabilities: vi.fn(),
  getHealth: vi.fn(),
  getOverview: vi.fn(),
  getRules: vi.fn(),
  getAuthors: vi.fn(),
  listMrs: vi.fn(),
  getSeverity: vi.fn(),
  getDismissalsByRule: vi.fn(),
  getTimeline: vi.fn(),
  getWeeklyReports: vi.fn(),
  getWeeklyReport: vi.fn(),
}));

vi.mock('@/api/settings', () => ({
  getSchema: (...a: any[]) => h.getSchema(...a),
  updateSetting: (...a: any[]) => h.updateSetting(...a),
  getBackendVersion: (...a: any[]) => h.getBackendVersion(...a),
  testRagflow: vi.fn(async () => ({ ok: true, status: 'ok', message: 'ok', detail: null })),
  testReviewAgent: vi.fn(async () => ({ ok: true, status: 'ok', message: 'ok', detail: null })),
  testDingTalk: vi.fn(async () => ({ ok: true, status: 'ok', message: 'ok', detail: null })),
  testGitLab: vi.fn(async () => ({ ok: true, status: 'ok', message: 'ok', detail: null })),
  testSoftwareStorage: vi.fn(async () => ({ ok: true, status: 'ok', message: 'ok', detail: null })),
}));

vi.mock('@/api/assets', () => ({
  getMarketConfig: vi.fn(async () => ({ workspace: '/tmp/ws', remote: 'git@x:y.git' })),
  listNotifications: vi.fn(async () => ({ items: [] })),
}));

vi.mock('@/api/users', () => ({
  listUsers: (...a: any[]) => h.listUsers(...a),
  createUser: (...a: any[]) => h.createUser(...a),
  updateUser: (...a: any[]) => h.updateUser(...a),
  getAuthConfig: (...a: any[]) => h.getAuthConfig(...a),
  getAccountHint: (...a: any[]) => h.getAccountHint(...a),
}));

vi.mock('@/api/capabilities', () => ({
  getCapability: (...a: any[]) => h.getCapability(...a),
  listCapabilities: (...a: any[]) => h.listCapabilities(...a),
}));

vi.mock('@/api/reviewagent', () => ({
  getHealth: (...a: any[]) => h.getHealth(...a),
  getOverview: (...a: any[]) => h.getOverview(...a),
  getRules: (...a: any[]) => h.getRules(...a),
  getAuthors: (...a: any[]) => h.getAuthors(...a),
  listMrs: (...a: any[]) => h.listMrs(...a),
  getSeverity: (...a: any[]) => h.getSeverity(...a),
  getDismissalsByRule: (...a: any[]) => h.getDismissalsByRule(...a),
  getTimeline: (...a: any[]) => h.getTimeline(...a),
  getWeeklyReports: (...a: any[]) => h.getWeeklyReports(...a),
  getWeeklyReport: (...a: any[]) => h.getWeeklyReport(...a),
}));

// ToolRunner 拉机台字典走 utils/request —— 打桩, 别真发请求
vi.mock('@/utils/request', () => ({
  default: { get: vi.fn(async () => ({ machines: [] })) },
}));

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  ElMessageBox: { confirm: vi.fn(), prompt: vi.fn() },
}));

import SettingsPage from '../index.vue';
import UserManage from '../components/UserManage.vue';
import ToolRunner from '@/views/Capability/ToolRunner.vue';
import BoardView from '@/views/Capability/BoardView.vue';
import LoginPage from '@/views/Login/index.vue';
import NoticeBar from '@/components/NoticeBar.vue';
import AppHeader from '@/components/AppHeader.vue';

// ===== 造数 =====
function schema() {
  return {
    groups: [
      {
        category: 'general', label: '⚙️ 通用',
        items: [
          {
            key: 'general.platform_name', value: 'TestMate', value_type: 'string',
            description: '平台显示名', is_secret: false, is_default: false, default: '',
          },
        ],
      },
    ],
    total: 1,
  };
}

function capability(withDefault = true) {
  return {
    id: 1, code: 'log-analysis', name: '日志分析', icon: '📊', category: 'auto_code',
    kind: 'tool' as const, version: 'v1.0.0', status: 'stable' as const,
    summary: '分析日志', use_when: '有日志时', not_for: '没日志时', tags: [],
    engine: 'demo', engine_config: {},
    input_schema: [
      {
        key: 'query', label: '查询指令', type: 'text' as const, required: true,
        // 没有 default 时 initDefaults 会留空 → 必填校验能拦住
        ...(withDefault ? { default: 'abc' } : {}),
      },
    ],
    data_sources: [], tools: [], call_count: 0, last_called_at: null, is_featured: false,
  };
}

function mrRow() {
  return {
    project_id: 1, mr_id: 42, title: 'feat: 加个功能', author: 'zhangsan',
    source_branch: 'feat/x', target_branch: 'main', state: 'opened',
    opened_at: '2026-10-30T01:00:00Z', url: 'http://x/1',
    suggestion_counts: { total: 3, applied: 1, dismissed: 0, open: 2, superseded: 0 },
  };
}

/** 起一个 admin 身份的 pinia —— 设置页是 adminOnly 的 */
function adminPinia() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useUserStore(pinia);
  store.token = 'test-token';
  store.user = { id: 1, username: 'admin', role: 'admin' };
  return pinia;
}

async function mountSettings() {
  const pinia = adminPinia();
  const w = mount(SettingsPage, {
    global: { plugins: [pinia], stubs: { 'el-drawer': { template: '<div><slot/></div>' } } },
  });
  await flushPromises();
  return w;
}

/**
 * jsdom 不支持原生跳转 (点 <a> 会报 "Not implemented: navigation") ——
 * 统一把链接的默认行为拦掉 (只影响默认动作, 不影响事件处理器).
 */
const stopNativeNav = (e: Event) => {
  const t = e.target as HTMLElement | null;
  if (t?.closest?.('a')) e.preventDefault();
};

beforeEach(() => {
  localStorage.clear();
  document.addEventListener('click', stopNativeNav, true);
  // ⚠️ jsdom 没实现 matchMedia —— 主题 store 的 resolved getter 要用 (ThemeSwitcher)
  if (!window.matchMedia) {
    window.matchMedia = ((q: string) => ({
      matches: false, media: q, onchange: null,
      addListener: () => {}, removeListener: () => {},
      addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
    })) as any;
  }
  // 默认实现 (每个测试要改哪个, 就在自己那个测试里覆盖)
  h.getSchema.mockReset();
  h.getSchema.mockResolvedValue(schema());
  h.getBackendVersion.mockReset();
  h.getBackendVersion.mockResolvedValue('0.1.0');
  h.listUsers.mockReset();
  h.listUsers.mockResolvedValue([]);
  h.getAuthConfig.mockReset();
  h.getAuthConfig.mockResolvedValue({ email_domain: '@twsc.com.cn' });
  h.getAccountHint.mockReset();
  h.getAccountHint.mockResolvedValue(null);
  h.listCapabilities.mockReset();
  h.listCapabilities.mockResolvedValue({ items: [], total: 0 });
  h.getRules.mockReset();
  h.getRules.mockResolvedValue([]);
  h.getAuthors.mockReset();
  h.getAuthors.mockResolvedValue([]);
  h.getSeverity.mockReset();
  h.getSeverity.mockResolvedValue([]);
  h.getDismissalsByRule.mockReset();
  h.getDismissalsByRule.mockResolvedValue([]);
  h.getWeeklyReports.mockReset();
  h.getWeeklyReports.mockResolvedValue([]);
  h.updateUser.mockReset();
  h.createUser.mockReset();
  vi.mocked(ElMessageBox.confirm).mockReset();
});

afterEach(() => {
  document.removeEventListener('click', stopNativeNav, true);
});

describe('设置页 · 首次进入的加载态', () => {
  it('配置还在读 → 只显示「正在读取平台配置…」, **不显示「0 项」**', async () => {
    // 让 schema 永远不返回 —— 模拟后端慢 / 没起
    let resolveSchema: (v: any) => void = () => {};
    h.getSchema.mockImplementation(() => new Promise((res) => { resolveSchema = res; }));

    const w = await mountSettings();
    await flushPromises();

    expect(w.text()).toContain('正在读取平台配置');
    // ⚠️ 关键断言: 加载中不能出现「0 项」—— 那会被读成"平台上没有配置项"
    expect(w.text()).not.toContain('0 项');
    // 目录也不该先渲染出来 (它带的也是一串 0)
    expect(w.find('.set-toc').exists()).toBe(false);

    // 数据到了 → 加载态收掉, 内容出现
    resolveSchema(schema());
    await flushPromises();
    expect(w.text()).not.toContain('正在读取平台配置');
    expect(w.find('.set-toc').exists()).toBe(true);
    expect(w.text()).toContain('通用');
    w.unmount();
  });

  it('拉失败 → 有错误卡, 不停在「正在读取…」', async () => {
    h.getSchema.mockRejectedValue({ response: { status: 502, data: { detail: 'bad gateway' } } });
    const w = await mountSettings();
    await flushPromises();
    expect(w.text()).not.toContain('正在读取平台配置');
    expect(w.text()).toContain('配置加载失败');
    w.unmount();
  });
});

describe('账号管理 · 停用要二次确认', () => {
  const users = [{
    id: 1, username: 'zhangsan@twsc.com.cn', role: 'tester' as const,
    is_active: true, password_required: false, created_at: '2026-10-25T10:00:00',
  }];

  it('点「停用」→ 先弹确认框 (说明后果), 确认前**不发请求**', async () => {
    // 确认框一直挂着 (用户还没点) —— 这期间不能发请求
    vi.mocked(ElMessageBox.confirm).mockReturnValue(new Promise(() => {}) as any);
    const w = mount(UserManage, { props: { users } });
    await flushPromises();

    const btn = w.findAll('button').find((b: any) => b.text().includes('停用'))!;
    await btn.trigger('click');
    await flushPromises();

    expect(ElMessageBox.confirm).toHaveBeenCalled();
    const [msg, title, opts] = (ElMessageBox.confirm as any).mock.calls[0];
    expect(title).toBe('停用账号');
    expect(msg).toContain('zhangsan@twsc.com.cn');
    expect(msg).toContain('确认停用');
    expect(opts.type).toBe('warning');
    expect(opts.confirmButtonText).toBe('确认停用');
    // ⚠️ 确认之前不能把账号停掉
    expect(h.updateUser).not.toHaveBeenCalled();
    w.unmount();
  });

  it('确认 → 才调 updateUser(is_active=false)', async () => {
    vi.mocked(ElMessageBox.confirm).mockResolvedValue('confirm' as any);
    const w = mount(UserManage, { props: { users } });
    await flushPromises();
    const btn = w.findAll('button').find((b: any) => b.text().includes('停用'))!;
    await btn.trigger('click');
    await flushPromises();
    expect(h.updateUser).toHaveBeenCalledWith(1, { is_active: false });
    w.unmount();
  });

  it('取消 → 不调接口', async () => {
    vi.mocked(ElMessageBox.confirm).mockRejectedValue('cancel' as any);
    const w = mount(UserManage, { props: { users } });
    await flushPromises();
    const btn = w.findAll('button').find((b: any) => b.text().includes('停用'))!;
    await btn.trigger('click');
    await flushPromises();
    expect(h.updateUser).not.toHaveBeenCalled();
    w.unmount();
  });
});

describe('路由 · 标签页标题', () => {
  it('切页面 → document.title 跟着走', async () => {
    adminPinia();   // 设置页是 adminOnly, 得有 admin 身份才进得去
    await router.push('/settings');
    await flushPromises();
    expect(document.title).toBe('设置 · TestMate');
  });

  it('没有 title 的页面 → 退回「TestMate」', async () => {
    adminPinia();
    await router.push('/login');
    await flushPromises();
    expect(document.title).toBe('TestMate');
  });
});

describe('登录页 · 探测失败 ≠ 账号没开通', () => {
  it('探测失败 → 说的是"查不到状态", 不是"账号需管理员提前开通"', async () => {
    h.getAccountHint.mockResolvedValue(null);
    const pinia = createPinia();
    setActivePinia(pinia);
    const w = mount(LoginPage, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await w.find('input[autocomplete="username"]').setValue('zhangsan');
    // 等防抖 (300ms) + 探测返回
    await new Promise((r) => setTimeout(r, 360));
    await flushPromises();

    const hint = w.find('.hint');
    expect(hint.exists()).toBe(true);
    // ⚠️ 以前这句话跟"真的没开通"撞了, 用户以为是自己账号的问题, 实际是平台挂了
    expect(hint.text()).not.toContain('账号需管理员提前开通');
    expect(hint.text()).toContain('账号状态暂时查不到');
    // 语气要是 warn (黄), 不能还是灰字 (plain) —— 灰字跟"一切正常"长得一样
    expect(hint.classes()).toContain('warn');
    w.unmount();
  });
});

describe('工具型运行页 · 运行中不许重置', () => {
  it('运行中 → 「重置」按钮禁用', async () => {
    h.getCapability.mockResolvedValue(capability());
    const pinia = createPinia();
    setActivePinia(pinia);
    const w = mount(ToolRunner, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const resetBtn = () => w.find('button.secondary').element as HTMLButtonElement;
    expect(resetBtn().disabled).toBe(false);

    await w.find('button.primary').trigger('click');
    await flushPromises();

    // ⚠️ 运行中点重置以前**不会停运行** —— 事件继续冒, 状态卡一直「运行中 · 0s」
    expect(resetBtn().disabled).toBe(true);
    w.unmount();
  });

  it('必填字段没填 → 点「运行」不跑, 错误贴在字段下面', async () => {
    h.getCapability.mockResolvedValue(capability(false));   // 没有 default → 值为空
    const pinia = createPinia();
    setActivePinia(pinia);
    const w = mount(ToolRunner, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await w.find('button.primary').trigger('click');
    await flushPromises();

    expect(w.find('.unknown').text()).toContain('请填写 查询指令');
    expect(w.find('.out-status').text()).toContain('待运行');   // 没跑起来
    w.unmount();
  });
});

describe('代码检视看板 · 窄屏与键盘可达', () => {
  async function mountBoard() {
    h.getHealth.mockResolvedValue({ configured: true, status: 'ok', message: 'ok' });
    h.getOverview.mockResolvedValue({
      mrs: { total: 1, merged: 0, open: 1, closed: 0 },
      suggestions: { total: 3, applied: 1, dismissed: 0, open: 2, resolved: 0, adoption_rate: 0.33, dismissal_rate: 0 },
      runs: { total: 2, failed: 0, success_rate: 1 },
      severity_breakdown: [],
    });
    h.listMrs.mockResolvedValue({ items: [mrRow()], failed_mr_count: 0, failed_items: [], total: 1 });
    const w = mount(BoardView, {
      // CapabilityShell 里用了 router (返回工作台) —— 装上免得报注入警告
      global: { plugins: [router], stubs: { 'el-drawer': { template: '<div><slot/></div>' } } },
    });
    await flushPromises();
    return w;
  }

  it('表格都被 .tbl-wrap 包住 (窄屏自己横滑, 不撑破卡片)', async () => {
    const w = await mountBoard();
    const tables = w.findAll('table.tbl');
    expect(tables.length).toBeGreaterThan(0);
    for (const t of tables) {
      expect(t.element.parentElement?.classList.contains('tbl-wrap')).toBe(true);
    }
    w.unmount();
  });

  it('周报统计卡可聚焦 (键盘用户能打开)', async () => {
    const w = await mountBoard();
    const card = w.find('.stat-link');
    expect(card.exists()).toBe(true);
    // 以前是 div @click: tabIndex = -1, role = null → Tab 键永远到不了
    expect(card.attributes('tabindex')).toBe('0');
    expect(card.attributes('role')).toBe('button');
    w.unmount();
  });
});

describe('通知栏 · 匿名用户的「登录」入口', () => {
  const notices = [{
    id: 'anon', type: 'info' as const,
    text: '您正在匿名访问, 进入具体能力需 [登录](/login?redirect=%2Fcode-review) 后使用',
  }];

  it('站内链接 → emit navigate (交给父组件 router.push, 不整页刷新)', async () => {
    const onNavigate = vi.fn();
    const w = mount(NoticeBar, {
      // ⚠️ 父组件接了 navigate → vnode.props.onNavigate 有值 → 才会拦默认行为
      props: { notices, onNavigate } as any,
      // ⚠️ 挂到 document 上 —— jsdom 只对**在文档里**的 <a> 做原生跳转,
      //    上面那个统一的 preventDefault 拦得住 (否则会刷 "Not implemented: navigation")
      attachTo: document.body,
    });
    await flushPromises();

    const link = w.find('a.nb-link');
    expect(link.exists()).toBe(true);
    await link.trigger('click');

    expect(w.emitted('navigate')).toBeTruthy();
    expect((w.emitted('navigate') as any)[0][0]).toContain('/login?redirect=');
    w.unmount();
  });

  it('父组件没接 navigate → 老路走 (整页跳), 链接不会点不动', async () => {
    const w = mount(NoticeBar, { props: { notices }, attachTo: document.body });
    await flushPromises();
    await w.find('a.nb-link').trigger('click');
    expect(w.emitted('navigate')).toBeFalsy();
    w.unmount();
  });

  it('顶栏的「登录」带上当前路径 (别把人送回首页)', async () => {
    const memRouter = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/code-review', name: 'code-review', component: { template: '<div/>' }, meta: { title: '代码检视' } }],
    });
    await memRouter.push('/code-review');
    const pinia = createPinia();
    setActivePinia(pinia);
    const w = mount(AppHeader, {
      global: {
        plugins: [pinia, memRouter],
        // element-plus 整个被打桩了 (见上面的 vi.mock) —— 把 UserMenu 里的下拉组件 stub 掉
        stubs: { 'el-dropdown': true, 'el-dropdown-menu': true, 'el-dropdown-item': true },
      },
    });
    await flushPromises();

    const link = w.find('a.nb-link');
    expect(link.exists()).toBe(true);
    // ⚠️ 以前 redirect 写死成 '/' —— 匿名用户登录完回首页, 不是原来那页
    expect(link.attributes('href')).toBe(`/login?redirect=${encodeURIComponent('/code-review')}`);
    w.unmount();
  });
});
