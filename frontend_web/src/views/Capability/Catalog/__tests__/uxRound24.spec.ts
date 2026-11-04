/**
 * **第二十四轮验收** (2026-11-04).
 *
 * 用户报的两件事:
 *   ① 固定下载链接里带版本号 (`aitestx-v2.1`) —— 用户担心它会变
 *      → 后端加了「下载别名」(与版本无关), URL 改成 /software/alias/{alias}/download;
 *   ② 「复制地址 / 复制命令」在生产上一律提示"复制失败 —— 请手动选中复制"
 *      → 根因: 内网 IP + HTTP 不是**安全上下文**, `navigator.clipboard` 是 undefined.
 *
 * 这个文件锁的是**结构/文案**层面的东西; 后端行为在
 * backend_gateway/tests/test_round24_alias_download.py 里.
 */
import { describe, expect, it, vi, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { copyToClipboard } from '@/utils/clipboard';

const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');

const swDetail = read('src/views/Software/SoftwareDetailDrawer.vue');
const clipboardUtil = read('src/utils/clipboard.ts');
const assetDetail = read('src/views/Capability/Catalog/AssetDetailDrawer.vue');
const mcpTokens = read('src/views/Settings/components/McpTokens.vue');

// ═══════════════ ② 剪贴板降级 ═══════════════

describe('② 剪贴板在非安全上下文下也能复制 (2026-11-04)', () => {
  const origClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');

  afterEach(() => {
    if (origClipboard) Object.defineProperty(navigator, 'clipboard', origClipboard);
    else delete (navigator as any).clipboard;
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  it('剪贴板 API 存在 → 走标准 API', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText }, configurable: true,
    });
    const ok = await copyToClipboard('hello');
    expect(ok).toBe(true);
    expect(writeText).toHaveBeenCalledWith('hello');
  });

  it('⚠️ 非安全上下文 (clipboard 是 undefined) → 降级到 execCommand, 不再失败', async () => {
    // ⚠️ 这就是现网的情形: http://10.20.65.25:8090 → navigator.clipboard 是 undefined
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined, configurable: true,
    });
    const exec = vi.fn().mockReturnValue(true);
    (document as any).execCommand = exec;

    const ok = await copyToClipboard('fallback-text');
    expect(ok).toBe(true);
    expect(exec).toHaveBeenCalledWith('copy');
    // 降级时用的是**离屏 textarea** —— 选中了才有东西可复制
    expect(exec).toHaveBeenCalled();
  });

  it('剪贴板 API 抛错 → 也降级 (权限被拒的情况)', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
      configurable: true,
    });
    const exec = vi.fn().mockReturnValue(true);
    (document as any).execCommand = exec;

    const ok = await copyToClipboard('denied-text');
    expect(ok).toBe(true);
    expect(exec).toHaveBeenCalledWith('copy');
  });

  it('两条路都失败 → 返回 false (调用方据此提示手动复制)', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined, configurable: true,
    });
    (document as any).execCommand = vi.fn().mockReturnValue(false);
    const ok = await copyToClipboard('nope');
    expect(ok).toBe(false);
  });

  it('空字符串 → 直接 false (不折腾剪贴板)', async () => {
    expect(await copyToClipboard('')).toBe(false);
  });

  it('降级用的 textarea 必须**移出屏幕但不能 display:none** —— 否则选不中', () => {
    // ⚠️ display:none 的元素没法被 select() 选中 → execCommand 会静默失败
    expect(clipboardUtil).toMatch(/ta\.style\.position\s*=\s*'fixed'/);
    expect(clipboardUtil).not.toMatch(/ta\.style\.display\s*=\s*'none'/);
    expect(clipboardUtil).toMatch(/ta\.setSelectionRange/);
  });

  it('三处复制按钮都用统一的工具, 不再直接调 navigator.clipboard', () => {
    // ⚠️ 直接调 navigator.clipboard.writeText 在内网 HTTP 下**必然**抛 TypeError
    // ⚠️ 只查**代码行** —— 注释里提到这个 API 是正常的 (那是在解释为什么改)
    for (const [name, src] of [
      ['软件详情', swDetail],
      ['扩展详情 (复制 MCP JSON)', assetDetail],
      ['设置页 (复制令牌)', mcpTokens],
    ] as [string, string][]) {
      const codeLines = src
        .split('\n')
        .filter((l) => !l.trim().startsWith('*') && !l.trim().startsWith('//'));
      const stillCalls = codeLines.filter((l) => /navigator\.clipboard\.writeText/.test(l));
      expect(stillCalls, `${name} 还在直接调 navigator.clipboard`).toEqual([]);
      expect(src, `${name} 没用统一工具`).toMatch(/copyToClipboard/);
    }
  });
});

// ═══════════════ ① 固定链接用别名 ═══════════════

describe('① 固定下载链接用「下载别名」—— URL 里没有版本号 (2026-11-04)', () => {
  it('固定链接区块的说明是**精简**的, 不再堆一大段', () => {
    // ⚠️ 2026-11-04: 用户要求精简 —— 原来三段说明 (含"免登录"提示) 太啰嗦,
    //    现在只留一句"地址不会变 + 永远给推荐版本".
    const sec = swDetail.slice(
      swDetail.indexOf('固定下载链接'),
      swDetail.indexOf('<!-- ===== 标签 / 元信息 ====='),
    );
    const tips = (sec.match(/class="fx-tip/g) || []).length;
    expect(tips, '说明段落太多').toBeLessThanOrEqual(1);
    expect(sec).toMatch(/不会变/);
    expect(sec).toMatch(/推荐/);
  });

  it('⚠️ 不再显示「免登录」的提示', () => {
    const sec = swDetail.slice(
      swDetail.indexOf('固定下载链接'),
      swDetail.indexOf('<!-- ===== 标签 / 元信息 ====='),
    );
    expect(sec).not.toMatch(/免登录/);
  });

  it('固定链接区块还在 (没被这次改动删掉)', () => {
    expect(swDetail).toMatch(/固定下载链接/);
    expect(swDetail).toMatch(/copyFixed\(fixedUrl\)/);
    expect(swDetail).toMatch(/copyFixed\(fixedWgetCmd\)/);
  });

  it('API 类型里有 download_alias', () => {
    const api = read('src/api/software.ts');
    expect(api).toMatch(/download_alias\?:\s*string/);
  });
});
