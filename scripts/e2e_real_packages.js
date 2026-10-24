#!/usr/bin/env node
/**
 * 资产市场 —— **真实包**端到端验收.
 *
 * 与 e2e_market_scenarios.js 的区别: 那个造的是占位级包 (一个 SKILL.md),
 * 测不出多文件目录结构、隐藏目录 (.qoder-plugin/)、安装产物是否逐字一致.
 * 这里用 scripts/make_real_packages.py 造的两个**结构完整、内容真实**的包:
 *   1. ssd-log-triage    —— skill:   SKILL.md + references/ + scripts/ + assets/
 *   2. qoder-trace-kit   —— plugin: .qoder-plugin/plugin.json + commands/ + agents/ + skills/ + hooks/
 *
 * 每种包都走完整生命周期:
 *   体检 → 上传 → 待审 → 驳回 → 重提 → 通过 → 上架 → 可见 → 详情/文档/文件清单
 *   → **内容逐字比对**(bundle 接口) → 更新版本 → 再比对
 *   → 下架 → 已装仍可见 → 重上架 → 彻底删除
 *
 * 另覆盖其余市场端点: 分类 / 配置 / 任务 / 审计 / 回执 / 同步状态 / GitLab 探测
 *     / 文件包 / 历史版本下载.
 *
 * 用法: node scripts/e2e_real_packages.js
 */
const puppeteer = require('puppeteer-core');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
// ⚠️ 互斥锁: 并行跑 e2e 会互相改生产设置/删资产 (见 e2e_lock.js)
require('./e2e_lock').acquire(__filename);


const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const API = process.env.TESTMATE_API || 'http://localhost:18000';
const ADMIN = process.env.TESTMATE_USER || 'admin';
const ADMIN_PW = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');

const PUBLISHER = { username: 'e2e_real_pub', password: 'Real@12345' };
const SKILL_CODE = 'ssd-log-triage';
const PLUGIN_CODE = 'qoder-trace-kit';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail) {
  const ts = new Date().toISOString().slice(11, 19);
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'} [${ts}] ${name}${detail ? '  :: ' + detail : ''}`);
}

// ---------- HTTP ----------
async function api(pathname, { method = 'GET', token, body, form } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) {
    payload = form;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const r = await fetch(API + pathname, { method, headers, body: payload });
  const text = await r.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* 非 JSON */ }
  return { status: r.status, json, text };
}

async function login(username, password) {
  const r = await api('/api/v1/auth/login', {
    method: 'POST', body: { username, password },
  });
  if (r.status !== 200) throw new Error(`登录失败 ${username}: ${r.status} ${r.text}`);
  return r.json.access_token;
}

async function setSetting(token, key, value) {
  const r = await api(`/api/v1/settings/${key}`, {
    method: 'PUT', token, body: { value },
  });
  if (r.status !== 200) throw new Error(`设置 ${key} 失败: ${r.status} ${r.text}`);
}

async function getSettings(token, keys) {
  const r = await api('/api/v1/settings/schema', { token });
  const out = {};
  if (r.status !== 200) return out;
  for (const g of (r.json.groups || [])) {
    for (const it of (g.items || [])) {
      if (keys.includes(it.key)) out[it.key] = it.value;
    }
  }
  return out;
}

