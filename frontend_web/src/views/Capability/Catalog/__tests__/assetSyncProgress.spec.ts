/**
 * 乌龟同步进度条 (2026-11-16).
 *
 * 只关心「什么状态下画什么」—— 百分比映射在 syncProgress.spec.ts 里测.
 */
import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import AssetSyncProgress from '../AssetSyncProgress.vue';

function mountView(props: Record<string, any>) {
  return mount(AssetSyncProgress, {
    props: {
      phase: 'syncing', percent: 74, title: '正在推送到 GitLab…',
      sub: '已用 12s', ...props,
    },
  });
}

describe('奔跑中', () => {
  it('乌龟在跑: 有动画态, 没有坐下/礼花', () => {
    const w = mountView({});
    expect(w.find('.sp-turtle').exists()).toBe(true);
    expect(w.find('.sp-turtle.run').exists()).toBe(true);
    expect(w.find('.sp-turtle.sit').exists()).toBe(false);
    expect(w.find('.sp-confetti').exists()).toBe(false);
  });

  it('进度条宽度和 aria 值跟百分比一致', () => {
    const w = mountView({ percent: 74 });
    expect((w.find('.sp-fill').element as HTMLElement).style.width).toBe('74%');
    const track = w.find('.sp-track');
    expect(track.attributes('role')).toBe('progressbar');
    expect(track.attributes('aria-valuenow')).toBe('74');
    expect(w.find('.sp-pct').text()).toBe('74%');
  });

  it('上传阶段显示已传字节', () => {
    const w = mountView({
      phase: 'uploading', percent: 23, title: '正在上传安装包…', sub: '6.7 MB / 29.1 MB',
    });
    expect(w.find('.sp-uploading').exists()).toBe(true);
    expect(w.text()).toContain('6.7 MB / 29.1 MB');
  });
});

describe('冲线完成', () => {
  it('礼花 + 印章 + 欢呼, 不再显示失败卡片', () => {
    const w = mountView({
      phase: 'done', percent: 100, title: '已完成', stamp: 'SUCCESS',
    });
    expect(w.find('.sp-confetti').exists()).toBe(true);
    expect(w.findAll('.sp-confetti i').length).toBeGreaterThan(3);
    expect(w.find('.sp-stamp').text()).toBe('SUCCESS');
    expect(w.find('.sp-stamp.is-bad').exists()).toBe(false);
    expect(w.find('.sp-turtle.cheer').exists()).toBe(true);
    expect(w.find('.sp-fail').exists()).toBe(false);
  });

  it('待审时的印章文案由调用方决定', () => {
    const w = mountView({
      phase: 'done', percent: 100, stamp: 'SUBMITTED',
    });
    expect(w.find('.sp-stamp').text()).toBe('SUBMITTED');
  });
});

describe('失败', () => {
  it('盖红色 FAILED 章', () => {
    const w = mountView({
      phase: 'failed', percent: 81, title: '推送 GitLab 失败', reason: '网络中断',
    });
    const stamp = w.find('.sp-stamp');
    expect(stamp.exists()).toBe(true);
    expect(stamp.text()).toBe('FAILED');
    expect(stamp.classes()).toContain('is-bad');
  });

  it('乌龟坐下, 进度冻结, 原因/建议/技术详情都在', () => {
    const w = mountView({
      phase: 'failed', percent: 81, title: '推送 GitLab 失败',
      reason: '网络中断或 GitLab 不可达', hint: '检查网线',
      detail: '[network] 网络异常, 无法连接 GitLab — 检查网线',
    });
    expect(w.find('.sp-turtle.sit').exists()).toBe(true);
    expect(w.find('.sp-confetti').exists()).toBe(false);
    expect(w.find('.sp-fail').text()).toContain('网络中断或 GitLab 不可达');
    expect(w.find('.sp-fail').text()).toContain('检查网线');
    // 原始 git 报错收在折叠里, 默认收起
    const detail = w.find('details.sp-detail');
    expect(detail.exists()).toBe(true);
    expect(detail.attributes('open')).toBeUndefined();
    expect(detail.text()).toContain('技术详情');
    // 进度条变失败态
    expect(w.find('.sp-track.is-bad').exists()).toBe(true);
  });

  it('"资产不会丢"只在已落盘 (savedOnServer) 时显示', () => {
    const notSaved = mountView({
      phase: 'failed', percent: 12, title: '上传失败', reason: '资产已存在',
    });
    expect(notSaved.find('.sp-fail-safe').exists()).toBe(false);

    const saved = mountView({
      phase: 'failed', percent: 81, title: '推送 GitLab 失败', reason: '网络中断',
      savedOnServer: true,
    });
    expect(saved.find('.sp-fail-safe').text()).toContain('已保存在服务端');
  });

  it('自动重试: 擦汗等待, 不显示失败卡片', () => {
    const w = mountView({
      phase: 'auto-retry', percent: 81,
      title: '遇到临时问题，正在自动重试',
      sub: '已试 1 次 · 4s 后继续',
    });
    expect(w.find('.sp-turtle.tired').exists()).toBe(true);
    expect(w.find('.sp-turtle.sit').exists()).toBe(false);
    expect(w.find('.sp-fail').exists()).toBe(false);
    expect(w.text()).toContain('4s 后继续');
  });

  it('上传请求失败也能复用失败态 (没有技术详情时不渲染折叠)', () => {
    const w = mountView({
      phase: 'failed', percent: 12, title: '上传失败',
      reason: '网络中断', detail: '',
    });
    expect(w.find('.sp-turtle.sit').exists()).toBe(true);
    expect(w.find('details.sp-detail').exists()).toBe(false);
  });
});
