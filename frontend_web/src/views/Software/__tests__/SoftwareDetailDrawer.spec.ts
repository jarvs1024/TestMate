/**
 * 软件详情抽屉 —— **选填信息栏** 与 **多版本并存** 的呈现.
 *
 * ⚠️ 这几条盯的是 2026-10-28 加的两件事:
 *   ① 安装说明 / 注意事项 —— **选填**, 有则显示、无则不占位;
 *   ② 一个软件挂两个版本、两个都有用 —— 版本列表要能区分谁是谁,
 *      并且说清「推荐下载哪个」.
 */
import { describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';

// ⚠️ vi.mock 的工厂函数会被**提升**到文件顶部 —— 直接用模块级的 const 会
//    "Cannot access 'getSoftware' before initialization". 必须用 vi.hoisted.
const { getSoftware } = vi.hoisted(() => ({ getSoftware: vi.fn() }));

vi.mock('@/api/software', () => ({
  getSoftware: (...a: any[]) => getSoftware(...a),
  downloadSoftware: vi.fn(async () => {}),
  purgeSoftware: vi.fn(async () => ({ ok: true, deleted_files: 1 })),
  updateSoftwareVersion: vi.fn(async () => ({})),
  deleteSoftwareVersion: vi.fn(async () => ({ ok: true, deleted_files: 1 })),
}));

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn() },
  ElMessageBox: { confirm: vi.fn(async () => true) },
}));

import SoftwareDetailDrawer from '../SoftwareDetailDrawer.vue';
import type { SoftwareDetail, SoftwareVersion } from '@/api/software';

function version(over: Partial<SoftwareVersion> = {}): SoftwareVersion {
  return {
    id: 1, version: '1.0.0', release_notes: '', variant: '', is_default: false,
    file_name: 'a.bin', file_size: 100, sha256: 'x', status: 'ready',
    last_error: '', author: 'admin', download_count: 0, created_at: '2026-10-28 10:00:00',
    ...over,
  };
}

function detail(over: Partial<SoftwareDetail> = {}): SoftwareDetail {
  return {
    code: 'demo-sw', name: '演示软件', icon: '🧰', version: '1.0.0',
    summary: '摘要', description: '', features: [], use_when: '', not_for: '',
    install_steps: '', caveats: '',
    platform: 'linux', category: '工具', tags: [], keywords: [], author: 'admin',
    download_count: 0, publish_status: 'published',
    created_at: '2026-10-28 10:00:00', updated_at: '2026-10-28 10:00:00',
    can_edit: true, download_version: '1.0.0',
    versions: [version()],
    ...over,
  };
}

/** 挂载抽屉并等它把详情读回来 */
async function mountDrawer(d: SoftwareDetail) {
  getSoftware.mockResolvedValueOnce(d);
  // ⚠️ 先挂成"关闭", 再打开 —— 抽屉靠 watch(modelValue) 触发读取,
  //    一上来就是 true 的话 watch 不会 fire (没变化), 详情永远是空的.
  const w = mount(SoftwareDetailDrawer, {
    props: { modelValue: false, code: d.code },
    global: { stubs: { 'el-drawer': { template: '<div><slot /></div>' } } },
  });
  await w.setProps({ modelValue: true });
  await flushPromises();
  await flushPromises();
  return w;
}

describe('安装说明 / 注意事项 (选填)', () => {
  it('填了安装说明 → 渲染成有序列表', async () => {
    const w = await mountDrawer(detail({
      install_steps: '解压到 /opt/tool\n运行 install.sh',
    }));
    const items = w.findAll('.step-list li');
    expect(items.length).toBe(2);
    expect(items[0].text()).toBe('解压到 /opt/tool');
    expect(items[1].text()).toBe('运行 install.sh');
  });

  it('没填安装说明 → 这一栏整个不渲染 (不占位)', async () => {
    const w = await mountDrawer(detail({ install_steps: '' }));
    expect(w.find('.step-list').exists()).toBe(false);
  });

  it('填了注意事项 → 用醒目提示块显示', async () => {
    const w = await mountDrawer(detail({ caveats: '需要管理员权限' }));
    expect(w.find('.caveat-box').exists()).toBe(true);
    expect(w.find('.caveat-box').text()).toContain('需要管理员权限');
  });

  it('没填注意事项 → 不渲染提示块', async () => {
    const w = await mountDrawer(detail({ caveats: '' }));
    expect(w.find('.caveat-box').exists()).toBe(false);
  });
});

