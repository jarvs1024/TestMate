<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!--
  TestMate 前端 —— macOS launchd 单元 (本地部署模式)

  对应 Linux 的 testmate-frontend.service —— 同样是个**独立 nginx 实例**
  (用 -c/-p 指定自己的配置和前缀), 不碰系统/brew 自带的 nginx.

  ⚠️ `-g "daemon off;"` —— 必须前台跑, launchd 才能盯着它 (崩了拉起).
     后台模式 (daemon on) 下 launchd 会认为进程秒退, 然后陷入疯狂重启.

  由 tmctl.sh launchd install 生成 —— 勿手改.
-->
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.testmate.frontend</string>

    <key>ProgramArguments</key>
    <array>
        <string>@@NGINX_BIN@@</string>
        <string>-c</string>
        <string>@@NGINX_CONF@@</string>
        <string>-p</string>
        <string>@@NGINX_PREFIX@@</string>
        <string>-g</string>
        <string>daemon off;</string>
    </array>

    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>

    <key>StandardOutPath</key>
    <string>@@LOG_DIR@@/nginx-launchd.log</string>
    <key>StandardErrorPath</key>
    <string>@@LOG_DIR@@/nginx-launchd-error.log</string>
</dict>
</plist>
