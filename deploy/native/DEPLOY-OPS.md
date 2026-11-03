# TestMate 裸机部署 · 实操手册 (native / systemd)

> 本文是 **25 服务器上实际跑起来的那套** 的部署与更新流程。
> 讲「怎么做」和「踩过什么坑」,功能说明看同目录的 `README.md`。
>
> 最后更新: 2026-11-03

---

## 0. 这台机器的现状(照抄就行)

| 项 | 值 |
|---|---|
| 服务器 | 25 (10.20.65.25),CentOS Stream 9 |
| 代码目录 | `/home/workflow/TestMate` |
| 部署目录 | `/home/workflow/TestMate/deploy/native/` |
| 运行时目录 | `deploy/native/runtime/`(venv / 前端产物 / 配置 / 数据) |
| 前端 | `http://10.20.65.25:8090` |
| 后端 | `127.0.0.1:8000`(只监听本机,由 nginx 反代) |
| admin | `admin` / `Admin@123` |
| MySQL | 本机 8.0.46,库 `testmate`,用户 `testmate` |
| Redis | 本机 6.2.22 |
| Python | **3.12.15**(`python3.12`;系统 `python3` 是 3.9,**别用**) |
| Node / npm | 22.23.1 / 10.9.8 |
| nginx | 1.20.1(TestMate 用独立实例,与系统 nginx 共存) |

**目录分工**:

```
/home/workflow/TestMate/
├── backend_gateway/          后端源码 (FastAPI)
├── frontend_web/             前端源码 (Vue3 + Vite)
├── deploy/
│   ├── docker-compose.yml    ← Docker 模式 (已弃用, 25 上已停)
│   ├── native/               ← 裸机模式 (25 现在跑这个)
│   │   ├── tmctl.sh          ★ 运维唯一入口
│   │   ├── preflight.sh      环境体检
│   │   ├── .env              配置 (含明文口令, 权限 600)
│   │   ├── .env.template     配置模板
│   │   ├── units/            systemd unit 模板
│   │   └── runtime/          运行时 (装出来的, 不要手动改)
│   │       ├── venv/         Python 虚拟环境
│   │       ├── frontend/     前端构建产物 (nginx 实际服务的)
│   │       ├── config/       backend.env + nginx.conf
│   │       ├── market/       资产市场 git 工作区
│   │       ├── data/software/ 软件包落盘
│   │       └── logs/         日志
│   └── README.md             Docker 模式文档
└── README.md                 项目总览
```

---

## 1. 首次安装

### 1.1 体检(只读, 不改任何东西)

```bash
cd /home/workflow/TestMate
sudo ./deploy/native/tmctl.sh check
```

看输出里 **`✗` 的项** —— 那些是硬阻塞(比如 Python 版本不够、端口被占)。
`!` 是警告(比如连不上公网 npm,内网机正常)。

### 1.2 一键安装

```bash
sudo ./deploy/native/tmctl.sh install --auto --yes
```

`--auto` = 缺什么依赖自己装;`--yes` = 非交互。

9 步依次是:体检 → 生成配置 → 服务用户 → 本机 MySQL → 本机 Redis →
Python 依赖 → 前端构建 → 资产市场 SSH 身份 → 注册 systemd + 启动 + 建 admin。

**装完会打印**:

```
前端:       http://10.20.65.25:8090
API 文档:   http://10.20.65.25:8090/docs
后端直连:   http://127.0.0.1:8000/docs   (只监听本机)
开机自启:   已启用
```

### 1.3 装完必须做的三件事

| # | 事项 | 怎么做 |
|---|---|---|
| 1 | **记下 admin 口令** | install 结束时打印;`.env` 里的 `ADMIN_DEFAULT_PASSWORD` 也是它 |
| 2 | **填资产市场 GitLab 地址** | 设置页 → 扩展市场 → 仓库地址(见 §5.1) |
| 3 | **配钉钉/通知** | 设置页 → 通知(可选) |

---

