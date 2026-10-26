#!/usr/bin/env bash
# TestMate 裸机部署 —— 环境体检
#
# 被 tmctl.sh source 进来. **不要**直接执行.
#
# 两件事:
#   ① 把"这台机器能不能装 TestMate"一次性查清楚 —— 不然装到一半才报缺包, 运维要抓瞎
#   ② 每条检查都给出**怎么修**, 而不是只说"不行"
#
# 原则: check 是**只读**的 —— 不装东西、不改文件、不起服务.
#      真要装东西那是 `tmctl install --auto` 的事 (它会先跑本文件的 check).

# ---------- 包名映射 (不同发行版叫法不一样) ----------
pkg_name() {
  local logical="$1" mgr="$2"
  case "$logical:$mgr" in
    python3:dnf|python3:yum|python3:zypper) echo "python3" ;;
    python3:apt-get) echo "python3" ;;
    python-devel:dnf|python-devel:yum|python-devel:zypper) echo "python3-devel" ;;
    python-devel:apt-get) echo "python3-dev" ;;
    python-venv:dnf|python-venv:yum) echo "python3" ;;
    python-venv:apt-get) echo "python3-venv" ;;
    pip:dnf|pip:yum|pip:zypper) echo "python3-pip" ;;
    pip:apt-get) echo "python3-pip" ;;
    libffi-dev:dnf|libffi-dev:yum|libffi-dev:zypper) echo "libffi-devel" ;;
    libffi-dev:apt-get) echo "libffi-dev" ;;
    ssl-dev:dnf|ssl-dev:yum|ssl-dev:zypper) echo "openssl-devel" ;;
    ssl-dev:apt-get) echo "libssl-dev" ;;
    compiler:dnf|compiler:yum|compiler:zypper) echo "gcc" ;;
    compiler:apt-get) echo "build-essential" ;;
    nginx:*) echo "nginx" ;;
    git:*) echo "git" ;;
    ssh:dnf|ssh:yum|ssh:zypper) echo "openssh-clients" ;;
    ssh:apt-get) echo "openssh-client" ;;
    mysql:dnf|mysql:yum) echo "mysql-server" ;;
    mysql:apt-get) echo "mysql-server" ;;
    mysql:zypper) echo "mysql-server" ;;
    mariadb:dnf|mariadb:yum) echo "mariadb-server" ;;
    mariadb:apt-get) echo "mariadb-server" ;;
    redis:dnf|redis:yum|redis:zypper) echo "redis" ;;
    redis:apt-get) echo "redis-server" ;;
    nodejs:dnf|nodejs:yum) echo "nodejs" ;;
    nodejs:apt-get) echo "nodejs" ;;
    nodejs:zypper) echo "nodejs" ;;
    *) echo "$logical" ;;
  esac
}

# 用包管理器装一个逻辑包
# ⚠️ 失败时**不吞错误** —— 把日志留在 PKG_LOG 里, 由调用方打出来.
#    以前这里 `>/dev/null 2>&1`, 结果 apt 装不上时用户只看到"自动安装失败",
#    不知道是包名不对 / 没 apt-get update / 没外网 —— 装机现场最费时间的就是这个.
PKG_LOG=""
APT_UPDATED=0
pkg_install() {
  local logical="$1" mgr="$2"
  local pkg
  pkg="$(pkg_name "$logical" "$mgr")"
  PKG_LOG="$(mktemp)"
  case "$mgr" in
    dnf)
      dnf install -y "$pkg" >"$PKG_LOG" 2>&1 ;;
    yum)
      yum install -y "$pkg" >"$PKG_LOG" 2>&1 ;;
    apt-get)
      # ⚠️ 必须先 update —— 刚装好的机器 / 长期不更新的机器, 包列表是空的,
      #    直接 install 会报 "Unable to locate package" 但看不出真实原因.
      #    ⚠️ 但**只 update 一次** —— 体检要装七八个包, 每次都 update 会慢到没法用.
      if [[ $APT_UPDATED -eq 0 ]]; then
        DEBIAN_FRONTEND=noninteractive apt-get update -qq >>"$PKG_LOG" 2>&1 || true
        APT_UPDATED=1
      fi
      DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg" >>"$PKG_LOG" 2>&1 ;;
    zypper)
      zypper --non-interactive install "$pkg" >"$PKG_LOG" 2>&1 ;;
    pacman)
      pacman -S --noconfirm "$pkg" >"$PKG_LOG" 2>&1 ;;
    *)
      echo "不认识的包管理器: $mgr" >"$PKG_LOG"
      return 1 ;;
  esac
}

