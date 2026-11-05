/**
 * 侧栏能力导航器.
 *
 * 为什么侧栏要按**角色**分组 (2026-10-25):
 *   以前侧栏是「广场 / 知识库」两个平级分区, 用户得先判断"我要去哪个功能区";
 *   现在侧栏跟首页共用同一份能力数据 —— 首页是总览, 侧栏是目录,
 *   不会出现"侧栏有、首页没有"的情况. 所以要盯住:
 *   ① 按角色分组, 组标题带角色图标与计数;
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
  cap({ id: 3, code: 'ext-library', name: '扩展库', kind: 'platform', icon: '🏪', route: 'page:extensions' }),
  cap({ id: 4, code: 'kb-inventory', name: '知识库', kind: 'platform', icon: '📚', route: 'page:kb-manage' }),
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
  // 带登录态 —— /extensions 这类页面要鉴权, 否则守卫会把我踢去 /login
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

  /**
   * 排版层次 (2026-10-25 第三轮: 用户反馈"无层次感"):
   *   总览入口「全部能力」→ 角色组 → 能力条目.
   *   顺序错了层次就塌了 —— 所以这里钉死 DOM 顺序.
   *
   * ⚠️ 2026-11-04 (第二十三轮): 顶部的「能力」区块标题**去掉**了 ——
   *   ① 它跟紧接着的「全部能力」语义重复 (同一句话说两遍);
   *   ② 侧栏下半的「📡 数据 / 工具」本来就有自己的标题, 不靠它分段;
   *   ③ 改成「能力墙」不对 —— 侧栏是目录 (列能力名), 首页才是墙 (列能力卡).
   *   所以现在是**三层**, 这里同步钉死.
   */
  it('三层结构: 总览入口 → 角色组 → 条目 (顶部不再有「能力」区块标题)', () => {
    const { w } = mountNav();
    // 旧标题彻底没了 —— 不是改成别的字, 是这个元素本身不存在
    expect(w.find('.nav-cap').exists()).toBe(false);
    expect(w.find('.nc-lb').exists()).toBe(false);
    const kids = w.element.children;
    expect(kids[0].classList.contains('all-link')).toBe(true);
    expect(kids[1].classList.contains('group')).toBe(true);
    w.unmount();
  });

  it('侧栏里不再出现单独的「能力」二字 (「全部能力」不算)', () => {
    const { w } = mountNav();
    const texts = w.findAll('.lb, .g-lb, .nc-lb').map((e) => e.text().trim());
    expect(texts).not.toContain('能力');
    expect(texts).toContain('全部能力');
    w.unmount();
  });

  it('「全部能力」是总览入口, 带上能力总数', () => {
    const { w } = mountNav();
    expect(w.find('.all-link .count').text()).toBe(String(CAPS.length));
    w.unmount();
  });

  it('每个角色组都有标题与组下分隔线 (组标题与它的条目成一个单元)', () => {
    const { w } = mountNav();
    const groups = w.findAll('.group');
    expect(groups).toHaveLength(3);
    for (const g of groups) {
      expect(g.find('.g-hd').exists()).toBe(true);
      expect(g.find('.g-rule').exists()).toBe(true);
    }
    w.unmount();
  });

  it('按角色分组, 组标题带图标与计数', () => {
    const { w } = mountNav();
    const heads = w.findAll('.g-hd').map((h) => h.text());
    expect(heads).toHaveLength(3);
    // ⚠️ 2026-10-27: 资产组排**最上面**, 角色名「底座」→「资产」
    expect(heads[0]).toContain('资产');
    expect(heads[0]).toContain('2');
    expect(heads[1]).toContain('工具');
    expect(heads[1]).toContain('2');
    expect(heads[2]).toContain('看板');
    expect(heads[2]).toContain('1');
    w.unmount();
  });

  it('每项能力都列出来了', () => {
    const { w } = mountNav();
    const labels = w.findAll('.item .i-lb').map((i) => i.text());
    // ⚠️ 资产组排前面 → 顺序跟着变; 「AI 资产市场」→「扩展」→「扩展库」
    expect(labels).toEqual(['扩展库', '知识库', '日志分析', '文本用例生成', '代码检视']);
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
    expect(hrefs).toContain('/extensions');
    expect(hrefs).toContain('/kb-manage');
    w.unmount();
  });

  it('当前所在的能力高亮', async () => {
    await router.push('/extensions');
    const { w } = mountNav();
    expect(router.currentRoute.value.path).toBe('/extensions');
    const active = w.findAll('.item').find((i) => i.classes().includes('active'));
    expect(active?.text()).toContain('扩展库');
    w.unmount();
  });
});
