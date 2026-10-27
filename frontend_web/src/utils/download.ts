/**
 * 浏览器下载辅助.
 *
 * 安装方式只有一条: **下载安装包** —— 后端给 zip, 用户自己解压到
 * ~/.qoder-cn/skills/<code>/ (或 Qoder 的 plugin cache 目录).
 *
 * 之所以不能直接给一个 <a href>: 下载端点要带 Authorization 头
 * (要登录态), 浏览器直接开链接不会带 → 得先 fetch 成 blob 再触发保存.
 *
 * ⚠️ **blob 这条路只适合小文件** —— 软件库的包最大 5G, 读成 blob 会把浏览器
 *    内存打爆, 所以那边走 :func:`nativeDownload` (浏览器原生下载器, 流式落盘).
 */

/**
 * 触发浏览器下载一个 blob.
 *
 * @param blob     内容
 * @param filename 建议的文件名 (浏览器会用它)
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // 立刻 revoke 会让部分浏览器来不及开始下载, 延后释放
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

/**
 * 交给**浏览器原生下载器**下载一个 URL —— 内存恒定, 边下边写盘.
 *
 * ⚠️ 为什么单独抽一个函数:
 *   jsdom 里 ``window.location`` 是 unforgeable 的 —— 直接写 ``location.href``
 *   既会触发 "Not implemented: navigation", 单测里也 spy 不了.
 *   抽出来之后, 单测 mock 掉这个模块就能断言"到底有没有把 url 交给浏览器".
 *
 * @param url 带短时下载票的地址 (不要把长期 token 拼进 URL —— 会进访问日志)
 */
export function nativeDownload(url: string): void {
  window.location.href = url;
}
