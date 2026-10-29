<template>
  <div class="kb">
    <!-- ===== 能力详情统一外壳 ===== -->
    <CapabilityShell
      name="知识库"
      icon="📚"
      kind="platform"
      status="stable"
      version="v0.1.0"
      category="ssd-kb" />

    <!-- 概览 -->
    <div class="card card-overview">
      <h2>
        <span>概览</span>
        <span class="rf-status" :class="`s-${rfStatus}`" v-if="rfStatus">
          <span class="dot"></span>{{ rfMsg }}
        </span>
      </h2>
      <div class="stats">
        <div class="stat"><div class="num">{{ datasets.length }}</div><div class="lbl">数据集</div></div>
        <div class="stat"><div class="num">{{ totalDocs }}</div><div class="lbl">文档</div></div>
        <div class="stat"><div class="num">{{ totalChunks }}</div><div class="lbl">分段</div></div>
        <div class="stat"><div class="num">{{ fmtSize(totalSize) }}</div><div class="lbl">总大小</div></div>
      </div>
    </div>

    <!-- 数据集列表 (P1 加列 + 行可展开看文档) -->
    <div class="card">
      <div class="ds-hd">
        <h2><span>数据集</span></h2>
        <!-- ⚠️ 建库和上传是知识库最常用的两个动作 —— 放在标题行右侧, 一眼就能看到 -->
        <div class="ds-tools">
          <!-- ⚠️ 搜索**就在这个卡片里** —— 不另开一个「文档搜索」box.
               搜索框放工具栏最左边(它是"查找", 不是"操作"),
               搜出来的结果直接落在下面那个表格区, 不用跳来跳去. -->
          <div class="search">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
            </svg>
            <input
              v-model="docSearchKw"
              placeholder="按文件名搜索文档（不区分大小写）"
              title="跨所有知识库搜 —— 只搜**文件名**, 不搜文档内容"
              @input="onDocSearchInput"
              @keyup.enter="doDocSearch" />
          </div>
          <button v-if="docSearchKw" class="ghost-btn srch-clear" @click="clearDocSearch">清空</button>
          <!-- ⚠️ 这句话**一直**在 —— 不然用户搜内容搜不到, 会以为文档不存在 -->
          <span class="ds-hint srch-hint">只搜文件名，不搜内容</span>
          <button
            v-if="canWrite"
            class="primary-btn ds-act"
            title="新建一个数据集 (比如 项目管理 / 协议管理 那种分类)"
            @click="openCreate">+ 新建数据集</button>
          <button
            v-if="canWrite"
            class="ghost-btn ds-act"
            title="上传文档到某个数据集 (单文件 ≤20MB, 单次 ≤5 个)"
            @click="openUploadTop">⬆ 上传文档</button>
          <button class="reload" @click="onReload" :disabled="loading">↻ 刷新</button>
        </div>
      </div>

      <!-- 搜索结果区 —— 有搜索词才出现, 直接落在「数据集」这个卡片里 -->
      <div v-if="docSearchError" class="empty err">
        搜索失败：{{ docSearchError }}
        <button class="ghost-btn" @click="doDocSearch">重试</button>
      </div>
      <div v-else-if="docSearchKw" class="srch-sec">
        <div class="srch-sec-t">
          搜索「{{ docSearchKw }}」找到 <b class="mono">{{ docSearchTotal }}</b> 篇文档
          <span class="ds-hint">（只搜文件名，不搜文档内容）</span>
        </div>
        <div class="tbl-wrap">
  <table class="ds-tbl srch-tbl">
            <thead>
              <tr>
                <th>文档名</th><th style="width:140px">所属数据集</th><th>大小</th><th>分段</th>
                <th>解析</th><th>上传者</th><th style="width:200px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="hit in docSearchHits" :key="hit.dataset_id + '/' + hit.id">
                <td class="nm">
                  <span class="doc-ic">{{ docIcon(hit.type) }}</span>
                  <span class="doc-name" :title="hit.location" @click="openDocDetail(hit)" style="cursor:pointer">{{ hit.name }}</span>
                </td>
                <td class="ds-desc" :title="hit.dataset_id">{{ hit.dataset_name || '—' }}</td>
                <td class="mono">{{ fmtSize(hit.size) }}</td>
                <td class="mono">{{ hit.chunk_count }}</td>
                <td>
                  <span class="run-badge" :class="runStatusClass(hit.run)" :title="hit.progress_msg">{{ runStatusLabel(hit.run) }}</span>
                  <span v-if="hit.run === 'RUNNING'" class="doc-prog"
                        :title="`解析中 ${Math.round((hit.progress || 0) * 100)}%`">
                    <i :style="{ width: `${Math.round((hit.progress || 0) * 100)}%` }"></i>
                  </span>
                </td>
                <td class="mono">{{ hit.uploaded_by_name || '—' }}</td>
                <td>
                  <button class="link-btn" @click="openChunks(dsOf(hit), hit)" title="查看分段内容">分段</button>
                  <button class="link-btn" title="下载原始文件" @click="onDownload(dsOf(hit), hit)">下载</button>
                  <!-- ⚠️ 更新 / 重解析 = 写操作 → tester 及以上 -->
                  <button
                    v-if="canWrite"
                    class="link-btn"
                    title="换新文件替换这一篇的内容 (旧版本会被永久删除)"
                    @click="openUpdate(dsOf(hit), hit)">更新</button>
                  <button
                    v-if="canWrite"
                    class="link-btn"
                    title="内容不变, 重跑一遍解析"
                    @click="doReparse(dsOf(hit), hit)">重解析</button>
                  <!-- ⚠️ 删除文档 = 硬删 → 只给 admin (跟文档子表里那个一个口径) -->
                  <button
                    v-if="isAdmin"
                    class="link-btn danger"
                    :disabled="deletingDocKey === `${hit.dataset_id}::${hit.id}`"
                    :title="deletingDocKey === `${hit.dataset_id}::${hit.id}` ? '删除中…' : '删除这一篇文档 (源文件和分段一起永久删除)'"
                    @click="doDeleteDocument(dsOf(hit), hit)">
                    {{ deletingDocKey === `${hit.dataset_id}::${hit.id}` ? '删除中…' : '🗑 删除' }}
                  </button>
                </td>
              </tr>
              <!-- ⚠️ 2026-10-29: 条件改成**只看 loading** ——
                   以前是「没有结果 && 在加载」, 可请求期间屏幕上还挂着上一个关键词的结果,
                   这一行永远不出现 → 用户以为没在搜. 现在请求一开始结果就清空, 这一行必定出现. -->
              <tr v-if="docSearchLoading">
                <td colspan="7" class="empty">搜索中…</td>
              </tr>
              <tr v-else-if="!docSearchHits.length && docSearched">
                <td colspan="7" class="empty">没找到含「{{ docSearchKw }}」的文档</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="docSearchTruncated" class="empty err">
          命中 {{ docSearchTotal }} 篇，只显示前 {{ docSearchHits.length }} 篇 —— 请把关键词写得更具体些
        </div>
      </div>

      <div class="tbl-wrap">
  <table class="ds-tbl">
          <thead>
            <tr>
              <th style="width:24px"></th>
              <th>名称</th>
              <th>说明</th>
              <th>状态</th>
              <th>文档</th>
              <th>分段</th>
              <th>切片法</th>
              <th>更新时间</th>
              <th style="width:140px">操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="d in datasets" :key="d.id">
              <tr class="ds-row" :class="{ open: expandedId === d.id }">
                <td class="exp-cell">
                  <!-- ⚠️ 折叠按钮要做得很**显眼** (2026-10-29) ——
                       以前就是一个灰色的 ▸ 字, 没人知道那能点.
                       现在做成带边框的胶囊 + 「展开/收起」文字, 一眼就知道能展开. -->
                  <button
                    class="exp"
                    :class="{ on: expandedId === d.id }"
                    @click="toggleExpand(d.id)"
                    :title="expandedId === d.id ? '收起文档列表' : '展开文档列表'">
                    <span class="exp-ic">{{ expandedId === d.id ? '▾' : '▸' }}</span>
                    <span class="exp-tx">{{ expandedId === d.id ? '收起' : '展开' }}</span>
                  </button>
                </td>
                <td class="nm">
                  <span class="ds-ic">📁</span>
                  <!-- ⚠️ 点**名字**也能展开 —— 用户看到名字就想点, 别只让用户猜那个小箭头.
                       ⚠️ 名字后面的 id 哈希 (`ec40ed92…`) 去掉了 —— 对用户没意义, 还占地方 -->
                  <!-- ⚠️ 2026-10-29: title 原来写死成「点击展开文档列表」——
                       用户悬停看不到**完整库名**. 现在 title 给库名本身,
                       "点击展开"的说明挪到左边的折叠按钮上 (那个按钮本来就有 title). -->
                  <span
                    class="ds-name"
                    :title="d.name"
                    @click="toggleExpand(d.id)">{{ d.name }}</span>
                </td>
                <td class="ds-desc" :title="d.description">{{ d.description || '—' }}</td>
                <td>
                  <span class="run-badge" :class="d.status === '1' ? 'run-done' : 'run-fail'">{{ d.status === '1' ? '启用' : '禁用' }}</span>
                </td>
                <td class="mono">{{ d.document_count }}</td>
                <td class="mono">{{ d.chunk_count }}</td>
                <td class="mono">{{ fmtChunkMethod(d.chunk_method) }}</td>
                <td class="mono">{{ fmtTime(d.update_time) || d.update_date || '—' }}</td>
                <td class="ds-ops">
                  <!-- ⚠️ 行内直接上传 —— 不用先展开子表就能往这个库塞文档 -->
                  <button
                    v-if="canWrite"
                    class="link-btn"
                    title="往这个数据集上传文档"
                    @click="openUpload(d)">⬆ 上传</button>
                  <button class="ghost-btn" @click="openDetail(d)">详情</button>
                  <!-- ⚠️ 删除数据集 = 硬删, 不可逆 → 只给 admin, 且要输入库名确认.
                       ⚠️ 2026-10-29: 删除期间**置灰 + 换文案** ——
                       以前全程零反馈 (后端删大库给了 120s 超时), 按钮还能再点 →
                       第二次又弹确认框 → 第一个已删完 → 404 → 红条「数据集不存在」,
                       **可删除其实成功了**. -->
                  <button
                    v-if="isAdmin"
                    class="link-btn danger"
                    :disabled="deletingDsId === d.id"
                    :title="deletingDsId === d.id ? '删除中…' : '删除整个数据集 (连同里面的文档一起永久删除)'"
                    @click="doDeleteDataset(d)">
                    {{ deletingDsId === d.id ? '删除中…' : '🗑 删除' }}
                  </button>
                </td>
              </tr>
              <!-- 展开的文档子表 -->
              <tr v-if="expandedId === d.id" class="ds-subrow">
                <td colspan="9" class="ds-subcell">
                  <div class="doc-panel">
                    <div class="doc-hd">
                      <div class="doc-t">📄 {{ d.name }} · 文档列表</div>
                      <div class="doc-tools">
                        <!-- ⚠️ 这里原来还有一个「⬆ 上传文档」按钮 —— **删掉了** (2026-10-29).
                             重复: 同一行的操作列里已经有「⬆ 上传」(锁定这个库),
                             页面顶部工具条也还有一个全局的「⬆ 上传文档」.
                             三个入口干同一件事, 看着像出了 bug. 这里只留「↻」 -->
                        <button class="reload sm" @click="loadDocs(d.id, true)" :disabled="docLoading(d.id)">↻</button>
                      </div>
                    </div>
                    <div class="tbl-wrap">
  <table class="doc-tbl">
                        <thead>
                          <tr>
                            <th>名称</th><th>大小</th><th>分段</th><th>解析</th><th>启用</th><th>更新</th><th style="width:270px">操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr v-for="doc in docsOf(d.id)" :key="doc.id" :class="{ failed: doc.run === 'FAIL' }">
                            <td class="nm">
                              <span class="doc-ic">{{ docIcon(doc.type) }}</span>
                              <span class="doc-name" :title="doc.location" @click="openDocDetail(doc)" style="cursor:pointer">{{ doc.name }}</span>
                            </td>
                            <td class="mono">{{ fmtSize(doc.size) }}</td>
                            <td class="mono">{{ doc.chunk_count }}</td>
                            <td>
                              <span class="run-badge" :class="runStatusClass(doc.run)" :title="runTitle(doc)">{{ runStatusLabel(doc.run) }}</span>
                              <!-- ⚠️ 解析进度 (2026-10-29) —— 接口一直给 progress,
                                   页面从没用过, 用户只看到一枚静态的「解析中」,
                                   不知道还要等多久、是不是卡住了. -->
                              <span v-if="doc.run === 'RUNNING'" class="doc-prog"
                                    :title="`解析中 ${Math.round((doc.progress || 0) * 100)}%`">
                                <i :style="{ width: `${Math.round((doc.progress || 0) * 100)}%` }"></i>
                              </span>
                            </td>
                            <td>
                              <span class="run-badge" :class="doc.status === '1' ? 'run-done' : 'run-fail'">{{ doc.status === '1' ? '启用' : '禁用' }}</span>
                            </td>
                            <td class="mono">{{ fmtTime(doc.update_time) || doc.update_date || '—' }}</td>
                            <td>
                              <button class="link-btn" @click="openChunks(d, doc)" title="查看分段内容">分段</button>
                              <!-- ⚠️ 下载是只读操作 → 所有登录用户都能用 -->
                              <button
                                class="link-btn"
                                title="下载原始文件"
                                @click="onDownload(d, doc)">下载</button>
                              <!-- ⚠️ 更新 / 重解析 = 写操作 → tester 及以上 (跟上传同一档) -->
                              <button
                                v-if="canWrite"
                                class="link-btn"
                                title="换新文件替换这一篇的内容 (旧版本会被永久删除)"
                                @click="openUpdate(d, doc)">更新</button>
                              <button
                                v-if="canWrite"
                                class="link-btn"
                                title="内容不变, 重跑一遍解析 (解析失败了可以用)"
                                @click="doReparse(d, doc)">重解析</button>
                              <!-- ⚠️ 删除文档 = **硬删** (源文件 + 分段一起没, 没回收站)
                                   → 只给 admin, 且要输入文档名二次确认 (跟删数据集一个口径) -->
                              <button
                                v-if="isAdmin"
                                class="link-btn danger"
                                :disabled="deletingDocKey === `${d.id}::${doc.id}`"
                                :title="deletingDocKey === `${d.id}::${doc.id}` ? '删除中…' : '删除这一篇文档 (源文件和分段一起永久删除)'"
                                @click="doDeleteDocument(d, doc)">
                                {{ deletingDocKey === `${d.id}::${doc.id}` ? '删除中…' : '🗑 删除' }}
                              </button>
                            </td>
                          </tr>
                          <!-- ⚠️ **加载中要有提示** (2026-10-29 整改) ——
                               子表以前一展开就是一张空表, 一点「加载中…」都没有,
                               RAGFlow 慢的时候用户以为"这个库没有文档". -->
                          <tr v-if="docLoading(d.id)">
                            <td :colspan="7" class="empty">加载中…</td>
                          </tr>
                          <!-- ⚠️ **加载失败要说失败** —— 以前失败时列表被清空,
                               显示成「暂无文档」, 文档明明都还在, 用户却以为被删了. -->
                          <tr v-else-if="docError(d.id)">
                            <td :colspan="7" class="empty err">
                              加载失败：{{ docError(d.id) }}
                              <button class="link-btn" @click="loadDocs(d.id, true)">重试</button>
                            </td>
                          </tr>
                          <tr v-else-if="docsOf(d.id).length === 0">
                            <td :colspan="7" class="empty">暂无文档</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                </div>
              </td>
            </tr>
          </template>
          <!-- ⚠️ 取不到数据集 ≠ 没有数据集 —— 以前这里直接显示「暂无数据集」,
               同页的"加载失败"提示跟它自相矛盾 (失败和空是两回事). -->
          <tr v-if="dsError">
            <td colspan="9" class="empty err">
              数据集加载失败：{{ dsError }}
              <button class="ghost-btn" @click="onReload">重试</button>
            </td>
          </tr>
          <tr v-else-if="datasets.length === 0 && !loading">
            <td colspan="9" class="empty">暂无数据集</td>
          </tr>
          <tr v-if="loading">
            <td colspan="9" class="empty">加载中…</td>
          </tr>
        </tbody>
      </table>
    </div>
      </div>

    <!-- 知识检索 / 知识对话: 两个 tab 共享一张卡 -->
    <div class="card card-share">
      <div class="share-hd">
        <div class="share-t">🔎 知识检索<span class="share-sub-inline">{{ activeSubLabel }}</span></div>
        <div class="share-tabs" role="tablist">
          <button class="share-tab" :class="{ active: activeTab === 'search' }" @click="activeTab = 'search'"><span class="lbl">搜索</span></button>
          <button class="share-tab" :class="{ active: activeTab === 'chat' }" @click="activeTab = 'chat'"><span class="lbl">对话</span></button>
        </div>
      </div>
      <template v-if="activeTab === 'search'">
        <template v-if="searchEmbedUrl">
          <div class="share-frame-wrap" :style="{ minHeight: searchMinHeight + 'px' }">
            <iframe :key="`search-${themeKey}-${themeNonce}`" :src="searchIframeSrc" frameborder="0" class="share-frame" :style="{ minHeight: searchMinHeight + 'px' }" title="knowledge-search" sandbox="allow-scripts allow-same-origin allow-popups allow-forms" referrerpolicy="no-referrer"></iframe>
          </div>
          <a :href="searchEmbedUrl" target="_blank" rel="noopener" class="share-pop">{{ searchOpenUrlLabel }}</a>
        </template>
        <div v-else class="search-placeholder">
          <div class="ph-ic">🔎</div><div class="ph-t">知识检索建设中</div>
          <div class="ph-d">admin 可在 设置 → 知识检索 配置 <code>search.embed_url</code> 启用</div>
        </div>
      </template>
      <template v-else-if="activeTab === 'chat'">
        <template v-if="chatEmbedUrl">
          <div class="share-frame-wrap" :style="{ minHeight: searchMinHeight + 'px' }">
            <iframe :key="`chat-${themeKey}-${themeNonce}`" :src="chatIframeSrc" frameborder="0" class="share-frame" :style="{ minHeight: searchMinHeight + 'px' }" title="knowledge-chat" sandbox="allow-scripts allow-same-origin allow-popups allow-forms" referrerpolicy="no-referrer"></iframe>
          </div>
          <a :href="chatEmbedUrl" target="_blank" rel="noopener" class="share-pop">{{ chatOpenUrlLabel }}</a>
        </template>
        <div v-else class="search-placeholder">
          <div class="ph-ic">💬</div><div class="ph-t">知识对话建设中</div>
          <div class="ph-d">admin 可在 设置 → 知识对话 配置 <code>chat.embed_url</code> 启用</div>
        </div>
      </template>
    </div>

    <!-- 操作记录 (谁在什么时候动了知识库) -->
    <!-- ⚠️ 只有 **admin** 能看 —— 里面有别人的**操作人账号和文件名**,
         那是治理信息, 跟「删除文档/删除数据集」同一档: 破坏性和治理性的
         操作都由 admin 掌握 -->
    <div v-if="isAdmin" class="card">
      <div class="ds-hd">
        <h2>
          <span>操作记录</span>
          <!-- ⚠️ `loadAudits()` 必须带括号 —— 直接写 `loadAudits` 会把
               MouseEvent 当成 page 参数传进去, 页码直接变成 NaN -->
          <button class="reload" @click="loadAudits()" :disabled="auditLoading">↻ 刷新</button>
        </h2>
        <!-- ⚠️ 总条数得说清楚 —— 这是 admin 的治理视图, 要知道一共发生过多少事 -->
        <span class="ds-count" v-if="auditTotal">共 {{ auditTotal }} 条</span>
      </div>
      <div v-if="auditError" class="empty err">
        操作记录加载失败：{{ auditError }}
        <button class="ghost-btn" @click="loadAudits()">重试</button>
      </div>
      <!-- ⚠️ `v-else` 必须在**包裹层**上, 不能留在 table 上 ——
           前面那个兄弟节点是 `<div v-if="auditError">`, 包一层之后
           table 的上一个兄弟变成了 wrapper, v-else 就没有配对的 v-if 了. -->
      <div v-else class="tbl-wrap">
        <table class="ds-tbl">
          <thead>
            <tr>
              <th>时间</th><th>谁</th><th>动作</th><th>数据集</th><th>文档</th><th>大小</th><th>结果</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in audits" :key="a.id">
              <td class="mono">{{ fmtIso(a.created_at) || '—' }}</td>
              <td class="mono">{{ a.actor_name || '—' }}</td>
              <td><span class="run-badge" :class="a.error ? 'run-fail' : 'run-done'">{{ auditActionLabel(a.action) }}</span></td>
              <td>{{ a.dataset_name || a.dataset_id || '—' }}</td>
              <td class="nm"><span class="doc-name">{{ a.doc_name || '—' }}</span></td>
              <td class="mono">{{ a.size ? fmtSize(a.size) : '—' }}</td>
              <td class="mono" :class="{ 'dt-err': a.error }" :title="a.error">{{ a.error ? '失败' : '成功' }}</td>
            </tr>
            <tr v-if="!audits.length && !auditLoading">
              <td colspan="7" class="empty">还没有操作记录</td>
            </tr>
            <tr v-if="auditLoading">
              <td colspan="7" class="empty">加载中…</td>
            </tr>
          </tbody>
        </table>
      </div>
      <!-- ⚠️ 分页控件 (2026-10-29) —— 只有一页的时候不显示, 别占地方 -->
      <div v-if="auditPages > 1" class="pg-bar">
        <span class="pg-info">
          第 <b>{{ auditPage }}</b> / {{ auditPages }} 页
        </span>
        <div class="pg-btns">
          <button class="pg-btn" :disabled="auditPage <= 1 || auditLoading" @click="gotoAuditPage(1)">« 首页</button>
          <button class="pg-btn" :disabled="auditPage <= 1 || auditLoading" @click="gotoAuditPage(auditPage - 1)">‹ 上一页</button>
          <button class="pg-btn" :disabled="auditPage >= auditPages || auditLoading" @click="gotoAuditPage(auditPage + 1)">下一页 ›</button>
          <button class="pg-btn" :disabled="auditPage >= auditPages || auditLoading" @click="gotoAuditPage(auditPages)">末页 »</button>
        </div>
        <label class="pg-size">
          每页
          <select v-model.number="auditPageSize" class="pg-select" @change="onAuditPageSizeChange">
            <option :value="10">10</option>
            <option :value="20">20</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
          </select>
          条
        </label>
      </div>
    </div>

    <!-- 数据集详情抽屉 (P1) -->
    <el-drawer v-model="detailOpen" :title="detailDs?.name || '数据集详情'" size="520px" direction="rtl">
      <template v-if="detailDs">
        <div class="dt">
          <div class="dt-row"><span class="dt-k">ID</span><span class="dt-v mono">{{ detailDs.id }}</span></div>
          <div class="dt-row"><span class="dt-k">名称</span><span class="dt-v">{{ detailDs.name }}</span></div>
          <div class="dt-row"><span class="dt-k">创建者</span><span class="dt-v">{{ detailDs.created_by_name || '—' }}</span></div>
          <div class="dt-row"><span class="dt-k">创建时间</span><span class="dt-v mono">{{ fmtIso(detailDs.created_at) }}</span></div>
          <div class="dt-row"><span class="dt-k">嵌入模型</span><span class="dt-v mono">{{ detailDs.embedding_model || '—' }}</span></div>
          <div class="dt-row"><span class="dt-k">权限</span><span class="dt-v"><span class="perm" :class="`perm-${detailDs.permission}`">{{ detailDs.permission === 'team' ? '团队' : '私有' }}</span></span></div>
          <div class="dt-row"><span class="dt-k">语言</span><span class="dt-v">{{ detailDs.language || '—' }}</span></div>
          <div class="dt-row"><span class="dt-k">文档数</span><span class="dt-v mono">{{ detailDs.document_count }}</span></div>
          <div class="dt-row"><span class="dt-k">分段数</span><span class="dt-v mono">{{ detailDs.chunk_count }}</span></div>
          <div class="dt-row"><span class="dt-k">Token 数</span><span class="dt-v mono">{{ detailDs.token_num }}</span></div>
          <div class="dt-row"><span class="dt-k">切片法</span><span class="dt-v">{{ fmtChunkMethod(detailDs.chunk_method) }}（{{ detailDs.chunk_method }}）</span></div>
          <div class="dt-row"><span class="dt-k">相似度阈值</span><span class="dt-v mono">{{ detailDs.similarity_threshold }}</span></div>
          <div class="dt-row"><span class="dt-k">向量权重</span><span class="dt-v mono">{{ detailDs.vector_similarity_weight }}</span></div>
          <div class="dt-row"><span class="dt-k">PageRank</span><span class="dt-v mono">{{ detailDs.pagerank }}</span></div>
          <div class="dt-row"><span class="dt-k">创建</span><span class="dt-v mono">{{ fmtTime(detailDs.create_time) }}</span></div>
          <div class="dt-row"><span class="dt-k">更新</span><span class="dt-v mono">{{ fmtTime(detailDs.update_time) }}</span></div>

          <div class="dt-sep">切片参数 (parser_config)</div>
          <pre class="dt-pre mono">{{ JSON.stringify(detailDs.parser_config, null, 2) }}</pre>
        </div>
      </template>
    </el-drawer>

    <!-- 新建数据集抽屉 (2026-10-29) -->
    <el-drawer v-model="createOpen" title="新建数据集" size="520px" direction="rtl">
      <div class="cd-panel">
        <div class="cd-field">
          <label class="cd-lbl">数据集名称 <span class="cd-req">*</span></label>
          <input
            v-model="createForm.name"
            class="cd-input"
            maxlength="128"
            placeholder="例如：项目管理 / 协议管理 / 售后培训资料" />
          <div v-if="createNameHint" class="cd-hint" :class="{ err: createNameConflict }">{{ createNameHint }}</div>
        </div>

        <div class="cd-field">
          <label class="cd-lbl">说明（选填）</label>
          <input
            v-model="createForm.description"
            class="cd-input"
            maxlength="500"
            placeholder="一句话讲清这个库放什么，方便别人找" />
          <div class="cd-hint">新建后会立刻出现在所有人的知识库列表里 —— 名字要说清楚</div>
        </div>

        <div class="cd-field">
          <label class="cd-lbl">切片方式</label>
          <div class="cd-choices">
            <label class="cd-choice" :class="{ on: createForm.chunkMethod === 'naive' }">
              <input type="radio" value="naive" v-model="createForm.chunkMethod" @change="onQuickChunk" />
              <span class="cd-ct">通用</span>
              <span class="cd-cd">自动分段，txt / md / docx / pdf 都能用</span>
            </label>
            <!-- ⚠️ 「手动」**删掉了** (2026-10-29 第七轮补) ——
                 手动切分意味着文档进来后**分段要自己再调**,
                 而 TestMate 里**没有调分段的功能** —— 建出来的库用户改不了, 是死路.
                 RAGFlow 那边还认 manual (协议文档那个库就是), 但不给用户选. -->
          </div>
          <!-- ⚠️ RAGFlow 还有 11 种解析器 (2026-10-29) —— 上面那个是最常用的,
               剩下的放这个下拉里, 免得把抽屉撑成一长串卡片.
               ⚠️ 值是 RAGFlow 的**内部名** (naive/qa/table/...) ——
               「通用」在 RAGFlow 里叫 naive, 叫 general 是**更新版本**的说法, 这版不认. -->
          <div class="cd-more">
            <select v-model="createForm.parserExtra" class="cd-select2" @change="onExtraParser">
              <option value="">更多解析方式…（不确定就用「通用」）</option>
              <option v-for="p in EXTRA_PARSERS" :key="p.v" :value="p.v">{{ p.label }} — {{ p.desc }}</option>
            </select>
            <div class="cd-hint" v-if="createForm.parserExtra">
              已选「{{ extraParserLabel }}」—— {{ extraParserDesc }}
            </div>
            <div class="cd-hint" v-else>
              不确定用哪种就用「通用」—— 什么文档都能处理，各家解析器只对特定格式更准
            </div>
          </div>
        </div>

        <!-- ⚠️ 语言 (2026-10-29) —— RAGFlow 的数据集有 language 字段,
             影响自动问答 / 关键词提取. 默认中文 (RAGFlow 那边默认是 English!). -->
        <div class="cd-field">
          <label class="cd-lbl">文档语言</label>
          <div class="cd-choices">
            <label class="cd-choice" :class="{ on: createForm.language === 'Chinese' }">
              <input type="radio" value="Chinese" v-model="createForm.language" />
              <span class="cd-ct">中文</span>
              <span class="cd-cd">要存的文档主要是中文的，选这个</span>
            </label>
            <label class="cd-choice" :class="{ on: createForm.language === 'English' }">
              <input type="radio" value="English" v-model="createForm.language" />
              <span class="cd-ct">英文</span>
              <span class="cd-cd">要存的文档主要是英文的，选这个</span>
            </label>
          </div>
        </div>

        <div class="cd-field">
          <label class="cd-lbl">先放几个文档进去（选填）</label>
          <div class="fpick">
            <input
              ref="createFileInput"
              type="file"
              multiple
              class="up-input up-file-hidden"
              :accept="UPLOAD_ACCEPT"
              @change="onPickCreateFiles" />
            <button type="button" class="fpick-btn" @click="openFilePicker(createFileInput)">
              <span class="fpick-ic">📎</span>
              <span class="fpick-tx">选择文件</span>
              <span class="fpick-hint">可多选 · 单个 ≤ {{ MAX_FILE_MB }}MB · 一次 ≤ {{ MAX_FILES }} 个</span>
            </button>
          </div>
          <ul v-if="createFiles.length" class="up-files">
            <li v-for="(f, i) in createFiles" :key="f.name + i">
              <span class="up-fn">{{ f.name }}</span>
              <span class="up-fs mono">{{ fmtSize(f.size) }}</span>
              <button class="up-rm" @click="removeCreateFile(i)">✕</button>
            </li>
          </ul>
          <div v-else class="up-empty">不选也行 —— 建完再上传一样可以</div>
        </div>

        <div v-if="createError" class="up-err">{{ createError }}</div>
        <div class="up-foot">
          <button class="ghost-btn" @click="createOpen = false">取消</button>
          <button class="primary-btn" :disabled="!canSubmitCreate || creating" @click="doCreate">
            {{ creating ? '创建中…' : (createFiles.length ? '创建并上传' : '创建数据集') }}
          </button>
        </div>
      </div>
    </el-drawer>

    <!-- 上传文档抽屉 (2026-10-29) -->
    <el-drawer v-model="uploadOpen" title="上传文档到知识库" size="520px" direction="rtl">
      <div class="up-panel">
        <div class="cd-field">
          <label class="cd-lbl">目标数据集</label>
          <el-select v-model="uploadDsId" class="cd-select" placeholder="选择要传进哪个库">
            <el-option v-for="d in datasets" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </div>
        <div class="up-rules">
          · 单个文件 ≤ <b>20MB</b>, 单次最多 <b>5</b> 个<br />
          · 上传后会自动启动解析，解析完成即可被检索到<br />
          · 内容进入<b>共享</b>知识库，所有登录用户都能看到；删除只有管理员能做
        </div>
        <!-- ⚠️ **自定义文件选择器** (2026-10-29) ——
             原生 <input type="file"> 渲染出来是浏览器自带的灰色小按钮, 宽度还随
             系统语言变, 跟抽屉里其它控件摆一起特别突兀 (图1).
             做法: input 藏起来 (还在 DOM 里 —— change 照样触发, 测试也还能定位到它),
             外面套一个自定义按钮, 点它转发给 input.click(). -->
        <div class="fpick">
          <input
            ref="fileInput"
            type="file"
            multiple
            class="up-input up-file-hidden"
            :accept="UPLOAD_ACCEPT"
            @change="onPickFiles" />
          <button type="button" class="fpick-btn" @click="openFilePicker(fileInput)">
            <span class="fpick-ic">📎</span>
            <span class="fpick-tx">选择文件</span>
            <span class="fpick-hint">可多选 · 单个 ≤ {{ MAX_FILE_MB }}MB · 一次 ≤ {{ MAX_FILES }} 个</span>
          </button>
        </div>
        <ul v-if="uploadFiles.length" class="up-files">
          <li v-for="(f, i) in uploadFiles" :key="f.name + i">
            <span class="up-fn">{{ f.name }}</span>
            <span class="up-fs mono">{{ fmtSize(f.size) }}</span>
            <button class="up-rm" @click="removeFile(i)">✕</button>
          </li>
        </ul>
        <div v-else class="up-empty">还没选文件</div>
        <div v-if="uploadError" class="up-err">{{ uploadError }}</div>
        <div class="up-foot">
          <button class="ghost-btn" @click="uploadOpen = false">取消</button>
          <button
            class="primary-btn"
            :disabled="!uploadFiles.length || uploading"
            @click="doUpload">
            {{ uploading ? '上传中…' : '上传并解析' }}
          </button>
        </div>
        <div v-if="uploadResult" class="up-result">
          已上传 <b>{{ uploadResult.uploaded }}</b> 个文档
          <template v-if="uploadResult.ingest_started">，解析已启动（异步，稍后刷新看状态）</template>
          <template v-else-if="!uploadResult.warning">，但解析启动失败 —— 请让管理员重跑解析</template>
        </div>
        <!-- ⚠️ 文档进了库但**没参与检索** —— 这话必须说清楚, 不能让用户以为白传了 -->
        <div v-if="uploadResult?.warning" class="up-err">{{ uploadResult.warning }}</div>
      </div>
    </el-drawer>

    <!-- 更新文档抽屉 (2026-10-29) -->
    <el-drawer v-model="updateOpen" title="更新文档内容" size="520px" direction="rtl">
      <div class="up-panel up-panel-update" v-if="updateDoc">
        <div class="up-rules">
          · 当前文档：<b>{{ updateDoc.name }}</b>（{{ fmtSize(updateDoc.size) }} / {{ updateDoc.chunk_count }} 个分段）<br />
          · 换新文件后，<b>旧版本会被永久删除</b>（操作记录里会留一条，但旧文件找不回来）<br />
          · 新文档名 = 你选的文件名；内容换完会自动重新解析<br />
          · 只能换<b>内容</b>，不能换文件类型（扩展名必须跟原来一致）
        </div>
        <div class="fpick">
          <input
            ref="updateFileInput"
            type="file"
            class="up-input up-input-update up-file-hidden"
            :accept="UPLOAD_ACCEPT"
            @change="onPickUpdateFile" />
          <button type="button" class="fpick-btn" @click="openFilePicker(updateFileInput)">
            <span class="fpick-ic">📎</span>
            <span class="fpick-tx">选择新文件</span>
            <span class="fpick-hint">只能选 1 个 · 扩展名必须跟原来一致</span>
          </button>
        </div>
        <ul v-if="updateFile" class="up-files">
          <li>
            <span class="up-fn">{{ updateFile.name }}</span>
            <span class="up-fs mono">{{ fmtSize(updateFile.size) }}</span>
            <button class="up-rm" @click="updateFile = null">✕</button>
          </li>
        </ul>
        <div v-else class="up-empty">还没选文件</div>
        <div v-if="updateError" class="up-err">{{ updateError }}</div>
        <div class="up-foot">
          <button class="ghost-btn" @click="updateOpen = false">取消</button>
          <button class="primary-btn" :disabled="!updateFile || updating" @click="doUpdate">
            {{ updating ? '更新中…' : '替换并重新解析' }}
          </button>
        </div>
        <div v-if="updateResult" class="up-result">
          已替换为 <b>{{ updateResult.name }}</b>，
          <template v-if="updateResult.ingest_started">解析已启动（异步，稍后刷新看状态）</template>
          <template v-else>但解析启动失败 —— 请让管理员重跑解析</template>
        </div>
        <!-- ⚠️ 文档换了但**没参与检索** —— 这话必须说清楚, 不能让用户以为白传了 -->
        <div v-if="updateResult?.warning" class="up-err">{{ updateResult.warning }}</div>
      </div>
    </el-drawer>

    <!-- 文档分段预览抽屉 -->
    <el-drawer v-model="chunksOpen" :title="chunksTitle" size="640px" direction="rtl">
      <div class="chunks-panel">
        <div class="chunks-hd">
          <div class="chunks-meta">
            <span class="chunks-tot">共 {{ chunksTotal }} 个分段</span>
            <span v-if="chunksLoading" class="chunks-load">加载中…</span>
          </div>
        </div>
        <!-- ⚠️ **加载失败要说失败** (2026-10-29) ——
             以前失败时抽屉里只剩「该文档暂无分段」, **加载失败被伪装成了"本来就没有分段"**.
             用户会以为文档没切好, 其实只是没取到. -->
        <div v-if="chunksError" class="empty err">
          加载分段失败：{{ chunksError }}
          <button class="link-btn" @click="retryChunks">重试</button>
        </div>
        <div v-else-if="chunksList.length === 0 && !chunksLoading" class="empty">该文档暂无分段</div>
        <div v-for="(c, idx) in chunksList" :key="c.id" class="chunk-card">
          <div class="chunk-hd">
            <span class="chunk-num">#{{ idx + 1 }}</span>
            <span class="chunk-id mono">{{ c.id.slice(0, 12) }}…</span>
            <span v-if="c.important_keywords?.length" class="chunk-kw">
              <span v-for="k in c.important_keywords" :key="k" class="kw-tag">{{ k }}</span>
            </span>
            <span v-if="c.tag_kwd?.length" class="chunk-kw">
              <span v-for="t in c.tag_kwd" :key="t" class="kw-tag kw-tag-tag">{{ t }}</span>
            </span>
          </div>
          <div class="chunk-body">{{ c.content || '—' }}</div>
        </div>
      </div>
    </el-drawer>

    <!-- 文档详情抽屉 -->
    <el-drawer v-model="docDetailOpen" :title="docDetail?.name || '文档详情'" size="540px" direction="rtl">
      <template v-if="docDetail">
        <div class="dt">
          <div class="dt-row"><span class="dt-k">ID</span><span class="dt-v mono">{{ docDetail.id }}</span></div>
          <div class="dt-row"><span class="dt-k">名称</span><span class="dt-v">{{ docDetail.name }}</span></div>
          <div class="dt-row"><span class="dt-k">上传者</span><span class="dt-v">{{ docDetail.uploaded_by_name || '—' }}</span></div>
          <div class="dt-row"><span class="dt-k">上传时间</span><span class="dt-v mono">{{ fmtIso(docDetail.uploaded_at) }}</span></div>
          <div class="dt-row"><span class="dt-k">路径</span><span class="dt-v mono">{{ docDetail.location || '—' }}</span></div>
          <div class="dt-row"><span class="dt-k">类型</span><span class="dt-v">{{ (docDetail.type || '').toUpperCase() || '—' }}</span></div>
          <div class="dt-row"><span class="dt-k">大小</span><span class="dt-v mono">{{ fmtSize(docDetail.size) }}</span></div>
          <div class="dt-row"><span class="dt-k">分段数</span><span class="dt-v mono">{{ docDetail.chunk_count }}</span></div>
          <div class="dt-row"><span class="dt-k">Token 数</span><span class="dt-v mono">{{ docDetail.token_count }}</span></div>
          <div class="dt-row"><span class="dt-k">来源</span><span class="dt-v">{{ sourceLabel(docDetail.source_type) }} ({{ docDetail.source_type || '—' }})</span></div>
          <div class="dt-row"><span class="dt-k">切片法</span><span class="dt-v">{{ fmtChunkMethod(docDetail.chunk_method) }}（{{ docDetail.chunk_method }}）</span></div>
          <div class="dt-row"><span class="dt-k">解析状态</span><span class="dt-v"><span class="run-badge" :class="runStatusClass(docDetail.run)">{{ runStatusLabel(docDetail.run) }}</span></span></div>
          <div class="dt-row"><span class="dt-k">状态</span><span class="dt-v"><span class="run-badge" :class="docDetail.status === '1' ? 'run-done' : 'run-fail'">{{ docDetail.status === '1' ? '启用' : '禁用' }}</span></span></div>
          <div v-if="docDetail.process_duration" class="dt-row"><span class="dt-k">处理耗时</span><span class="dt-v mono">{{ fmtDuration(docDetail.process_duration) }}</span></div>
          <div v-if="docDetail.process_begin_at" class="dt-row"><span class="dt-k">开始处理</span><span class="dt-v mono">{{ docDetail.process_begin_at }}</span></div>
          <div v-if="docDetail.progress_msg && docDetail.run === 'FAIL'" class="dt-row"><span class="dt-k">失败信息</span><span class="dt-v mono dt-err">{{ docDetail.progress_msg }}</span></div>
          <div class="dt-row"><span class="dt-k">创建</span><span class="dt-v mono">{{ fmtTime(docDetail.create_time) || docDetail.create_date || '—' }}</span></div>
          <div class="dt-row"><span class="dt-k">更新</span><span class="dt-v mono">{{ fmtTime(docDetail.update_time) || docDetail.update_date || '—' }}</span></div>

          <div class="dt-sep">切片参数 (parser_config)</div>
          <pre class="dt-pre mono">{{ JSON.stringify(docDetail.parser_config || {}, null, 2) }}</pre>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { buildEmbedUrl as apiBuildEmbedUrl, getSchema } from '@/api/settings';
