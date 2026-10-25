/**
 * e2e 测试账号清理 —— **必须回读核对**, 不能"删完就报成功".
 *
 * ⚠️ 这里踩过的坑 (2026-10-26 发现):
 *   清理语句写的是 ``WHERE username='e2e_real_pub'``, 但后端建号时会把
 *   普通用户的用户名**归一成邮箱形式** —— 库里实际存的是 ``e2e_real_pub@twsc.com.cn``.
 *   于是 DELETE 删了 **0 行**, 脚本却照常打印「[清理] 测试账号已删除」,
 *   几个已知口令的测试账号就这么长期挂在生产库里 (谁都不知道).
 *
 *   所以这里:
 *     · 按**前缀**删 (短名 / 邮箱形式都覆盖)
 *     · 删完**回读**确认真的没了, 没干净就大声报出来 (而不是假装成功)
 *
 * 用法:
 *   const { deleteTestUsers } = require('./e2e_cleanup');
 *   deleteTestUsers(['e2e_real_pub', 'e2e_scenario_pub']);
 */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ENV_FILE = path.join(__dirname, '..', 'deploy', '.env');

/** 读 MySQL root 口令 (跟其它 e2e 脚本一样从 deploy/.env 取) */
function mysqlRootPw() {
  const env = fs.readFileSync(ENV_FILE, 'utf8');
  const pw = (env.match(/^MYSQL_ROOT_PASSWORD=(.*)$/m) || [])[1];
  return pw ? pw.trim().replace(/^["']|["']$/g, '') : '';
}

/** 跑一条 mysql -e, 返回 stdout */
function mysql(sql) {
  const pw = mysqlRootPw();
  if (!pw) throw new Error('deploy/.env 里没有 MYSQL_ROOT_PASSWORD');
  return execFileSync(
    'docker', ['exec', 'test-mate-mysql-1', 'mysql', '-uroot', `-p${pw}`, 'testmate', '-N', '-B', '-e', sql],
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
  );
}

/**
 * 删掉这些测试账号, 并**回读核对**.
 *
 * @param {string[]} names 用户名 (短名即可, 邮箱形式也能)
 * @returns {{ok: boolean, left: string[], msg: string}}
 */
function deleteTestUsers(names) {
  const list = (names || []).filter(Boolean);
  if (!list.length) return { ok: true, left: [], msg: '(没有要清理的账号)' };

  // 前缀匹配 —— 短名 'e2e_x' 与邮箱形式 'e2e_x@twsc.com.cn' 都能命中
  const where = list.map((n) => {
    const safe = String(n).replace(/[^A-Za-z0-9_.@-]/g, '');
    return `username LIKE '${safe}%'`;
  }).join(' OR ');

  try {
    mysql(`DELETE FROM users WHERE ${where};`);
  } catch (e) {
    const msg = `账号清理失败: ${String(e.message).split('\n')[0]}`;
    console.error(`  [清理] ⚠️ ${msg}`);
    return { ok: false, left: list, msg };
  }

  // ⚠️ 回读核对 —— 没删干净就**大声**报出来, 别再假装成功
  let left = [];
  try {
    const out = mysql(`SELECT username FROM users WHERE ${where};`).trim();
    left = out ? out.split('\n').map((s) => s.trim()).filter(Boolean) : [];
  } catch (e) {
    const msg = `账号清理回读失败: ${String(e.message).split('\n')[0]}`;
    console.error(`  [清理] ⚠️ ${msg}`);
    return { ok: false, left: list, msg };
  }

  if (left.length) {
    const msg = `测试账号**没删干净**, 还在库里: ${left.join(', ')} —— 请手动清理`;
    console.error(`  [清理] ⚠️ ${msg}`);
    return { ok: false, left, msg };
  }
  console.log(`  [清理] 测试账号已删除 (回读确认: 0 条残留)`);
  return { ok: true, left: [], msg: '已删除' };
}

module.exports = { deleteTestUsers, mysql, mysqlRootPw };
