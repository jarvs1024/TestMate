/**
 * 复制到剪贴板 —— **带降级** (2026-11-04 第二十四轮).
 *
 * ⚠️ 为什么不能直接用 `navigator.clipboard.writeText`:
 *   剪贴板 API **只在安全上下文 (secure context) 可用** ——
 *   HTTPS, 或者 `localhost` / `127.0.0.1`.
 *   而现网是 `http://10.20.65.25:8090` (内网 IP + 明文 HTTP) ——
 *   浏览器判定 `window.isSecureContext === false`, 于是
 *   **`navigator.clipboard` 整个是 `undefined`**,
 *   `navigator.clipboard.writeText(...)` 直接抛
 *   `TypeError: Cannot read properties of undefined (reading 'writeText')`.
 *   → 页面上就是「复制失败 —— 请手动选中复制」, 而且**没有一次能成功**.
 *   ⚠️ 本地开发 (localhost) 是安全上下文 → **本地测不出来**, 一上生产就翻车.
 *
 * 降级路径: 造一个离屏 `<textarea>` → 选中 → `document.execCommand('copy')`.
 *   这是老 API, 在任何上下文都能用 (包括内网 HTTP),
 *   唯一要求是**必须由用户手势 (click) 直接触发** —— 所以只能在点击处理器里同步调用.
 *
 * ⚠️ `execCommand` 在部分浏览器上会返回 false (没复制成功), 那才算失败;
 *   返回 true 就是成功了 —— 不能只看有没有抛异常.
 */

/** 复制是否成功 (true = 已进剪贴板) */
export async function copyToClipboard(text: string): Promise<boolean> {
  const value = String(text ?? '');
  if (!value) return false;

  // ---- ① 首选: 标准剪贴板 API (HTTPS / localhost 下走这条) ----
  // ⚠️ 必须**先判存在** —— 非安全上下文下 navigator.clipboard 是 undefined,
  //    直接 .writeText 会抛 TypeError (不是它自己抛的错, 是读 undefined 的属性).
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      // 权限被拒 / 浏览器策略拦了 → 往下走降级
    }
  }

  // ---- ② 降级: execCommand (内网 HTTP 下走这条) ----
  return legacyCopy(value);
}

/**
 * 老办法复制 —— 离屏 textarea + execCommand('copy').
 *
 * ⚠️ 必须在**用户手势的同步调用栈**里执行 (不能 await 别的异步再复制) ——
 *    隔了异步, 浏览器会认为不是用户触发的, execCommand 也会失败.
 */
function legacyCopy(text: string): boolean {
  const ta = document.createElement('textarea');
  ta.value = text;
  // ⚠️ 这几个属性一个都不能少:
  //   readonly — 防止 iOS 聚焦时弹键盘
  //   position/left/top — 移出屏幕 (但不能 display:none, 那样选不中)
  //   opacity:0 — 看不见
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  ta.style.top = '0';
  ta.style.opacity = '0';
  document.body.appendChild(ta);

  let ok = false;
  try {
    ta.focus();
    ta.select();
    // setSelectionRange 在某些浏览器上比 select() 更可靠 (iOS)
    ta.setSelectionRange(0, ta.value.length);
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  } finally {
    document.body.removeChild(ta);
  }
  return ok;
}