import {
  listDatasets, kbHealth, type KbDataset, type KbDocument,
  listDocuments, listDocChunks,
  type KbDocChunk,
  uploadKbDocuments, downloadKbDocument, listKbAudits, type KbAuditItem,
  createKbDataset, type KbChunkMethod, type KbLanguage, deleteKbDataset, deleteKbDocuments,
  updateKbDocument, reparseKbDocument,
  searchKbDocuments, type KbDocSearchHit,
} from '@/api/kb';
import { useThemeStore } from '@/stores/theme';
import { useUserStore } from '@/stores/user';
import CapabilityShell from '@/components/CapabilityShell.vue';
import {
  fmtSize, fmtTime, fmtIso, fmtChunkMethod, docIcon,
  runStatusClass, runStatusLabel, fmtDuration, sourceLabel,
} from '@/utils/format';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';

const userStore = useUserStore();
/**
 * 能不能**写**知识库 (上传文档).
 *
 * ⚠️ viewer 是**只读**角色 —— 能看、能下载, 但不能往共享知识库里塞东西.
 *    后端也这么判 (kb.py 的 _can_write), 前端只是提前把入口藏掉.
 */
const canWrite = computed(() => {
  const r = userStore.user?.role;
  return r === 'admin' || r === 'tester';
});

