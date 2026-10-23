/**
 * 浏览器下载辅助.
 *
 * 安装方式只有一条: **下载安装包** —— 后端给 zip, 用户自己解压到
 * ~/.qoder-cn/skills/<code>/ (或 Qoder 的 plugin cache 目录).
 *
 * 之所以不能直接给一个 <a href>: 下载端点要带 Authorization 头
 * (要登录态), 浏览器直接开链接不会带 → 得先 fetch 成 blob 再触发保存.
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
