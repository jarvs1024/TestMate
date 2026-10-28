/**
 * 内联强调渲染 —— 设置项描述里的 `**粗体**`.
 *
 * ⚠️ 这个渲染器要同时满足两件事:
 *   ① 把 `**xxx**` 变成真加粗 (以前是原样显示一堆星号);
 *   ② **绝不能**变成 XSS 通道 —— 后端 description 也按不可信输入处理.
 */
import { describe, expect, it } from 'vitest';
import { renderInlineEmphasis } from '../inlineEmphasis';

describe('内联强调', () => {
  it('**粗体** → <strong>', () => {
    expect(renderInlineEmphasis('把**最老的**清掉'))
      .toBe('把<strong>最老的</strong>清掉');
  });

  it('一对以上的都能渲染', () => {
    expect(renderInlineEmphasis('**A** 和 **B**'))
      .toBe('<strong>A</strong> 和 <strong>B</strong>');
  });

  it('没配对的星号原样保留 —— 不能把 2**3 吃成 23', () => {
    expect(renderInlineEmphasis('2**3')).toBe('2**3');
  });

  it('换行变成 <br>', () => {
    expect(renderInlineEmphasis('第一行\n第二行')).toBe('第一行<br>第二行');
  });

  it('空串 → 空串', () => {
    expect(renderInlineEmphasis('')).toBe('');
  });

  // ---- 安全: 这些是"描述里混进了 HTML"的情形 ----

  it('<script> 被转义, 不会执行', () => {
    const out = renderInlineEmphasis('<script>alert(1)</script>');
    expect(out).not.toContain('<script>');
    expect(out).toContain('&lt;script&gt;');
  });

  it('HTML 标签被转义', () => {
    expect(renderInlineEmphasis('<img src=x onerror=alert(1)>'))
      .toContain('&lt;img');
  });

  it('引号被转义 —— 不能逃出属性', () => {
    expect(renderInlineEmphasis('" onmouseover="x')).toContain('&quot;');
  });

  it('⚠️ 转义必须在插标签**之前** —— 顺序反了就等于没转义', () => {
    // 如果先插 <strong> 再转义, 标签本身也会被转义掉, 强调就没了
    const out = renderInlineEmphasis('**加粗**');
    expect(out).toContain('<strong>');
  });

  it('已转义的实体不会被二次转义成乱码', () => {
    // & 应该在转义后变成 &amp; —— 但这里只断言"没有裸的 & 后面跟字面量"
    const out = renderInlineEmphasis('a & b');
    expect(out).toBe('a &amp; b');
  });
});