/**
 * 删除数据集 —— **只有 admin**.
 *
 * ⚠️ 跟"上传"不是一个档: 上传是往里加东西(加错了还能删文档),
 *    删数据集是**硬删** —— 库里的文档、分段、源文件一起没了, RAGFlow 不提供撤销.
 *    所以门槛更高, 而且前端还要**输入库名**二次确认.
 */
const isAdmin = computed(() => userStore.user?.role === 'admin');

const datasets = ref<KbDataset[]>([]);
const loading = ref(false);
/**
 * 数据集列表加载失败 —— 页面内提示用.
 *
 * ⚠️ 以前 catch 只弹一个 ElMessage, datasets 保持空 —— 表格同时显示「暂无数据集」,
 *    同页两条信息互相矛盾 (到底是没数据还是没取到?). 现在表格里直接说失败.
 */
const dsError = ref('');
const rfStatus = ref<'ok' | 'warn' | 'off' | ''>('');
const rfMsg = ref('');

const themeStore = useThemeStore();

// search/chat embed 配置 (沿用)
type ShareTab = 'search' | 'chat';
const activeTab = ref<ShareTab>('search');
const searchEngine = ref('ragflow-share');
const searchEmbedUrl = ref('');
const searchLabel = ref('基于 RAGFlow 共享 Search App');
const searchOpenUrlLabel = ref('↗ 新窗口打开 RAGFlow 共享搜索');
const searchMinHeight = ref(600);
const chatEmbedUrl = ref('');
const chatLabel = ref('基于 RAGFlow 共享 Chat App');
const chatOpenUrlLabel = ref('↗ 新窗口打开 RAGFlow 共享对话');
const activeSubLabel = computed(() => activeTab.value === 'chat' ? chatLabel.value : searchLabel.value);
const themeKey = computed(() => themeStore.resolved);
const themeNonce = ref(Date.now());

