/**
 * 设置项描述里的**内联强调**渲染.
 *
 * ⚠️ 为什么不用 utils/markdown.ts 的 renderMarkdown:
 *   那个是给**文档正文**(README / SKILL.md)用的 —— 完整 markdown 文档,
 *   有标题、列表、代码块. 设置项的 description 是一**段连续的自然语言**,
 *   只需要处理 `**粗体**` 这一种记号.
 *   走完整 markdown 会把一段话拆成 <p>, 段落间距全乱.
 *
 * ⚠️ 为什么不用 v-html 直接塞后端字符串:
 *   后端 description 是管理员写的, 但仍然要按**不可信**处理 ——
 *   里面混一个 <script> 就是 XSS. 所以:
 *     ① 先把 < > & " ' 全转义 (用户看到的就是原样的字面量)
 *     ② 再把转义后的 `**xxx**` 换成 <strong>xxx</strong>
 *   这样只有我们自己生成的 <strong> 是标签, 别的都只是文字.
 */

/** HTML 转义 —— 必须先转义再插标签, 顺序反了就等于没转义 */
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * 把描述里的 `**粗体**` 渲染成 <strong>.
 *
 * ⚠️ 只处理成对的 `**` —— 没配对的不动 (免得把正常的 `2**3` 也吃掉).
 * ⚠️ 换行保留成 <br> —— description 里有的是多句带换行的说明.
 */
export function renderInlineEmphasis(src: string): string {
  if (!src) return '';
  let html = escapeHtml(src);
  // 成对的 **…** → <strong>…</strong>
  html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  // 换行 → <br>
  html = html.replace(/\n/g, '<br>');
  return html;
}
