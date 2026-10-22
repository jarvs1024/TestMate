/**
 * Markdown 渲染与消毒 —— **存储型 XSS 的最后一道防线**.
 *
 * 资产正文 (SKILL.md / README.md) 来自用户上传, 团队成员之间互传, 属于不可信输入.
 * 直接 v-html 渲染 = 任何人都能在市场里种一个 XSS.
 */
import { describe, expect, it } from 'vitest';
import { markdownToText, renderMarkdown } from '../markdown';

describe('renderMarkdown', () => {
  it('空输入返回空串', () => {
    expect(renderMarkdown('')).toBe('');
  });

  it('渲染基础 markdown', () => {
    const html = renderMarkdown('# 标题\n\n正文 **加粗**');
    expect(html).toContain('<h1');
    expect(html).toContain('标题');
    expect(html).toContain('<strong>加粗</strong>');
  });

  it('渲染列表与代码', () => {
    const html = renderMarkdown('- 一\n- 二\n\n`code`');
    expect(html).toContain('<li>一</li>');
    expect(html).toContain('<code>code</code>');
  });

  // ---------- XSS ----------

  it('剥离 script 标签', () => {
    const html = renderMarkdown('<script>alert(1)</script>');
    expect(html.toLowerCase()).not.toContain('<script');
    expect(html).not.toContain('alert(1)');
  });

  it('剥离 on* 事件属性', () => {
    const html = renderMarkdown('<img src=x onerror="alert(1)">');
    expect(html.toLowerCase()).not.toContain('onerror');
  });

  it('剥离 javascript: 链接', () => {
    const html = renderMarkdown('[点我](javascript:alert(1))');
    expect(html.toLowerCase()).not.toContain('javascript:');
  });

  it('剥离 iframe / object / embed / form', () => {
    const html = renderMarkdown(
      '<iframe src="http://evil"></iframe><object data="x"></object>' +
      '<embed src="y"><form><input name="z"></form>',
    );
    const low = html.toLowerCase();
    expect(low).not.toContain('<iframe');
    expect(low).not.toContain('<object');
    expect(low).not.toContain('<embed');
    expect(low).not.toContain('<form');
    expect(low).not.toContain('<input');
  });

  it('保留普通链接', () => {
    const html = renderMarkdown('[文档](https://example.com)');
    expect(html).toContain('href="https://example.com"');
  });

  it('代码块里的内容也不会变成可执行标签', () => {
    const html = renderMarkdown('```\n<script>alert(1)</script>\n```');
    expect(html.toLowerCase()).not.toContain('<script');
  });
});

describe('markdownToText', () => {
  it('空输入返回空串', () => {
    expect(markdownToText('')).toBe('');
  });

  it('去掉 frontmatter', () => {
    const txt = markdownToText('---\nname: x\ndescription: y\n---\n\n正文内容');
    expect(txt).not.toContain('name: x');
    expect(txt).toContain('正文内容');
  });

  it('去掉代码块与 markdown 符号', () => {
    const txt = markdownToText('# 标题\n\n`code`\n\n```\nblock\n```');
    expect(txt).not.toContain('#');
    expect(txt).not.toContain('```');
  });

  it('超长截断并加省略号', () => {
    const txt = markdownToText('a'.repeat(500), 50);
    expect(txt.length).toBeLessThanOrEqual(51);
    expect(txt.endsWith('…')).toBe(true);
  });
});