function readCurrentTheme(): string { return themeStore.resolved; }

async function resolve(prefix: 'search' | 'chat', raw: string): Promise<string> {
  if (!raw) return '';
  try { const r = await apiBuildEmbedUrl(prefix, readCurrentTheme()); return r.url || raw; }
  catch (e) { console.warn('build embed url failed', prefix, e); return raw; }
}
const searchResolvedUrl = ref('');
const chatResolvedUrl = ref('');
function withNonce(u: string, nonce: number): string {
  if (!u) return '';
  return u + (u.includes('?') ? '&' : '?') + '_t=' + nonce;
}
const searchIframeSrc = computed(() => withNonce(searchResolvedUrl.value, themeNonce.value));
const chatIframeSrc = computed(() => withNonce(chatResolvedUrl.value, themeNonce.value));

async function reResolve(prefix: 'search' | 'chat') {
  const raw = prefix === 'search' ? searchEmbedUrl.value : chatEmbedUrl.value;
  if (!raw) return;
  const u = await resolve(prefix, raw);
  if (prefix === 'search') searchResolvedUrl.value = u; else chatResolvedUrl.value = u;
}

watch(() => themeStore.resolved, async () => {
  themeNonce.value++;
  await Promise.all([reResolve('search'), reResolve('chat')]);
});
watch(activeTab, async (t) => {
  if (t === 'search' && searchEmbedUrl.value && !searchResolvedUrl.value) await reResolve('search');
  else if (t === 'chat' && chatEmbedUrl.value && !chatResolvedUrl.value) await reResolve('chat');
});
watch(searchEmbedUrl, (v) => { if (v && activeTab.value === 'search' && !searchResolvedUrl.value) reResolve('search'); });
watch(chatEmbedUrl, (v) => { if (v && activeTab.value === 'chat' && !chatResolvedUrl.value) reResolve('chat'); });

async function loadShareConfig() {
  try {
    const r = await getSchema();
    const searchItems = r.groups.find((g) => g.category === 'search')?.items || [];
    const chatItems = r.groups.find((g) => g.category === 'chat')?.items || [];
    for (const it of searchItems) {
      const v = it.value;
      if (it.key === 'search.engine') searchEngine.value = v ?? 'ragflow-share';
      else if (it.key === 'search.embed_url') searchEmbedUrl.value = v ?? '';
      else if (it.key === 'search.label') searchLabel.value = v ?? '基于 RAGFlow 共享 Search App';
      else if (it.key === 'search.open_url_label') searchOpenUrlLabel.value = v ?? '↗ 新窗口打开';
      else if (it.key === 'search.min_height') searchMinHeight.value = Number(v) || 600;
    }
    for (const it of chatItems) {
      const v = it.value;
      if (it.key === 'chat.embed_url') chatEmbedUrl.value = v ?? '';
      else if (it.key === 'chat.label') chatLabel.value = v ?? '基于 RAGFlow 共享 Chat App';
      else if (it.key === 'chat.open_url_label') chatOpenUrlLabel.value = v ?? '↗ 新窗口打开';
    }
    if (searchEngine.value === 'none') searchEmbedUrl.value = '';
  } catch (e) { console.error('load search/chat config failed', e); }
}

// === 数据集 + 文档 ===
const totalDocs = computed(() => datasets.value.reduce((s, d) => s + d.document_count, 0));
const totalChunks = computed(() => datasets.value.reduce((s, d) => s + d.chunk_count, 0));
// P1: 概览加总大小 — 文档加载后从 docsByDataset 实时汇总
const totalSize = computed(() =>
  Object.values(docsByDataset.value).reduce(
    (s, list) => s + list.reduce((ss, doc) => ss + (doc.size || 0), 0), 0,
  ),
);

// 行展开
const expandedId = ref('');
const docsByDataset = ref<Record<string, KbDocument[]>>({});
const docLoadingByDs = ref<Record<string, boolean>>({});
/**
 * 文档列表**加载失败**的库 id.
 *
 * ⚠️ 2026-10-29: 以前手动刷新失败时把该库的文档列表**清空** (`= []`),
 *    表格于是显示「暂无文档」—— 文档明明都还在, 用户却以为被删了.
 *    轮询路径早就改对了 (静默失败保留旧数据), 手动刷新路径漏了.
 *    现在保留旧数据 + 单独记一个错误, 表格里显示「加载失败 + 重试」.
 */
const docErrorByDs = ref<Record<string, string>>({});

function docsOf(datasetId: string): KbDocument[] { return docsByDataset.value[datasetId] || []; }
function docLoading(datasetId: string): boolean { return !!docLoadingByDs.value[datasetId]; }
function docError(datasetId: string): string { return docErrorByDs.value[datasetId] || ''; }

/**
 * 删除进行中的 id —— 用来置灰按钮 + 换文案.
 *
 * ⚠️ 2026-10-29: 以前删库/删文档全程零反馈 —— 后端删大库给了 120s 超时,
 *    这几秒里页面一点变化都没有, 按钮还能再点 → 第二次又弹一个确认框 →
 *    第一个已经删完, 第二个请求 404 → 红色 toast「数据集不存在」,
 *    **可删除其实成功了**. 现在请求期间按钮置灰并显示「删除中…」.
 */
const deletingDsId = ref('');
const deletingDocKey = ref('');   // `${datasetId}::${docId}`

async function toggleExpand(datasetId: string) {
  if (expandedId.value === datasetId) { expandedId.value = ''; return; }
  expandedId.value = datasetId;
  if (!docsByDataset.value[datasetId]) await loadDocs(datasetId);
}

async function loadDocs(datasetId: string, force = false, silent = false) {
  // ⚠️ **force** —— 「↻ 刷新」按钮必须真的重新拉!
  //    以前这里只有 `if (已缓存) return`, 结果两个刷新按钮全是摆设:
  //      · 文档子表的 ↻ → 缓存命中 → 直接 return, 什么都没干
  //      · 数据集卡片的 ↻ 刷新 → warmupAllDocs 也走这里 → 文档列表还是旧的
  //
  // ⚠️ **silent** —— 轮询时用. 轮询失败不该弹错误框 (每 3 秒弹一次能把人逼疯),
  //    也不该把文档列表清空 (网络抖一下, 用户看着文档全没了, 更慌).
  //    静默失败 → 保留上一次的数据, 等下一轮.
  if (!force && docsByDataset.value[datasetId]) return; // 已缓存, 不重复拉
  docLoadingByDs.value[datasetId] = true;
  try {
    // RAGFlow 单页上限 100, 分页拿全量用于准确汇总 totalSize
    const all: KbDocument[] = [];
    const PAGE = 100;
    const first = await listDocuments(datasetId, { page: 1, page_size: PAGE }, { silent: true });
    all.push(...first.docs);
    const total = first.total || first.docs.length;
    for (let page = 2; all.length < total; page++) {
      const r = await listDocuments(datasetId, { page, page_size: PAGE }, { silent: true });
      if (!r.docs.length) break;
      all.push(...r.docs);
    }
    docsByDataset.value[datasetId] = all;
    delete docErrorByDs.value[datasetId];   // 这次成功了 —— 撤掉上次的错误
  } catch (e: any) {
    if (!silent) {
      // ⚠️ **不要把列表清空** (2026-10-29 整改) ——
      //    以前这里 `docsByDataset[datasetId] = []`, 表格于是显示「暂无文档」,
      //    文档明明都还在, 用户却以为被删了 (网络抖一下的事).
      //    保留旧数据 + 单独记错误, 表格里显示「加载失败 + 重试」.
      docErrorByDs.value[datasetId] =
        httpErrorText(errorStatus(e), errorDetail(e), '加载失败');
    }
  } finally {
    docLoadingByDs.value[datasetId] = false;
    // ⚠️ 拉完看一眼要不要继续轮询 (解析是异步的, 状态会自己变)
    scheduleDocPoll();
  }
}

// ---------- 文档状态轮询 ----------
//
// ⚠️ **为什么需要**: 解析是 RAGFlow **后台异步**跑的 —— 上传/更新完立刻拉一次,
//    拿到的还是「解析中」, 之后就没人管了, 用户盯着看永远不变.
//    所以只要还有文档在解析, 就定期重拉.
//
// ⚠️ 只认 `run === 'RUNNING'` ——
//    「UNSTART」不能算: 手动分块的数据集我们压根不发解析, 那些文档会**永远**
//    停在 UNSTART, 算进去就是无限轮询.
//    上传后那段「还没变成 RUNNING」的空窗, 用下面的**观察窗口**兜住.
const DOC_POLL_INTERVAL = 3000;      // 轮询间隔
const DOC_POLL_WINDOW = 90_000;      // 上传/更新后的观察窗口 (90 秒)
const DOC_POLL_MAX_MS = 10 * 60_000; // 轮询总时长上限 (防跑飞)
let docPollTimer: ReturnType<typeof setTimeout> | null = null;
let docPollStartedAt = 0;
/** 观察窗口截止时间 —— 上传/更新/重解析后延长 */
let docWatchUntil = 0;

function markDocsWatch() {
  docWatchUntil = Date.now() + DOC_POLL_WINDOW;
  docPollStartedAt = 0;      // 重新起算总时长
  scheduleDocPoll();
}

function hasRunningDocs(): boolean {
  return Object.values(docsByDataset.value)
    .some((list) => (list || []).some((d) => d.run === 'RUNNING'));
}

function scheduleDocPoll() {
  if (docPollTimer) { clearTimeout(docPollTimer); docPollTimer = null; }
  // 页面在后台就别轮询 —— 白费 RAGFlow 的请求
  if (typeof document !== 'undefined' && document.hidden) return;
  const running = hasRunningDocs();
  const inWindow = Date.now() < docWatchUntil;
  if (!running && !inWindow) return;
  // 兜底: 轮询跑太久就停 (万一有个文档卡在 RUNNING 不出来)
  if (docPollStartedAt && Date.now() - docPollStartedAt > DOC_POLL_MAX_MS) return;
  if (!docPollStartedAt) docPollStartedAt = Date.now();
  docPollTimer = setTimeout(() => {
    docPollTimer = null;
    void pollDocs();
  }, DOC_POLL_INTERVAL);
}

async function pollDocs() {
  const ids = Object.keys(docsByDataset.value);
  for (const id of ids) {
    // ⚠️ 页面切走了就别拉了
    if (typeof document !== 'undefined' && document.hidden) return;
    // ⚠️ 库已经被删了 (本页面删的) → 别再去问 RAGFlow, 那是 404
    if (!datasets.value.some((d) => d.id === id)) continue;
    // ⚠️ silent=true —— 轮询失败不弹框、不清列表 (详见 loadDocs 注释)
    await loadDocs(id, true, true);
  }
  scheduleDocPoll();
}

// === 详情抽屉 ===
const detailOpen = ref(false);
const detailDs = ref<KbDataset | null>(null);
function openDetail(d: KbDataset) { detailDs.value = d; detailOpen.value = true; }
// chunks 抽屉状态
const chunksOpen = ref(false);
const chunksTitle = ref('');
const chunksList = ref<KbDocChunk[]>([]);
const chunksTotal = ref(0);
const chunksLoading = ref(false);
/**
 * 分段加载失败的原因 (2026-10-29) ——
 * ⚠️ 以前失败时只弹一个 toast, 抽屉里只剩「该文档暂无分段」,
 *    **加载失败被伪装成了"本来就没有分段"**. 用户会以为文档没切好.
 */
