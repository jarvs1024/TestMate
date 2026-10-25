/**
 * 市场页的「项目 + 排序」合并筛选菜单 (2026-10-25).
 *
 * 为什么有这两个测试:
 *   ① 按钮文案要能一眼看出"现在筛的是什么" (项目 + 排序都在按钮上);
 *   ② 「点外面收起」必须注册在**捕获阶段** —— element-plus 的抽屉内容层带
 *      `@click.stop`, 冒泡阶段的事件到不了 document (AssetUploadDialog 的图标面板
 *      已经踩过这个坑, 见 commit 7716e85).
 *
 * ⚠️ 组件必须**挂到真实 document** (attachTo) —— vue-test-utils 默认把组件挂在
 *    脱离文档的树上, 那样点它根本不会冒泡到 document, 测不出真实行为.
 */
import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import MarketFilterMenu from '../MarketFilterMenu.vue';

const PROJECTS = [
  { code: 'general', name: '通用', total: 15 },
  { code: '6100', name: '6100', total: 3 },
  { code: '8560', name: '8560', total: 0 },
];

function mountMenu(props: Record<string, any> = {}) {
  return mount(MarketFilterMenu, {
    props: { project: '', sort: 'hot', projects: PROJECTS, ...props },
    attachTo: document.body,
  });
}

describe('市场筛选菜单', () => {
  it('按钮上同时显示当前项目和排序', () => {
    const w = mountMenu();
    expect(w.find('.filter-trigger').text()).toContain('全部项目');
    expect(w.find('.filter-trigger').text()).toContain('热门');
    w.unmount();
  });

  it('选了项目 + 排序 → 按钮文案跟着变', async () => {
    const w = mountMenu({ project: '6100', sort: 'new' });
    const t = w.find('.filter-trigger').text();
    expect(t).toContain('6100');
    expect(t).toContain('最新');
    expect(t).not.toContain('热门');
    w.unmount();
  });

  it('选「通用」→ 按钮显示通用', () => {
    const w = mountMenu({ project: 'general' });
    expect(w.find('.filter-trigger').text()).toContain('通用');
    w.unmount();
  });

  it('点项目 → emit update:project, 菜单收起', async () => {
    const w = mountMenu();
    await w.find('.filter-trigger').trigger('click');
    expect(w.find('.filter-panel').exists()).toBe(true);
    const item = w.findAll('.fp-item').find((i) => i.text().includes('6100'))!;
    await item.trigger('click');
    expect(w.emitted('update:project')?.[0]).toEqual(['6100']);
    expect(w.find('.filter-panel').exists()).toBe(false);
    w.unmount();
  });

  it('点排序 → emit update:sort', async () => {
    const w = mountMenu();
    await w.find('.filter-trigger').trigger('click');
    const item = w.findAll('.fp-item').find((i) => i.text().trim() === '最新')!;
    await item.trigger('click');
    expect(w.emitted('update:sort')?.[0]).toEqual(['new']);
    w.unmount();
  });

  it('点外面 → 收起 (捕获阶段才能收到, 冒泡阶段收不到)', async () => {
    const w = mountMenu();
    await w.find('.filter-trigger').trigger('click');
    expect(w.find('.filter-panel').exists()).toBe(true);
    // 模拟 element-plus 抽屉内容层的 @click.stop —— 冒泡到这里就断了
    const stopper = (e: Event) => e.stopPropagation();
    document.body.addEventListener('click', stopper);
    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    document.body.removeEventListener('click', stopper);
    await w.vm.$nextTick();
    expect(w.find('.filter-panel').exists()).toBe(false);
    w.unmount();
  });

  it('Esc → 收起', async () => {
    const w = mountMenu();
    await w.find('.filter-trigger').trigger('click');
    expect(w.find('.filter-panel').exists()).toBe(true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await w.vm.$nextTick();
    expect(w.find('.filter-panel').exists()).toBe(false);
    w.unmount();
  });
});