# 打印上次 pkg_install 的日志尾部
pkg_log_tail() {
  [[ -n "$PKG_LOG" && -f "$PKG_LOG" ]] || return 0
  tail -n 8 "$PKG_LOG" | sed 's/^/        /'
}

# ---------- 单项依赖检查 ----------
# check_dep <逻辑名> <人类名> <最低版本> <安装提示>
# 有 --auto 时先尝试装
check_dep() {
  local logical="$1" label="$2" minver="$3" hint="$4"
  local cmdname version

  case "$logical" in
    python3) cmdname="python3" ;;
    pip)     cmdname="pip3" ;;
    node)    cmdname="node" ;;
    npm)     cmdname="npm" ;;
    *)       cmdname="$logical" ;;
  esac

  if ! have_cmd "$cmdname"; then
    if [[ "${PREFLIGHT_AUTO:-0}" == "1" ]]; then
      info "安装 $label ..."
      if pkg_install "$logical" "$PKG_MGR"; then
        have_cmd "$cmdname" || { chk_fail "$label 装完仍不可用 ($cmdname)"; return 1; }
      else
        chk_fail "$label 缺失 —— 自动安装失败, 手动装: $hint"
        echo "        ── 安装日志尾部 ──"
        pkg_log_tail
        return 1
      fi
    else
      chk_fail "$label 缺失 —— 手动装: $hint"
      return 1
    fi
  fi

  version="$(cmd_version "$cmdname" || true)"
  if [[ -n "$minver" && -n "$version" ]] && ! ver_ge "$version" "$minver"; then
    chk_fail "$label 版本过低 ($version < $minver) —— $hint"
    return 1
  fi
  chk_pass "$label $version"
  return 0
}

