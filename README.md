# AI 工作平台

本地单页 Web 应用,把 RAGFlow / Dify 的嵌入实例并排展示在一个主页,带独立配置页。

## 启动

```bash
npm install
npm run dev      # 开发模式,http://localhost:5173
npm run build    # 生产构建,产物在 dist/
npm run preview  # 预览生产构建
```

## 使用

1. 打开主页 `http://localhost:5173/`
2. 右上角点 **⚙ 配置** 进入配置页
3. 在 **RAGFlow 实例** / **Dify 实例** 两个区里点 **+ 新增**,填名称、URL(可选 Auth Token / API Key)
4. 保存后点 **← 返回主页**,即可看到实例以 grid 形式并排展示
5. 单个面板右上角 **⛶** 切换全屏;按 **Esc** 或再次点 **退出全屏** 退出

## 配置存储

- 浏览器 `localStorage`,key = `ai-platform:instances:v1`
- 同一浏览器同一域名共享,清浏览器数据会丢
- 配置页底部 **导出配置 JSON** 可下载备份;**导入配置 JSON** 在新浏览器恢复(按 id 去重,不覆盖)

## iframe 安全

`src/components/InstancePanel.tsx` 给 iframe 配的 `sandbox`:

```
allow-scripts allow-same-origin allow-forms allow-popups
```

**不**含 `allow-top-navigation`,防止嵌入页把整个平台劫持到外站。
