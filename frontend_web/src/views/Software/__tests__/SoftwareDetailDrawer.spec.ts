/**
 * 软件详情抽屉 —— **选填信息栏** 与 **多版本并存** 的呈现.
 *
 * ⚠️ 这几条盯的是 2026-10-28 加的两件事:
 *   ① 安装说明 / 注意事项 —— **选填**, 有则显示、无则不占位;
 *   ② 一个软件挂两个版本、两个都有用 —— 版本列表要能区分谁是谁,
 *      并且说清「推荐下载哪个」.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';

// ⚠️ vi.mock 的工厂函数会被**提升**到文件顶部 —— 直接用模块级的 const 会
//    "Cannot access 'getSoftware' before initialization". 必须用 vi.hoisted.
const { getSoftware, deleteSoftwareVersion, elMessage, elMessageBox } = vi.hoisted(() => ({
  getSoftware: vi.fn(),
  deleteSoftwareVersion: vi.fn(),
  elMessage: { success: vi.fn(), error: vi.fn() },
  elMessageBox: { confirm: vi.fn(async () => true) },
}));

vi.mock('@/api/software', () => ({
  getSoftware: (...a: any[]) => getSoftware(...a),
  downloadSoftware: vi.fn(async () => {}),
  purgeSoftware: vi.fn(async () => ({ ok: true, deleted_files: 1 })),
  updateSoftwareVersion: vi.fn(async () => ({})),
  deleteSoftwareVersion: (...a: any[]) => deleteSoftwareVersion(...a),
}));

vi.mock('element-plus', () => ({
  ElMessage: elMessage,
  ElMessageBox: elMessageBox,
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

/**
 * 「下架这版」成功却报错的 bug (2026-10-28 用户报的).
 *
 * ⚠️ 现场: 删掉**最后一个**版本 → 后端会把条目一并下架 (软删) →
 *    前端下架成功后**又去查详情** → 必然 404 → 弹一条红字
 *    「软件 xxx 不存在」. 明明成功, 看着像坏了.
 */
describe('下架版本 (成功不该报错)', () => {
  /** 抽屉里点「下架这版」 */
  async function clickUnpublishVersion(w: any) {
    const btn = w.findAll('.ver-row .vr-hd .mini-btn')
      .find((b: any) => b.text().includes('下架这版'));
    expect(btn).toBeTruthy();
    await btn.trigger('click');
    await flushPromises();
    await flushPromises();
  }

  beforeEach(() => {
    elMessage.success.mockClear();
    elMessage.error.mockClear();
    elMessageBox.confirm.mockClear();
  });

  it('删掉最后一个版本 → 条目被连带下架 → 关抽屉 + 说明, 不报红错', async () => {
    deleteSoftwareVersion.mockResolvedValueOnce({
      ok: true, deleted_files: 1, item_unpublished: true, remaining_versions: 0,
    });
    const w = await mountDrawer(detail({ versions: [version()] }));
    await clickUnpublishVersion(w);

    expect(elMessage.error).not.toHaveBeenCalled();
    expect(elMessage.success).toHaveBeenCalled();
    // 提示里要说清"软件也一并下架了" —— 否则用户以为只撤了一个版本
    expect(elMessage.success.mock.calls[0][0]).toContain('一并下架');
    // 抽屉请求关闭
    expect(w.emitted('update:modelValue')?.some((e: any) => e[0] === false)).toBe(true);
  });

  it('还有别的版本 → 正常刷新详情, 抽屉不关, 不报错', async () => {
    deleteSoftwareVersion.mockResolvedValueOnce({
      ok: true, deleted_files: 1, item_unpublished: false, remaining_versions: 1,
    });
    const d = detail({
      versions: [version({ id: 2, version: '2.0.0' }), version({ id: 1 })],
    });
    // 后面 refresh 时的 load() 也要有数据
    getSoftware.mockResolvedValue(d);
    const w = await mountDrawer(d);
    await clickUnpublishVersion(w);

    expect(elMessage.error).not.toHaveBeenCalled();
    // 抽屉不该被关掉 (条目还在) —— 没发过 update:modelValue 就是没关
    expect(w.emitted('update:modelValue')).toBeFalsy();
  });

  it('详情读回来是 404 (条目已经不在了) → 静默关抽屉, 不弹红错', async () => {
    getSoftware.mockRejectedValue({
      response: { status: 404, data: { detail: '软件 xxx 不存在' } },
    });
    const w = mount(SoftwareDetailDrawer, {
      props: { modelValue: false, code: 'gone-sw' },
      global: { stubs: { 'el-drawer': { template: '<div><slot /></div>' } } },
    });
    await w.setProps({ modelValue: true });
    await flushPromises();
    await flushPromises();

    expect(elMessage.error).not.toHaveBeenCalled();
    expect(w.emitted('update:modelValue')?.some((e: any) => e[0] === false)).toBe(true);
  });
});