## 2. 日常运维

```bash
cd /home/workflow/TestMate
S=deploy/native/tmctl.sh

sudo $S status              # 状态: 服务 / 端口 / 健康
sudo $S logs -f             # 跟日志 (后端+前端)
sudo $S logs -f testmate-backend
sudo $S restart             # 重启
sudo $S reload              # 只重载 nginx (后端不动)
sudo $S stop / start
sudo $S enable / disable    # 开机自启
sudo $S doctor              # 深度排障 (比 check 看得深)
sudo $S backup              # 备份 (MySQL + 配置)
```

---

## 3. ★ 更新部署流程(改代码后)

这是最容易踩坑的一段,**顺序不能乱**。

### 3.1 标准流程

```bash
cd /home/workflow/TestMate

# ① 备份数据库 (迁移会改 schema, 先留个还原点)
mkdir -p /home/backup/testmate-$(date +%F)
mysqldump -utestmate -p'<密码>' -h 127.0.0.1 --single-transaction \
  --routines --triggers testmate \
  > /home/backup/testmate-$(date +%F)/testmate-pre.sql

# ② 同步代码 (见 §4 —— 这台机器有坑)
#    要点: 别用 git clone/pull (25 连不上 github), 用打包上传

# ③ 前端改动必须重新 build —— ⚠️ 不 build 就是线上跑旧代码!
cd frontend_web && npm run build && cd ..

# ④ 拷到 runtime/frontend (nginx 实际服务这个目录)
rm -rf deploy/native/runtime/frontend
mkdir -p deploy/native/runtime/frontend
cp -R frontend_web/dist/. deploy/native/runtime/frontend/
chown -R testmate:testmate deploy/native/runtime/frontend

# ⑤ 重启后端 (加载新的 Python 代码)
sudo systemctl restart testmate-backend

# ⑥ 重启前端 (让它读新的 runtime/frontend)
sudo systemctl restart testmate-frontend

# ⑦ 验证
curl -s http://127.0.0.1:8090/api/v1/health     # {"status":"ok",...}
sudo deploy/native/tmctl.sh status
```

### 3.2 ⚠️ 最容易忘的一步:前端 build

`check_deploy.sh` 这个脚本就是专门防这个的 —— **改了前端源码忘了 build**,
线上跑的还是旧 bundle,e2e 全绿但测的是旧代码。

```bash
# 漂移检测: 挑几个只在新源码里出现的特征串, 确认 bundle 里也有
scripts/check_deploy.sh
```

**自己判断要不要 build**:改了 `frontend_web/src/**` → **必须 build**;
只改了 `backend_gateway/**` → 不用 build,重启后端即可。

### 3.3 数据库迁移会自动跑

后端启动时 (`app/main.py` 的 lifespan) 会跑 `alembic upgrade head`。
**不用手动跑**。看日志确认:

```bash
journalctl -u testmate-backend --since "5 min ago" | grep -i "init_db"
# [init_db] 当前迁移版本 0028_kb_ownerships, 执行 upgrade head
```

⚠️ **迁移前一定要备份**(§3.1 步骤 ①)。迁移失败会让后端起不来。

### 3.4 `tmctl.sh install` 可以重跑(幂等)

重跑 install 是安全的,各步都会跳过已完成的部分:

| 步骤 | 重跑时 |
|---|---|
| 体检 | 只读 |
| 生成配置 | `.env` 已存在 → 只同步 `REPO_ROOT`;端口被自己占用 → 保持不变 |
| 服务用户 | 已存在 → 跳过 |
| MySQL / Redis | 连得上 → 跳过 |
| Python 依赖 | venv 已存在 → 不重建;版本一致 → 只校验 |
| 前端构建 | **有 node_modules → 跳过 npm,只 build**(见 §4.3) |
| systemd | 重渲染 unit + enable |

唯一实际动作是「重启服务 + 前端重新 build」。

---

## 4. ★ 这台机器的三个坑