/** MySQL root 口令 (从 deploy/.env 取) —— 直接动 DB 模拟故障 */
function mysqlRootPw() {
  const env = fs.readFileSync(path.join(__dirname, '..', 'deploy', '.env'), 'utf8');
  return (env.match(/^MYSQL_ROOT_PASSWORD=(.*)$/m) || [])[1]?.trim().replace(/^["']|["']$/g, '') || '';
}

// ---------- 包 ----------
function buildPackages() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  execFileSync('python3', [
    path.join(__dirname, 'make_real_packages.py'), '--out-dir', OUT_DIR,
  ], { stdio: 'inherit' });
  const manifest = JSON.parse(
    fs.readFileSync(path.join(OUT_DIR, 'real-packages-manifest.json'), 'utf8'),
  );
  return {
    skill: {
      zip: manifest.skill.zip,
      files: manifest.skill.files,
      code: SKILL_CODE,
      kind: 'skill',
      version: '1.3.0',
      name: 'SSD 日志分诊',
      summary: '读 SMART / nvme-cli / 内核日志, 判断是介质坏还是链路问题, 给出下一步动作',
      description: '第一轮分诊工具: 读 SMART、nvme-cli 输出与内核日志, 按 NVMe 状态码区分介质类错误与链路类错误, 输出可执行的换盘/换线判断。',
      use_when: '现场出现 I/O error、nvme timeout、介质错误计数增长时',
      not_for: '固件升级、RAID 重建期误报',
      category: '质量诊断',
      icon: '🔍',
      tags: '["ssd","nvme","日志","分诊"]',
      keywords: '["smart","nvme","io error","介质","换盘"]',
      author: 'TestMate 平台组',
      permissions: '{"read":["日志文件","SMART 输出"]}',
      install_steps: '["放到 ~/.qoder-cn/skills/ssd-log-triage/"]',
    },
    plugin: {
      zip: manifest.plugin.zip,
      files: manifest.plugin.files,
      code: PLUGIN_CODE,
      kind: 'plugin',
      version: '1.2.0',
      name: 'Trace 分析工具包',
      summary: 'SSD 抓 trace 的命令集、审查 agent 与采集后置校验, 覆盖采集到出报告全流程',
      description: '给 SSD trace 抓取场景用的 Qoder 插件: 斜杠命令引导采集, trace-reviewer agent 复核完整性, 采集后置 hook 做样本量校验。',
      use_when: '需要抓取并分析 SSD trace 时',
      not_for: '不负责 trace 数据落盘与存储',
      category: '质量诊断',
      icon: '🧩',
      tags: '["trace","插件","命令"]',
      keywords: '["bpftrace","trace","采集","分析"]',
      author: 'TestMate 平台组',
      permissions: '{"exec":["bpftrace"]}',
      install_steps: '["放到 ~/.qoder-cn/plugins/cache/qoder-marketplace/qoder-trace-kit/"]',
    },
  };
}

// ---------- 上传表单 ----------
function uploadForm(pkg, over = {}) {
  const form = {
    code: pkg.code, kind: pkg.kind, name: pkg.name, version: pkg.version,
    summary: pkg.summary, description: pkg.description, use_when: pkg.use_when,
    not_for: pkg.not_for, category: pkg.category, icon: pkg.icon,
    tags: pkg.tags, keywords: pkg.keywords,
    featured: 'false', permissions: pkg.permissions,
    install_steps: pkg.install_steps, bindings: '{}',
  };
  Object.assign(form, over);
  return form;
}

/**
 * 上传一个包.
 * @param filename 覆盖上传时的文件名 —— ⚠️ 包名必须与资产 code 一致 (命名契约),
 *   改了 code 就要同时给一个同名包 (否则后端 422).
 */
async function uploadPackage(token, pkg, over = {}, filename) {
  const buf = fs.readFileSync(pkg.zip);
  const form = new FormData();
  for (const [k, v] of Object.entries(uploadForm(pkg, over))) form.append(k, v);
  form.append('package', new Blob([buf]), filename || path.basename(pkg.zip));
  const r = await api('/api/v1/assets/upload', { method: 'POST', token, form });
  return r;
}

/**
 * 更新版本 —— 必须走 `PUT /{code}`.
 * ⚠️ 不能用 POST /upload: 那是"新建", 资产已存在时直接 409.
 */
async function updatePackage(token, pkg, over = {}) {
  const buf = fs.readFileSync(pkg.zip);
  const form = new FormData();
  for (const [k, v] of Object.entries(uploadForm(pkg, over))) form.append(k, v);
  form.append('package', new Blob([buf]), path.basename(pkg.zip));
  const r = await api(`/api/v1/assets/${pkg.code}`, { method: 'PUT', token, form });
  return r;
}

/** 等 job 跑到终态 (推送要几秒, 固定 sleep 不可靠) */
async function waitJob(token, jobId, timeoutMs = 60000) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < timeoutMs) {
    const r = await api(`/api/v1/assets/jobs/${jobId}`, { token });
    last = r.json;
    if (last && ['pushed', 'failed'].includes(last.status)) return last;
    await sleep(700);
  }
  return last;
}

