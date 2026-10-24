/**
 * 资产卡片的**状态徽标** —— 状态是卡片自己的属性, 不是视图筛选.
 *
 * 徽标同时可能挂多个 (待审核 + 待同步 …).
 * ⚠️ 不再有「已安装 / 可更新」—— 安装只是下载, 后端不知道用户装没装.
 */
import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import AssetCard from '../AssetCard.vue';
import type { AssetItem } from '@/api/assets';

function item(over: Partial<AssetItem> = {}): AssetItem {
  return {
    code: 'demo', name: '演示资产', icon: '🧩', kind: 'skill', version: '1.0.0',
    summary: '摘要', description: '说明', use_when: '何时', not_for: '何时不',
    category: 'misc', tags: [], keywords: [], author: 'admin', featured: false,
    homepage: null, permissions: {}, install_steps: [], bindings: {},
    git_path: 'assets/skills/misc/demo', git_commit_sha: '', git_web_url: '',
    download_count: 0, updated_at: null,
    sync_status: 'pushed', last_error: '', publish_status: 'published',
    review_note: '', can_review: false,
    ...over,
  };
}

function badges(w: ReturnType<typeof mount>) {
  return w.findAll('.ac-badge').map((b) => b.text().trim());
}

describe('AssetCard 状态徽标', () => {
  it('在架且没装 → 不显示任何状态徽标', () => {
    const w = mount(AssetCard, { props: { item: item() } });
    expect(badges(w)).toEqual([]);
  });

  it('不再有「已安装 / 可更新」徽标 —— 安装只是下载', () => {
    const w = mount(AssetCard, { props: { item: item() } });
    const b = badges(w);
    expect(b).not.toContain('✓ 已安装');
    expect(b).not.toContain('↑ 可更新');
  });

  it('待审核 → 📋 待审核', () => {
    const w = mount(AssetCard, { props: { item: item({ publish_status: 'pending' }) } });
    expect(badges(w)).toContain('📋 待审核');
  });

  it('已驳回 → ❌ 已驳回', () => {
    const w = mount(AssetCard, { props: { item: item({ publish_status: 'rejected' }) } });
    expect(badges(w)).toContain('❌ 已驳回');
  });

  it('已下架 → ⚠️ 已下架', () => {
    const w = mount(AssetCard, { props: { item: item({ publish_status: 'unpublished' }) } });
    expect(badges(w)).toContain('⚠️ 已下架');
  });

  it('待下架审核 → ⏳ 待下架审核 (2026-10-24 申请制)', () => {
    const w = mount(AssetCard, { props: { item: item({ publish_status: 'unpublish_pending' }) } });
    expect(badges(w)).toContain('⏳ 待下架审核');
  });

  it('待同步 → 🕐 待同步', () => {
    const w = mount(AssetCard, { props: { item: item({ sync_status: 'staged' }) } });
    expect(badges(w)).toContain('🕐 待同步');
  });

  it('同步失败 → ❌ 同步失败', () => {
    const w = mount(AssetCard, { props: { item: item({ sync_status: 'failed' }) } });
    expect(badges(w)).toContain('❌ 同步失败');
  });

  it('多个状态可以同时出现', () => {
    const w = mount(AssetCard, {
      props: { item: item({ publish_status: 'pending', sync_status: 'staged' }) },
    });
    const b = badges(w);
    expect(b).toContain('📋 待审核');
    expect(b).toContain('🕐 待同步');
  });

  it('显示下载次数', () => {
    const w = mount(AssetCard, { props: { item: item({ download_count: 7 }) } });
    expect(w.text()).toContain('⬇ 7');
  });

  it('点卡片 → 抛 open 事件带该资产', async () => {
    const it_ = item();
    const w = mount(AssetCard, { props: { item: it_ } });
    await w.find('.asset-card').trigger('click');
    expect(w.emitted('open')).toBeTruthy();
    expect((w.emitted('open') as any)[0][0].code).toBe('demo');
  });
});