### 4.1 25 连不上公网 —— npm / pypi 要分别处理

| 东西 | 状态 | 怎么办 |
|---|---|---|
| pypi | ✅ 通 `http://10.20.27.253/aliyun/pypi/simple/` | `pip.conf` 已配好,直接用 |
| npm registry | ❌ **全部不通**(npmmirror / npmjs / 腾讯 / 华为都 ECONNRESET) | 见 §4.2 |
| github | ❌ 不通 | 代码只能**打包上传**,不能 clone/pull |

内网镜像站 `10.20.27.253` 只有 yum 和 pypi,**没有 npm**。

### 4.2 前端依赖:离线 tarball

`node_modules` 是靠本机 `npm pack` 打的干净 tarball 手工装好的
(位置 `/tmp/tm-pkgs/`,**已清理,需要时重做**)。流程:

```bash
# ① 本机 (Windows, 能连 npm):打 tarball
cd <本地代码目录>/frontend_web
npm install --registry=https://registry.npmmirror.com/     # 先装出 node_modules
npm pack <每个依赖>@<版本> --pack-destination ./pkgs       # 逐个 pack
tar -czf pkgs.tar.gz pkgs/

# ② 上传到 25,解压
tar -xzf pkgs.tar.gz -C /tmp/tm-pkgs/

# ③ 按 package-lock.json 的权威路径解包 (npm install 装不了, 连不上 registry)
python3 /tmp/install-by-lock.py

# ④ 补装 lock 里没有的平台包 (esbuild / rollup 的 linux-x64)
python3 /tmp/install-platform-pkgs.py

# ⑤ chmod +x (Windows 打的包没有执行位)
chmod +x node_modules/.bin/*
```

⚠️ **两个坑**:
- `npm install --offline <tarball>` **不行** —— npm 还要 registry 的 packument
  (包元数据), 会卡在 `fetch manifest`。
- 必须**按 `package-lock.json` 的完整路径**解包。npm 的扁平化会把
  `estree-walker` 2.x/3.x 装到同一个位置, 冲突 → `MODULE_NOT_FOUND`。

### 4.3 ⚠️ Defender 会篡改源码(Windows 本机)

本机 Defender 的篡改检测会给新写入的 `.vue` / `.ts` / `.js` **文本文件**
加一个 `%TSD-Header-###%` 二进制头。表现:

```
[vite:vue] AssetDetailDrawer.vue (6:113): Attribute name cannot contain U+0022 (")
```

**症状**:同一份代码在 GitHub 上是好的,打包传到 25 就编译失败。

**排查**:

```bash
# 在 25 上扫一遍有没有被污染
grep -rlI '^%TSD-Header' /home/workflow/TestMate 2>/dev/null
# 或
python3 -c "
import os
for r,d,fs in os.walk('/home/workflow/TestMate'):
    for f in fs:
        p=os.path.join(r,f)
        try:
            if open(p,'rb').read(16).startswith(b'%TSD-Header'): print(p)
        except OSError: pass"
```

**解法:base64 传输**(纯文本不过 Defender):

```bash
# 本机
git show HEAD:<相对路径> | base64 -w0 > /tmp/file.b64
# 上传 /tmp/file.b64,25 上
base64 -d /tmp/file.b64 > <目标路径>.tmp && mv <目标路径>.tmp <目标路径>
```

⚠️ `git checkout -- <file>` **没用** —— Defender 会在恢复后立刻重新污染。

⚠️ 同理,本机 `npm install` 装出来的 `node_modules` 也会被污染。
**`npm pack` 出来的 tarball 是干净的**(gzip 二进制),所以走 pack 路线。

---

## 5. 资产市场(GitLab)配置

### 5.1 仓库地址 —— SSH URL 格式容易错

```
✅ ssh://git@10.20.27.7/epc/skills_market.git
❌ ssh://git@10.20.27.7:epc/skills_market.git
```

⚠️ **SSH URL 里冒号后面是端口号**, `epc` 不是数字 → git 报:

