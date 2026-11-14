/**
 * 设置页「知识库用户空间」管理块 —— 2026-11-14.
 *
 * ⚠️ 一把 RAGFlow API Key = 一个用户空间. 这里管的是"有哪些空间",
 *    知识库页只负责"切到哪个空间".
 *
 * ⚠️ Key 只显示前 4 位: 末 4 位也露出来的话, 截图/录屏时凭据的一半就泄了.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';

const mocks = vi.hoisted(() => ({
  createKbSpace: vi.fn(async () => ({ ok: true, space: { id: 'sp_new', name: '新空间', is_default: false, configured: true } })),
  updateKbSpace: vi.fn(async () => ({ ok: true, space: { id: 'sp_a', name: '空间A', is_default: true, configured: true } })),
  deleteKbSpace: vi.fn(async () => ({ ok: true })),
  testKbSpace: vi.fn(async () => ({ ok: true, status: 'ok', message: '连接正常' })),
}));

const { createKbSpace, updateKbSpace, deleteKbSpace, testKbSpace } = mocks;

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn() },
  ElMessageBox: { confirm: vi.fn(async () => 'confirm') },
}));

vi.mock('@/api/kb', () => ({
  listKbSpaces: vi.fn(async () => ({
    items: [
      { id: 'sp_a', name: '空间A', is_default: true, configured: true, key_masked: 'ragf••••1111' },
      { id: 'sp_b', name: '空间B', is_default: false, configured: true, key_masked: 'ragf••••2222' },
    ],
    default_id: 'sp_a',
  })),
  ...mocks,
}));

import KbSpaces from '../components/KbSpaces.vue';

async function mountKbs() {
  const w = mount(KbSpaces);
  await flushPromises();
  return w;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('设置页 用户空间管理', () => {
  it('列出空间, Key 只显示前 4 位', async () => {
    const w = await mountKbs();
    expect(w.text()).toContain('空间A');
    expect(w.text()).toContain('空间B');
    expect(w.text()).toContain('ragf');
    // ⚠️ 末 4 位不能出现 —— 半截凭据在截图里也能被利用
    expect(w.text()).not.toContain('1111');
    expect(w.text()).not.toContain('2222');
  });

  it('新建空间: 填名称和 Key 后提交', async () => {
    const w = await mountKbs();
    await w.find('[data-test="add-space"]').trigger('click');
    await w.find('[data-test="space-name"]').setValue('新空间');
    await w.find('[data-test="space-key"]').setValue('ragflow-new-3333');
    await w.find('[data-test="save-space"]').trigger('click');
    await flushPromises();

    expect(createKbSpace).toHaveBeenCalledTimes(1);
    const args = createKbSpace.mock.calls[0] as unknown as [{ name: string; api_key: string }];
    expect(args[0].name).toBe('新空间');
    expect(args[0].api_key).toBe('ragflow-new-3333');
  });

  it('编辑空间: Key 留空 = 只改名称, 不覆盖原 Key', async () => {
    const w = await mountKbs();
    const edit = w.findAll('[data-test="edit-space"]');
    await edit[0].trigger('click');
    await w.find('[data-test="space-name"]').setValue('空间A2');
    await w.find('[data-test="save-space"]').trigger('click');
    await flushPromises();

    expect(updateKbSpace).toHaveBeenCalledTimes(1);
    const [id, payload] = updateKbSpace.mock.calls[0] as unknown as [string, Record<string, unknown>];
    expect(id).toBe('sp_a');
    expect(payload.name).toBe('空间A2');
    expect('api_key' in payload).toBe(false);
  });

  it('⚠️ 默认空间不能删除', async () => {
    const w = await mountKbs();
    const del = w.findAll('[data-test="delete-space"]');
    expect(del[0].attributes('disabled')).toBeDefined();
    expect(del[1].attributes('disabled')).toBeUndefined();
  });

  it('删除非默认空间 → 二次确认后调删除接口', async () => {
    const w = await mountKbs();
    const del = w.findAll('[data-test="delete-space"]');
    await del[1].trigger('click');
    await flushPromises();
    expect(deleteKbSpace).toHaveBeenCalledWith('sp_b');
  });

  it('设为默认 → 调 update 且 is_default=true', async () => {
    const w = await mountKbs();
    const mk = w.findAll('[data-test="make-default"]');
    await mk[1].trigger('click');
    await flushPromises();

    const [id, payload] = updateKbSpace.mock.calls[0] as unknown as [string, Record<string, unknown>];
    expect(id).toBe('sp_b');
    expect(payload.is_default).toBe(true);
  });

  it('测试连接 → 显示结果', async () => {
    const w = await mountKbs();
    const test = w.findAll('[data-test="test-space"]');
    await test[0].trigger('click');
    await flushPromises();

    expect(testKbSpace).toHaveBeenCalledWith('sp_a');
    expect(w.text()).toContain('连接正常');
  });
});
