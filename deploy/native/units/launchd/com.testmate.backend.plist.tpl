<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!--
  TestMate 后端 —— macOS launchd 单元 (本地部署模式)

  对应 Linux 的 testmate-backend.service —— 两边行为一致:
    · RunAtLoad  = 开机自启
    · KeepAlive  = 崩了自动拉起 (崩溃自愈)
    · 环境变量从 backend.env 生成 (同一份配置, 两边不打架)

  ⚠️ 后端**只能一个 worker** —— 跟 systemd 版同理由:
     资产市场的 job 消费者走进程内队列, 多 worker 会重复消费同一个 job.

  由 tmctl.sh launchd install 生成 —— 勿手改.
-->
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.testmate.backend</string>

    <key>ProgramArguments</key>
    <array>
        <string>@@VENV_BIN@@/uvicorn</string>
        <string>app.main:app</string>
        <string>--host</string>
        <string>@@BIND_ADDR@@</string>
        <string>--port</string>
        <string>@@BACKEND_PORT@@</string>
        <string>--workers</string>
        <string>@@WORKERS@@</string>
        <string>--proxy-headers</string>
        <string>--forwarded-allow-ips</string>
        <string>@@FORWARDED_ALLOW@@</string>
    </array>

    <key>WorkingDirectory</key>
    <string>@@BACKEND_DIR@@</string>

    <key>EnvironmentVariables</key>
    <dict>
@@ENV_VARS@@
    </dict>

    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>

    <key>StandardOutPath</key>
    <string>@@LOG_DIR@@/backend.log</string>
    <key>StandardErrorPath</key>
    <string>@@LOG_DIR@@/backend-error.log</string>
</dict>
</plist>
