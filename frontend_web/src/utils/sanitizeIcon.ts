/**
 * icon HTML 清洗:
 * - 只放行白名单标签: svg, path, rect, circle, line, polyline, polygon, g, defs, use
 * - 剥除所有 on* 事件属性 (onclick= / onerror= / onload= ...)
 * - 剥除所有 javascript:/data:text/html URL
 * - 剥除 <script> 标签
 *
 * 用途: AppSidebar / 任何后端返回的 icon 字段在 v-html 渲染前过这一层.
 */

const ALLOWED_TAGS = new Set([
  'svg',
  'path',
  'rect',
  'circle',
  'line',
  'polyline',
  'polygon',
  'g',
  'defs',
  'use',
])

const ALLOWED_ATTRS = new Set([
  'width', 'height', 'viewBox', 'fill', 'stroke', 'stroke-width',
  'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray', 'stroke-opacity',
  'fill-opacity', 'opacity', 'x', 'y', 'cx', 'cy', 'r', 'rx', 'ry',
  'x1', 'y1', 'x2', 'y2', 'points', 'd', 'transform',
  'href', 'xlink:href',
])

export function sanitizeIcon(html: string): string {
  if (!html) return ''
  // 用浏览器 DOMParser 解析, 比正则更可靠
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html')
  const root = doc.body.firstElementChild
  if (!root) return ''
  walk(root)
  return root.outerHTML
}

function walk(el: Element) {
  // 剥掉 <script> / <style> 等禁止标签
  const tag = el.tagName.toLowerCase()
  if (!ALLOWED_TAGS.has(tag)) {
    // 未知标签: 把它的子节点提到父级, 然后删自己
    const parent = el.parentNode
    if (parent) {
      while (el.firstChild) parent.insertBefore(el.firstChild, el)
      parent.removeChild(el)
    }
    return
  }
  // 清洗属性
  for (const attr of Array.from(el.attributes)) {
    const name = attr.name.toLowerCase()
    const value = attr.value
    // 1) on* 事件直接剥
    if (name.startsWith('on')) {
      el.removeAttribute(attr.name)
      continue
    }
    // 2) href/src 一律要求非 javascript: / data:text/html
    if (name === 'href' || name === 'src' || name === 'xlink:href') {
      const lower = value.trim().toLowerCase()
      if (lower.startsWith('javascript:') || lower.startsWith('data:text/html')) {
        el.removeAttribute(attr.name)
        continue
      }
    }
    // 3) 白名单
    if (!ALLOWED_ATTRS.has(name)) {
      el.removeAttribute(attr.name)
    }
  }
  // 递归
  for (const child of Array.from(el.children)) walk(child)
}
