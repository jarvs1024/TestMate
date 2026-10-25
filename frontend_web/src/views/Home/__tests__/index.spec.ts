/**
 * 首页 · 能力墙 (2026-10-25 重构).
 *
 * 盯住四件事:
 *   ① 卡片按**形态**筛选 (不再是"精选/稳定/Beta"那套智能体口径);
 *   ② **规划中的能力沉底** —— 不可用的东西不占首屏;
 *   ③ **匿名只读**: 首页看得见, 点进非公开能力要去登录;
 *      代码检视看板保持匿名可看 (跟重构前一致);
 *   ④ 待办带只放"需要你行动"的事.
 *
 * ⚠️ 两条容易踩的坑 (都踩过):
 *   ① 用**真路由** (@/router), 别造假的 —— Home 靠 `router.getRoutes()` 里的
 *      publicRead 标记判断"能不能匿名进", 造假路由等于把这个判断测空了;
 *   ② 断言用 **router.push 的入参**, 别断言 currentRoute ——
 *      真路由会把目标页的 .vue 懒加载进来 (连带它的一堆 API 模块),
 *      测试里没桩全就会在 import 阶段炸, 导航被中止, 断言看起来像"功能没实现".
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import router from '@/router';
import { useUserStore } from '@/stores/user';

const { listCapabilities } = vi.hoisted(() => ({ listCapabilities: vi.fn() }));

vi.mock('@/api/capabilities', () => ({
  listCapabilities: (...a: any[]) => listCapabilities(...a),
  getCapability: vi.fn(),
}));

// 看板 / 目录 / 知识的 meta 取数 —— 桩掉, 只保留最小结构
vi.mock('@/api/reviewagent', () => ({
  getOverview: vi.fn(async () => ({
    mrs: { total: 128, merged: 10, open: 20 },
    suggestions: { total: 340, applied: 1, dismissed: 2, open: 3, adoption_rate: 0.5, dismissal_rate: 0.1 },
    runs: { total: 1, failed: 0, success_rate: 1 },
    severity_breakdown: [],
  })),
}));

vi.mock('@/api/assets', () => ({
  listAssets: vi.fn(async () => ({ items: [], total: 54 })),
  getSyncStatus: vi.fn(async () => ({
    my_review_count: 3, failed_count: 0, unpublish_pending_count: 0,
    pending_count: 0, conflict_count: 0,
  })),
}));

vi.mock('@/api/kb', () => ({
  kbHealth: vi.fn(async () => ({ status: 'ok', message: '正常' })),
  listDatasets: vi.fn(async () => ({
    items: [{ id: 'd1', document_count: 46, chunk_count: 1200 }],
    total: 1,
  })),
}));

function cap(over: any = {}) {
  return {
    id: 1, code: 'log-analysis', name: '日志分析', icon: '📜',
    category: 'ssd-trace', kind: 'tool', version: 'v0.1.0', status: 'beta',
    summary: '贴日志自动分段', use_when: '', not_for: '', tags: ['日志'],
    engine: 'builtin', engine_config: {}, input_schema: [], data_sources: [], tools: [],
    call_count: 3, last_called_at: null, is_featured: false, route: null,
    ...over,
  };
}

const CAPS = [
  cap({ id: 1, code: 'code-review', name: '代码检视', icon: '🧬', kind: 'board', status: 'stable', category: 'auto-code', route: 'page:code-review' }),
  cap({ id: 2, code: 'agent-market', name: 'AI 资产市场', icon: '🏪', kind: 'catalog', status: 'beta', category: 'ai-market', route: 'page:market' }),
  cap({ id: 3, code: 'kb-inventory', name: '知识库存', icon: '📚', kind: 'library', status: 'stable', category: 'ssd-kb', route: 'page:kb-manage' }),
  cap({ id: 4, code: 'log-analysis', name: '日志分析', icon: '📜', kind: 'tool', status: 'beta', category: 'ssd-trace' }),
  cap({ id: 5, code: 'testcase-gen', name: '文本用例生成', icon: '🧪', kind: 'tool', status: 'draft', category: 'ssd-spec' }),
];

// router.push 是重载方法, spy 的泛型推不出来 —— 这里用 any 收着 (只断言调用入参)
let pushSpy: any;

async function mountHome(opts: { loggedIn?: boolean } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const userStore = useUserStore(pinia);
  if (opts.loggedIn) {
    userStore.token = 'test-token';
    userStore.user = { id: 1, username: 'tester', role: 'tester' } as any;
  }
  const Home = (await import('../index.vue')).default;
  const w = mount(Home, { global: { plugins: [pinia, router] } });
  await flushPromises();
  // ⚠️ isReady 必须在 mount 之后等 —— router 插件装上之前初始导航不会开始,
  //    提前 await 会永远挂着 (第一版就是这么卡住的)
  await router.isReady();
  return { w, userStore };
}

beforeEach(async () => {
  listCapabilities.mockReset();
  listCapabilities.mockResolvedValue({ items: CAPS, total: CAPS.length });
  pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as any);
});

afterEach(() => {
  pushSpy.mockRestore();
});

describe('首页 · 能力墙', () => {
  it('渲染出全部能力卡', async () => {
    const { w } = await mountHome();
    expect(w.findAllComponents({ name: 'CapabilityCard' }).length).toBe(5);
    expect(w.text()).toContain('代码检视');
    expect(w.text()).toContain('知识库存');
    w.unmount();
  });

  it('规划中的能力沉底 (可用项排在前面)', async () => {
    const { w } = await mountHome();
    const names = w.findAllComponents({ name: 'CapabilityCard' })
      .map((c) => c.props('capability').name);
    expect(names[names.length - 1]).toBe('文本用例生成');
    w.unmount();
  });

  it('形态筛选: 只留对应形态的卡', async () => {
    const { w } = await mountHome();
    const chip = w.findAll('.filter').find((f) => f.text().includes('看板'))!;
    await chip.trigger('click');
    const names = w.findAllComponents({ name: 'CapabilityCard' })
      .map((c) => c.props('capability').name);
    expect(names).toEqual(['代码检视']);
    w.unmount();
  });

  it('形态 chips 上带计数', async () => {
    const { w } = await mountHome();
    const all = w.findAll('.filter').find((f) => f.text().includes('全部'))!;
    expect(all.text()).toContain('5');
    const tool = w.findAll('.filter').find((f) => f.text().includes('工具'))!;
    expect(tool.text()).toContain('2');
    const lib = w.findAll('.filter').find((f) => f.text().includes('知识'))!;
    expect(lib.text()).toContain('1');
    w.unmount();
  });

  it('搜索按名称 / 标签过滤, 搜不到给空态', async () => {
    const { w } = await mountHome();
    await w.find('.search input').setValue('知识');
    expect(w.findAllComponents({ name: 'CapabilityCard' }).length).toBe(1);
    await w.find('.search input').setValue('不存在的关键词');
    expect(w.find('.state').text()).toContain('没有匹配的能力');
    w.unmount();
  });

  it('状态筛选: 只看规划中', async () => {
    const { w } = await mountHome();
    await w.find('.status-sel').setValue('planned');
    const names = w.findAllComponents({ name: 'CapabilityCard' })
      .map((c) => c.props('capability').name);
    expect(names).toEqual(['文本用例生成']);
    w.unmount();
  });

  it('匿名用户: 点公开只读的能力 (代码检视) 直接进', async () => {
    const { w } = await mountHome({ loggedIn: false });
    const card = w.findAllComponents({ name: 'CapabilityCard' })
      .find((c) => c.props('capability').code === 'code-review')!;
    await card.find('.cc-cta').trigger('click');
    expect(pushSpy).toHaveBeenCalledWith({ name: 'code-review' });
    w.unmount();
  });

  it('匿名用户: 点非公开能力 → 去登录 (带 redirect)', async () => {
    const { w } = await mountHome({ loggedIn: false });
    const card = w.findAllComponents({ name: 'CapabilityCard' })
      .find((c) => c.props('capability').code === 'agent-market')!;
    await card.find('.cc-cta').trigger('click');
    expect(pushSpy).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'login', query: { redirect: expect.any(String) } }),
    );
    w.unmount();
  });

  it('登录用户: 点任意能力直接进对应页', async () => {
    const { w } = await mountHome({ loggedIn: true });
    const card = w.findAllComponents({ name: 'CapabilityCard' })
      .find((c) => c.props('capability').code === 'agent-market')!;
    await card.find('.cc-cta').trigger('click');
    expect(pushSpy).toHaveBeenCalledWith({ name: 'market' });
    w.unmount();
  });

  it('登录用户: 工具型能力进运行页并带上 code', async () => {
    const { w } = await mountHome({ loggedIn: true });
    const card = w.findAllComponents({ name: 'CapabilityCard' })
      .find((c) => c.props('capability').code === 'log-analysis')!;
    await card.find('.cc-cta').trigger('click');
    expect(pushSpy).toHaveBeenCalledWith({ name: 'tool-runner', params: { code: 'log-analysis' } });
    w.unmount();
  });

  it('规划中的能力点了没反应 (卡片本身不 emit open)', async () => {
    const { w } = await mountHome({ loggedIn: true });
    const card = w.findAllComponents({ name: 'CapabilityCard' })
      .find((c) => c.props('capability').code === 'testcase-gen')!;
    await card.find('.cc-summary').trigger('click');
    expect(pushSpy).not.toHaveBeenCalled();
    w.unmount();
  });

  it('待办带: 登录后显示需要处理的事, 匿名显示登录提示', async () => {
    const { w } = await mountHome({ loggedIn: true });
    expect(w.find('.todo-strip').text()).toContain('3 个资产等你处理');
    w.unmount();

    const anon = await mountHome({ loggedIn: false });
    expect(anon.w.find('.todo-strip.anon').text()).toContain('登录后可见你的待办');
    anon.w.unmount();
  });

  it('形态 meta 取真实数据: 看板 128 个 MR / 目录 54 个资产 / 知识 46 文档', async () => {
    const { w } = await mountHome({ loggedIn: true });
    await flushPromises();
    const text = w.text();
    expect(text).toContain('128 个 MR');
    expect(text).toContain('54 个资产');
    expect(text).toContain('46 文档');
    w.unmount();
  });

  it('首页跳的目标路由在真路由表里都存在 (别跳到空页)', () => {
    const names = router.getRoutes().map((r) => r.name);
    for (const n of ['home', 'tool-runner', 'code-review', 'market', 'kb-manage']) {
      expect(names).toContain(n);
    }
  });
});
