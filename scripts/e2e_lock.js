/**
 * e2e 脚本互斥锁.
 *
 * 为什么需要: 这些脚本会**改生产设置** (发布白名单 / 通知开关) 和**删资产**.
 * 两个脚本并行跑时必然互相干扰 —— 见过白名单被对方的账号覆盖、
 * 通知开关静音后没还原 (下一个脚本还把 false 当成"原值"存下来).
 * 而且这种干扰是**偶发**的, 排查起来极其费时间.
 *
 * 用法: 在脚本最开头 (做任何事之前) 调 acquire()
 *   const lock = require('./e2e_lock');
 *   const release = lock.acquire('e2e_market.js');
 *   ... 脚本主体 ...
 *   release();   // 进程退出时也会自动释放
 */
const fs = require('fs');
const os = require('os');
const path = require('path');

const LOCK_FILE = path.join(os.tmpdir(), 'testmate-e2e.lock');

/** 锁是不是"上一轮留下的僵尸" (进程早就没了, 但 exit handler 没跑到) */
function isStale() {
  try {
    const raw = fs.readFileSync(LOCK_FILE, 'utf8');
    const m = raw.match(/pid=(\d+)/);
    if (!m) return true;
    const pid = Number(m[1]);
    if (!pid) return true;
    // process.kill(pid, 0) 只探测存在性, 不发信号
    try {
      process.kill(pid, 0);
      return false;
    } catch {
      return true;   // 进程不在了 → 僵尸锁
    }
  } catch {
    return true;
  }
}

/** @returns {() => void} 释放锁的函数 */
function acquire(name) {
  if (fs.existsSync(LOCK_FILE)) {
    if (isStale()) {
      console.warn(`[e2e] 发现上次留下的僵尸锁 (${LOCK_FILE}), 已清理`);
      try { fs.unlinkSync(LOCK_FILE); } catch { /* 算了 */ }
    } else {
      let holder = '?';
      try { holder = fs.readFileSync(LOCK_FILE, 'utf8').trim(); } catch { /* 读不到就算了 */ }
      console.error(
        `[e2e] 拒绝启动: 已有另一个 e2e 脚本在跑 (${holder}).\n`
        + '       并行跑会互相改生产设置/删资产 —— 等前一个跑完再启动。',
      );
      process.exit(3);
    }
  }
  fs.writeFileSync(LOCK_FILE, `${name} pid=${process.pid}`);
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    try { fs.unlinkSync(LOCK_FILE); } catch { /* 已经没了 */ }
  };
  // 正常退出 / 被 kill / 抛异常 —— 都要把锁放掉, 别让下一个脚本干等
  process.on('exit', release);
  process.on('SIGINT', () => { release(); process.exit(130); });
  process.on('SIGTERM', () => { release(); process.exit(143); });
  return release;
}

module.exports = { acquire, LOCK_FILE };