describe('多版本并存', () => {
  it('版本行显示变体标签 —— 两个版本靠它区分', async () => {
    const w = await mountDrawer(detail({
      versions: [
        version({ id: 2, version: '2.0.0', variant: 'Windows 版', is_default: true }),
        version({ id: 1, version: '1.0.0', variant: 'LTS 版' }),
      ],
      download_version: '2.0.0',
    }));
    const variants = w.findAll('.vr-variant').map((v) => v.text());
    expect(variants).toContain('Windows 版');
    expect(variants).toContain('LTS 版');
  });

  it('没变体标签 → 不显示标签 (不是每个版本都要起名)', async () => {
    const w = await mountDrawer(detail({ versions: [version()] }));
    expect(w.find('.vr-variant').exists()).toBe(false);
  });

  it('推荐版本有标记 —— 只有一个', async () => {
    const w = await mountDrawer(detail({
      versions: [
        version({ id: 2, version: '2.0.0', variant: 'Windows 版', is_default: true }),
        version({ id: 1, version: '1.0.0', variant: 'LTS 版' }),
      ],
      download_version: '2.0.0',
    }));
    expect(w.findAll('.vr-default').length).toBe(1);
  });

  it('下载按钮显示推荐版本 —— 版本号 + 变体标签', async () => {
    const w = await mountDrawer(detail({
      versions: [
        version({ id: 2, version: '2.0.0', variant: 'Windows 版', is_default: true }),
        version({ id: 1, version: '1.0.0', variant: 'LTS 版' }),
      ],
      download_version: '2.0.0',
    }));
    const btn = w.find('.sw-hd-actions .mini-btn.primary');
    expect(btn.text()).toContain('2.0.0');
    expect(btn.text()).toContain('Windows 版');
  });

  it('多个版本时, 标题区说清推荐下载哪个', async () => {
    const w = await mountDrawer(detail({
      versions: [
        version({ id: 2, version: '2.0.0', is_default: true }),
        version({ id: 1, version: '1.0.0' }),
      ],
      download_version: '2.0.0',
    }));
    expect(w.text()).toContain('共 2 个版本');
    expect(w.text()).toContain('推荐下载');
  });

  it('只有一个版本 → 不显示"共 N 个版本" (多余的话)', async () => {
    const w = await mountDrawer(detail({ versions: [version()] }));
    expect(w.text()).not.toContain('共 1 个版本');
  });

  it('非推荐版本有「设为推荐」按钮, 推荐版本没有', async () => {
    const w = await mountDrawer(detail({
      versions: [
        version({ id: 2, version: '2.0.0', is_default: true }),
        version({ id: 1, version: '1.0.0' }),
      ],
      download_version: '2.0.0',
    }));
    const labels = w.findAll('.ver-row .vr-hd .mini-btn').map((b) => b.text());
    expect(labels.filter((t) => t.includes('设为推荐')).length).toBe(1);
  });

  it('有编辑权时每个版本都能单独下架', async () => {
    const w = await mountDrawer(detail({
      can_edit: true,
      versions: [version({ id: 2 }), version({ id: 1, version: '0.9.0' })],
    }));
    const labels = w.findAll('.ver-row .vr-hd .mini-btn').map((b) => b.text());
    expect(labels.filter((t) => t.includes('下架这版')).length).toBe(2);
  });

  it('没有编辑权 → 不显示下架单版本的按钮', async () => {
    const w = await mountDrawer(detail({ can_edit: false }));
    const labels = w.findAll('.ver-row .vr-hd .mini-btn').map((b) => b.text());
    expect(labels.some((t) => t.includes('下架这版'))).toBe(false);
  });
});
