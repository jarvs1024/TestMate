# 软件库 —— 2026-10-28

> 一句话: **能力墙上的「软件库」卡真能用上了** —— 传任意格式的软件包(≤5G)到服务端磁盘,
> 卡片式浏览, 下载 / 发新版本, 每个软件都能写清楚**功能 / 详情 / 适用场景 / 发布与更新说明**。

---

## 一、为什么它跟「插件·技能·连接」分家

| | 插件·技能·连接 | **软件库** |
|---|---|---|
| 装给谁 | 装进 **Agent** 的扩展 | **人**用的内部软件 |
| 文件长什么样 | 文本包 (zip / tar.gz) | **任意格式的二进制** (exe / deb / img …) |
| 真身在哪儿 | **GitLab** 仓库 (有 git 版本历史) | **服务端磁盘** (本地目录) |
| 上限 | 50 MB | **5 GB** |
| 审核 | 有审核队列 | **上架即上架** (没有审核态) |
| 命名空间 | `/api/v1/assets` | `/api/v1/software` |
| 页面 | `/market` | `/software` |

⚠️ **为什么必须分家**: 二进制根本进不了 GitLab; 5G 的包整包进内存会打死进程;
审核/权限口径也完全不同。硬塞进一张表, 现有市场逻辑会被拖垮。
但**前端视觉保持一致** —— 复用资产卡片的类名体系 (`.asset-card` / `.ac-hd` / `.ac-summary` …),
两个页面看起来是一套东西。

---

## 二、上传:单次流式(不走 multipart)

两步:

```
① POST /api/v1/software              (JSON 元数据)  → 建条目, 版本行 awaiting_file
② PUT  /api/v1/software/{code}/file  (原始字节流)   → 边收边写盘, 版本转 ready, 条目转 published
```

### 为什么不用 multipart

starlette 1.10 的 multipart 会把文件字段先 spool 到**系统临时目录**(1MB 后落盘) ——
5G 的包会在临时目录**再存一份**:磁盘翻倍,容器模式下还会撑爆可写层。
所以端点直接拿 `Request`,`async for chunk in request.stream()` 逐块写盘。

### 落盘过程

```
<root>/.tmp/<uuid>.part      ← 边收边写, 同时算 sha256 / 计数
<root>/<code>/<version>/<清洗后的文件名>   ← os.replace 原子改名
<root>/<code>/<version>/release.json      ← 该版本的元信息快照
```

- **原子改名**: 中途断线只会多一个 `.part` 残留, 不会多一个"半个软件包"(半个包被当成完整版本,
  用户下下来才发现是坏的)。
- **实收 ≠ 声明** → 409「传输可能中断了, 请重传」(在改名**之前**判定, 半截文件不会落到正式目录)。
- **超过上限** → 413 + 删临时文件(不留残留)。
- **磁盘满**(ENOSPC)→ 500 + 人话「服务端磁盘空间不足」。
- **上传中断** → 版本行留在 `awaiting_file`/`failed`, 用户可以重传(覆盖)。

---

## 三、下载:短时票据,不是 blob

```
① POST /api/v1/software/{code}/download-ticket  (Bearer) → {"url": ".../dl?t=<jwt>&v=<ver>", "expires_in": 600}
② GET  /api/v1/software/dl?t=...                  (无 Authorization 头) → FileResponse 流式回传
```

⚠️ **为什么不用 blob**: 5G 的 blob 会把浏览器内存打爆 —— 必须让浏览器自己流式落盘。
前端用 `window.location.href = url` 把 url 交给**浏览器原生下载器**。

⚠️ **为什么不把长期 token 拼进 URL**: 会进 nginx access_log 和浏览器历史 —— 谁都能捡走。
短时票窗口 10 分钟、绑定具体版本、可撤销。

票据校验:签名有效 + 未过期 + 类型对得上 + **用户仍存在且未停用** + 该版本仍是 `ready`。
匿名也能要票,但要管理员开了 `software.public_download`。

---

## 四、数据模型

```
software_items                 (条目 = 卡片)
  code / name / icon / version / summary / description
  features(JSON)              ← 展示功能
  use_when / not_for          ← 适用场景 / 不适合的场景
  platform / category / tags / keywords
  author / download_count
  publish_status              awaiting_file | published | hidden
  deleted_at                  ← 软删

software_versions             (版本 = 文件)
  item_id / version           (item_id, version) 唯一
  release_notes               ← 发布与更新说明
  file_name / file_path       ← **相对**存储根的路径
  file_size / sha256
  status                      awaiting_file | uploading | ready | failed
  declared_size / last_error
```

⚠️ **`file_path` 存相对路径**:绝对路径换机器 / 改设置项就失效,相对路径不会。

⚠️ **条目与版本是 1:N**: 版本历史要能单独下载、单独带更新说明、能按保留策略清理。