# ---------- 主检查流程 ----------
preflight_run() {
  detect_os
  PKG_MGR="$(detect_pkg_mgr)"

  echo "${C_BOLD}TestMate 裸机部署 · 环境体检${C_OFF}"
  echo "  模式: native (systemd + 裸进程)"

  # ============ 一、系统 ============
  section "一、系统"

  case "$OS_ID" in
    ubuntu|debian|rhel|centos|rocky|almalinux|anolis|openeuler|feanolis|kylin)
      chk_pass "操作系统: $OS_NAME" ;;
    *)
      chk_warn "操作系统: $OS_NAME —— 不在验证过的列表里 (Ubuntu/Debian/RHEL/Rocky/Alma/Anolis/openEuler/Kylin), 出问题请先看日志" ;;
  esac

  if [[ "$OS_ARCH" == "x86_64" || "$OS_ARCH" == "aarch64" ]]; then
    chk_pass "架构: $OS_ARCH"
  else
    chk_warn "架构: $OS_ARCH —— 只在 x86_64 / aarch64 上验证过"
  fi

  local kepoch
  kepoch="$(kernel_epoch)"
  if [[ $kepoch -ge 5004000 ]]; then
    chk_pass "内核: $(uname -r)"
  else
    chk_warn "内核 $(uname -r) 偏老 (建议 >= 5.4)"
  fi

  if systemd_available; then
    chk_pass "systemd: 可用 (开机自启动靠它)"
  elif [[ "${PREFLIGHT_DRIVER:-systemd}" == "local" ]]; then
    # local driver: 进程用 PID 文件管, 开机自启靠 launchd —— systemd 本来就不需要
    chk_pass "systemd: 不需要 (local 模式 —— 进程用 PID 文件管, 开机自启用 launchd)"
  else
    chk_fail "systemd 不可用 —— 裸机模式靠 systemd 管进程和开机自启; 容器里 PID1 不是 systemd 时请用 Docker 模式 (deploy/deploy.sh)"
  fi

  if is_root; then
    chk_pass "权限: root"
  else
    chk_warn "权限: 非 root —— install / start / stop 需要 sudo (检查本身不需要)"
  fi

  if [[ -n "$PKG_MGR" ]]; then
    chk_pass "包管理器: $PKG_MGR"
  else
    chk_warn "没认出来包管理器 (dnf/yum/apt-get/zypper/pacman) —— 缺依赖只能手动装"
  fi

  # ============ 二、运行时依赖 ============
  section "二、运行时依赖"

  check_dep python3 "Python" "3.11" \
    "需要 Python >= 3.11 (3.10 及以下跑不动): ${PKG_MGR:+$(pkg_name python3 "$PKG_MGR")}" || true

  # venv 模块 (Debian/Ubuntu 上 python3 与 venv 是分开的包)
  if have_cmd python3 && python3 -c 'import venv' >/dev/null 2>&1; then
    chk_pass "Python venv 模块: 可用"
  elif [[ "${PREFLIGHT_AUTO:-0}" == "1" ]] && [[ -n "$PKG_MGR" ]]; then
    if pkg_install python-venv "$PKG_MGR"; then
      chk_pass "Python venv 模块: 已安装"
    else
      chk_fail "Python venv 模块缺失 —— 装: $(pkg_name python-venv "$PKG_MGR")"
      pkg_log_tail
    fi
  else
    chk_fail "Python venv 模块缺失 —— 装: $(pkg_name python-venv "$PKG_MGR") (Debian/Ubuntu 上 python3 不含 venv)"
  fi

  check_dep pip "pip" "" "pip3 装不上就先装 python3-pip" || true

  # ⚠️ Node 的坑: 发行版自带的 nodejs 往往**太老** ——
  #    Ubuntu 22.04 = v12 / RHEL9 = v16 / Debian 12 = v18.
  #    vite 5 要求 >= 18, 所以装了 nodejs 包还是过不了关.
  #    提示里直接给 NodeSource 的命令, 别让人卡在"装完了还是不行".
  local node_hint="需要 Node >= 18 (vite 5 的要求)"
  case "$OS_ID" in
    ubuntu|debian)
      node_hint="需要 Node >= 18 (vite 5 的要求); ⚠️ 本发行版自带的 nodejs 是 v12, 不够 —— 用 NodeSource: curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y nodejs" ;;
    *)
      node_hint="需要 Node >= 18 (vite 5 的要求); ⚠️ 发行版自带的 nodejs 可能太老, 建议用 NodeSource 装 20.x" ;;
  esac
  check_dep node "Node.js" "18" "$node_hint" || true
  check_dep npm "npm" "" "跟 Node 一起装 (NodeSource 装完自带 npm)" || true

  # 编译依赖 —— bcrypt / cryptography / aiomysql 里的 cryptography 要编译
  if have_cmd gcc && have_cmd make; then
    chk_pass "编译工具: $(cmd_version gcc) gcc"
  else
    if [[ "${PREFLIGHT_AUTO:-0}" == "1" ]] && [[ -n "$PKG_MGR" ]]; then
      pkg_install compiler "$PKG_MGR" || true
    fi
    if have_cmd gcc; then
      chk_pass "编译工具: gcc"
    else
      chk_fail "缺 gcc/make —— cryptography 要编译 wheel: $(pkg_name compiler "$PKG_MGR")"
      pkg_log_tail
    fi
  fi

  # Python 头文件 (编译扩展模块需要)
  local py_ok=0
  if python3 -c 'import sysconfig,sys; p=sysconfig.get_paths()["include"]; import os; sys.exit(0 if os.path.exists(os.path.join(p,"Python.h")) else 1)' >/dev/null 2>&1; then
    py_ok=1
  else
    if [[ "${PREFLIGHT_AUTO:-0}" == "1" ]] && [[ -n "$PKG_MGR" ]]; then
      pkg_install python-devel "$PKG_MGR" || true
      python3 -c 'import sysconfig,sys,os; p=sysconfig.get_paths()["include"]; sys.exit(0 if os.path.exists(os.path.join(p,"Python.h")) else 1)' >/dev/null 2>&1 && py_ok=1
    fi
  fi
  if [[ $py_ok -eq 1 ]]; then
    chk_pass "Python 开发头文件: 有"
  else
    chk_fail "缺 Python.h —— 装: $(pkg_name python-devel "$PKG_MGR")"
    pkg_log_tail
  fi

  check_dep nginx "nginx" "" \
    "nginx 用来托管前端静态文件 + 反代 /api/; 装: $(pkg_name nginx "$PKG_MGR")" || true
  check_dep git "git" "" \
    "git 是资产市场 commit/push 的硬依赖; 装: $(pkg_name git "$PKG_MGR")" || true
  check_dep ssh "SSH 客户端" "" \
    "资产市场走 SSH 连 GitLab; 装: $(pkg_name ssh "$PKG_MGR")" || true

  # ============ 三、数据存储 ============
  section "三、数据存储"

  local mycli
  mycli="$(mysql_client_cmd)"
  if [[ -n "$mycli" ]]; then
    chk_pass "MySQL/MariaDB 客户端: $mycli $(cmd_version "$mycli")"
  else
    chk_warn "没有 mysql/mariadb 客户端 —— 装一个: mac: brew install mysql  (Linux: $(pkg_name mysql "$PKG_MGR"))"
  fi

  # MySQL 服务 —— 按这台机器用哪套服务管理来判 (systemd / brew)
  case "$(service_backend)" in
    brew)
      if brew_formula_installed mysql; then
        local my_st
        my_st="$(brew_service_status mysql)"
        if [[ "$my_st" == "started" ]]; then
          chk_pass "MySQL 服务: brew services ($my_st)"
        else
          chk_warn "MySQL 装好了但没在跑 ($my_st) —— 起: brew services start mysql"
        fi
      else
        chk_warn "本机没有 MySQL —— 装: brew install mysql   (加 --auto 让脚本自己装)"
      fi ;;
    systemd)
      if unit_exists "mysqld.service" || unit_exists "mariadb.service" || unit_exists "mysql.service"; then
        chk_pass "MySQL 服务: 宿主机已装 (unit: $(mysql_service_name))"
      elif have_cmd mysqld || have_cmd mariadbd; then
        chk_warn "有 mysqld 二进制但没有 systemd 服务 —— 装: $(pkg_name mysql "$PKG_MGR")"
      else
        chk_warn "宿主机没有 MySQL —— 装: $(pkg_name mysql "$PKG_MGR") (或 $(pkg_name mariadb "$PKG_MGR"))"
      fi ;;
    *)
      chk_fail "这台机器既没有 systemd 也没有 brew —— 装不了本机 MySQL (裸机部署不用容器, 必须本机服务)" ;;
  esac

  if have_cmd redis-cli; then
    chk_pass "Redis 客户端: $(cmd_version redis-cli)"
  else
    chk_warn "没有 redis-cli —— 装: mac: brew install redis  (Linux: $(pkg_name redis "$PKG_MGR"))"
  fi

  # Redis 服务 —— 同样分 systemd / brew
  case "$(service_backend)" in
    brew)
      if brew_formula_installed redis; then
        local rd_st
        rd_st="$(brew_service_status redis)"
        if [[ "$rd_st" == "started" ]]; then
          chk_pass "Redis 服务: brew services ($rd_st)"
        else
          chk_warn "Redis 装好了但没在跑 ($rd_st) —— 起: brew services start redis"
        fi
      else
        chk_warn "本机没有 Redis —— 装: brew install redis   (加 --auto 让脚本自己装)"
      fi ;;
    systemd)
      if unit_exists "redis.service" || unit_exists "redis-server.service"; then
        chk_pass "Redis 服务: 宿主机已装 (unit: $(redis_service_name))"
      else
        chk_warn "宿主机没有 Redis —— 装: $(pkg_name redis "$PKG_MGR")"
      fi ;;
    *)
      chk_fail "这台机器既没有 systemd 也没有 brew —— 装不了本机 Redis (裸机部署不用容器, 必须本机服务)" ;;
  esac

  # ============ 四、端口 ============
  section "四、端口占用"

  local fe_port be_port my_port rd_port
  fe_port="$(env_get "$ENV_FILE" "FRONTEND_PORT" || echo 8080)"
  be_port="$(env_get "$ENV_FILE" "BACKEND_PORT" || echo 8000)"
  my_port="$(env_get "$ENV_FILE" "MYSQL_PORT" || echo 3306)"
  rd_port="$(env_get "$ENV_FILE" "REDIS_PORT" || echo 6379)"

  check_port_free() {
    local p="$1" label="$2" reuse="$3"
    if ! port_in_use "$p"; then
      chk_pass "$label 端口 $p: 空闲"
      return 0
    fi
    # ⚠️ 自己占的端口**不是问题** —— 那是服务正在跑.
    #    以前一律报 "被占用, 换端口", 让人以为装不了 (其实服务跑得好好的).
    if port_owned_by_ours "$p"; then
      chk_pass "$label 端口 $p: 被**本部署自己**占用 (服务在跑 —— 预期内)"
      return 0
    fi
    local owner
    owner="$(port_owner "$p")"
    if [[ "$reuse" == "yes" ]]; then
      # MySQL/Redis 本来就该在监听 —— 但要确认占着的确实是它, 不是别的程序
      if [[ -n "$owner" ]] && echo "$owner" | grep -qiE 'mysql|maria|redis'; then
        chk_pass "$label 端口 $p: 已被 $owner 占用 (预期内, 复用它)"
      elif [[ -n "$owner" ]] && echo "$owner" | grep -qiE 'docker'; then
        # ⚠️ 这是 Docker 模式映射出来的**容器**端口 ——
        #    裸机部署不能连它 (容器一停, 裸机后端就废了).
        chk_warn "$label 端口 $p: 是 Docker 模式映射出来的容器端口 ($owner) —— 裸机部署要用**本机**服务"
        chk_warn "  装的时候会自动换回本机默认端口 (MySQL 3306 / Redis 6379); 想自己指定就改 .env 的 $label 端口"
      else
        chk_warn "$label 端口 $p: 被别的程序占用${owner:+ (PID $owner)} —— 装完连不上, 改 .env 的 $label 端口"
      fi
      return 0
    fi
    chk_fail "$label 端口 $p: 被占用${owner:+ (PID $owner)} —— 换端口: 改 .env 里的 $label"
    return 1
  }

  # ⚠️ 每项都要 `|| true` —— 脚本开着 set -e, 一项没过就把体检掐断,
  #    后面的章节压根不跑. 体检的价值是"一次跑完, 列出所有问题 + 怎么修".
  check_port_free "$fe_port" "FRONTEND" "no" || true
  check_port_free "$be_port" "BACKEND" "no" || true
  check_port_free "$my_port" "MYSQL" "yes" || true
  check_port_free "$rd_port" "REDIS" "yes" || true

  # ============ 五、资源 ============
  section "五、机器资源"

  local disk_gb mem_gb
  disk_gb="$(disk_free_gb "$REPO_ROOT")"
  if [[ -n "$disk_gb" && "$disk_gb" -ge 10 ]]; then
    chk_pass "磁盘剩余: ${disk_gb} GB"
  elif [[ -n "$disk_gb" ]]; then
    chk_warn "磁盘只剩 ${disk_gb} GB (建议 >= 10 GB: venv + node_modules + 镜像 + 数据库各占一块)"
  else
    chk_warn "读不到磁盘剩余"
  fi

  mem_gb="$(mem_total_gb)"
  if [[ -n "$mem_gb" && "$mem_gb" -ge 4 ]]; then
    chk_pass "内存: ${mem_gb} GB"
  elif [[ -n "$mem_gb" ]]; then
    chk_warn "内存只有 ${mem_gb} GB (建议 >= 4 GB; 跟 MySQL 同机时更吃内存)"
  else
    chk_warn "读不到内存大小"
  fi

  # ============ 六、目录与权限 ============
  section "六、目录与权限"

  if [[ -d "$REPO_ROOT" && -r "$REPO_ROOT" ]]; then
    chk_pass "源码目录: $REPO_ROOT"
  else
    chk_fail "源码目录不可读: $REPO_ROOT"
  fi

  # ⚠️ **不建目录** —— check 承诺只读, 不留任何痕迹.
  #    找最近的已存在祖先, 看能不能写.
  local wanc
  if wanc="$(nearest_writable_ancestor "$RUNTIME_DIR")"; then
    chk_pass "运行时目录可写: $RUNTIME_DIR (祖先 $wanc 可写)"
  else
    chk_fail "运行时目录不可写: $RUNTIME_DIR —— 用 sudo 跑 install, 或改 .env 里的 RUNTIME_DIR"
  fi

  # ============ 七、配置 ============
  section "七、部署配置"

  if [[ -f "$ENV_FILE" ]]; then
    chk_pass "配置文件: $ENV_FILE"
  else
    chk_warn "没有 $ENV_FILE —— install 会从模板生成 (记得改里面的口令)"
  fi

  if [[ -f "$ENV_FILE" ]]; then
    local jwt mypwd adminpwd
    jwt="$(env_get "$ENV_FILE" "JWT_SECRET" || true)"
    mypwd="$(env_get "$ENV_FILE" "MYSQL_PASSWORD" || true)"
    adminpwd="$(env_get "$ENV_FILE" "ADMIN_DEFAULT_PASSWORD" || true)"

    local msg
    if msg="$(jwt_check "$jwt")"; then
      chk_pass "JWT_SECRET 强度合格"
    else
      chk_fail "JWT_SECRET 不合格 —— $msg"
    fi

    if msg="$(pw_check "$mypwd" "MYSQL_PASSWORD")"; then
      chk_pass "MYSQL_PASSWORD 强度合格"
    else
      chk_fail "MYSQL_PASSWORD 不合格 —— $msg"
    fi

    if msg="$(pw_check "$adminpwd" "ADMIN_DEFAULT_PASSWORD")"; then
      chk_pass "ADMIN_DEFAULT_PASSWORD 强度合格"
    else
      chk_fail "ADMIN_DEFAULT_PASSWORD 不合格 —— $msg"
    fi
  fi

  # ============ 八、网络 ============
  section "八、网络连通 (装依赖要用)"

  if have_cmd curl; then
    if curl -fsS -o /dev/null --max-time 8 https://pypi.org/simple/ 2>/dev/null; then
      chk_pass "pypi.org 可达"
    else
      chk_warn "pypi.org 不可达 —— 要么走内网镜像源 (改 pip.conf), 要么用 --offline 预装 wheel"
    fi

    if curl -fsS -o /dev/null --max-time 8 https://registry.npmjs.org/ 2>/dev/null; then
      chk_pass "npm registry 可达"
    else
      chk_warn "npm registry 不可达 —— 要么走内网镜像源 (改 .npmrc), 要么用 --offline 预装 node_modules"
    fi
  else
    chk_warn "没有 curl —— 装: $(pkg_name curl "$PKG_MGR")"
  fi

  # ============ 九、Docker 主机名 (仅 local driver) ============
  # local driver 的进程跑在**宿主**上, 而 host.docker.internal 是**容器里**访问宿主用的名字.
  # 在宿主上它解析到 Docker 的虚拟网卡 (macOS 上 198.18.x.x), 从宿主侧连不通 ——
  # 于是代码检视连不上、资产市场推不到 GitLab.
  if [[ "${PREFLIGHT_DRIVER:-systemd}" == "local" ]]; then
    section "九、Docker 主机名 (local 模式专属)"
    local alias broken_alias=""
    for alias in "${DOCKER_HOST_ALIASES[@]}"; do
      if host_alias_broken "$alias"; then
        broken_alias="$broken_alias $alias"
      else
        chk_pass "$alias: 在宿主上指回 127.0.0.1"
      fi
    done
    if [[ -n "$broken_alias" ]]; then
      # ⚠️ 2026-10-27: 这项从 FAIL 降成 WARN ——
      #    后端现在自己把 host.docker.internal ↔ 127.0.0.1 双向改写
      #    (settings_store._rewrite_loopback / git_sync._rewrite_remote),
      #    平台功能不再依赖 /etc/hosts.
      #    只有别的工具 (curl / ssh / 浏览器直接访问) 也想用这个别名时才需要修.
      chk_warn "这些名字在宿主上连不通:$broken_alias —— 它们是容器里访问宿主用的名字"
      echo "        后端会**自动改写**这类地址, 平台功能不受影响 —— 不用改 /etc/hosts 也能用."
      echo "        别的工具也想用这个别名时才修: sudo $0 local hosts fix"
    fi
  fi
}