const chunksError = ref('');
/** 当前打开的分段抽屉对应的文档 —— 失败后「重试」要靠它再拉一次 */
const chunksCtx = ref<{ dsId: string; docId: string; docName: string } | null>(null);

// run badge tooltip: 失败时显示 progress_msg, DONE 时显示 process_begin_at + duration
function runTitle(doc: KbDocument): string {
  if (doc.run === 'FAIL' && doc.progress_msg) return doc.progress_msg;
  if (doc.run === 'DONE' && doc.process_duration) {
    const dur = fmtDuration(doc.process_duration);
    return `完成, 耗时 ${dur}`;
  }
  return '';
}

// 文档详情抽屉状态
const docDetailOpen = ref(false);
const docDetail = ref<KbDocument | null>(null);
function openDocDetail(doc: KbDocument) {
  docDetail.value = doc;
  docDetailOpen.value = true;
}

// === 上传文档 (2026-10-29) ===
/** ⚠️ 后端限: 单文件 20MB / 单次 5 个 —— 前端先挡一道, 别让用户白等上传完才报错 */
const MAX_FILE_MB = 20;
const MAX_FILES = 5;
const UPLOAD_ACCEPT = '.txt,.md,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.csv,.json,.html,.htm';

const uploadOpen = ref(false);
/**
 * 目标数据集 —— 存 **id** 而不是对象.
 *
 * ⚠️ 顶部工具条的「⬆ 上传文档」进来时还不知道传哪个库, 得让人自己选;
 *    所以这里用 id 存, 由 :dataset 列表反查对象 (库被删了也不会拿到过期对象).
 */
const uploadDsId = ref('');
const uploadDs = computed(() => datasets.value.find(d => d.id === uploadDsId.value) || null);
const uploadFiles = ref<File[]>([]);
const uploading = ref(false);
const uploadError = ref('');
const uploadResult = ref<{ uploaded: number; ingest_started: boolean; warning?: string } | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

/** 从某个数据集那一行点「⬆ 上传」进来 —— 直接锁定目标库. */
function openUpload(d: KbDataset) {
  uploadDsId.value = d.id;
  uploadFiles.value = [];
  uploadError.value = '';
  uploadResult.value = null;
  uploadOpen.value = true;
}

/** 从标题行点「⬆ 上传文档」进来 —— 默认选第一个, 用户可改. */
function openUploadTop() {
  if (!datasets.value.length) {
    ElMessage.warning('还没有数据集 —— 先新建一个');
    openCreate();
    return;
  }
  uploadDsId.value = uploadDsId.value || datasets.value[0].id;
  uploadFiles.value = [];
  uploadError.value = '';
  uploadResult.value = null;
  uploadOpen.value = true;
}

/**
 * 打开系统文件选择框 —— 自定义按钮转发给藏起来的原生 input.
 *
 * ⚠️ 先把 value 清空 —— 否则**连续选同一个文件**第二次不会触发 change,
 *    用户看着就是"按钮没反应".
 */
function openFilePicker(el: HTMLInputElement | null) {
  if (!el) return;
  el.value = '';
  el.click();
}

function onPickFiles(e: Event) {
  const el = e.target as HTMLInputElement;
  const picked = Array.from(el.files || []);
  uploadError.value = '';
  const kept: File[] = [];
  for (const f of picked) {
    if (f.size > MAX_FILE_MB * 1024 * 1024) {
      uploadError.value = `「${f.name}」超过单文件上限 (${MAX_FILE_MB}MB)`;
      continue;
    }
    if (kept.length + uploadFiles.value.length >= MAX_FILES) {
      uploadError.value = `单次最多上传 ${MAX_FILES} 个文件`;
      break;
    }
    kept.push(f);
  }
  uploadFiles.value = [...uploadFiles.value, ...kept];
  // ⚠️ 清掉 input 的值 —— 否则选同一个文件两次不会触发 change
  el.value = '';
}

function removeFile(i: number) {
  uploadFiles.value = uploadFiles.value.filter((_, idx) => idx !== i);
  uploadError.value = '';
}

async function doUpload() {
  const ds = uploadDs.value;
  if (!ds) { uploadError.value = '先选一个目标数据集'; return; }
  if (!uploadFiles.value.length) { uploadError.value = '还没选文件'; return; }
  uploading.value = true;
  uploadError.value = '';
  uploadResult.value = null;
  try {
    const r = await uploadKbDocuments(ds.id, uploadFiles.value, { silent: true });
    uploadResult.value = {
      uploaded: r.uploaded,
      ingest_started: r.ingest_started,
      warning: r.warning || '',
    };
    uploadFiles.value = [];
    // ⚠️ 有 warning 说明文档进了库但**没参与检索** —— 别弹"成功"把用户骗了
    if (r.warning) ElMessage.warning(r.warning);
    else ElMessage.success(`已上传 ${r.uploaded} 个文档, 解析已启动`);
    // 刷新文档列表 —— 新文档要能马上看见
    delete docsByDataset.value[ds.id];
    await loadDocs(ds.id);
    markDocsWatch();          // ⚠️ 解析是异步的 —— 接着轮询, 让「解析中」自己变成「已完成」
    // ⚠️ 数据集快照也得刷 —— 「文档 / 分段」两列和概览卡统计都来自它.
    //    不刷的话, 刚传完的库还显示「文档 0」, 删库确认框就会照着 0 说话 (硬删!).
    await reloadDatasets();
    await loadAudits(1);   // ⚠️ 新记录在最前面 —— 跳回第 1 页, 别停在旧页码看不见
  } catch (e: any) {
    uploadError.value = httpErrorText(errorStatus(e), errorDetail(e), '上传失败');
  } finally {
    uploading.value = false;
  }
}

/** 下载文档原始文件 (只读操作 → 所有登录用户都能用). */
async function onDownload(d: DsRef, doc: KbDocument) {
  try {
    await downloadKbDocument(d.id, doc.id, doc.name);
  } catch (e: any) {
    ElMessage.error('下载失败: ' + (e?.message || '未知错误'));
  }
}

// === 新建数据集 (2026-10-29) ===
const createOpen = ref(false);
const creating = ref(false);
const createError = ref('');
const createFiles = ref<File[]>([]);
const createFileInput = ref<HTMLInputElement | null>(null);

/**
 * RAGFlow v0.26.1 的**其余**解析器 (「通用」在上面做成大卡片了).
 *
 * ⚠️ 值是 RAGFlow 的**内部名** —— 「通用」在 RAGFlow 里叫 `naive`,
 *    叫 `general` 是**更新版本**的说法, 这版不认 (真机实测 code 101).
 * ⚠️ 合法集合跟 RAGFlow 的校验器对齐 —— 不在集合里的值, 库根本建不出来.
 * ⚠️ **不含 `manual`** —— 手动切分意味着文档进来后分段要自己再调,
 *    而 TestMate 里**没有调分段的功能** —— 建出来的库用户改不了, 是死路.
 *    (协议文档那个老库是 manual, 不受影响; 只是不再给新库提供这个选项)
 *
 * ⚠️ 每条的 `desc` 写的是**「适合存什么文档」** —— 别写成解析器内部行为。
 *    用户是按"我要存的东西"来选的, 不是按"解析器怎么工作"来选的。
 */
const EXTRA_PARSERS: { v: KbChunkMethod; label: string; desc: string }[] = [
  { v: 'qa', label: '问答', desc: '适合 FAQ、售后话术、题库' },
  { v: 'table', label: '表格', desc: '适合台账、清单、参数表' },
  { v: 'paper', label: '论文', desc: '适合研究报告、学术论文' },
  { v: 'book', label: '书籍', desc: '适合手册、教材、有章节的长文档' },
  { v: 'laws', label: '法规', desc: '适合制度、协议、条款类文件' },
  { v: 'presentation', label: 'PPT', desc: '适合幻灯片、演示文稿' },
  { v: 'picture', label: '图片', desc: '适合以图片为主的资料' },
  { v: 'one', label: '单段', desc: '适合短文件，整个当一段' },
  { v: 'email', label: '邮件', desc: '适合邮件归档' },
  { v: 'tag', label: '标签', desc: '适合标签式碎片内容' },
  { v: 'resume', label: '简历', desc: '适合简历库' },
];

const createForm = ref<{
  name: string; description: string; chunkMethod: KbChunkMethod;
  /** 「更多解析方式」下拉的值 —— 空 = 跟着上面的大卡片走 */
  parserExtra: string;
  language: KbLanguage;
}>({
  name: '', description: '', chunkMethod: 'naive', parserExtra: '', language: 'Chinese',
});

const extraParserLabel = computed(
  () => EXTRA_PARSERS.find((p) => p.v === createForm.value.parserExtra)?.label || '',
);

const extraParserDesc = computed(
  () => EXTRA_PARSERS.find((p) => p.v === createForm.value.parserExtra)?.desc || '',
);

/** 点了上面的大卡片 (通用/手动) → 把「更多解析方式」清掉, 免得两个选择打架 */
function onQuickChunk() {
  createForm.value.parserExtra = '';
}

/** 点了「更多解析方式」→ 它**覆盖**大卡片的选择 */
function onExtraParser() {
  const v = createForm.value.parserExtra;
  if (!v) return;
  createForm.value.chunkMethod = v as KbChunkMethod;
}

/**
 * ⚠️ 重名在前端先拦一道.
 *
 * RAGFlow 的数据集名**大小写不敏感且唯一**, 重名了它会自己加数字后缀
 * (`项目管理` → `项目管理(1)`) —— 用户以为建了个新库, 结果多出两个几乎一样的库.
 * 所以这里先查一遍, 撞了就直接不让提交.
 */
const createNameConflict = computed(() => {
  const n = createForm.value.name.trim().toLowerCase();
  if (!n) return false;
  return datasets.value.some(d => (d.name || '').trim().toLowerCase() === n);
});

const createNameHint = computed(() => {
  const n = createForm.value.name.trim();
  if (!n) return '';
  if (createNameConflict.value) return `已经有一个叫「${n}」的数据集了，换个名字`;
  return `将新建「${n}」`;
});

const canSubmitCreate = computed(() => {
  const n = createForm.value.name.trim();
  return !!n && !createNameConflict.value && !creating.value;
});

function openCreate() {
  createForm.value = {
    name: '', description: '', chunkMethod: 'naive', parserExtra: '', language: 'Chinese',
  };
  createFiles.value = [];
  createError.value = '';
  createOpen.value = true;
}

function onPickCreateFiles(e: Event) {
  const el = e.target as HTMLInputElement;
  const picked = Array.from(el.files || []);
  createError.value = '';
  const kept: File[] = [];
  for (const f of picked) {
    if (f.size > MAX_FILE_MB * 1024 * 1024) {
      createError.value = `「${f.name}」超过单文件上限 (${MAX_FILE_MB}MB)`;
      continue;
    }
    if (kept.length + createFiles.value.length >= MAX_FILES) {
      createError.value = `单次最多上传 ${MAX_FILES} 个文件`;
      break;
    }
    kept.push(f);
  }
  createFiles.value = [...createFiles.value, ...kept];
  // 清掉 input 的值 —— 否则选同一个文件两次不会触发 change
  el.value = '';
}

function removeCreateFile(i: number) {
  createFiles.value = createFiles.value.filter((_, idx) => idx !== i);
  createError.value = '';
}

/**
 * 建库 (+ 可选: 顺手把文件传进去).
 *
 * ⚠️ 建完再传是**两步** —— 中间失败的话库还在、文件没进去,
 *    所以上传失败要单独说清楚, 不能只报"成功".
 */
async function doCreate() {
  if (!canSubmitCreate.value) return;
  creating.value = true;
  createError.value = '';
  const form = { ...createForm.value };
  const files = [...createFiles.value];
  try {
    // ⚠️ 最终生效的切片方式 = 「更多解析方式」优先, 没有就用大卡片选的
    const chunkMethod = (createForm.value.parserExtra || createForm.value.chunkMethod) as KbChunkMethod;
    const r = await createKbDataset(
      form.name.trim(), form.description.trim(), chunkMethod, form.language,
    );
    const ds = r.dataset;
    let upStatus: 'none' | 'ok' | 'warn' | 'fail' = 'none';
    let upMsg = '';
    if (files.length && ds?.id) {
      try {
        const u = await uploadKbDocuments(ds.id, files);
        if (u.warning) { upStatus = 'warn'; upMsg = u.warning; }
        else { upStatus = 'ok'; upMsg = `已上传 ${u.uploaded} 个文档，解析已启动`; }
      } catch (ue: any) {
        upStatus = 'fail';
        upMsg = `上传失败：${httpErrorText(errorStatus(ue), errorDetail(ue))}`;
      }
    }
    createOpen.value = false;
    await loadAll();
    // 自动展开新库 —— 建完得让人**马上看见**自己建了什么
    if (ds?.id) { expandedId.value = ds.id; await loadDocs(ds.id); }
    const head = `数据集「${ds?.name || form.name}」已创建`;
    // ⚠️ 后端可能带回 warning (比如语言没设上) —— 如实说, 别只报"成功"
    if (r.warning) {
      ElMessage.warning(`${head}，但 ${r.warning}`);
    } else if (upStatus === 'ok') ElMessage.success(`${head}，${upMsg}`);
    else if (upStatus === 'warn') ElMessage.warning(`${head}，但 ${upMsg}`);
    else if (upStatus === 'fail') ElMessage.error(`${head}，但 ${upMsg}`);
    else ElMessage.success(head);
  } catch (e: any) {
    createError.value = httpErrorText(errorStatus(e), errorDetail(e), '创建失败');
  } finally {
    creating.value = false;
  }
}

