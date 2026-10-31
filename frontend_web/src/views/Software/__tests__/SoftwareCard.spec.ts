/**
 * 软件卡片的呈现 —— 状态徽标 / 功能清单 / 平台标签.
 *
 * ⚠️ 卡片跟「插件·技能·连接」的卡片是**同一套视觉** (asset-card / ac-* 类名),
 *    差异只在软件特有的字段 (平台 / 功能清单).
 */
import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import SoftwareCard from '../SoftwareCard.vue';
import type { SoftwareItem } from '@/api/software';

function item(over: Partial<SoftwareItem> = {}): SoftwareItem {
  return {
    code: 'demo', name: '演示软件', icon: '🧰', version: '1.0.0',
    summary: '摘要', description: '', features: [], use_when: '', not_for: '',
    install_steps: '', caveats: '',
    platform: '', category: '工具', tags: [], keywords: [], author: 'admin',
    download_count: 0, publish_status: 'published',
    created_at: null, updated_at: '2026-10-27 12:00:00',
    can_edit: false, download_version: '1.0.0',
    ...over,
  };
}

function badges(w: ReturnType<typeof mount>) {
  return w.findAll('.ac-badge').map((b) => b.text().trim());
}

describe('SoftwareCard 状态徽标', () => {
  it('已上架且有文件 → 不显示状态徽标', () => {
    const w = mount(SoftwareCard, { props: { item: item() } });
    expect(badges(w)).toEqual([]);
  });

  it('待传文件 → 🕐 待传文件 (不能让人以为已经能下载)', () => {
    const w = mount(SoftwareCard, { props: { item: item({ publish_status: 'awaiting_file' }) } });
    expect(badges(w)).toContain('🕐 待传文件');
  });

  it('已删除 → ⚠️ 已删除', () => {
    const w = mount(SoftwareCard, { props: { item: item({ publish_status: 'hidden' }) } });
    expect(badges(w)).toContain('⚠️ 已删除');
  });

  it('已上架但没有可下载文件 → ❌ 无文件', () => {
    const w = mount(SoftwareCard, { props: { item: item({ download_version: '' }) } });
    expect(badges(w)).toContain('❌ 无文件');
  });
});

describe('SoftwareCard 平台标签', () => {
  it('有平台才显示', () => {
    const w = mount(SoftwareCard, { props: { item: item({ platform: 'linux' }) } });
    // ⚠️ 2026-10-30: 可见文字走 platformLabel —— 以前显示的是后端原值 'linux',
    //    跟上传表单里的 'Linux' 两种写法 (后端存的仍是小写原值)
    expect(badges(w)).toContain('🐧 Linux');
  });

  it('没平台不显示', () => {
    const w = mount(SoftwareCard, { props: { item: item({ platform: '' }) } });
    expect(badges(w).some((b) => b.includes('linux'))).toBe(false);
  });
});

describe('SoftwareCard 功能清单', () => {
  it('最多显示 3 条, 多了写"还有 N 项…"', () => {
    const w = mount(SoftwareCard, {
      props: { item: item({ features: ['一', '二', '三', '四', '五'] }) },
    });
    const lis = w.findAll('.ac-features li');
    expect(lis.length).toBe(4);
    expect(lis[3].text()).toContain('还有 2 项');
  });

  it('没有功能清单就不渲染这一块', () => {
    const w = mount(SoftwareCard, { props: { item: item({ features: [] }) } });
    expect(w.find('.ac-features').exists()).toBe(false);
  });
});

describe('SoftwareCard 基本信息', () => {
  it('名字 / 版本 / 分类 / 摘要都摆出来', () => {
    const w = mount(SoftwareCard, { props: { item: item() } });
    expect(w.find('.ac-name').text()).toBe('演示软件');
    expect(w.find('.ac-ver').text()).toContain('1.0.0');
    expect(w.find('.ac-ver').text()).toContain('工具');
    expect(w.find('.ac-summary').text()).toBe('摘要');
  });

  it('下载次数与上传人', () => {
    const w = mount(SoftwareCard, { props: { item: item({ download_count: 7 }) } });
    expect(w.find('.ac-meta').text()).toContain('7');
    expect(w.find('.ac-meta').text()).toContain('admin');
  });
});

/**
 * 作者只显示**用户名** (2026-10-31 第十六轮).
 *
 * ⚠️ 用户原话「软件库卡片作者信息只显示用户名, 去掉 @twsc.com.cn」——
 *    邮箱后缀每张卡都一样, 摊出来既占地方又吵.
 * ⚠️ 但全账号不能真丢 —— 挂 title, 悬停还能看到.
 */
describe('SoftwareCard 作者显示', () => {
  it('作者是邮箱 → 卡片上只显示用户名', () => {
    const w = mount(SoftwareCard, {
      props: { item: item({ author: 'jiakejiang@twsc.com.cn' }) },
    });
    const meta = w.find('.ac-meta').text();
    expect(meta).toContain('jiakejiang');
    expect(meta).not.toContain('@twsc.com.cn');
    expect(meta).not.toContain('jiakejiang@twsc.com.cn');
  });

  it('作者是短名 → 原样显示', () => {
    const w = mount(SoftwareCard, { props: { item: item({ author: 'admin' }) } });
    expect(w.find('.ac-meta').text()).toContain('admin');
  });

  it('没有作者 → 显示「未知」', () => {
    const w = mount(SoftwareCard, { props: { item: item({ author: '' }) } });
    expect(w.find('.ac-meta').text()).toContain('未知');
  });

  it('全账号挂在 title 上 (悬停还能看到)', () => {
    const w = mount(SoftwareCard, {
      props: { item: item({ author: 'jiakejiang@twsc.com.cn' }) },
    });
    const spans = w.findAll('.ac-meta .meta-item');
    const authorSpan = spans.find((s) => s.attributes('title') === 'jiakejiang@twsc.com.cn');
    expect(authorSpan).toBeTruthy();
  });
});
