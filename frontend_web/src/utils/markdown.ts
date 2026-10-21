/**
 * Markdown 渲染 — **必须消毒**.
 *
 * 资产正文 (SKILL.md / README.md) 来自用户上传, 是不可信输入.
 * 团队成员互传资产时, 直接 v-html 渲染就是**存储型 XSS**.
 * 所以: marked 解析 → DOMPurify 消毒 → 才允许进 v-html.
 *
 * 项目里唯一已有的 v-html 是 sanitizeIcon.ts 消毒过的 SVG;
 * 这条路径同样不能绕过消毒.
 */
import { marked } from 'marked';
import DOMPurify from 'dompurify';

marked.setOptions({
  gfm: true,
  breaks: true,
});

/** 渲染成**已消毒**的 HTML, 可安全用于 v-html */
export function renderMarkdown(src: string): string {
  if (!src) return '';
  const raw = marked.parse(src, { async: false }) as string;
  return DOMPurify.sanitize(raw, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'form', 'input', 'button', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['style', 'srcset'],
  });
}

/** 纯文本预览 (摘要场景, 不需要 HTML) */
export function markdownToText(src: string, maxLen = 200): string {
  if (!src) return '';
  const txt = src
    .replace(/^---[\s\S]*?---/, '')          // 去 frontmatter
    .replace(/```[\s\S]*?```/g, ' ')          // 去代码块
    .replace(/[#>*_`~\-[\]()!]/g, ' ')        // 去常见 markdown 符号
    .replace(/\s+/g, ' ')
    .trim();
  return txt.length > maxLen ? txt.slice(0, maxLen) + '…' : txt;
}