// === 更新文档 / 重新解析 (2026-10-29) ===
//
// ⚠️ **RAGFlow 的文档是不可变的** —— 它没有"替换内容"的接口.
//    所以后端是「传新文件 → 删旧文档 → 改回目标名 → 迁移归属 + 重新解析」四步.
//    前端要记住两件事:
//      ① 更新完**文档 id 变了** —— 必须重新拉列表, 别拿旧 id 继续操作;
//      ② 旧版本是**永久删除**的 —— 得让用户看清楚再点.
const updateOpen = ref(false);
const updateDs = ref<DsRef | null>(null);
const updateDoc = ref<KbDocument | null>(null);
const updateFile = ref<File | null>(null);
const updating = ref(false);
const updateError = ref('');
const updateResult = ref<{ name: string; warning?: string; ingest_started?: boolean } | null>(null);
const updateFileInput = ref<HTMLInputElement | null>(null);

function openUpdate(d: DsRef, doc: KbDocument) {
  updateDs.value = d;
  updateDoc.value = doc;
  updateFile.value = null;
  updateError.value = '';
  updateResult.value = null;
  updateOpen.value = true;
}

function onPickUpdateFile(e: Event) {
  const el = e.target as HTMLInputElement;
  const f = (el.files || [])[0];
  // ⚠️ 清掉 input 的值 —— 否则选同一个文件两次不会触发 change
  el.value = '';
  if (!f) return;
  updateError.value = '';
  if (f.size > MAX_FILE_MB * 1024 * 1024) {
    updateError.value = `「${f.name}」超过单文件上限 (${MAX_FILE_MB}MB)`;
    return;
  }
  updateFile.value = f;
}

async function doUpdate() {
  const ds = updateDs.value;
  const doc = updateDoc.value;
  const f = updateFile.value;
  if (!ds || !doc) return;
  if (!f) { updateError.value = '还没选文件'; return; }
  updating.value = true;
  updateError.value = '';
  updateResult.value = null;
  try {
    const r = await updateKbDocument(ds.id, doc.id, f, { silent: true });
    updateResult.value = {
      name: r.updated?.name || f.name,
      warning: r.warning || '',
      ingest_started: r.ingest_started,
    };
    updateFile.value = null;
    // ⚠️ 文档 id 变了 —— 必须丢掉缓存重新拉, 不然前端拿着旧 id 继续操作会 404
    delete docsByDataset.value[ds.id];
    await loadDocs(ds.id);
    markDocsWatch();          // ⚠️ 解析是异步的 —— 接着轮询, 让「解析中」自己变成「已完成」
    // ⚠️ 数据集快照也得刷 —— 「文档 / 分段」两列和概览卡统计都来自它.
    //    不刷的话, 刚传完的库还显示「文档 0」, 删库确认框就会照着 0 说话 (硬删!).
    await reloadDatasets();
    await loadAudits(1);   // ⚠️ 新记录在最前面 —— 跳回第 1 页, 别停在旧页码看不见
    if (r.warning) {
      // ⚠️ 有 warning 说明文档换了但**没参与检索** —— 别弹"成功"把用户骗了,
      //    抽屉也别关, 让他把这段话看完
      ElMessage.warning(r.warning);
    } else if (!r.ingest_started) {
      // ⚠️ 解析没起来 —— 文档换了但**参与不了检索**, 得说清楚
      ElMessage.warning(`「${doc.name}」已替换, 但解析启动失败 —— 请让管理员重跑解析`);
      updateOpen.value = false;
    } else {
      ElMessage.success(`「${doc.name}」已替换为「${r.updated?.name || f.name}」，解析已启动`);
      updateOpen.value = false;
    }
  } catch (e: any) {
    updateError.value = httpErrorText(errorStatus(e), errorDetail(e), '更新失败');
  } finally {
    updating.value = false;
  }
}

/** 重新解析 (内容不变, 重跑一遍切片/向量化). */
async function doReparse(d: DsRef, doc: KbDocument) {
  const chunks = doc.chunk_count || 0;
  try {
    await ElMessageBox.confirm(
      `重新解析「${doc.name}」？会清掉现有的 ${chunks} 个分段，再重新跑一遍。`,
      '重新解析',
      {
        type: 'warning',
        confirmButtonText: '重新解析',
        cancelButtonText: '取消',
      },
    );
  } catch {
    return; // 用户取消 —— 不是错误
  }
  try {
    await reparseKbDocument(d.id, doc.id, { silent: true });
    ElMessage.success(`「${doc.name}」已重新提交解析`);
    delete docsByDataset.value[d.id];
    await loadDocs(d.id);
    markDocsWatch();          // ⚠️ 重解析也是异步的 —— 状态要自己跟上
    await reloadDatasets();   // ⚠️ 分段数会变 —— 数据集快照跟着刷
    await loadAudits(1);   // ⚠️ 新记录在最前面 —— 跳回第 1 页, 别停在旧页码看不见
  } catch (e: any) {
    ElMessage.error('重新解析失败: ' + httpErrorText(errorStatus(e), errorDetail(e)));
  }
}

// === 文档搜索 (2026-10-29) ===
//
// ⚠️ **只搜文件名, 不搜文档内容** —— RAGFlow 的 keywords 语义是
//    `LOWER(name).contains(keywords.lower())` (api/db/services/document_service.py:135),
//    **不区分大小写的子串匹配**. 页面上得说清楚, 别让人以为搜不到就是没有.
/**
 * 数据集引用 —— **只要 id 就够了**.
 *
 * ⚠️ 搜索结果里没有完整的 KbDataset 对象 (只有 dataset_id / dataset_name),
 *    所以这几个操作函数的第一个参数收窄成 `{ id: string }` ——
 *    完整的 KbDataset 照样能传 (结构化类型).
 */
type DsRef = { id: string };

const docSearchKw = ref('');
const docSearchHits = ref<KbDocSearchHit[]>([]);
const docSearchLoading = ref(false);
const docSearchError = ref('');
/** 已经搜过了 —— 用来区分「搜了没结果」和「还没搜」 */
const docSearched = ref(false);
const docSearchTotal = ref(0);
const docSearchTruncated = ref(false);
/** 防抖定时器 —— 必须清, 否则离开页面后它照样触发 */
let docSearchTimer: ReturnType<typeof setTimeout> | null = null;

/** 搜索结果里的文档 → 它所在的库 */
function dsOf(hit: KbDocSearchHit): DsRef { return { id: hit.dataset_id }; }

function onDocSearchInput() {
  if (docSearchTimer) clearTimeout(docSearchTimer);
  const kw = docSearchKw.value.trim();
  if (!kw) { clearDocSearch(); return; }
  // ⚠️ 防抖 —— 每敲一个字就发一轮「每个库一次请求」, 库多了会把 RAGFlow 打爆
  docSearchTimer = setTimeout(() => { void doDocSearch(); }, 400);
}

/**
 * 跨库搜索 —— 请求序号.
 *
 * ⚠️ 2026-10-29: 跨库搜索要**逐个库**查 (后端并发发 N 个请求), 耗时可观.
 *    以前慢的旧请求后返回会**覆盖**新关键词的结果 —— 用户搜「2024」,
 *    屏幕上却是「手册」那批, 标题还写着「搜索「2024」找到 3 篇」.
 *    只认最后一次请求的结果.
 */
let docSearchSeq = 0;

async function doDocSearch() {
  const kw = docSearchKw.value.trim();
  if (!kw) { clearDocSearch(); return; }
  const seq = ++docSearchSeq;
  docSearchLoading.value = true;
  docSearchError.value = '';
  // ⚠️ **发起即清空** —— 以前保留上一个关键词的结果, 请求期间屏幕上还是旧数据,
  //    标题却已经变成新关键词 → 用户以为搜错了. 清空后走「搜索中…」那一行.
  docSearchHits.value = [];
  docSearchTotal.value = 0;
  docSearchTruncated.value = false;
  docSearched.value = true;
  try {
    const r = await searchKbDocuments(kw, '', { silent: true });
    // ⚠️ 迟到的旧请求 —— 丢掉, 别覆盖新结果
    if (seq !== docSearchSeq) return;
    docSearchHits.value = r.items || [];
    docSearchTotal.value = r.total || 0;
    docSearchTruncated.value = !!r.truncated;
  } catch (e: any) {
    if (seq !== docSearchSeq) return;
    docSearchError.value = httpErrorText(errorStatus(e), errorDetail(e), '搜索失败');
    docSearchHits.value = [];
    docSearchTotal.value = 0;
    docSearchTruncated.value = false;
  } finally {
    if (seq === docSearchSeq) docSearchLoading.value = false;
  }
}

function clearDocSearch() {
  if (docSearchTimer) { clearTimeout(docSearchTimer); docSearchTimer = null; }
  // ⚠️ 序号也要推进 —— 否则在途的旧请求回来还会把结果写回来
  docSearchSeq++;
  docSearchKw.value = '';
  docSearchHits.value = [];
  docSearchError.value = '';
  docSearched.value = false;
  docSearchTotal.value = 0;
  docSearchTruncated.value = false;
  docSearchLoading.value = false;
}

// ⚠️ 离开页面要把定时器清掉 —— 不然它在后台照样触发, 白发一轮请求
onBeforeUnmount(() => {
  if (docSearchTimer) clearTimeout(docSearchTimer);
  if (docPollTimer) { clearTimeout(docPollTimer); docPollTimer = null; }
});

// === 操作记录 (审计) ===
const audits = ref<KbAuditItem[]>([]);
const auditLoading = ref(false);
const auditError = ref('');
// ⚠️ 分页状态 (2026-10-29) —— 审计流水只增不减, 一次拉 50 条后面全是旧的
// ⚠️ 默认每页 **10** 条 —— 20 条的话表格太长, 分页条被顶到屏幕外看不见了
const auditPage = ref(1);
const auditPageSize = ref(10);
const auditTotal = ref(0);
const auditPages = ref(1);

function auditActionLabel(a: string): string {
  // ⚠️ 2026-10-29: **delete 和 delete_doc 要分开** ——
  //    delete = 删除数据集 (硬删整个库), delete_doc = 删除数据集里的某篇文档.
  //    以前两者都显示「删除」, admin 在操作记录里分不清删的是库还是文档.
  return ({
    upload: '上传', delete: '删除数据集', delete_doc: '删除文档',
    ingest: '解析', create: '新建', update: '更新', reparse: '重解析',
  } as Record<string, string>)[a] || a;
}

/**
 * 删除数据集 —— **必须输入库名**才能删.
 *
 * ⚠️ RAGFlow 的删除是**硬删**: 库里的每个文档都会走 `remove_document`,
 *    连同 MinIO 里的源文件、ES 里的分段一起没了, **没有回收站**.
 *    所以光点一下「确定」不够 —— 得把库名敲出来, 逼用户确认自己删的是哪个库.
 *    (这项目刚出过误删 5 篇协议 PDF 的事故 —— 见交接文档 §㉕⑧)
 *
 * ⚠️ ElMessageBox 是**纯文本**, 不渲染 Markdown —— 别写 `**强调**`.
 */
async function doDeleteDataset(d: KbDataset) {
  // ⚠️ **绝对不能用列表快照里的 document_count** (2026-10-29 整改) ——
  //    那是**上一次 loadAll() 时**的旧值. 上传文档后 doUpload 只刷了文档列表,
  //    没刷数据集列表 → 计数停留在上传前.
  //    结果就是: 库里明明有 3 篇文档, 确认框却写「这个库目前是空的」,
  //    admin 以为只是删个空壳, 结果 3 篇文档连同源文件、分段一起没了 ——
  //    **RAGFlow 是硬删, 没有回收站, 这一步不可逆.**
  //    所以这里**现查一次真实篇数**; 查不到就退化成不带数字的措辞
  //    (绝不能瞎报 0 —— 报 0 等于骗用户).
  let realDocs = -1;
  try {
    const r = await listDocuments(d.id, { page: 1, page_size: 1 }, { silent: true });
    realDocs = Number(r.total ?? r.docs?.length ?? 0);
  } catch {
    realDocs = -1;   // 查不到 —— 别猜
  }
  const scope = realDocs > 0
    ? `会连同该库里的 ${realDocs} 篇文档、它们的分段和源文件一起永久删除，无法恢复`
    : realDocs === 0
      ? '该库目前确实是空的（已核实），删除后无法恢复'
      : '该库下的全部文档、分段和源文件会被永久删除，无法恢复';
  try {
    await ElMessageBox.prompt(
      `即将删除「${d.name}」—— ${scope}。\n请输入数据集名称「${d.name}」以确认：`,
      '删除数据集',
      {
        type: 'warning',
        confirmButtonText: '永久删除',
        cancelButtonText: '取消',
        inputPlaceholder: d.name,
        inputValidator: (v: string) =>
          (v || '').trim() === d.name ? true : '名称对不上 —— 请原样输入上面的数据集名称',
      },
    );
  } catch {
    // 用户取消 —— 不是错误
    return;
  }
  deletingDsId.value = d.id;
  try {
    const r = await deleteKbDataset(d.id, { silent: true });
    ElMessage.success(`数据集「${r.deleted?.name || d.name}」已删除`);
    // 本地缓存也要清 —— 库没了, 文档列表也没了
    delete docsByDataset.value[d.id];
    delete docLoadingByDs.value[d.id];
    delete docErrorByDs.value[d.id];
    if (expandedId.value === d.id) expandedId.value = '';
    await loadAll();
    await loadAudits(1);   // ⚠️ 新记录在最前面 —— 跳回第 1 页, 别停在旧页码看不见
  } catch (e: any) {
    ElMessage.error('删除失败: ' + httpErrorText(errorStatus(e), errorDetail(e)));
  } finally {
    deletingDsId.value = '';
  }
}

/**
 * 删除**一篇文档** —— 只给 admin, 且要**输入文档名**确认.
 *
 * ⚠️ RAGFlow 的删除是**硬删**: 源文件(MinIO)、分段(ES) 一起没了, **没有回收站**.
 *    所以跟删数据集一个口径 —— 让用户把文档名敲出来, 逼他确认删的是哪一篇.
 * ⚠️ 权限跟「删除数据集/查看操作记录」同一档: **admin only**.
 * ⚠️ ElMessageBox 是**纯文本**, 不渲染 Markdown —— 别写 `**强调**`.
 */
