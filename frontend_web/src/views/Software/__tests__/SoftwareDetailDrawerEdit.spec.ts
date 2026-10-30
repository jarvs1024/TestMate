/**
 * 软件详情抽屉 —— **「编辑」按钮的显隐** (2026-10-30 · 第十一轮 · 问题5).
 *
 * 用户报的问题: "软件详情页新增编辑功能（上传者和管理员才显示编辑）,
 *              可以编辑软件的基本信息".
 *
 * ⚠️ 为什么这条要**真渲染**而不是源码断言:
 *   按钮显隐是 `v-if` + prop 传递的组合 —— 源码看着对, 传错了 prop 一样不出按钮.
 *   源码断言挡不住"父组件没传 canEdit"这种错.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';

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
import type { SoftwareDetail } from '@/api/software';

function detail(over: Partial<SoftwareDetail> = {}): SoftwareDetail {
  return {
    code: 'demo-sw', name: '演示软件', icon: '🧰', version: '1.0.0',
    summary: '摘要', description: '', features: [], use_when: '', not_for: '',
    install_steps: '', caveats: '',
    platform: 'linux', category: '工具', tags: [], keywords: [], author: 'admin',
    download_count: 0, publish_status: 'published',
    created_at: '2026-10-28 10:00:00', updated_at: '2026-10-28 10:00:00',
    can_edit: true, download_version: '1.0.0',
    versions: [],
    ...over,
  };
}

/** 挂载抽屉并等它把详情读回来 */
async function mountDrawer(d: SoftwareDetail, canEdit?: boolean) {
  getSoftware.mockResolvedValueOnce(d);
  // ⚠️ 先挂成"关闭", 再打开 —— 抽屉靠 watch(modelValue) 触发读取
  const w = mount(SoftwareDetailDrawer, {
    props: {
      modelValue: false,
      code: d.code,
      ...(canEdit === undefined ? {} : { canEdit }),
    },
    global: { stubs: { 'el-drawer': { template: '<div><slot /></div>' } } },
  });
  await w.setProps({ modelValue: true });
  await flushPromises();
  await flushPromises();
  return w;
}

/** 头部动作区里的按钮文本 */
function actionTexts(w: any): string[] {
  return w.findAll('.sw-hd-actions button').map((b: any) => b.text());
}

describe('软件详情页的「编辑」按钮', () => {
  beforeEach(() => {
    getSoftware.mockReset();
  });

  it('canEdit = true → 显示「编辑」按钮', async () => {
    const w = await mountDrawer(detail(), true);
    expect(actionTexts(w).join(' ')).toContain('编辑');
  });

  it('canEdit = false → 不显示「编辑」按钮', async () => {
    const w = await mountDrawer(detail(), false);
    expect(actionTexts(w).join(' ')).not.toContain('编辑');
  });

  it('没传 canEdit → 不显示 (保守默认 —— 拿不准就不给)', async () => {
    const w = await mountDrawer(detail());
    expect(actionTexts(w).join(' ')).not.toContain('编辑');
  });

  it('「编辑」和「发布新版本」是两个按钮 —— 改说明不用传安装包', async () => {
    const w = await mountDrawer(detail(), true);
    const texts = actionTexts(w).join(' ');
    expect(texts).toContain('编辑');
    expect(texts).toContain('发布新版本');
  });

  it('点「编辑」→ 抛出 edit 事件 (父组件去开编辑抽屉)', async () => {
    const w = await mountDrawer(detail(), true);
    const btn = w.findAll('.sw-hd-actions button').find((b: any) => b.text().includes('编辑'));
    expect(btn).toBeTruthy();
    await btn!.trigger('click');
    expect(w.emitted('edit')).toBeTruthy();
    expect((w.emitted('edit') as any[])[0][0].code).toBe('demo-sw');
  });
});