// ---------- 内容比对 ----------
/** 包内归档路径 → 落盘后应有的相对路径 (顶层公共目录会被剥掉) */
function expectedLayout(files) {
  const tops = new Set(Object.keys(files).map((p) => p.split('/')[0]));
  const strip = tops.size === 1 ? [...tops][0] + '/' : '';
  const out = {};
  for (const rel of Object.keys(files)) {
    out[strip && rel.startsWith(strip) ? rel.slice(strip.length) : rel] = files[rel];
  }
  return out;
}

/**
 * 用 bundle 接口把内容拉回来, 与包内容逐字比对.
 *
 * ⚠️ 服务端写盘通道已下线 —— 文件由浏览器写在**用户本机**, 后端不再碰磁盘.
 *    内容正确性靠这条链路验证: 上传 → 解包 → 落工作区 → bundle 返回给前端写盘.
 *    (前端那一步写盘是纯文件复制, 由前端单测覆盖)
 */
async function compareViaBundle(token, pkg, code) {
  const r = await api(`/api/v1/assets/${code}/bundle`, { token });
  if (r.status !== 200 || !r.json || !r.json.files) {
    return {
      ok: false, count: 0, got: {}, missing: ['(bundle 请求失败)'],
      mismatch: [], extra: [], detail: `status=${r.status}`,
    };
  }
  const expect = expectedLayout(pkg.files);
  const got = {};
  for (const f of r.json.files) got[f.path] = f;
  const missing = [];
  const mismatch = [];
  for (const [rel, content] of Object.entries(expect)) {
    const f = got[rel];
    if (!f) { missing.push(rel); continue; }
    const text = f.encoding === 'base64'
      ? Buffer.from(f.content, 'base64').toString('utf8')
      : f.content;
    if (text !== content) {
      mismatch.push(`${rel} (期望 ${content.length} 字节, 实际 ${text.length} 字节)`);
    }
  }
  const extra = Object.keys(got).filter((k) => !(k in expect));
  return {
    ok: !missing.length && !mismatch.length && !extra.length,
    count: Object.keys(expect).length,
    got, missing, mismatch, extra,
    detail: `${r.json.total} 个文件`,
  };
}

// ---------- 生命周期 ----------
/**
 * 走完一种包的全生命周期.
 * @param {object} pkg  包描述
 * @param {string} token admin token
 * @param {string} pubToken 发布者 token
 * @param {string} tag 检查项前缀 (便于在结果里区分)
 */