async function doDeleteDocument(d: DsRef, doc: KbDocument) {
  const chunks = doc.chunk_count || 0;
  const scope = chunks
    ? `源文件和 ${chunks} 个分段会一起永久删除，无法恢复`
    : '源文件会永久删除，无法恢复';
  try {
    await ElMessageBox.prompt(
      `即将删除文档「${doc.name}」—— ${scope}。\n请输入文档名称「${doc.name}」以确认：`,
      '删除文档',
      {
        type: 'warning',
        confirmButtonText: '永久删除',
        cancelButtonText: '取消',
        inputPlaceholder: doc.name,
        inputValidator: (v: string) =>
          (v || '').trim() === doc.name ? true : '名称对不上 —— 请原样输入上面的文档名称',
      },
    );
  } catch {
    // 用户取消 —— 不是错误
    return;
  }
  const docKey = `${d.id}::${doc.id}`;
  deletingDocKey.value = docKey;
  try {
    await deleteKbDocuments(d.id, [doc.id], false, { silent: true });
    ElMessage.success(`文档「${doc.name}」已删除`);
    // ⚠️ 本地缓存要立刻清 —— 不然列表里还挂着那一篇 (下一次轮询才会消失)
    const list = docsByDataset.value[d.id];
    if (list) {
      docsByDataset.value[d.id] = list.filter((x) => x.id !== doc.id);
    }
    await loadAll();
    await loadAudits(1);   // ⚠️ 新记录在最前面 —— 跳回第 1 页
  } catch (e: any) {
    ElMessage.error('删除失败: ' + httpErrorText(errorStatus(e), errorDetail(e)));
  } finally {
    deletingDocKey.value = '';
  }
}

async function loadAudits(page?: number) {
  // ⚠️ 只有 admin 能看操作记录 —— 别去请求 (后端会 403, 还会弹一个没意义的错误)
  if (!isAdmin.value) return;
  // ⚠️ 不传 page 就留在当前页; 传了就跳到那一页
  //    (操作完一个动作后要跳回第 1 页 —— 最新的记录在**最前面**)
  if (page && page >= 1) auditPage.value = page;
  auditLoading.value = true;
  auditError.value = '';
  try {
    const r = await listKbAudits(auditPage.value, auditPageSize.value);
    audits.value = r.items || [];
    // ⚠️ 这里再做一次兜底 —— 测试里 mock 掉的是整个 listKbAudits,
    //    api 层那套归一化不会跑, 组件自己也得扛住缺字段的情况
    auditTotal.value = Number(r.total ?? audits.value.length);
    auditPages.value = Number(
      r.pages ?? Math.max(1, Math.ceil(auditTotal.value / auditPageSize.value)),
    );
    // ⚠️ 后端可能把越界页码纠正回最后一页 —— 跟着它走, 别让页码显示跟内容对不上
    if (r.page && r.page !== auditPage.value) auditPage.value = r.page;
  } catch (e: any) {
    auditError.value = httpErrorText(errorStatus(e), errorDetail(e), '读取失败');
  } finally {
    auditLoading.value = false;
  }
}

/** 翻页 —— 目标页跟当前页一样就什么都不干 (别白发一轮请求) */
function gotoAuditPage(p: number) {
  if (p < 1 || p > auditPages.value || p === auditPage.value) return;
  void loadAudits(p);
}

/** 改每页条数 —— 回到第 1 页 */
function onAuditPageSizeChange() {
  auditPage.value = 1;
  void loadAudits(1);
}

// 角色变了(比如切账号 / 权限被改) —— 顺手把已经看到的记录清掉, 别留在屏幕上
watch(isAdmin, (ok) => {
  if (!ok) {
    audits.value = [];
    auditError.value = '';
  }
});

async function openChunks(d: DsRef, doc: KbDocument) {
  chunksTitle.value = `📑 ${doc.name} · 分段预览`;
  chunksOpen.value = true;
  chunksList.value = [];
  chunksLoading.value = true;
  // ⚠️ **总数也要重置** (2026-10-29 整改) ——
  //    以前只清了列表, 标题上「共 37 个分段」还挂着**上一篇**的数字,
  //    用户点开新文档却看到旧文档的分段数.
  chunksTotal.value = 0;
  chunksError.value = '';
  chunksCtx.value = { dsId: d.id, docId: doc.id, docName: doc.name };
  try {
    // RAGFlow 限制 page_size <= 100, 后端 / API 层都会兜底; 这里用 100
    const r = await listDocChunks(d.id, doc.id, { page_size: 100 });
    chunksList.value = r.chunks;
    chunksTotal.value = r.total;
  } catch (e: any) {
    // ⚠️ **别用「该文档暂无分段」冒充失败** —— 加载失败要说失败,
    //    否则用户以为这篇文档本来就没分段 (其实是没取到).
    chunksError.value = httpErrorText(errorStatus(e), errorDetail(e), '加载分段失败');
    ElMessage.error('加载分段失败: ' + chunksError.value);
  } finally {
    chunksLoading.value = false;
  }
}

/** 分段加载失败后「重试」—— 拿上下文再拉一次 */
async function retryChunks() {
  const c = chunksCtx.value;
  if (!c) return;
  chunksError.value = '';
  chunksLoading.value = true;
  chunksList.value = [];
  try {
    const r = await listDocChunks(c.dsId, c.docId, { page_size: 100 });
    chunksList.value = r.chunks;
    chunksTotal.value = r.total;
  } catch (e: any) {
    chunksError.value = httpErrorText(errorStatus(e), errorDetail(e), '加载分段失败');
  } finally {
    chunksLoading.value = false;
  }
}

// === 数据加载 ===
async function loadAll() {
  loading.value = true;
  dsError.value = '';
  // ⚠️ **健康检查跟列表加载要分开 try** (2026-10-29 整改) ——
  //    以前两个请求串在同一个 try 里, health 一抛错 (网关 5xx / 代理层异常),
  //    `datasets` 就留在空数组, 页面上写「数据集加载失败」——
  //    **可 `/kb/datasets` 压根没被请求过**. 用户以为知识库挂了, 其实只是探针抖了.
  try {
    const h = await kbHealth({ silent: true });
    rfStatus.value = h.status as any;
    rfMsg.value = h.message || h.status;
  } catch (e: any) {
    // ⚠️ 探针失败只把徽标置灰, **不能**因此不加载列表
    rfStatus.value = 'warn';
    rfMsg.value = '健康检查失败（列表仍会加载）';
  }
  try {
    const r = await listDatasets({ silent: true });
    datasets.value = r.items;
    // 清掉已展开 dataset 不存在的 docs
    const keep = new Set(r.items.map(x => x.id));
    for (const id of Object.keys(docsByDataset.value)) {
      if (!keep.has(id)) {
        delete docsByDataset.value[id];
        delete docLoadingByDs.value[id];
        delete docErrorByDs.value[id];
      }
    }
  } catch (e: any) {
    rfStatus.value = rfStatus.value === 'ok' ? 'ok' : 'off';
    // ⚠️ 失败 ≠ 空列表 —— 表格里要单独说 (别再显示「暂无数据集」)
    dsError.value = httpErrorText(errorStatus(e), errorDetail(e), '数据集加载失败');
    ElMessage.error('知识库加载失败: ' + dsError.value);
  } finally { loading.value = false; }
}

/**
 * 只刷**数据集列表** (不重探健康).
 *
 * ⚠️ 上传/更新/重解析之后必须调它 (2026-10-29 整改) ——
 *    表格里的「文档 / 分段」两列和概览卡的统计都来自这份快照.
 *    以前上传完只刷了**文档列表**, 数据集快照还是上传前的 ——
 *    于是「文档 0」的库其实有 3 篇, 删库确认框就照着 0 说话 (硬删, 不可逆!).
 *    这里刷的是纯列表接口, 代价小.
 */
async function reloadDatasets() {
  try {
    const r = await listDatasets({ silent: true });
    datasets.value = r.items;
  } catch {
    // 静默 —— 计数只是暂时不准, 不该因此打断用户手上的事
  }
}

async function onReload() {
  await loadAll();
  // ⚠️ **文档缓存也得清掉** —— 以前只 loadAll() (刷数据集列表),
  //    文档列表走的是缓存, 结果点「↻ 刷新」数据集变了、文档还是旧的.
  //    用户看着「点了没反应」就是这个原因.
  for (const id of Object.keys(docsByDataset.value)) delete docsByDataset.value[id];
  await warmupAllDocs(true);
}

// 预热所有数据集的文档, 让概览的总大小/分段/文档数立即准确, 且展开时直接命中缓存
async function warmupAllDocs(force = false) {
  if (!datasets.value.length) return;
  await Promise.allSettled(datasets.value.map(d => loadDocs(d.id, force)));
}

onMounted(async () => {
  await Promise.allSettled([
    loadAll(),
    loadShareConfig(),
    // ⚠️ 操作记录只有 admin 能看 —— 别的角色别去请求
    isAdmin.value ? loadAudits() : Promise.resolve(),
  ]);
  // 不阻塞 UI: 后台预热文档列表, 概览总大小 / 分段数 / 文档数随后到位
  warmupAllDocs();
  if (activeTab.value === 'search' && searchEmbedUrl.value) await reResolve('search');
  else if (activeTab.value === 'chat' && chatEmbedUrl.value) await reResolve('chat');
});
</script>

<style scoped>
.kb { display: flex; flex-direction: column; gap: 10px; }
.card-overview { padding: 14px 18px; }
.card-overview h2 { margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
.card-overview .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.card-overview .stat { text-align: center; padding: 8px 6px; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 8px; }
.card-overview .num { font-size: 20px; font-weight: 800; font-family: var(--font-mono); line-height: 1; letter-spacing: -0.5px; background: var(--primary-grad-text); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; color: transparent; }
.card-overview .lbl { font-size: 11px; color: var(--ink-500); margin-top: 4px; }

/* RAGFlow 共享搜索 */
.card-share { display: flex; flex-direction: column; padding: 14px 18px; }
.share-hd { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 8px; flex-wrap: wrap; }
.share-t { font-size: 15px; font-weight: 700; color: var(--ink-900); display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.share-tabs { display: inline-flex; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 9px; padding: 3px; gap: 2px; }
.share-tab { background: transparent; border: 0; cursor: pointer; padding: 6px 14px; border-radius: 7px; font-size: 12.5px; font-weight: 500; font-family: inherit; color: var(--ink-700); transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s ease; }
.share-tab:hover { color: var(--ink-900); }
.share-tab.active { background: var(--surface); font-weight: 600; box-shadow: inset 0 0 0 1px var(--border); }
.share-tab.active .lbl { display: inline-block; background: var(--primary-grad-text); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; color: transparent; }
.share-sub-inline { font-size: 12px; font-weight: 400; color: var(--ink-500); }
.share-frame-wrap { width: 100%; border-radius: 10px; overflow: hidden; border: 1px solid var(--border); background: var(--surface-sunken); }
.share-frame { display: block; border: 0; width: 100%; height: 100%; min-height: inherit; }
.share-pop { display: inline-block; margin-top: 10px; font-size: 11.5px; color: var(--primary); text-decoration: none; align-self: flex-end; }
.share-pop:hover { text-decoration: underline; }
.search-placeholder { padding: 60px 20px; text-align: center; color: var(--ink-500); }
.ph-ic { font-size: 48px; opacity: 0.4; margin-bottom: 12px; }
.ph-t { font-size: 16px; font-weight: 600; color: var(--ink-700); margin-bottom: 6px; }
.ph-d { font-size: 12.5px; color: var(--ink-500); }
.ph-d code { background: var(--surface-sunken); padding: 2px 6px; border-radius: 4px; font-size: 11.5px; color: var(--primary); }

h2 { font-size: 15px; font-weight: 700; margin: 0 0 14px; color: var(--ink-900); display: flex; align-items: center; gap: 8px; }

.rf-status { margin-left: auto; font-size: 11px; font-weight: 500; display: inline-flex; align-items: center; gap: 5px; padding: 3px 9px; border-radius: var(--radius-pill); }
.rf-status .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.s-ok { background: rgba(16, 185, 129, 0.1); color: var(--ok); }
.s-warn { background: rgba(245, 158, 11, 0.1); color: var(--warn); }
.s-off { background: rgba(239, 68, 68, 0.1); color: var(--err); }

/* 数据集表 */
.ds-hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.ds-hd h2 { margin: 0; }
.reload { background: transparent; border: 1px solid var(--border); padding: 4px 10px; border-radius: 6px; color: var(--ink-700); font-size: 11.5px; cursor: pointer; font-family: inherit; }
.reload:hover { border-color: var(--primary); color: var(--primary); }
.reload:disabled { opacity: 0.5; }
.reload.sm { padding: 2px 8px; font-size: 11px; }

/* ⚠️ 分页条 (2026-10-29) —— 操作记录页数多, 必须能翻 */
.ds-count { font-size: 12px; color: var(--ink-500); }
.pg-bar {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border);
  font-size: 12px; color: var(--ink-500);
}
.pg-info b { color: var(--ink-700); }
.pg-btns { display: flex; gap: 6px; }
.pg-btn {
  background: transparent; border: 1px solid var(--border); border-radius: 6px;
  color: var(--ink-700); font-size: 11.5px; padding: 4px 10px;
  cursor: pointer; font-family: inherit; white-space: nowrap;
}
.pg-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.pg-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.pg-size { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.pg-select {
  border: 1px solid var(--border); border-radius: 6px; background: var(--surface);
  color: var(--ink-700); font-size: 12px; padding: 3px 6px; font-family: inherit;
  cursor: pointer;
}

/* ⚠️ **表格横向滚动容器** (2026-10-29 补) ——
   数据集表有 9 列 (含 140px 的「操作」列), 文档子表 7 列 (含 270px 操作列).
   没有包裹层的话, 窄屏下表格的 min-content 宽度会**穿透卡片边框**,
   还会让 `.tm-main` 冒出横向滚动条 (整页被拖走).
   ⚠️ min-width 不能省 —— 只加 overflow 的话, 窄屏下表格还是被压成一团. */
.tbl-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.tbl-wrap > .ds-tbl { min-width: 760px; }
.tbl-wrap > .doc-tbl { min-width: 700px; }

.ds-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.ds-tbl th { text-align: left; padding: 10px 12px; color: var(--ink-500); font-weight: 500; font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid var(--border); }
.ds-tbl td { padding: 10px 12px; color: var(--ink-700); border-bottom: 1px solid var(--border); vertical-align: middle; }
.ds-tbl tr:hover { background: var(--surface-sunken); }
.ds-row.open { background: var(--surface-sunken); }
.ds-row.open td { border-bottom-color: transparent; }

/* ⚠️ 折叠按钮 (2026-10-29) —— 以前是个灰色的 ▸ 字, 没人知道能点.
   改成带边框的胶囊 + 「展开/收起」文字, 一眼就知道这个库能展开看文档. */
.exp-cell { width: 92px; }
.exp {
  display: inline-flex; align-items: center; gap: 4px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 999px;
  color: var(--ink-700); cursor: pointer; font-size: 11.5px; font-family: inherit;
  padding: 3px 10px; white-space: nowrap;
  transition: border-color .15s, color .15s, background .15s;
}
.exp:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-soft); }
.exp.on { border-color: var(--primary); color: var(--primary); background: var(--primary-soft); }
.exp-ic { font-size: 10px; line-height: 1; }

