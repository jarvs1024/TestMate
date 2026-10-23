/**
 * download —— 触发浏览器保存一个 blob.
 *
 * 安装只剩「下载安装包」这一条路, 所以这里只有这一个能力.
 */
import { describe, it, expect, vi } from 'vitest';
import { downloadBlob } from '../download';

describe('downloadBlob', () => {
  it('用 <a download> 触发保存', () => {
    const origCreate = (URL as any).createObjectURL;
    const origRevoke = (URL as any).revokeObjectURL;
    (URL as any).createObjectURL = vi.fn(() => 'blob:fake');
    (URL as any).revokeObjectURL = vi.fn();
    const clicked: any[] = [];
    const origClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () { clicked.push(this); };

    try {
      downloadBlob(new Blob(['x']), 'pkg.zip');
      expect((URL as any).createObjectURL).toHaveBeenCalled();
      expect(clicked.length).toBe(1);
      expect(clicked[0].download).toBe('pkg.zip');
      expect(clicked[0].getAttribute('href')).toBe('blob:fake');
    } finally {
      HTMLAnchorElement.prototype.click = origClick;
      (URL as any).createObjectURL = origCreate;
      (URL as any).revokeObjectURL = origRevoke;
    }
  });

  it('临时 <a> 不留在 DOM 里', () => {
    const origCreate = (URL as any).createObjectURL;
    const origRevoke = (URL as any).revokeObjectURL;
    (URL as any).createObjectURL = vi.fn(() => 'blob:fake');
    (URL as any).revokeObjectURL = vi.fn();
    const origClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () { /* 不真的点 */ };

    try {
      const before = document.body.querySelectorAll('a').length;
      downloadBlob(new Blob(['x']), 'pkg.zip');
      expect(document.body.querySelectorAll('a').length).toBe(before);
    } finally {
      HTMLAnchorElement.prototype.click = origClick;
      (URL as any).createObjectURL = origCreate;
      (URL as any).revokeObjectURL = origRevoke;
    }
  });
});