---

## 五、存储路径

| 形态 | 路径 | 怎么来的 |
|---|---|---|
| 裸机 (macOS/Linux) | `<runtime>/data/software` | `tmctl.sh` 写进 `backend.env` 的 `SOFTWARE_STORAGE_PATH` |
| 容器 | `/data/software` | `docker-compose.yml` 的环境变量 + 宿主 `DATA_ROOT/software` 挂载 |

设置项 `software.storage_path` (admin only) 可以改;**留空 = 用环境变量**。
⚠️ **改这个等于换根目录** —— 已传的文件不会自动搬过去,设置页的「检查路径」会列出缺哪些文件。

> ⚠️ **2026-10-28 踩过的坑**: launchd 启动后端时用的是 **plist 里写死的 EnvironmentVariables**,
> 不是 `backend.env`。`local update` 以前只重新生成 `backend.env` → `SOFTWARE_STORAGE_PATH`
> 到不了进程 → 后端默默用了兜底路径 `<仓库>/data/software`,软件包落到了**仓库目录**里。
> 而且光重生成 plist 也不够 —— launchd 只在 bootstrap 那一刻读它,改完必须重新
> `bootout + bootstrap`(`kickstart` 重启的还是旧定义)。
> 现在 `local update` 会重生成 plist **并且**重新装载,`selftest.sh` §6.2 守着这条。

---

## 六、权限与状态

| 动作 | 谁能做 |
|---|---|
| 上传 / 发新版本 | `market_policy.can_publish(user)` —— **复用市场的发布权**,不另设设置项 |
| 改元信息 / 删条目 | **作者本人或管理员** |
| 彻底清理(删文件) | **仅管理员**,二次确认 |
| 匿名下载 | 需管理员开 `software.public_download` |

条目状态:`awaiting_file`(信息填好没传文件,卡片可见但**不可下载**)→ `published` → `hidden`(软删)。
**没有审核态** —— 上架即上架。所有动作进 `asset_audits`(命名空间 `sw:<code>`)。

---

## 七、设置项

| key | 类型 | 默认 | 说明 |
|---|---|---|---|
| `software.storage_path` | string (admin only) | 空 (= 用环境变量) | 存放根目录;改它 = 换根目录,文件要自己搬 |
| `software.max_size_mb` | int | `5120` | 单包上限(5G) |
| `software.keep_versions` | int | `10` | 每个软件保留几个历史版本,超出删最老的(文件也删) |
| `software.public_download` | bool | `false` | 匿名能不能下载 |

---

## 八、nginx(两处都要改)

```nginx
location /api/v1/software {          # ⚠️ 结尾**不能带斜杠**
    proxy_pass http://127.0.0.1:8000;
    client_max_body_size 6g;         # 5G 包 + 余量
    proxy_request_buffering off;     # ★ 边收边转, nginx 不缓冲 5G
    proxy_send_timeout 3600s;
    proxy_read_timeout 3600s;
    proxy_buffering off;             # 下载同样不缓冲
}
```

- 裸机:`deploy/native/units/nginx.conf.tpl`
- 容器:`frontend_web/nginx.conf`

⚠️ **结尾不能带斜杠** (2026-10-28 踩过): nginx 对 `location /xxx/` 会**自动 301 补斜杠**
(像访问目录),而 FastAPI 的路由是 `/api/v1/software`(没斜杠)→ 又 **307 弹回来** →
两边撞成**重定向死循环**,而且 nginx 改写 Location 时按 `$host` 拼会**把端口吞掉**
(`127.0.0.1:8081` → `localhost:80`)→ 最后 `ERR_CONNECTION_REFUSED`,软件列表整个加载不出来。

`selftest.sh` §6.1 盯着两处 nginx:都要有软件库 location、都要放开 body 上限、
都要关 request buffering、结尾都不能带斜杠。

---

## 九、实测结果(裸机)

| 项 | 结果 |
|---|---|
| 200MB 上传(sha256) | 一致 `9a520ae7…` |
| nginx 缓冲目录 | **全程 0KB**(没多存一份) |
| 后端内存 | 117MB → 121MB(+3MB / 200MB 包)= **内存恒定** |
| 后端 `.tmp` | 0 → 196MB → 0(原子改名后清空) |
| 200MB 下载 | 0.35s,sha256 一致 |
| e2e | `scripts/e2e_software.js` 26/26 |

---

## 十、还没做的

- 分片上传 / 断点续传(协议上留了口子:以后可加 `Content-Range`)
- 杀毒扫描
- 软件自动分发到测试机
- 软件许可管理
- 存储总容量上限(暂时只按 `keep_versions` 清理历史版本)
- 跨节点存储(存储是**单机**本地目录)

⚠️ **软件目录不进 `tmctl.sh backup`**(体积太大)—— 要备份得单独拷这个目录。