```
ssh: Could not resolve hostname 10.20.27.7:epc
```

GitLab 的组/命名空间(`epc`)是**路径的一部分**,不是端口。

配好后确认后端拿到了:

```bash
journalctl -u testmate-backend --since "5 min ago" | grep git_config
# {"remote": "ssh://git@10.20.27.7/epc/skills_market.git", "branch": "main", ...}
```

### 5.2 SSH 身份

```bash
# 看市场用的公钥 (贴到 GitLab 账号的 SSH Keys)
sudo deploy/native/tmctl.sh ssh show

# 钉住 GitLab 主机的 host key
sudo deploy/native/tmctl.sh ssh trust
```

自测连通:

```bash
ssh -i deploy/native/runtime/ssh/id_ed25519 -o IdentitiesOnly=yes \
    -o UserKnownHostsFile=deploy/native/runtime/ssh/known_hosts \
    -o BatchMode=yes -T git@10.20.27.7
# Welcome to GitLab, @<你的用户名>!
```

### 5.3 配置存在哪

**DB 优先**(设置页改的为准),env 只是初值:

| 位置 | 变量 | 说明 |
|---|---|---|
| `.env` | `EXTENSIONS_GIT_REMOTE` | 初值 |
| `runtime/config/backend.env` | `EXTENSIONS_GIT_REMOTE` | 由 `.env` 渲染, 后端读它 |
| DB `system_settings` | `extensions.git.remote` | **设置页改这个**, 改完立即生效 |

⚠️ 变量名从 `MARKET_*` 改成了 `EXTENSIONS_*`(2026-11-02)。
老的 `.env` 里还是旧名 → `cfg()` 会自动回退读旧名,但**建议直接改成新名**。

---

## 6. 备份与恢复

```bash
sudo deploy/native/tmctl.sh backup                    # 默认 /var/backups/testmate
sudo deploy/native/tmctl.sh backup /home/backup/tm
sudo deploy/native/tmctl.sh restore <备份目录> --dry-run   # 先演练
sudo deploy/native/tmctl.sh restore <备份目录>
```

⚠️ `backup` **只备份 MySQL + 配置**。这些**不在备份里**,要另外拷:

| 目录 | 内容 | 体积 |
|---|---|---|
| `runtime/data/software/` | 软件包落盘(最多 5G/个) | 大 |
| `runtime/market/` | 资产市场 git 工作区 | 中 |
| `runtime/frontend/` | 前端产物(可从源码重建) | 小 |
| `runtime/venv/` | Python venv(可从 requirements.lock 重建) | ~135M |

**代码本身的备份**:

```bash
tar -czf /home/backup/testmate-code-$(date +%Y%m%d-%H%M).tar.gz \
    --exclude=node_modules --exclude=.venv --exclude=runtime \
    -C /home/workflow TestMate
```

---

## 7. 排障

### 7.1 服务起不来

```bash
sudo systemctl status testmate-backend
journalctl -u testmate-backend --no-pager -n 50
sudo deploy/native/tmctl.sh doctor
```

**常见原因**:

| 日志里的关键字 | 原因 | 解决 |
|---|---|---|
| `FileNotFoundError: ... alembic` | systemd 的 PATH 里没有 venv/bin | unit 模板要加 `Environment=PATH=@@VENV_BIN@@:...` |
| `No matching distribution found for fastapi` | 建 venv 用了 python3(3.9) | `tmctl.sh` / `preflight.sh` 要用 `PYTHON_BIN` 挑 3.11+ |
| `Application startup failed` | 迁移失败 | 看日志里的 alembic 报错;必要时从备份恢复 |
| `MODULE_NOT_FOUND` (前端 build) | node_modules 被 npm 重装成别的平台的二进制 | 见 §4.2 |

### 7.2 前端显示旧功能

**几乎都是忘了 build**(§3.2)。查:

