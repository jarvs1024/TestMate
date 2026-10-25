/**
 * 侧栏能力导航器.
 *
 * 为什么侧栏要按**形态**分组 (2026-10-25):
 *   以前侧栏是「广场 / 知识库」两个平级分区, 用户得先判断"我要去哪个功能区";
 *   现在侧栏跟首页共用同一份能力数据 —— 首页是总览, 侧栏是目录,
 *   不会出现"侧栏有、首页没有"的情况. 所以要盯住:
 *   ① 按形态分组, 组标题带形态图标与计数;
 *   ② 每项都能跳到对应能力的路由 (工具型要带 code);
 *   ③ 当前所在的能力高亮.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import router from '@/router';
import { useCapabilityStore } from '@/stores/capabilities';
import { useUserStore } from '@/stores/user';
import CapabilityNav from '../CapabilityNav.vue';
import type { Capability } from '@/api/capabilities';

function cap(over: Partial<Capability> = {}): Capability {
  return {
    id: 1, code: 'log-analysis', name: '日志分析', icon: '📜',
    category: 'ssd-trace', kind: 'tool', version: 'v0.1.0', status: 'beta',
    summary: '贴日志自动分段', use_when: '', not_for: '', tags: [],
    engine: 'builtin', engine_config: {}, input_schema: [], data_sources: [], tools: [],
    call_count: 0, last_called_at: null, is_featured: false, route: null,
    ...over,
  } as Capability;
}

const CAPS = [
  cap({ id: 1, code: 'log-analysis', name: '日志分析', kind: 'tool' }),
  cap({ id: 2, code: 'code-review', name: '代码检视', kind: 'board', icon: '🧬', route: 'page:code-review' }),
  cap({ id: 3, code: 'agent-market', name: 'AI 资产市场', kind: 'catalog', icon: '🏪', route: 'page:market' }),
  cap({ id: 4, code: 'kb-inventory', name: '知识库存', kind: 'library', icon: '📚', route: 'page:kb-manage' }),
  cap({ id: 5, code: 'testcase-gen', name: '文本用例生成', kind: 'tool', status: 'draft' }),
];

function mountNav() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useCapabilityStore(pinia);
  store.items = CAPS;
  store.loaded = true;
  const w = mount(CapabilityNav, { global: { plugins: [pinia, router] } });
  return { w, store };
}

beforeEach(async () => {
  // ⚠️ pinia 要先就位: 路由守卫里 useUserStore() 拿的是**当前 active** 的 pinia,
  //    没有 active pinia 会直接抛错, 导航被中止 (第一版就是这么"路由没跳过去"的)
  const pinia = createPinia();
  setActivePinia(pinia);
  // 带登录态 —— /market 这类页面要鉴权, 否则守卫会把我踢去 /login
  useUserStore(pinia).token = 'test-token';
  await router.replace('/');
});

describe('侧栏能力导航器', () => {
  it('顶部是「全部能力」入口', () => {
    const { w } = mountNav();
    expect(w.find('.all-link').text()).toContain('全部能力');
    expect(w.find('.all-link').attributes('href')).toBe('/');
    w.unmount();
  });

  it('按形态分组, 组标题带图标与计数', () => {
    const { w } = mountNav();
    const heads = w.findAll('.g-hd').map((h) => h.text());
    expect(heads).toHaveLength(4);
    expect(heads[0]).toContain('工具');
    expect(heads[0]).toContain('2');
    expect(heads[1]).toContain('看板');
    expect(heads[3]).toContain('知识');
    w.unmount();
  });

  it('每项能力都列出来了', () => {
    const { w } = mountNav();
    const labels = w.findAll('.item .i-lb').map((i) => i.text());
    expect(labels).toEqual(['日志分析', '文本用例生成', '代码检视', 'AI 资产市场', '知识库存']);
    w.unmount();
  });

  it('规划中的能力标「规划中」', () => {
    const { w } = mountNav();
    const planned = w.findAll('.item').find((i) => i.text().includes('文本用例生成'))!;
    expect(planned.text()).toContain('规划中');
    expect(planned.classes()).toContain('planned');
    w.unmount();
  });

  it('工具型跳运行页并带 code, 其余跳各自页面', () => {
    const { w } = mountNav();
    const hrefs = w.findAll('.item').map((i) => i.attributes('href'));
    expect(hrefs).toContain('/c/log-analysis');
    expect(hrefs).toContain('/code-review');
    expect(hrefs).toContain('/market');
    expect(hrefs).toContain('/kb-manage');
    w.unmount();
  });

  it('当前所在的能力高亮', async () => {
    await router.push('/market');
    const { w } = mountNav();
    expect(router.currentRoute.value.path).toBe('/market');
    const active = w.findAll('.item').find((i) => i.classes().includes('active'));
    expect(active?.text()).toContain('AI 资产市场');
    w.unmount();
  });
});
