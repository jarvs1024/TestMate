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
const NATIVE_ENV_FILE = path.join(__dirname, '..', 'deploy', 'native', '.env');

/** 读一个 env 文件里的某个键 */
function envGet(file, key) {
  try {
    const s = fs.readFileSync(file, 'utf8');
    const m = s.match(new RegExp(`^${key}=(.*)$`, 'm'));
    return m ? m[1].trim().replace(/^["']|["']$/g, '') : '';
  } catch (e) {
    return '';
  }
}

/** 读 MySQL root 口令 (跟其它 e2e 脚本一样从 deploy/.env 取) */
function mysqlRootPw() {
  const pw = envGet(ENV_FILE, 'MYSQL_ROOT_PASSWORD');
  return pw || '';
}

/**
 * 连的是哪个 MySQL —— **裸机模式优先**, 否则 Docker 容器.
 *
 * ⚠️ 2026-10-27: 裸机模式下后端连的是**本机** MySQL, 而 Docker 的 mysql 容器
 *    可能还开着 (数据是旧的) —— 按"谁在服务"选, 别按"容器在不在"选.
 *    判据: 本机有没有裸机后端进程 (uvicorn app.main:app)。
 */
function mysqlTarget() {
  const nativeBackendRunning = (() => {
    try {
      execFileSync('pgrep', ['-f', 'uvicorn app.main:app'], { stdio: 'ignore' });
      return true;
    } catch (e) {
      return false;
    }
  })();
  const containerRunning = (() => {
    try {
      const out = execFileSync('docker', ['ps', '--format', '{{.Names}}'], { encoding: 'utf8' });
      return out.split('\n').map((s) => s.trim()).includes('test-mate-mysql-1');
    } catch (e) {
      return false;
    }
  })();

  if (nativeBackendRunning) {
    return {
      kind: 'native',
      host: envGet(NATIVE_ENV_FILE, 'MYSQL_HOST') || '127.0.0.1',
      port: envGet(NATIVE_ENV_FILE, 'MYSQL_PORT') || '3306',
      user: envGet(NATIVE_ENV_FILE, 'MYSQL_ROOT_USER') || 'root',
      pw: envGet(NATIVE_ENV_FILE, 'MYSQL_ROOT_PASSWORD') || '',
      db: envGet(NATIVE_ENV_FILE, 'MYSQL_DATABASE') || 'testmate',
    };
  }
  if (containerRunning) {
    return { kind: 'docker', container: 'test-mate-mysql-1', pw: mysqlRootPw(), db: 'testmate' };
  }
  // 谁都不在跑 —— 退回本机 (root 一般免密)
  return {
    kind: 'native',
    host: envGet(NATIVE_ENV_FILE, 'MYSQL_HOST') || '127.0.0.1',
    port: envGet(NATIVE_ENV_FILE, 'MYSQL_PORT') || '3306',
    user: envGet(NATIVE_ENV_FILE, 'MYSQL_ROOT_USER') || 'root',
    pw: envGet(NATIVE_ENV_FILE, 'MYSQL_ROOT_PASSWORD') || '',
    db: envGet(NATIVE_ENV_FILE, 'MYSQL_DATABASE') || 'testmate',
  };
}

/** 跑一条 mysql -e, 返回 stdout */
function mysql(sql) {
  const t = mysqlTarget();
  if (t.kind === 'docker') {
    if (!t.pw) throw new Error('deploy/.env 里没有 MYSQL_ROOT_PASSWORD');
    return execFileSync(
      'docker', ['exec', 'test-mate-mysql-1', 'mysql', '-uroot', `-p${t.pw}`, t.db, '-N', '-B', '-e', sql],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
    );
  }
  const args = ['-h', t.host, '-P', String(t.port), '-u', t.user, t.db, '-N', '-B', '-e', sql];
  if (t.pw) args.splice(4, 0, `-p${t.pw}`);
  return execFileSync('mysql', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
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

module.exports = { deleteTestUsers, mysql, mysqlRootPw, mysqlTarget };
