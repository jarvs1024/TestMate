/**
 * 作者身份口径 —— 跟后端 `app/core/identity.py` 保持一致.
 *
 * ⚠️ 为什么需要它 (2026-10-25 用户名改版):
 *   用户名现在是**邮箱式** (`zhangsan@twsc.com.cn`), 而资产/软件的 `author` 字段
 *   可能还是**短名** (`zhangsan`) —— 存量数据 / 迁移没跑到的环境都是这样.
 *   后端认两种写法 (identity.author_forms), 前端如果只认一种, 就会出现
 *   **"后端放行、前端不给按钮"** 的拧巴状态:
 *     · 详情抽屉不显示「发布新版本」→ 作者更新不了自己的资产
 *     · 「只看这些」里空空的 → 自己提交的资产整片消失
 *     · 被驳回后没有「重新提交审核」
 *     · 不能删掉自己还没上架的资产
 *
 * 所以前端凡是判断"这是不是我的东西", 都要走这里 —— 别再写 `a.author === me`.
 *
 * ⚠️ 2026-10-30: 从 `views/Capability/Catalog/identity.ts` **上移**到这里 ——
 *    软件库 (views/Software) 也要用同一套判定, 但不该反过来去 import
 *    资产市场的目录 (跨模块反向依赖, 以后拆目录就断链).
 *    Catalog/identity.ts 保留为 re-export, 老的 import 路径照常能用.
 */

/** 用户名的各种可能写法 (当前写法 + @ 前的本地部分). */
export function authorForms(username: string | null | undefined): string[] {
  const u = (username || '').trim().toLowerCase();
  if (!u) return [];
  const out = [u];
  const lp = u.split('@', 1)[0];
  if (lp && lp !== u) out.push(lp);
  return out;
}

/** 这个东西的作者是不是这个人 (短名 / 全邮箱**双向**都认).

    ⚠️ 双向的原因: 后端 identity.name_matches 两个方向都认 ——
       author 字段可能是全邮箱 ('zhangsan@twsc.com.cn'), 而登录用户名是短名
       ('zhangsan'), 反过来也一样. 前端只认一个方向就会漏判.
    */
export function isAuthor(
  assetAuthor: string | null | undefined,
  username: string | null | undefined,
): boolean {
  const a = (assetAuthor || '').trim().toLowerCase();
  const u = (username || '').trim().toLowerCase();
  if (!a || !u) return false;
  if (a === u) return true;
  // 本地部分相同即视为同一人 ('zhangsan@twsc.com.cn' ≡ 'zhangsan')
  const la = a.split('@', 1)[0];
  const lu = u.split('@', 1)[0];
  return !!la && !!lu && la === lu;
}