```bash
# 源码里的特征串在 bundle 里有没有
grep -rqF '特征串' frontend_web/src && echo "源码有"
grep -rqF '特征串' deploy/native/runtime/frontend/assets/ && echo "bundle 有"
# 只有一个有 = 漂移了, 重新 build
```

### 7.3 资产上架推不出去

```bash
# ① 后端拿到的远端地址对不对
journalctl -u testmate-backend --since "10 min ago" | grep git_config

# ② 工作区的 origin 对不对 (空 = 被清空了, 见 §7.4)
git -C deploy/native/runtime/market remote -v
git -C deploy/native/runtime/market config --get remote.origin.url

# ③ SSH 通不通
ssh -i deploy/native/runtime/ssh/id_ed25519 -o IdentitiesOnly=yes \
    -o UserKnownHostsFile=deploy/native/runtime/ssh/known_hosts \
    -o BatchMode=yes -T git@10.20.27.7

# ④ 手动试一次 push
K=deploy/native/runtime/ssh/id_ed25519
KH=deploy/native/runtime/ssh/known_hosts
sudo -u testmate env GIT_SSH_COMMAND="ssh -i $K -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$KH -o BatchMode=yes" \
  git -C deploy/native/runtime/market push --dry-run origin HEAD:main
```

### 7.4 ⚠️ `fatal: no path specified`

```
fatal: no path specified; see 'git help pull' for valid url syntax
```

**含义**:`remote.origin.url` **被清空了**。git 把 `origin main` 当成两个**路径**
而不是 "remote + refspec"。

**原因**:远端地址为空时,`git remote set-url origin ""` 会把 URL 清掉,
之后所有 fetch/push 全挂。而且错误在 stderr 里,前端显示成
`git 失败 (rc=1):` —— **错误消息是空的**,看不出原因。

**已修**(2026-11-03,commit `1a9b6d3`):地址为空时**原样不动**,并抛说人话的错。

**手工恢复**:

```bash
sudo -u testmate git -C deploy/native/runtime/market \
  remote set-url origin "ssh://git@10.20.27.7/epc/skills_market.git"
```

### 7.5 端口漂移

`install` 时端口被占会自动往后找空闲端口(8090→8091)。**已修**(commit `1a9b6d3`):
`port_is_own_service` 现在认 systemd 的 MainPID。

**手工固定**:

```bash
# .env 里改, 然后重新 install
sed -i 's|^FRONTEND_PORT=.*|FRONTEND_PORT=8090|' deploy/native/.env
sed -i 's|^BACKEND_PORT=.*|BACKEND_PORT=8000|' deploy/native/.env
sudo deploy/native/tmctl.sh install --auto --yes
```

⚠️ 改完端口要**同时**检查 nginx 反代目标和 `runtime/config/backend.env`。

---

## 8. 一页速查

```bash
cd /home/workflow/TestMate
S=deploy/native/tmctl.sh

# 状态 / 日志 / 重启
sudo $S status ; sudo $S logs -f ; sudo $S restart

# 更新部署(改代码后)
mysqldump -utestmate -p'***' -h 127.0.0.1 --single-transaction testmate \
  > /home/backup/tm-$(date +%F).sql
# 同步代码(打包上传,见 §4.2)
cd frontend_web && npm run build && cd ..
rm -rf deploy/native/runtime/frontend && mkdir -p deploy/native/runtime/frontend
cp -R frontend_web/dist/. deploy/native/runtime/frontend/
chown -R testmate:testmate deploy/native/runtime/frontend
sudo systemctl restart testmate-backend testmate-frontend
curl -s http://127.0.0.1:8090/api/v1/health

# 备份
sudo $S backup /home/backup/tm

# 排障
sudo $S doctor
journalctl -u testmate-backend --no-pager -n 50
```

**三个最容易忘的**:

1. 改前端 → **必须 `npm run build`**(否则线上跑旧代码)
2. 改代码 → **25 不能 git pull**,只能打包上传(§4.1)
3. 迁移前 → **先 mysqldump**(§3.1)