async function runLifecycle(pkg, token, pubToken, tag) {
  const A = `/api/v1/assets/${pkg.code}`;

  // 预清理: 上一次跑崩了可能留下同名资产 (脚本必须能重复运行)
  const pre = await api(A, { method: 'DELETE', token });
  if (pre.status === 200) console.log(`  [预清理] 已删除残留资产 ${pkg.code}`);

  // ① 上传前体检
  const buf = fs.readFileSync(pkg.zip);
  const pv = await api('/api/v1/assets/preview-package', {
    method: 'POST', token,
    form: (() => {
      const f = new FormData();
      f.append('kind', pkg.kind);
      f.append('package', new Blob([buf]), path.basename(pkg.zip));
      return f;
    })(),
  });
  check(`${tag} ① 上传前体检通过`,
    pv.status === 200 && pv.json.ok === true && pv.json.installable === true,
    `ok=${pv.json && pv.json.ok} installable=${pv.json && pv.json.installable} ` +
    `files=${pv.json && pv.json.total_files} doc=${pv.json && pv.json.doc_file} ` +
    `block=${pv.json && pv.json.block_reason}`);
  check(`${tag} ② 体检识别出类型标志`,
    pkg.kind === 'skill'
      ? pv.json.has_skill_md === true
      : pv.json.has_plugin_manifest === true,
    `skill_md=${pv.json.has_skill_md} plugin_manifest=${pv.json.has_plugin_manifest}`);

  // ③ 上传 → 待审
  const up = await uploadPackage(pubToken, pkg);
  check(`${tag} ③ 上传返回 202`,
    up.status === 202, `status=${up.status} ${up.text.slice(0, 120)}`);
  if (up.status !== 202) return null;
  const job = await waitJob(token, up.json.id);
  check(`${tag} ④ 后台任务推到 GitLab`,
    job && job.status === 'pushed',
    `job=${job && job.id} status=${job && job.status} sha=${job && (job.commit_sha || '').slice(0, 10)}`);

  // ⑤ 状态待审
  let det = await api(A, { token });
  check(`${tag} ⑤ 状态为待审核`, det.json && det.json.publish_status === 'pending',
    `publish_status=${det.json && det.json.publish_status}`);

  // ⑥ 驳回
  const rej = await api(`${A}/review`, {
    method: 'POST', token, form: (() => {
      const f = new FormData();
      f.append('decision', 'reject');
      f.append('comment', 'references 里缺少固件版本说明, 请补充后再提交');
      return f;
    })(),
  });
  check(`${tag} ⑥ 驳回成功`, rej.status === 200, `status=${rej.status}`);
  det = await api(A, { token });
  check(`${tag} ⑦ 驳回理由写进资产`,
    det.json && /固件版本/.test(det.json.review_note || ''),
    `note=${det.json && det.json.review_note}`);

  // ⑧ 重新提交
  const sub = await api(`${A}/submit`, {
    method: 'POST', token, form: (() => {
      const f = new FormData();
      f.append('comment', '已补充固件版本说明');
      return f;
    })(),
  });
  check(`${tag} ⑧ 重新提交回到待审`, sub.status === 200, `status=${sub.status}`);
  det = await api(A, { token });
  check(`${tag} ⑨ 状态回到待审核`, det.json && det.json.publish_status === 'pending',
    `publish_status=${det.json && det.json.publish_status}`);

  // ⑩ 审核通过 → 上架
  const appr = await api(`${A}/review`, {
    method: 'POST', token, form: (() => {
      const f = new FormData();
      f.append('decision', 'approve');
      f.append('comment', '内容完整, 通过');
      return f;
    })(),
  });
  check(`${tag} ⑩ 审核通过`, appr.status === 200, `status=${appr.status}`);
  det = await api(A, { token });
  check(`${tag} ⑪ 上架成功`, det.json && det.json.publish_status === 'published',
    `publish_status=${det.json && det.json.publish_status}`);

  // ⑫ 列表可见
  const list = await api(`/api/v1/assets?kind=${pkg.kind}&limit=100`, { token });
  const hit = (list.json.items || []).find((i) => i.code === pkg.code);
  check(`${tag} ⑫ 列表里可见`, !!hit,
    hit ? `${hit.name} ${hit.version} ${hit.publish_status}` : '没找到');

  // ⑬ 详情 / 文档 / 文件清单
  check(`${tag} ⑬ 详情可读`,
    det.status === 200 && det.json.code === pkg.code && det.json.kind === pkg.kind,
    `kind=${det.json && det.json.kind} version=${det.json && det.json.version}`);
  const doc = await api(`${A}/doc`, { token });
  const docWant = pkg.kind === 'skill' ? 'SSD 日志分诊' : 'Trace 分析工具包';
  check(`${tag} ⑭ 展示文档正文可读`,
    doc.status === 200 && doc.json.content && doc.json.content.includes(docWant),
    `file=${doc.json && doc.json.filename} 长度=${doc.json && doc.json.content && doc.json.content.length}`);

  // files 端点返回**扁平节点列表** (目录是 type=tree 的节点), 只数 blob
  const files = await api(`${A}/files`, { token });
  const nodes = files.json.files || [];
  const blobs = nodes.filter((n) => n.type === 'blob');
  const trees = nodes.filter((n) => n.type === 'tree');
  const fileList = blobs.map((n) => n.path);
  // 子目录结构按 kind 各自断言 (skill 有 references/scripts/assets, plugin 有 .qoder-plugin/commands/...)
  const wantDirs = pkg.kind === 'skill'
    ? ['references/', 'scripts/', 'assets/']
    : ['.qoder-plugin/', 'commands/', 'agents/', 'skills/', 'hooks/'];
  const hitDirs = wantDirs.filter((d) => fileList.some((f) => String(f).startsWith(d)));
  check(`${tag} ⑮ 文件清单含子目录结构`,
    files.status === 200
    && fileList.length === Object.keys(pkg.files).length
    && hitDirs.length === wantDirs.length,
    `${fileList.length} 文件 / ${trees.length} 目录, 子目录命中 ${hitDirs.length}/${wantDirs.length}`);

  // ⑱ 内容逐字比对 (核心): 包内容 == 后端解包落工作区后返回给前端的内容
  const cmp = await compareViaBundle(token, pkg, pkg.code);
  check(`${tag} ⑱ 内容逐字一致 (${cmp.count} 个文件)`,
    cmp.ok,
    cmp.ok ? cmp.detail
      : `缺=${cmp.missing.join(',')} 不一致=${cmp.mismatch.join(',')} 多余=${cmp.extra.join(',')}`);

  // ⑲ plugin.json 能被解析 (plugin 专属)
  if (pkg.kind === 'plugin') {
    const pj = cmp.got['.qoder-plugin/plugin.json'];
    let parsed = null;
    try { parsed = JSON.parse(pj ? pj.content : ''); } catch { /* 解析失败 */ }
    check(`${tag} ⑲ plugin.json 可解析且字段正确`,
      parsed && parsed.name === 'trace-kit' && parsed.version === '1.2.0'
      && Array.isArray(parsed.commands) === false && parsed.commands === './commands',
      parsed ? `name=${parsed.name} version=${parsed.version} commands=${parsed.commands}` : '解析失败');
  } else {
    const sk = cmp.got['SKILL.md'];
    const txt = sk ? sk.content : '';
    check(`${tag} ⑲ SKILL.md frontmatter 完整`,
      txt.startsWith('---') && txt.includes('name: ssd-log-triage')
      && txt.includes('allowed-tools:') && txt.includes('metadata:'),
      `前 40 字: ${txt.slice(0, 40).replace(/\n/g, '⏎')}`);
  }

  // ㉑ 更新版本 → 装新版 (必须走 PUT /{code}, POST /upload 是"新建", 已存在会 409)
  const newVersion = pkg.kind === 'skill' ? '1.4.0' : '1.3.0';
  const upd = await updatePackage(pubToken, pkg, { version: newVersion });
  check(`${tag} ㉑ 更新版本返回 202`, upd.status === 202, `status=${upd.status}`);
  const updJob = upd.status === 202 ? await waitJob(token, upd.json.id) : null;
  check(`${tag} ㉒ 更新推到 GitLab`,
    updJob && updJob.status === 'pushed',
    `status=${updJob && updJob.status}`);
  det = await api(A, { token });
  check(`${tag} ㉓ 版本号已更新`,
    det.json && det.json.version === newVersion,
    `version=${det.json && det.json.version}`);

  const cmp2 = await compareViaBundle(token, pkg, pkg.code);
  check(`${tag} ㉖ 新版本内容逐字一致`, cmp2.ok,
    cmp2.ok ? cmp2.detail : `缺=${cmp2.missing.join(',')} 不一致=${cmp2.mismatch.join(',')}`);

  // ㉖c 历史版本下载 —— 更新前的那个包还留在 package/ 里, 应该还能下
  const dl = await fetch(
    `${API}/api/v1/assets/${pkg.code}/versions/${pkg.version}/download`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const dlBuf = Buffer.from(await dl.arrayBuffer());
  const dlSha = dl.headers.get('x-content-sha256') || '';
  const origSha = crypto.createHash('sha256').update(fs.readFileSync(pkg.zip)).digest('hex');
  check(`${tag} ㉖c 历史版本包可下载`,
    dl.status === 200 && dlBuf.length > 0 && dlSha === origSha,
    `status=${dl.status} ${dlBuf.length} 字节 sha=${dlSha.slice(0, 12)} ` +
    `(原包 ${origSha.slice(0, 12)})`);

  // ㉗ 申请下架 → 待下架审核 (资产**仍在架**, 确认后才会被彻底删除)
  //    ⚠️ 下架现在是申请制 (2026-10-24): 要带 confirm_code, 提交后进「待下架审核」.
  //    而且更新版本后资产会回到「待审核」, 得先审过才能申请下架.
  const appr2 = await api(`${A}/review`, {
    method: 'POST', token, form: (() => {
      const f = new FormData();
      f.append('decision', 'approve');
      f.append('comment', '新版本通过');
      return f;
    })(),
  });
  check(`${tag} ㉗a 新版本审核通过`, appr2.status === 200, `status=${appr2.status}`);

  const unpub = await api(`${A}/unpublish`, {
    method: 'POST', token, form: (() => {
      const f = new FormData();
      f.append('confirm_code', pkg.code);
      f.append('comment', '端到端验证下架');
      return f;
    })(),
  });
  check(`${tag} ㉗ 申请下架成功`, unpub.status === 200, `status=${unpub.status}`);
  // 申请后资产**仍在市场可见** —— 管理员确认前它还在被用 (只是挂个待审徽标).
  const listAfter = await api(
    `/api/v1/assets?kind=${pkg.kind}&limit=100&client_id=e2e-real`, { token: pubToken },
  );
  const still = (listAfter.json.items || []).find((i) => i.code === pkg.code);
  check(`${tag} ㉘ 待下架审核期间资产仍在市场可见`,
    !!still && still.publish_status === 'unpublish_pending',
    still ? `${still.publish_status} installed=${still.installed}` : '消失了');

  // ㉙ 撤销下架申请 → 回到在架
  const re = await api(`${A}/unpublish-cancel`, {
    method: 'POST', token, form: (() => {
      const f = new FormData(); f.append('comment', '端到端验证撤销下架'); return f;
    })(),
  });
  check(`${tag} ㉙ 撤销下架申请成功`, re.status === 200, `status=${re.status}`);

  // ㉛ 文件包下载 (选目录安装靠它拿明文文件写盘)
  const bundle = await api(`${A}/bundle`, { token });
  check(`${tag} ㉛ 文件包可下载`,
    bundle.status === 200 && (bundle.json.files || []).length > 0,
    `${(bundle.json.files || []).length} 个文件`);

  // ㉛b 安装包 (zip) 能下载 —— 「下载安装包」这条路要用
  const zdl = await fetch(
    `${API}/api/v1/assets/${pkg.code}/versions/${newVersion}/download`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const zbuf = Buffer.from(await zdl.arrayBuffer());
  check(`${tag} ㉛b 安装包 zip 可下载`,
    zdl.status === 200 && zbuf.length > 0
    && zbuf.subarray(0, 2).toString('latin1') === 'PK',
    `status=${zdl.status} ${zbuf.length} 字节`);

  // ㉘ 从工作区 index.json 回灌 DB (模拟 DB 记录丢失)
  const before = await api(A, { token });
  const dbRows = (await api(`/api/v1/assets?kind=${pkg.kind}&limit=200&status=all`, { token }))
    .json.items || [];
  const row = dbRows.find((i) => i.code === pkg.code);
  if (row) {
    execFileSync('docker', ['exec', 'test-mate-mysql-1', 'mysql', '-uroot', `-p${mysqlRootPw()}`,
      'testmate', '-e', `DELETE FROM assets WHERE code='${pkg.code}';`], { stdio: 'ignore' });
    const goneDb = await api(A, { token });
    check(`${tag} ㉘ 模拟 DB 记录丢失`, goneDb.status === 404, `status=${goneDb.status}`);
    const sync = await api('/api/v1/assets/sync', { method: 'POST', token });
    check(`${tag} ㉘ /sync 从 index.json 回灌成功`,
      sync.status === 200 && sync.json.ok === true,
      `status=${sync.status} added=${sync.json && sync.json.added} updated=${sync.json && sync.json.updated}`);
    const back = await api(A, { token });
    check(`${tag} ㉘ 资产已恢复`,
      back.status === 200 && back.json.version === before.json.version,
      `version=${back.json && back.json.version}`);
  } else {
    check(`${tag} ㉘ 模拟 DB 记录丢失`, false, '列表里没找到资产, 跳过');
  }

  // ㉝ 彻底删除
  const del = await api(`${A}?comment=端到端清理`, { method: 'DELETE', token });
  check(`${tag} ㉝ 彻底删除成功`, del.status === 200, `status=${del.status} ${del.text.slice(0, 100)}`);
  const gone = await api(A, { token });
  check(`${tag} ㉞ 删除后不可查`, gone.status === 404, `status=${gone.status}`);
  const listGone = await api(`/api/v1/assets?kind=${pkg.kind}&limit=100`, { token });
  check(`${tag} ㉟ 删除后不在列表里`,
    !(listGone.json.items || []).some((i) => i.code === pkg.code));

  return { code: pkg.code };
}

/**
 * 失败任务重试 —— 制造一次推送失败, 恢复远端后重试成功.
 *
 * 这条路径以前有个真 bug: _commit 只查 stderr 判 "nothing to commit",
 * 而 git 把这句话打在 **stdout** → 提交成功但推送失败之后, 每次重试都卡在这,
 * 资产永远推不上去, 卡在本地. 这里端到端复验.
 */
async function runRetryScenario(adminToken, pubToken, pkg) {
  const cfg = await api('/api/v1/assets/config', { token: adminToken });
  const goodRemote = cfg.json.remote;
  const BAD = 'ssh://git@127.0.0.1:1/definitely-unreachable.git';
  const CODE = 'retry-demo';

  try {
    // 1) 把远端指到不可达地址
    await setSetting(adminToken, 'marketplace.git.remote', BAD);

    // 2) 上传 → 提交成功但推送失败
    // ⚠️ 包名必须跟 code 一致 (命名契约) —— 这里 code 换了, 包名也得换
    const up = await uploadPackage(pubToken, pkg, { code: CODE, version: '1.0.0' }, `${CODE}.zip`);
    check('R1 失败场景上传受理', up.status === 202, `status=${up.status}`);
    if (up.status !== 202) return;
    const job = await waitJob(adminToken, up.json.id, 90000);
    check('R2 推送失败, 任务落到 failed', job && job.status === 'failed',
      `job=${job && job.id} status=${job && job.status} err=${job && String(job.error || '').slice(0, 70)}`);
    if (!job || job.status !== 'failed') return;

    // 3) 恢复远端 → 重试
    await setSetting(adminToken, 'marketplace.git.remote', goodRemote);
    const rt = await api(`/api/v1/assets/jobs/${job.id}/retry`, { method: 'POST', token: adminToken });
    check('R3 重试接口受理', rt.status === 200, `status=${rt.status}`);
    const job2 = await waitJob(adminToken, job.id, 90000);
    check('R4 重试后推送成功', job2 && job2.status === 'pushed',
      `status=${job2 && job2.status} sha=${job2 && String(job2.commit_sha || '').slice(0, 10)}`);

    // 4) 资产应当也能查到
    const det = await api(`/api/v1/assets/${CODE}`, { token: adminToken });
    check('R5 重试后资产可查', det.status === 200, `status=${det.status}`);
  } finally {
    // 无论成败都必须把远端改回去
    try { await setSetting(adminToken, 'marketplace.git.remote', goodRemote); } catch (e) { /* 尽力而为 */ }
    // 清理这个临时资产
    try {
      await api(`/api/v1/assets/${CODE}?comment=重试场景清理`, { method: 'DELETE', token: adminToken });
    } catch (e) { /* 尽力而为 */ }
  }
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const adminToken = await login(ADMIN, ADMIN_PW);

  // 发布者账号 + 白名单 (改设置前先存原值, 结束还原)
  await api('/api/v1/auth/register', {
    method: 'POST', token: adminToken,
    body: { username: PUBLISHER.username, password: PUBLISHER.password, role: 'tester' },
  });
  const pubToken = await login(PUBLISHER.username, PUBLISHER.password);
  check('P0 发布者账号就绪', !!pubToken);

  const TOUCHED = [
    'marketplace.review.enabled', 'marketplace.publisher_usernames',
    'marketplace.git.remote',
    'dingtalk.notify_on_publish', 'dingtalk.notify_on_update',
    'dingtalk.notify_on_unpublish', 'dingtalk.notify_on_delete',
  ];
  const saved = await getSettings(adminToken, TOUCHED);
  const pkgs = buildPackages();

  let browser = null;
  try {
    // ⚠️ 改生产设置必须**在 try 里** —— 否则中途抛错(比如浏览器起不来)
    //    就永远还原不了, 把真实配置留在静音/白名单改掉的状态
    // 开审核 + 加白名单 + 静音钉钉 (测试不该往真实群刷屏)
    await setSetting(adminToken, 'marketplace.review.enabled', 'true');
    await setSetting(adminToken, 'marketplace.publisher_usernames', PUBLISHER.username);
    for (const k of TOUCHED.filter((x) => x.startsWith('dingtalk.'))) {
      await setSetting(adminToken, k, 'false');
    }

    browser = await puppeteer.launch({
      executablePath: CHROME,
      headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
      defaultViewport: { width: 1600, height: 1000 },
    });
    // 前端真实页面看一眼: 上架后市场页能看到这个包
    const ctx = await browser.createBrowserContext();
    const page = await ctx.newPage();
    const jsErrors = [];
    // ⚠️ 关掉缓存 —— 否则会加载上一次的旧 JS, 调已下线的端点
    await page.setCacheEnabled(false);
    page.on('pageerror', (e) => jsErrors.push(String(e.message)));
    page.on('console', (m) => { if (m.type() === 'error') jsErrors.push(m.text()); });
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await page.evaluate((tk) => localStorage.setItem('testmate:token', tk), adminToken);

    await runLifecycle(pkgs.skill, adminToken, pubToken, '[技能]');
    await runLifecycle(pkgs.plugin, adminToken, pubToken, '[插件]');
    await runRetryScenario(adminToken, pubToken, pkgs.skill);

    // ===== 其余市场端点 =====
    const cats = await api('/api/v1/assets/categories', { token: adminToken });
    check('X1 分类接口可读',
      cats.status === 200 && (cats.json.items || cats.json.categories || []).length > 0,
      JSON.stringify(cats.json).slice(0, 120));

    const cfg = await api('/api/v1/assets/config', { token: adminToken });
    check('X2 市场配置接口可读',
      cfg.status === 200 && cfg.json.install_enabled !== undefined
      && cfg.json.skill_dir && cfg.json.plugin_dir,
      `install_enabled=${cfg.json && cfg.json.install_enabled} ` +
      `skill_dir=${cfg.json && cfg.json.skill_dir} ` +
      `plugin_dir=${cfg.json && cfg.json.plugin_dir}`);

    const jobs = await api('/api/v1/assets/jobs?limit=20', { token: adminToken });
    check('X3 任务列表可读', jobs.status === 200 && Array.isArray(jobs.json.items),
      `${(jobs.json.items || []).length} 条任务`);

    const audits = await api('/api/v1/assets/audits?limit=50', { token: adminToken });
    check('X4 审计留痕可读', audits.status === 200 && (audits.json.items || []).length > 0,
      `${(audits.json.items || []).length} 条审计`);

    const notif = await api('/api/v1/assets/notifications?limit=50', { token: adminToken });
    check('X5 通知回执可读', notif.status === 200, `${(notif.json.items || []).length} 条回执`);

    const sync = await api('/api/v1/assets/sync-status?client_id=e2e-real', { token: adminToken });
    check('X6 同步状态可读',
      sync.status === 200 && sync.json.pending_count >= 0 && sync.json.failed_count >= 0,
      `pending=${sync.json && sync.json.pending_count} failed=${sync.json && sync.json.failed_count}`);

    const probe = await api('/api/v1/assets/probe/gitlab', { token: adminToken });
    check('X7 GitLab 连通探测', probe.status === 200 && probe.json.ok === true,
      `ok=${probe.json && probe.json.ok} ${(probe.json && probe.json.message || '').slice(0, 80)}`);

    // ===== 前端页面真实渲染 =====
    await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.asset-card, .empty-state', { timeout: 15000 });
    await sleep(1500);
    const cards = await page.evaluate(() => document.querySelectorAll('.asset-card').length);
    check('X8 市场页正常渲染', cards > 0, `${cards} 张卡片`);
    await page.screenshot({ path: path.join(OUT_DIR, 'real-packages-market.png'), fullPage: false });

    check('X9 全程无 JS 错误', jsErrors.length === 0, jsErrors.slice(0, 2).join(' ; '));
  } finally {
    if (browser) await browser.close();

    // 还原设置 (改生产设置必须还原)
    for (const k of TOUCHED) {
      if (saved[k] === undefined) continue;
      try { await setSetting(adminToken, k, String(saved[k])); } catch (e) { /* 尽力而为 */ }
    }
    // 删测试账号
    try {
      const env = fs.readFileSync(path.join(__dirname, '..', 'deploy', '.env'), 'utf8');
      const pw = (env.match(/^MYSQL_ROOT_PASSWORD=(.*)$/m) || [])[1]?.trim().replace(/^["']|["']$/g, '');
      if (pw) {
        execFileSync('docker', ['exec', 'test-mate-mysql-1', 'mysql', '-uroot', `-p${pw}`,
          'testmate', '-e',
          `DELETE FROM users WHERE username='${PUBLISHER.username}';`], { stdio: 'ignore' });
        console.log('  [清理] 测试账号已删除');
      }
    } catch (e) {
      console.log('  [清理] 账号清理跳过: ' + String(e.message).split('\n')[0]);
    }
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) {
    console.log('失败项:\n' + failed.map((f) => ` - ${f.name} :: ${f.detail}`).join('\n'));
  }
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('FATAL', e);
  process.exit(2);
});
