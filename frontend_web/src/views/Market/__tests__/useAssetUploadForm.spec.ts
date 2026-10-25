/**
 * 上传表单 composable —— 抽出来就是为了让这些逻辑**可单测**.
 *
 * 以前它们埋在组件里, 靠 watch 串起来 —— 只能靠 e2e 兜, 于是出过
 * "发布新版本时图标被悄悄改掉"「新资产不再自动分配图标」这类问题.
 */
import { describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';
import { useAssetUploadForm } from '../useAssetUploadForm';

vi.mock('@/api/assets', () => ({
  listAssets: vi.fn(async () => ({ items: [] })),
  listCategories: vi.fn(async () => ({ items: [] })),
  listProjects: vi.fn(async () => ({
    items: [
      { code: 'general', name: '通用', total: 0, is_general: true },
      { code: '6100', name: '6100', total: 0 },
    ],
  })),
  previewPackage: vi.fn(async () => ({})),
}));

function makeForm(over: Partial<Parameters<typeof useAssetUploadForm>[0]> = {}) {
  const opts = {
    mode: () => 'create' as const,
    asset: () => null,
    initialKind: () => '' as const,
    open: () => true,
    ...over,
  };
  const f = useAssetUploadForm(opts as any);
  f.reset();
  return f;
}

describe('上传表单: 初始化', () => {
  it('新建: 没指定形态时停在第 ① 步 (让人选, 不默认「技能」)', () => {
    const f = makeForm();
    expect(f.step.value).toBe('pick');
    expect(f.form.code).toBe('dml-');
    expect(f.form.project).toBe('');       // 默认通用
  });

  it('新建: 入口指定了形态 → 直接进表单', () => {
    const f = makeForm({ initialKind: () => 'mcp' as const });
    expect(f.step.value).toBe('form');
    expect(f.form.kind).toBe('mcp');
    expect(f.isMcp.value).toBe(true);
  });

  it('更新: 带出原值 (含适用范围)', () => {
    const asset: any = {
      code: 'dml-x', kind: 'skill', name: '老资产', version: '2.0.0',
      summary: '摘要', description: '说明', use_when: '何时', not_for: '',
      category: '质量诊断', icon: '🔍', project: '6100', featured: false,
      tags: ['a'], keywords: ['b'], install_steps: [], permissions: {},
    };
    const f = makeForm({ mode: () => 'update' as const, asset: () => asset });
    expect(f.step.value).toBe('form');
    expect(f.form.code).toBe('dml-x');
    expect(f.form.project).toBe('6100');
    expect(f.form.use_when).toBe('何时');
  });
});

describe('上传表单: 缺项清单', () => {
  it('什么都没填时把必填项都列出来', () => {
    const f = makeForm({ initialKind: () => 'skill' as const });
    const m = f.missing.value;
    expect(m).toContain('安装包');
    expect(m).toContain('名称');
    expect(m).toContain('一句话简介');
    expect(m).toContain('分类');
    expect(f.canSubmit.value).toBe(false);
  });

  it('连接器形态: 要配置不要包', () => {
    const f = makeForm({ initialKind: () => 'mcp' as const });
    expect(f.missing.value).not.toContain('安装包');
    expect(f.missing.value).toContain('MCP 配置');
  });
});

describe('上传表单: code 与包名/连接器名一致', () => {
  it('包名与 code 不一致 → 报错 + 不让上架', () => {
    const f = makeForm({ initialKind: () => 'skill' as const });
    f.form.code = 'dml-other';
    f.pkgFile.value = new File(['x'], 'dml-weekly-report.zip');
    expect(f.codeSyncError.value).toContain('安装包名');
    expect(f.missing.value).toContain('code 与名称一致');
    expect(f.canSubmit.value).toBe(false);
  });

  it('包名与 code 一致 → 不报错', () => {
    const f = makeForm({ initialKind: () => 'skill' as const });
    f.form.code = 'dml-weekly-report';
    f.pkgFile.value = new File(['x'], 'dml-weekly-report.zip');
    expect(f.codeSyncError.value).toBe('');
  });

  it('更新连接器时跳过一致性 (code 不可改, 改了也改不动)', () => {
    const asset: any = { code: 'dml-x', kind: 'mcp', name: 'x', version: '1.0.0',
      summary: 's', description: '', use_when: '', not_for: '', category: '其他',
      icon: '🔌', project: '', featured: false, tags: [], keywords: [],
      install_steps: [], permissions: {}, mcp_config: { mcpServers: { 'dml-other': {} } } };
    const f = makeForm({ mode: () => 'update' as const, asset: () => asset });
    expect(f.codeSyncError.value).toBe('');
  });
});

describe('上传表单: 图标', () => {
  it('面板里不含已被别的资产用掉的图标', () => {
    const f = makeForm({ initialKind: () => 'skill' as const });
    f.usedIcons.value = new Set(['🔍', '🩺']);
    expect(f.iconChoices.value).not.toContain('🔍');
    expect(f.iconChoices.value).not.toContain('🩺');
    expect(f.iconChoices.value.length).toBeGreaterThan(20);
  });

  it('更新版本时**不**自动分配图标 (别把别人的图标改掉)', () => {
    const asset: any = { code: 'dml-x', kind: 'skill', name: 'x', version: '1.0.0',
      summary: 's', description: '', use_when: '', not_for: '', category: '其他',
      icon: '🔍', project: '', featured: false, tags: [], keywords: [],
      install_steps: [], permissions: {} };
    const f = makeForm({ mode: () => 'update' as const, asset: () => asset });
    f.form.name = '改个名';
    expect(f.form.icon).toBe('🔍');
  });
});

describe('上传表单: 切换形态', () => {
  it('技能 → 连接器: 清掉安装包', () => {
    const f = makeForm({ initialKind: () => 'skill' as const });
    f.pkgFile.value = new File(['x'], 'dml-weekly-report.zip');
    f.chooseKind('mcp');
    expect(f.pkgFile.value).toBe(null);
    expect(f.isMcp.value).toBe(true);
  });

  it('连接器 → 技能: 清掉 MCP 配置, code 重新跟包名同步', async () => {
    const f = makeForm({ initialKind: () => 'mcp' as const });
    f.mcpConfigText.value = '{"mcpServers": {"dml-conn": {"url": "http://h/mcp"}}}';
    await nextTick();          // code 的同步是 watch 做的 —— 等一拍
    expect(f.form.code).toBe('dml-conn');
    f.chooseKind('skill');
    expect(f.mcpConfigText.value).toBe('');
    // code 不可编辑 —— 切回技能后由**包名**重新派生 (同步在 watch 里, 等一拍)
    f.pkgFile.value = new File(['x'], 'dml-from-package.zip');
    await nextTick();
    expect(f.form.code).toBe('dml-from-package');
  });
});