.nm { display: flex; align-items: center; gap: 6px; color: var(--ink-900); font-weight: 500; }
.ds-ic { font-size: 16px; }
/* ⚠️ 名字也能点开 —— 给个手型 + 悬停变色, 让用户知道这是个可点的入口 */
/* ⚠️ 2026-10-29: 库名要**能截断** —— `td.nm` 是 display:flex, 不限宽的话
   一长串英文库名会把这一列撑开, 其它列全被压扁, 表格横向溢出卡片.
   跟 `.doc-name` 一个口径 (max-width 280 + 省略号). */
.ds-name {
  cursor: pointer; border-bottom: 1px dashed transparent;
  max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ds-name:hover { color: var(--primary); border-bottom-color: var(--primary); }
/* ⚠️ 解析进度条 (2026-10-29) —— 接口给了 progress 字段但页面从没用过,
   用户只看到一枚静态的「解析中」, 不知道还要等多久、是不是卡住了. */
.doc-prog {
  display: block; width: 70px; height: 3px; margin-top: 3px;
  border-radius: 2px; background: var(--border-strong); overflow: hidden;
}
.doc-prog > i {
  display: block; height: 100%; border-radius: 2px;
  background: var(--primary); transition: width .4s ease;
}
.emb { color: var(--ink-500); font-size: 11.5px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ds-desc { color: var(--ink-700); font-size: 12px; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.perm { font-size: 10.5px; padding: 2px 7px; border-radius: var(--radius-pill); font-weight: 600; }
.perm-me { background: var(--surface-sunken); color: var(--ink-700); }
.perm-team { background: rgba(13, 148, 136, 0.12); color: var(--primary-2, var(--primary)); }

.mono { font-family: var(--font-mono); font-size: 12px; }
.empty { text-align: center; color: var(--ink-500); padding: 32px 12px !important; }
/* 取数失败 —— 跟"真的没有数据"区分开 */
.empty.err { color: var(--err); }
.empty.err .ghost-btn { margin-left: 10px; }

.ghost-btn { background: transparent; border: 1px solid var(--border); color: var(--ink-700); padding: 3px 9px; border-radius: 6px; font-size: 11.5px; cursor: pointer; font-family: inherit; transition: border-color .15s, color .15s; }
.ghost-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.ghost-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* 文档子表 */
.ds-subcell { padding: 0 12px 14px 36px !important; background: var(--surface-sunken); }
.doc-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.doc-hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.doc-t { font-size: 12.5px; font-weight: 600; color: var(--ink-900); }
.doc-tools { display: flex; gap: 6px; align-items: center; }
.doc-tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.doc-tbl th { text-align: left; padding: 6px 8px; color: var(--ink-500); font-weight: 500; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid var(--border); }
.doc-tbl td { padding: 7px 8px; color: var(--ink-700); border-bottom: 1px dashed var(--border); }
.doc-tbl tr:last-child td { border-bottom: none; }
.doc-tbl tr.failed td { background: rgba(239, 68, 68, 0.04); }
.doc-ic { font-size: 15px; margin-right: 4px; }
.doc-name { color: var(--ink-900); font-weight: 500; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; vertical-align: middle; }

/* run 状态徽章 */
.run-badge { display: inline-block; font-size: 10.5px; padding: 2px 8px; border-radius: var(--radius-pill); font-weight: 600; white-space: nowrap; }
.run-done { background: rgba(16, 185, 129, 0.12); color: var(--ok); }
.run-running { background: rgba(59, 130, 246, 0.12); color: var(--primary); }
.run-unstart { background: var(--surface-sunken); color: var(--ink-500); }
.run-cancel { background: rgba(245, 158, 11, 0.12); color: var(--warn); }
.run-fail { background: rgba(239, 68, 68, 0.12); color: var(--err); }

/* 详情抽屉 */
.dt { display: flex; flex-direction: column; gap: 10px; }
.dt-row { display: grid; grid-template-columns: 110px 1fr; gap: 10px; align-items: baseline; padding: 6px 0; border-bottom: 1px dashed var(--border); }
.dt-k { font-size: 11.5px; color: var(--ink-500); }
.dt-v { font-size: 12.5px; color: var(--ink-900); }
.dt-v.mono { font-family: var(--font-mono); font-size: 12px; }
.dt-sep { font-size: 12.5px; font-weight: 700; color: var(--ink-700); margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); }
.dt-pre { font-family: var(--font-mono); font-size: 11.5px; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 6px; padding: 10px; max-height: 240px; overflow: auto; white-space: pre-wrap; word-break: break-all; }
.dt-err { color: var(--err); white-space: pre-wrap; word-break: break-word; max-height: 160px; overflow: auto; display: block; }

/* 文档行内联操作按钮 (下载 / 分段) */
.link-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--ink-700);
  padding: 3px 9px;
  border-radius: 6px;
  font-size: 11px;
  font-family: inherit;
  cursor: pointer;
  margin-right: 4px;
  text-decoration: none;
  display: inline-block;
  transition: border-color .15s, color .15s, background .15s;
}
.link-btn:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-soft); }
.link-btn:last-child { margin-right: 0; }

/* 上传文档 (2026-10-29) */
/* ⚠️ `.upload-btn` 已删 (2026-10-29) —— 它只挂在文档子表那个重复的
   「⬆ 上传文档」按钮上, 那个按钮删了以后这行样式也一起删掉, 别留死代码 */
.up-panel { display: flex; flex-direction: column; gap: 12px; }
.up-tip { font-size: 13px; color: var(--ink-700); }
.up-tip b { color: var(--ink-900); }
.up-rules { font-size: 12px; color: var(--ink-500); line-height: 1.9; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.up-rules b { color: var(--ink-900); }
.up-input { font-size: 12px; color: var(--ink-700); }
/* ⚠️ **自定义文件选择器** (2026-10-29) ——
   原生 <input type="file"> 渲染出来是浏览器自带的灰色小按钮, 宽度还随系统语言变,
   跟抽屉里其它控件摆一起特别突兀 (图1).
   做法: input 藏起来 (还在 DOM 里 —— change 照样触发, 测试也还能定位到它),
   外面套一个自定义按钮, 点它转发给 input.click(). */
.up-file-hidden {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}
.fpick { display: flex; }
.fpick-btn {
  display: flex; align-items: center; gap: 8px; width: 100%; box-sizing: border-box;
  background: var(--surface); border: 1px dashed var(--border);
  border-radius: 8px; padding: 10px 12px; cursor: pointer;
  font-family: inherit; font-size: 12.5px; color: var(--ink-700); text-align: left;
  transition: border-color .15s, background .15s;
}
.fpick-btn:hover { border-color: var(--primary); background: var(--primary-soft); }
.fpick-btn:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }
.fpick-ic { font-size: 15px; line-height: 1; }
.fpick-tx { font-weight: 600; color: var(--ink-900); white-space: nowrap; }
.fpick-hint { color: var(--ink-500); font-size: 11.5px; margin-left: auto; text-align: right; }
.up-files { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.up-files li { display: flex; align-items: center; gap: 8px; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 7px; padding: 6px 10px; font-size: 12px; }
.up-fn { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-900); }
.up-fs { color: var(--ink-500); font-size: 11px; }
.up-rm { background: transparent; border: 0; color: var(--ink-500); cursor: pointer; font-size: 12px; padding: 0 2px; }
.up-rm:hover { color: var(--err); }
.up-empty { font-size: 12px; color: var(--ink-500); padding: 12px 0; }
.up-err { font-size: 12px; color: var(--err); }
.up-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
.primary-btn { background: var(--primary); border: 1px solid var(--primary); color: #fff; padding: 6px 16px; border-radius: 7px; font-size: 12.5px; font-weight: 600; font-family: inherit; cursor: pointer; }
.primary-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.up-result { font-size: 12px; color: var(--ink-700); background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px; }

/* chunks 抽屉 */
.chunks-panel { display: flex; flex-direction: column; gap: 12px; }
.chunks-hd { display: flex; align-items: center; justify-content: space-between; padding: 4px 0 8px; border-bottom: 1px solid var(--border); }
.chunks-meta { display: flex; gap: 10px; align-items: center; font-size: 12px; color: var(--ink-500); }
.chunks-tot { font-weight: 600; color: var(--ink-900); }
.chunks-load { color: var(--primary); }
.chunk-card { background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.chunk-hd { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.chunk-num { font-size: 11px; font-weight: 700; color: var(--primary); font-family: var(--font-mono); }
.chunk-id { font-size: 10.5px; color: var(--ink-500); }
.chunk-kw { display: inline-flex; gap: 4px; flex-wrap: wrap; margin-left: auto; }
.kw-tag { font-size: 10px; padding: 2px 7px; border-radius: var(--radius-pill); background: rgba(59, 130, 246, 0.1); color: var(--primary); font-weight: 500; }
.kw-tag-tag { background: rgba(13, 148, 136, 0.12); color: var(--primary-2, var(--primary)); }
.chunk-body { font-size: 12.5px; color: var(--ink-700); line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow: auto; }

/* ---------- 数据集管理: 建库 / 上传 (2026-10-29) ---------- */
/* 标题行右侧的主操作条 —— 建库和上传是知识库最高频的两个动作, 摆这儿一眼就能看见 */
.ds-tools { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ds-act { padding: 5px 13px; font-size: 12.5px; }
/* 文档搜索框 —— 沿用「资产市场」那套 .search 样式 (放大镜 + 输入框) */
.search {
  display: flex; align-items: center; gap: 6px;
  background: var(--surface); border: 1px solid var(--border);
  padding: 5px 10px; border-radius: 8px; color: var(--ink-500);
}
.search input {
  border: 0; outline: none; background: transparent;
  font-size: 12.5px; color: var(--ink-900); font-family: inherit; width: 230px;
}
/* 搜索框旁边那句「只搜文件名」 —— 一直挂着, 别让人以为能搜内容 */
.srch-hint { white-space: nowrap; }
/* 搜索结果区 —— 在「数据集」这个卡片里, 跟数据集表格挨着 */
.srch-sec {
  margin-bottom: 14px; padding-bottom: 12px;
  border-bottom: 1px dashed var(--border);
}
.srch-sec-t {
  font-size: 12px; color: var(--ink-700); margin-bottom: 8px;
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
/* 搜索结果里的补充说明 —— 告诉用户「只搜文件名」 */
.ds-hint { color: var(--ink-500); font-size: 11.5px; }
/* 行内操作列 —— 「⬆ 上传」和「详情」并排, 别让按钮糊成一坨 */
.ds-ops { white-space: nowrap; }
.ds-ops .link-btn, .ds-ops .ghost-btn { margin-right: 4px; }
.ds-ops .ghost-btn { margin-right: 0; }
/* 删除数据集 —— 红色, 一眼能跟"上传"分开 */
.link-btn.danger { color: var(--err); }
.link-btn.danger:hover { border-color: var(--err); color: var(--err); background: rgba(239, 68, 68, 0.08); }

/* 新建数据集抽屉 */
.cd-panel { display: flex; flex-direction: column; gap: 16px; }
.cd-field { display: flex; flex-direction: column; gap: 6px; }
.cd-lbl { font-size: 12px; font-weight: 600; color: var(--ink-700); }
.cd-req { color: var(--err); }
.cd-input {
  width: 100%; box-sizing: border-box; font-size: 13px; font-family: inherit;
  color: var(--ink-900); background: var(--surface); border: 1px solid var(--border);
  border-radius: 7px; padding: 7px 10px; outline: none;
}
.cd-input:focus { border-color: var(--primary); }
.cd-hint { font-size: 11.5px; color: var(--ink-500); }
.cd-hint.err { color: var(--err); }
.cd-select { width: 100%; }

/* 切片方式 —— 卡片式单选 (比原生 radio 好懂) */
.cd-choices { display: flex; flex-direction: column; gap: 8px; }
.cd-choice {
  display: grid; grid-template-columns: 16px 1fr; grid-template-rows: auto auto;
  column-gap: 9px; row-gap: 2px; align-items: center;
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 11px; cursor: pointer;
  transition: border-color .15s, background .15s;
}
.cd-choice:hover { border-color: var(--primary); }
.cd-choice.on { border-color: var(--primary); background: var(--primary-soft); }
.cd-choice input { grid-row: 1 / 3; margin: 0; accent-color: var(--primary); }
.cd-ct { font-size: 13px; font-weight: 600; color: var(--ink-900); }
.cd-cd { font-size: 11.5px; color: var(--ink-500); }

/* 「更多解析方式」下拉 (2026-10-29) —— 其余 11 种 RAGFlow 解析器 */
.cd-more { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }
.cd-select2 {
  width: 100%; box-sizing: border-box;
  border: 1px solid var(--border); border-radius: 8px; background: var(--surface);
  color: var(--ink-700); font-size: 12.5px; font-family: inherit;
  padding: 8px 10px; cursor: pointer;
}
.cd-select2:focus { border-color: var(--primary); outline: none; }

</style>
