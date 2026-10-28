<template>
  <div class="set">
    <h1 class="title" style="display:none">⚙️ 设置</h1>
    <!-- 描述只在页头说一次 (AppHeader 的 lede) —— 原来页头下面又跟一行灰字,
         两行说的是同一件事, 白占一行的正文空间. "改完立刻生效" 已经并进页头 lede. -->

    <!-- ⚠️ **非管理员整个设置页都看不到** (2026-10-28) ——
         以前是"只读模式": 配置项照常列出来, 但每一项都是禁用的.
         那样等于给普通用户看了一屏平台机密 (存储路径、仓库地址、审核白名单…),
         还改不了 —— 纯干扰. 现在只有一句提示, 一个配置项都不列.

         这层是**兜底** —— 真正的闸在两处:
           · 路由守卫 (router/index.ts 的 adminOnly) —— 手敲地址 / 旧书签都进不来
           · 顶栏菜单 (UserMenu.vue) —— 入口不出现
         万一将来有人改路由守卫, 这一层还能挡住. -->
    <div v-if="!isAdmin" class="card warn-card">
      <div class="warn-ic">🔒</div>
      <div>
        <div class="warn-t">设置仅管理员可见</div>
        <div class="warn-d">
          当前账号（{{ userStore.user?.username || '未登录' }} · {{ roleText }}）没有 admin 权限.
          平台配置、账号管理这些都归管理员管, 请用 admin 账号登录后再来.
        </div>
      </div>
    </div>

    <!-- ⚠️ 下面这些**只在 admin 时渲染** —— 非管理员看不到任何配置项 -->
    <template v-if="isAdmin">
    <!-- ⚠️ 配置拉失败 → 页面内明确提示 (不能只靠全局 toast:
         页面上各 section 的计数会显示「0 项」, 用户会以为配置被清空了) -->
    <div v-if="loadError" class="card err-card">
      <div class="err-ic">⚠️</div>
      <div class="err-body">
        <div class="err-t">配置加载失败</div>
        <div class="err-d">{{ loadError }} —— 配置<strong>没有被改动</strong>, 请检查后端服务后重试.</div>
        <button class="err-btn" @click="load">重试</button>
      </div>
    </div>

    <div class="set-layout">
      <!-- 左 sticky 目录 -->
      <aside class="set-toc">
        <div class="toc-hd">配置目录</div>
        <template v-for="s in sections" :key="s.id">
          <div :class="['toc-item', { active: activeTop === s.id }]"
               @click="onPickTop(s.id)">
            <span class="toc-ic">{{ s.icon }}</span>
            <span class="toc-lb">{{ s.label }}</span>
            <span v-if="!s.children?.length" class="toc-cnt">{{ s.count }}</span>
          </div>
          <ul v-if="s.children && s.children.length" class="toc-sub">
            <li v-for="c in s.children" :key="c.id"
                :class="{ active: activeTop === s.id && activeSub === c.id,
                          'has-sub': !!(c.children && c.children.length) }"
                @click.stop="onPickSub(s.id, c.id)">
              <span class="toc-dot"></span>
              <span class="toc-lb">{{ c.label }}</span>
              <span class="toc-cnt">{{ c.count }}</span>
              <!-- ⚠️ 第三层 (2026-10-28) —— 「能力墙 → 资产 → 插件·技能·连接」这种三级结构.
                   目录只有两层的话, 「插件·技能·连接」和「知识库」就得挤在同一层,
                   用户看不出它们是资产的三张卡, 而不是三种能力角色. -->
              <ul v-if="c.children && c.children.length" class="toc-sub toc-sub3">
                <li v-for="g in c.children" :key="g.id"
                    :class="{ active: activeTop === s.id && activeSub === c.id && activeSub2 === g.id }"
                    @click.stop="onPickSub2(s.id, c.id, g.id)">
                  <span class="toc-dot"></span>
                  <span class="toc-lb">{{ g.label }}</span>
                  <span class="toc-cnt">{{ g.count }}</span>
                </li>
              </ul>
            </li>
          </ul>
        </template>
      </aside>

      <!-- 右侧 sections -->
      <main class="set-main">
        <!-- 🗂️ 能力墙 -->
        <!-- ⚠️ 2026-10-28 大改: 这里以前是**三个平级的顶级 section**
             (📚 知识库 / 🗂️ 能力墙 / 🧰 软件库), 而首页能力墙的分类是
             **📦 资产 / 🛠 工具 / 📊 看板** —— 资产下面才是
             插件·技能·连接 / 知识库 / 软件库 三张卡.
             设置页跟首页两套分类, 用户配「知识库」得先知道它在设置页
             叫哪个顶级项. 现在**两边一套名字、一套层级**.

             新的结构:
               🗂️ 能力墙
                 📦 资产
                   🧩 插件·技能·连接   marketplace.*
                   📚 知识库            search.* / chat.* / ragflow.*
                   🧰 软件库            software.*
                 🛠 工具               (暂无配置项)
                 📊 看板
                   📈 代码检视          review_agent.*

             ⚠️ 数据源 (RAGFlow / ReviewAgent) 原来挤在「通用 → 📡 数据源」——
                那是"按技术分类"而不是"按能力分类". 现在各归各家:
                RAGFlow 就是知识库的 API, ReviewAgent 就是代码检视看板的后端. -->
        <section v-if="activeTop === 'sec-capability'" :id="'sec-capability'" class="card grp">
          <h2>
            <span>🗂️ 能力墙</span>
            <span class="grp-cnt">{{ capabilityTotal }} 项</span>
          </h2>
          <div class="hint">
            💡 这里按<strong>首页能力墙的分类</strong>组织 —— 📦 资产 / 🛠 工具 / 📊 看板.
            每种能力下面就是它自己的配置项, 不用再去别的组里找.
            改完<strong>立即生效</strong>, 不用重启后端.
          </div>

          <!-- ===== 📦 资产 ===== -->
          <div id="sec-asset" class="sub-grp">
            <h3>📦 资产 <span class="sub-cnt">{{ assetTotal }} 项</span></h3>
            <div class="hint">
              💡 资产 = <strong>能被复用、给别人供料</strong>的东西 —— 首页能力墙里这三张卡都属于它.
            </div>

            <!-- 🧩 插件·技能·连接 -->
            <div id="sec-asset-market" class="sub-grp sub3">
              <h4>🧩 插件·技能·连接 <span class="sub-cnt">{{ marketItems.length }} 项</span></h4>
              <div class="hint">
                💡 资产市场的后端配置 —— GitLab 仓库在哪、项目列表怎么配、谁能发布、
                怎么对外暴露 marketplace.json. 改完<strong>立即生效</strong>, 不用重启后端.
              </div>
              <SettingRow v-for="(it, idx) in marketItems" :key="it.key"
                :item="it" :is-first="idx === 0" :is-admin="isAdmin"
                :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
                :saving="saving === it.key" :secret-display="getInputValue(it)"
                @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />

              <!-- ⚠️ 测试连接 = **admin only** (后端已收紧) ——
                   非管理员点了只会吃一个 403, 不如不显示. -->
              <div v-if="isAdmin" class="test-row">
                <button class="test-btn" :disabled="!!testing" @click="onTest('gitlab')">
                  {{ testing === 'gitlab' ? '测试中…' : '🔌 测试仓库连接' }}
                </button>
                <div v-if="testResults['gitlab']" class="test-result" :class="`s-${testResults['gitlab']?.status}`">
                  <span class="dot"></span>
                  <span class="msg">{{ testResults['gitlab']?.message }}</span>
                </div>
              </div>
              <div class="workdir mono">
                <div>工作区 <code>{{ marketWorkspace }}</code>
                  <span class="muted">（运行时不可改 —— 换了会丢掉现有工作副本）</span>
                </div>
                <div>远端 <code>{{ marketRemote }}</code>
                  <span class="muted">（当前生效值, 改上面的「GitLab 仓库地址」后立即生效）</span>
                </div>
              </div>
            </div>

            <!-- 📚 知识库 -->
            <div id="sec-asset-kb" class="sub-grp sub3">
              <h4>📚 知识库 <span class="sub-cnt">{{ kbTotal }} 项</span></h4>
              <div class="hint">
                💡 RAG 知识源 —— 检索/对话页的嵌入地址, 以及底下的 RAGFlow API.
              </div>

              <h5>🔎 知识检索 <span class="sub-cnt">{{ searchItems.length }} 项</span></h5>
              <SettingRow v-for="(it, idx) in searchItems" :key="it.key"
                :item="it" :is-first="idx === 0" :is-admin="isAdmin"
                :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
                :saving="saving === it.key" :secret-display="getInputValue(it)"
                @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
              <div class="hint">
                💡 这组控制 <code>/kb-manage</code> 页"知识检索"卡片的嵌入 URL. 换 RAGFlow 共享 Search App 或任意可嵌入页面都改这里, 不需要改代码.
              </div>

              <h5>💬 知识对话 <span class="sub-cnt">{{ chatItems.length }} 项</span></h5>
              <SettingRow v-for="(it, idx) in chatItems" :key="it.key"
                :item="it" :is-first="idx === 0" :is-admin="isAdmin"
                :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
                :saving="saving === it.key" :secret-display="getInputValue(it)"
                @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
              <div class="hint">
                💡 这组控制 <code>/kb-manage</code> 页"知识对话"tab 的嵌入 URL (RAGFlow 共享 Chat App / 任意可嵌入聊天页).
              </div>

              <!-- 📡 RAGFlow (知识库自己的后端 API) -->
              <h5>📡 RAGFlow <span class="sub-cnt">{{ kbSourceTotal }} 项</span></h5>
              <div class="hint">
                💡 知识库底下的 RAGFlow API —— 地址和 Key.
              </div>
              <div v-for="grp in kbSourceGroups" :key="grp.id" class="ds-grp">
                <div class="ds-head">
                  <span class="ds-icon">{{ grp.icon }}</span>
                  <span class="ds-label">{{ grp.label }}</span>
                  <span class="sub-cnt">{{ grp.items.length }} 项</span>
                  <span class="ds-hint">{{ grp.hint }}</span>
                </div>
                <SettingRow v-for="(it, idx) in grp.items" :key="it.key"
                  :item="it" :is-first="idx === 0" :is-admin="isAdmin"
                  :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
                  :saving="saving === it.key" :secret-display="getInputValue(it)"
                  @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
                <!-- ⚠️ 测试连接 = admin only (后端已收紧) -->
                <div v-if="isAdmin" class="test-row">
                  <button class="test-btn" :disabled="!!testing" @click="onTest(grp.testKey)">
                    {{ testing === grp.testKey ? '测试中…' : '🔌 测试连接' }}
                  </button>
                  <div v-if="testResults[grp.testKey]" class="test-result" :class="`s-${testResults[grp.testKey]?.status}`">
                    <span class="dot"></span>
                    <span class="msg">{{ testResults[grp.testKey]?.message }}</span>
                    <span v-if="testResults[grp.testKey]?.detail" class="det">{{ JSON.stringify(testResults[grp.testKey]?.detail) }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 🧰 软件库 -->
            <!-- ⚠️ 2026-10-28: 这一组后端一直有 (software.* 四项), 但前端**从来没渲染过** ——
                 所以「软件包存放根目录」这种关键配置在设置页里根本看不见, 只能手改 DB.
                 现在补上, 并且把「体检存储目录」按钮接上 (换根目录不会自动搬文件,
                 必须告诉管理员"缺哪些文件"). -->
            <div id="sec-asset-sw" class="sub-grp sub3">
              <h4>🧰 软件库 <span class="sub-cnt">{{ softwareItems.length }} 项</span></h4>
              <div class="hint">
                💡 内部软件的分发配置 —— 软件包存在哪、单包能多大、留几个历史版本、
                未登录的人能不能下载. 改完<strong>立即生效</strong>, 不用重启后端.
              </div>

              <!-- ⚠️ 存储路径体检 = admin only (后端已收紧) -->
              <div v-if="isAdmin" class="test-row">
                <button class="test-btn" :disabled="!!testing" @click="onTest('software-storage')">
                  {{ testing === 'software-storage' ? '体检中…' : '🔌 体检存储目录' }}
                </button>
                <div v-if="testResults['software-storage']"
                     class="test-result" :class="`s-${testResults['software-storage']?.status}`">
                  <span class="dot"></span>
                  <span class="msg">{{ testResults['software-storage']?.message }}</span>
                  <span v-if="testResults['software-storage']?.detail" class="det">{{
                    storageDetailText(testResults['software-storage']?.detail)
                  }}</span>
                </div>
              </div>

              <SettingRow v-for="(it, idx) in softwareItems" :key="it.key"
                :item="it" :is-first="idx === 0" :is-admin="isAdmin"
                :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
                :saving="saving === it.key" :secret-display="getInputValue(it)"
                @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
            </div>
          </div>

          <!-- ===== 🛠 工具 ===== -->
          <div id="sec-tool" class="sub-grp">
            <h3>🛠 工具 <span class="sub-cnt">{{ toolItems.length }} 项</span></h3>
            <!-- ⚠️ 空组要**说清楚为什么空** —— 干巴巴一个「0 项」会让人以为功能坏了.
                 工具类的运行参数在能力表里 (engine / 参数), 不走平台设置;
                 以后工具类能力上线, 配置会自动出现在这里. -->
            <div v-if="!toolItems.length" class="hint">
              💡 工具 = <strong>能直接干活</strong>的卡 (首页能力墙里的 🛠 组) —— 这一类目前
              <strong>还没有可配置项</strong>: 工具的运行参数在能力表里, 不走平台设置.
              等工具类能力上线, 它的配置会出现在这里.
            </div>
            <SettingRow v-for="(it, idx) in toolItems" :key="it.key"
              :item="it" :is-first="idx === 0" :is-admin="isAdmin"
              :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
              :saving="saving === it.key" :secret-display="getInputValue(it)"
              @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
          </div>

          <!-- ===== 📊 看板 ===== -->
          <div id="sec-board" class="sub-grp">
            <h3>📊 看板 <span class="sub-cnt">{{ boardTotal }} 项</span></h3>
            <div id="sec-board-code-review" class="sub-grp sub3">
              <h4>📈 代码检视 <span class="sub-cnt">{{ boardTotal }} 项</span></h4>
              <div class="hint">
                💡 代码检视看板的数据来源 —— ReviewAgent telemetry API.
              </div>
              <!-- ⚠️ board 类设置项 (后端目前还没有这个 category) —— 先留着位置,
                   后端加了不用改模板. -->
              <SettingRow v-for="(it, idx) in boardItems" :key="it.key"
                :item="it" :is-first="idx === 0" :is-admin="isAdmin"
                :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
                :saving="saving === it.key" :secret-display="getInputValue(it)"
                @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
              <div v-for="grp in boardSourceGroups" :key="grp.id" class="ds-grp">
                <div class="ds-head">
                  <span class="ds-icon">{{ grp.icon }}</span>
                  <span class="ds-label">{{ grp.label }}</span>
                  <span class="sub-cnt">{{ grp.items.length }} 项</span>
                  <span class="ds-hint">{{ grp.hint }}</span>
                </div>
                <SettingRow v-for="(it, idx) in grp.items" :key="it.key"
                  :item="it" :is-first="idx === 0" :is-admin="isAdmin"
                  :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
                  :saving="saving === it.key" :secret-display="getInputValue(it)"
                  @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
                <!-- ⚠️ 测试连接 = admin only (后端已收紧) -->
                <div v-if="isAdmin" class="test-row">
                  <button class="test-btn" :disabled="!!testing" @click="onTest(grp.testKey)">
                    {{ testing === grp.testKey ? '测试中…' : '🔌 测试连接' }}
                  </button>
                  <div v-if="testResults[grp.testKey]" class="test-result" :class="`s-${testResults[grp.testKey]?.status}`">
                    <span class="dot"></span>
                    <span class="msg">{{ testResults[grp.testKey]?.message }}</span>
                    <span v-if="testResults[grp.testKey]?.detail" class="det">{{ JSON.stringify(testResults[grp.testKey]?.detail) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section v-if="activeTop === 'sec-general'" :id="'sec-general'" class="card grp">
          <h2>
            <span>⚙️ 通用</span>
            <!-- ⚠️ 计数只算 generalItems (2026-10-28) ——
                 数据源 (RAGFlow / ReviewAgent) 已经拆去「能力墙 → 资产 / 看板」,
                 各自跟着自己的能力走. 这里剩下的都是**不属于任何一类能力**的全局项. -->
            <span class="grp-cnt">{{ generalItems.length }} 项</span>
          </h2>
          <div class="hint">
            💡 这里是<strong>不属于任何一类能力</strong>的全局配置 —— 跟具体能力相关的
            (资产市场 / 知识库 / 软件库 / 看板) 都在<strong>能力墙</strong>下面, 跟着各自的能力走.
          </div>
          <!-- ⚠️ 这里以前是**手抄的一整套 row 模板** (跟 SettingRow 重复) ——
               后果是 SettingRow 后来加的「描述渲染粗体」「secret 掩码提示」这些
               改进, 通用组全都吃不到. 现在统一用 SettingRow, 一处改全场生效. -->
          <SettingRow v-for="(it, idx) in generalItems" :key="it.key"
            :item="it" :is-first="idx === 0" :is-admin="isAdmin"
            :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
            :saving="saving === it.key" :secret-display="getInputValue(it)"
            @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
        </section>


        <!-- 🔔 通知 (钉钉机器人 · 市场上下架通知) -->
        <section v-if="activeTop === 'sec-notification'" :id="'sec-notification'" class="card grp">
          <h2>
            <span>🔔 通知</span>
            <span class="grp-cnt">{{ notificationItems.length }} 项</span>
          </h2>
          <div class="hint">
            💡 通知分<strong>两个群</strong>:
            <strong>审核群</strong>收「上架待审核」「下架申请」—— 需要管理员处理的事;
            <strong>市场群</strong>收「上架成功」「版本更新」「彻底下架」(都 @所有人)
            和「审核不通过」(只 @发布者)。
            两个群的 webhook / 加签密钥 / 关键词各配各的 —— 测试环境可以把两边配成一样的。
            <br />下架要走审核: 申请阶段通知<b>审核群</b>, 等管理员确认、资产真的被移除才在<b>市场群</b>通知一次。
            配好 webhook 后点对应的「测试发送」自检一下; 群里立刻收到一条自检消息, 配不对会直接告诉你原因。
          </div>

          <SettingRow v-for="(it, idx) in notificationItems" :key="it.key"
            :item="it" :is-first="idx === 0" :is-admin="isAdmin"
            :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
            :saving="saving === it.key" :secret-display="getInputValue(it)"
            @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />

          <!-- ⚠️ 测试发送 = admin only (后端已收紧) -->
          <div v-if="isAdmin" class="test-row">
            <button class="test-btn" :disabled="!!testing" @click="onTest('dingtalk-market')">
              {{ testing === 'dingtalk-market' ? '发送中…' : '📨 测试市场群' }}
            </button>
            <button class="test-btn" :disabled="!!testing" @click="onTest('dingtalk-review')">
              {{ testing === 'dingtalk-review' ? '发送中…' : '📨 测试审核群' }}
            </button>
            <div v-if="testResults['dingtalk-market']" class="test-result" :class="`s-${testResults['dingtalk-market']?.status}`">
              <span class="dot"></span>
              <span class="msg">{{ testResults['dingtalk-market']?.message }}</span>
            </div>
            <div v-if="testResults['dingtalk-review']" class="test-result" :class="`s-${testResults['dingtalk-review']?.status}`">
              <span class="dot"></span>
              <span class="msg">{{ testResults['dingtalk-review']?.message }}</span>
            </div>
          </div>

          <!-- 最近通知 (送达回执) -->
          <div class="sub-grp notif-log">
            <h3>📜 最近通知 <span class="sub-cnt">{{ notifyLog.length }} 条</span>
              <button class="mini-link" @click="loadNotifyLog">刷新</button>
            </h3>
            <!-- ⚠️ 取不到回执 ≠ 从来没发过通知 —— 失败要单独说清楚 -->
            <div v-if="notifyError" class="notif-empty err">
              通知记录加载失败：{{ notifyError }}
              <button class="mini-link" @click="loadNotifyLog">重试</button>
            </div>
            <div v-else-if="!notifyLog.length" class="notif-empty">还没有通知记录</div>
            <ul v-else class="notif-list">
              <li v-for="n in notifyLog" :key="n.id" :class="n.status">
                <span class="nl-act">{{ NOTIFY_EVENTS[n.event] || n.event }}</span>
                <code v-if="n.code" class="nl-code">{{ n.code }}</code>
                <span class="nl-chip" :class="n.status">
                  {{ n.status === 'sent' ? '已送达' : n.status === 'failed' ? '失败' : n.status === 'skipped' ? '未发送' : '待发' }}
                </span>
                <span class="nl-time mono">{{ fmtTime(n.last_attempt_at || n.created_at) }}</span>
                <span v-if="n.error" class="nl-err" :title="n.error">{{ n.error }}</span>
              </li>
            </ul>
          </div>
        </section>

        <!-- 👥 用户管理 (仅 admin) —— 账号必须在这里建出来才能登录 -->
        <!-- ⚠️ 取不到账号列表 ≠ 一个账号都没有 —— 错误由 UserManage 自己显示 (带重试) -->
        <UserManage v-if="activeTop === 'sec-users'" :users="users" :error="usersError" @changed="loadUsers" />

        <div class="card info-card">
          <h2>📌 说明</h2>
          <ul class="tips">
            <li><strong>配置优先级</strong> · 显式环境变量 &gt; DB &gt; .env &gt; 代码默认</li>
            <li><strong>改了立即生效</strong> · 不需要重启 backend, 下次调用就拿新值</li>
            <li><strong>已定制</strong> 标记 = 当前值跟你 .env 默认不一样, 是 UI 改过的</li>
            <li><strong>生产部署</strong> · DB 是单一真源, 不要再改 .env (重启会被 seed 覆盖)</li>
            <li><strong>测试连接</strong> · 用当前值去 ping 一下, 验证 key 没过期</li>
          </ul>
        </div>
      </main>
    </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { getSchema, updateSetting, testRagflow, testReviewAgent, testDingTalk, testGitLab, testSoftwareStorage, type SettingItem, type TestResult } from '@/api/settings';
import { getMarketConfig, listNotifications, type AssetNotification } from '@/api/assets';
import { listUsers, type ManagedUser } from '@/api/users';
import SettingRow from './components/SettingRow.vue';
import UserManage from './components/UserManage.vue';
import { useUserStore } from '@/stores/user';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';

const userStore = useUserStore();
const isAdmin = computed(() => userStore.user?.role === 'admin');

/** 角色 → 中文 (「仅管理员可见」那句提示里用) */
const roleText = computed(() => {
  const r = userStore.user?.role;
  if (r === 'admin') return '管理员';
  if (r === 'tester') return '测试工程师';
  if (r === 'viewer') return '只读';
  return '未知角色';
});

// ===== 账号管理 (仅 admin) =====
// 账号列表的**唯一数据源** —— 建号/停用/改角色之后都靠 loadUsers() 重新拉.
// ⚠️ 非 admin 看不到这个 section (目录里也不列) —— 接口本身也拒了, 前端只是不白费一趟请求.
const users = ref<ManagedUser[]>([]);
/**
 * 账号列表加载失败 —— 页面内提示用.
 *
 * ⚠️ 以前 catch 里直接 users.value = [], 模板显示「还没有账号 —— 在上面建一个吧」:
 *    后端 500 时管理员会以为账号被清空了 (实际是取不到). 失败 ≠ 空列表.
 */
const usersError = ref('');
async function loadUsers() {
  if (!isAdmin.value) {
    users.value = [];
    usersError.value = '';
    return;
  }
  try {
    // ⚠️ silent: 失败由页面内的错误态提示, 不用再弹一个全局红条 (重复提示)
    users.value = await listUsers({ silent: true });
    usersError.value = '';
  } catch (e: any) {
    usersError.value = errText(e, '账号列表加载失败');
  }
}

/** 后端 422 的 detail 是字符串, 403/409 也是 —— 统一取出来给人看 (对象 detail 退化到 message) */
function errText(e: any, fallback: string): string {
  // ⚠️ 状态码也要翻译 —— 502/503 的原始报文 ("Request failed with status code 502")
  //    对用户是天书, 而这恰恰是本地部署最常见的故障 (后端没在跑).
  return httpErrorText(errorStatus(e), errorDetail(e), fallback);
}

const groups = ref<{ category: string; label: string; items: SettingItem[] }[]>([]);
const drafts = reactive<Record<string, any>>({});
const originals = reactive<Record<string, any>>({});
const showSecrets = reactive<Record<string, boolean>>({});
const saving = ref<string | null>(null);
const testing = ref<string | null>(null);
const testResults = reactive<Record<string, TestResult | null>>({});

// 当前选中的顶级 section + 子级 (sub group) + 第三级 (2026-10-28)
// ⚠️ 默认落在「能力墙 → 资产 → 插件·技能·连接」—— 那是设置页里项最多的地方.
const activeTop = ref<string>('sec-capability');
const activeSub = ref<string>('sec-asset');
const activeSub2 = ref<string>('sec-asset-market');

// ===== 按 category 拆分 (后端 schema 是单一来源) =====
const searchItems = computed(() => itemsByCategory('search'));
const chatItems = computed(() => itemsByCategory('chat'));
const generalItems = computed(() => itemsByCategory('general'));
// 通知 (钉钉机器人: webhook / 关键词 / 加签 / 触发开关)
const notificationItems = computed(() => itemsByCategory('notification'));
// 资产市场 (GitLab 仓库 / 安装目录 / 发布白名单 / 对外暴露方式)
const marketItems = computed(() => itemsByCategory('marketplace'));
// 软件库 (存储根目录 / 单包上限 / 保留版本数 / 公开下载)
// ⚠️ 2026-10-28: 这一组后端一直有, 前端一直没渲染 —— 补上.
const softwareItems = computed(() => itemsByCategory('software'));
// 工具类能力的配置 —— 目前后端还没有这个 category, 这里是**空组**
// (工具的运行参数在能力表里, 不走平台设置). 后端加了就自动出现.
const toolItems = computed(() => itemsByCategory('tool'));
// 看板类能力的配置 (后端 board 类设置项) —— 目前空, 看板的实际配置是 ReviewAgent (见 boardSourceGroups)
const boardItems = computed(() => itemsByCategory('board'));

// 市场当前生效的配置 (只读, 用来展示"工作区在哪 / 远端是哪个")
const marketWorkspace = ref('');
const marketRemote = ref('');
async function loadMarketConfig() {
  try {
    const c = await getMarketConfig();
    marketWorkspace.value = c.workspace || '(未知)';
    marketRemote.value = c.remote || '(未配置)';
  } catch {
    // ⚠️ 以前失败时 marketRemote = '' → 模板渲染出一个**空代码块**,
    //    用户分不清"没配"还是"读失败". 两个都标成「读取失败」.
    marketWorkspace.value = '(读取失败)';
    marketRemote.value = '(读取失败)';
  }
}

// ===== 通知回执 (送达记录) =====
const notifyLog = ref<AssetNotification[]>([]);
/**
 * 通知回执加载失败 —— 页面内提示用.
 *
 * ⚠️ 以前 catch 里直接 notifyLog.value = [], 模板显示「还没有通知记录」:
 *    钉钉 webhook 配错时管理员会以为通知**从未发出过**. 失败 ≠ 没有记录.
 */
const notifyError = ref('');
/**
 * 通知事件 → 中文 (回执列表用).
 *
 * ⚠️ 必须跟后端的 _EVENT_TEXT (app/core/dingtalk.py) **一一对应** ——
 *    以前这里只写了 4 个, 缺的 review / unpublish_request / reject
 *    在列表里直接显示原始 event id, 看不懂.
 */
const NOTIFY_EVENTS: Record<string, string> = {
  review: '新资产待审核',
  unpublish_request: '申请下架, 待确认',
  publish: '新资产上架',
  update: '版本更新',
  unpublish: '资产已下架',
  reject: '审核未通过',
  delete: '资产已删除',
};
async function loadNotifyLog() {
  try {
    const r = await listNotifications(20);
    notifyLog.value = r.items || [];
    notifyError.value = '';
  } catch (e: any) {
    notifyError.value = errText(e, '通知记录加载失败');
  }
}
function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

// ===== 数据源 sub-group: 按 prefix 拆子组 (RAGFlow / ReviewAgent) =====
// 配置项都标 category='data-source', 这里按 key 前缀再细分, 让"测试连接"按钮紧贴对应配置.
// 后续接新数据源: 在 SOURCE_GROUPS 数组里加一项即可.
//
// ⚠️ 2026-10-28: 原来这里是一整块「通用 → 📡 数据源」, 两个数据源平铺在一起.
//    但 RAGFlow 和 ReviewAgent 分属**不同的能力** —— RAGFlow 是知识库的 API,
//    ReviewAgent 是代码检视看板的后端. 现在加了 scope 字段, 各归各家:
//      scope='asset-kb' → 渲染在「能力墙 → 资产 → 知识库」下
//      scope='board'    → 渲染在「能力墙 → 看板 → 代码检视」下
const dataSourceItems = computed(() => itemsByCategory('data-source'));

interface DataSourceGroup {
  id: string;          // 模板里渲染用, 也是测试结果 key
  prefix: string;      // key 必须以这个开头
  scope: 'asset-kb' | 'board';  // 归到哪个能力下面 (2026-10-28)
  icon: string;
  label: string;       // 显示名
  testKey: string;     // 调用 settings.onTest 用的分类
  hint: string;
  items: SettingItem[];   // 经 vue computed 注入实际匹配项
}
// SOURCE_GROUPS 是静态声明 (没有 items 字段), 经 sourceGroups computed 注入实际匹配项.
type SourceGroupDef = Omit<DataSourceGroup, 'items'>;
const SOURCE_GROUPS: SourceGroupDef[] = [
  { id: 'ragflow',  prefix: 'ragflow.',  scope: 'asset-kb', icon: '📚', label: 'RAGFlow (知识库 API)', testKey: 'ragflow',  hint: 'KB 知识库 · 数据集 / 文档 / chunking API' },
  { id: 'review-agent', prefix: 'review_agent.', scope: 'board', icon: '🧬', label: 'ReviewAgent (代码检视)', testKey: 'review-agent', hint: '代码检视 · HTTP / 健康检查' },
];
const sourceGroups = computed<DataSourceGroup[]>(() =>
  SOURCE_GROUPS.map(g => ({
    ...g,
    items: dataSourceItems.value.filter(it => it.key.startsWith(g.prefix)),
  })).filter(g => g.items.length > 0),
);
/** 按 scope 取数据源组 —— 渲染在各自能力下面 */
function groupsByScope(scope: SourceGroupDef['scope']): DataSourceGroup[] {
  return sourceGroups.value.filter(g => g.scope === scope);
}
const kbSourceGroups = computed(() => groupsByScope('asset-kb'));
const boardSourceGroups = computed(() => groupsByScope('board'));

/** 一组数据源占几项 —— 计数用 */
function countOf(groups: DataSourceGroup[]): number {
  return groups.reduce((n, g) => n + g.items.length, 0);
}

// ===== 能力墙的计数 (2026-10-28) =====
// ⚠️ 这些数**必须跟目录里显示的一致** —— 两处对不上用户会以为漏了配置.
//    每一类能力对应首页能力墙上的一张卡 (或多张).
const kbSourceTotal = computed(() => countOf(kbSourceGroups.value));
/** 知识库 = 知识检索 + 知识对话 + RAGFlow API */
const kbTotal = computed(() => searchItems.value.length + chatItems.value.length + kbSourceTotal.value);
/** 资产 = 插件·技能·连接 + 知识库 + 软件库 (首页资产组的三张卡) */
const assetTotal = computed(() => marketItems.value.length + kbTotal.value + softwareItems.value.length);
/** 看板 = 代码检视的数据源 + 以后可能有的 board 类设置项 */
const boardTotal = computed(() => boardItems.value.length + countOf(boardSourceGroups.value));
/** 能力墙总计 */
const capabilityTotal = computed(() => assetTotal.value + toolItems.value.length + boardTotal.value);

// ⚠️ 「智能体业务」那一组已经删掉了 (Dify 下线后没有 agents 类别的配置项,
//    留着只会永远显示「暂无智能体业务配置」). 能力相关的配置都在下面的「数据源」里.

function itemsByCategory(cat: string): SettingItem[] {
  for (const g of groups.value) {
    if (g.category === cat) return g.items;
  }
  return [];
}

// ===== 左侧目录 (sections 定义) =====
// ⚠️ TocItem 自己也能有 children —— 目录是**三层**的:
//   能力墙 → 资产 → 插件·技能·连接
//   (第一层 children 是能力角色, 第二层 children 是该角色下的具体能力)
interface TocItem { id: string; label: string; count: number; children?: TocItem[] }
interface TocSection { id: string; icon: string; label: string; count: number; children: TocItem[] }

// ⚠️ 「👥 用户」只在 admin 的目录里出现 —— 非 admin 连目录项都看不到
//    (账号管理是 admin 的活, 普通用户点进去只会撞一堵 403 墙).
const sections = computed<TocSection[]>(() => {
  const list: TocSection[] = [
  {
    // ⚠️ 2026-10-28: 目录跟着**首页能力墙的分类**走 ——
    //   📦 资产 / 🛠 工具 / 📊 看板, 资产下面才是首页那三张卡
    //   (插件·技能·连接 / 知识库 / 软件库).
    //   以前这里是三个平级顶级项 (知识库 / 能力墙 / 软件库), 跟首页对不上.
    id: 'sec-capability',
    icon: '🗂️',
    label: '能力墙',
    count: capabilityTotal.value,
    children: [
      {
        id: 'sec-asset',
        label: '📦 资产',
        count: assetTotal.value,
        children: [
          { id: 'sec-asset-market', label: '🧩 插件·技能·连接', count: marketItems.value.length },
          { id: 'sec-asset-kb',      label: '📚 知识库',         count: kbTotal.value },
          { id: 'sec-asset-sw',      label: '🧰 软件库',         count: softwareItems.value.length },
        ],
      },
      {
        id: 'sec-tool',
        label: '🛠 工具',
        count: toolItems.value.length,
        children: [],
      },
      {
        id: 'sec-board',
        label: '📊 看板',
        count: boardTotal.value,
        children: [
          { id: 'sec-board-code-review', label: '📈 代码检视', count: boardTotal.value },
        ],
      },
    ],
  },
  { id: 'sec-general',      icon: '⚙️', label: '通用',   count: generalItems.value.length, children: [] },
  { id: 'sec-notification', icon: '🔔', label: '通知',   count: notificationItems.value.length, children: [] },
  ];
  if (isAdmin.value) {
    list.push({ id: 'sec-users', icon: '👥', label: '用户', count: users.value.length, children: [] });
  }
  return list;
});

// ===== 点击目录 =====
// ⚠️ onPickTop / onPickSub / onPickSub2 是**三级**的 —— 目录有三层
//   (能力墙 → 资产 → 插件·技能·连接), 点击要跟得上层数, 否则高亮会停在错的地方.
function onPickTop(topId: string) {
  activeTop.value = topId;
  // 滚到右侧 section 顶部 (不滚到子级)
  nextTick(() => {
    const el = document.getElementById(topId);
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  // 通知区带送达回执, 进区就拉一次
  if (topId === 'sec-notification') loadNotifyLog();
  // 资产市场区展示当前生效的工作区/远端
  if (topId === 'sec-capability') loadMarketConfig();
  // 用户管理区拉账号列表
  if (topId === 'sec-users') loadUsers();
}

function onPickSub(topId: string, subId: string) {
  activeTop.value = topId;
  activeSub.value = subId;
  // 滚到右侧子 group 顶部
  nextTick(() => {
    const el = document.getElementById(subId);
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

/** 第三级 (资产的三张卡 / 看板下的代码检视) */
function onPickSub2(topId: string, subId: string, sub2Id: string) {
  activeTop.value = topId;
  activeSub.value = subId;
  activeSub2.value = sub2Id;
  nextTick(() => {
    const el = document.getElementById(sub2Id);
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  // ⚠️ 软件库是资产里的第三级 —— 进它就体检存储目录 (admin only)
  if (sub2Id === 'sec-asset-sw' && isAdmin.value) onTest('software-storage');
}

// ===== 加载 / 渲染 =====
/** bool 开关统一成真正的布尔 —— 后端可能回 "false" 字符串, !!"false" 是 true, 界面会骗人 */
function toBool(v: any, def = false): boolean {
  if (typeof v === 'boolean') return v;
  if (v === null || v === undefined || v === '') return def;
  if (typeof v === 'number') return v !== 0;
  const s = String(v).trim().toLowerCase();
  if (['true', '1', 'yes', 'on'].includes(s)) return true;
  if (['false', '0', 'no', 'off'].includes(s)) return false;
  return def;
}

/**
 * 配置加载失败 —— 页面内提示用.
 *
 * ⚠️ 以前 load() 没有 catch: /settings/schema 挂了就变成 unhandled rejection,
 *    页面照样渲染, 但知识库显示「0 项」—— 用户以为配置被清空了.
 */
const loadError = ref('');

async function load() {
  loadError.value = '';
  try {
    const resp = await getSchema();
    groups.value = resp.groups;
    for (const g of resp.groups) {
      for (const it of g.items) {
        const v = it.value_type === 'bool' ? toBool(it.value) : it.value;
        drafts[it.key] = v;
        originals[it.key] = v;
      }
    }
  } catch (e: any) {
    // 失败不抛 —— 抛出去就是 unhandled rejection, 页面上什么都看不出来
    loadError.value = httpErrorText(errorStatus(e), errorDetail(e), '配置加载失败');
  }
}

function isDirty(it: SettingItem) {
  if (it.is_secret) {
    const v = drafts[it.key];
    // secret: 空串或纯占位 = 没改, 跟原值有差异才算改
    if (v === '' || (typeof v === 'string' && /^•+$/.test(v))) return false;
    return v !== originals[it.key];
  }
  return drafts[it.key] !== originals[it.key];
}

function setDraft(key: string, v: any) {
  drafts[key] = v;
}
function toggleShow(key: string) {
  showSecrets[key] = !showSecrets[key];
}

function getInputValue(it: SettingItem) {
  if (it.is_secret) {
    const v = drafts[it.key];
    if (v === '' || v === undefined || v === null) return '';
    return v;
  }
  return drafts[it.key];
}

function revert(it: SettingItem) {
  drafts[it.key] = originals[it.key];
}

async function onSave(it: SettingItem) {
  saving.value = it.key;
  try {
    const updateSecret = it.is_secret;
    const v = drafts[it.key];
    await updateSetting(it.key, v, updateSecret);
    originals[it.key] = v;
    drafts[it.key] = v;
    ElMessage.success(`已保存: ${it.key}`);
  } catch (e: any) {
    ElMessage.error(`保存失败: ${httpErrorText(errorStatus(e), errorDetail(e))}`);
  } finally {
    saving.value = null;
  }
}

// ===== 数据源连接测试 =====
// testKey 跟 SOURCE_GROUPS[i].testKey 对齐: 'ragflow' / 'review-agent'.
const _testClients: Record<string, () => Promise<TestResult>> = {
  'ragflow':  testRagflow,
  'review-agent': testReviewAgent,
  // 钉钉分两个频道 (市场群 / 审核群), 各配各的 webhook → 也要分别自检
  'dingtalk-market': () => testDingTalk('market'),
  'dingtalk-review': () => testDingTalk('review'),
  'gitlab': testGitLab,
  // 软件库存储目录体检 (admin only)
  'software-storage': testSoftwareStorage,
};

/**
 * 存储目录体检结果的补充说明 —— 路径 + 来源 + 缺多少文件.
 *
 * ⚠️ 为什么不直接 JSON.stringify: 那是一坨原始字段, 用户看不懂.
 *    这里挑出"这个路径是哪来的" (设置项 / 环境变量 / 默认) 和"缺几个文件",
 *    剩下的数字太细就不显示了.
 */
function storageDetailText(detail: any): string {
  if (!detail || typeof detail !== 'object') return '';
  const parts: string[] = [];
  if (detail.root) parts.push(`路径 ${detail.root}`);
  if (detail.source) {
    const srcMap: Record<string, string> = {
      setting: '来自设置项',
      env: '来自环境变量',
      default: '默认值（都没配）',
    };
    parts.push(srcMap[detail.source] || detail.source);
  }
  if (detail.missing_count) {
    parts.push(`缺 ${detail.missing_count} 个版本的文件`);
  }
  return parts.join(' · ');
}
async function onTest(testKey: string) {
  const fn = _testClients[testKey];
  if (!fn) return;
  testing.value = testKey;
  try {
    testResults[testKey] = await fn();
  } catch (e: any) {
    testResults[testKey] = { ok: false, status: 'off', message: httpErrorText(errorStatus(e), errorDetail(e), '请求失败'), detail: null };
  } finally {
    testing.value = null;
  }
}

onMounted(() => {
  load();
  // 管理员进设置页就把账号列表拉好 (目录上的数字要显示)
  if (isAdmin.value) loadUsers();
});
</script>

<style scoped>

/* ===== 能力墙 section: 数据源区 / 能力业务区 分割线 ===== */
.sec-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--border), transparent);
  margin: 20px 0;
}
.sec-divider::before {
  content: '';
}
.agent-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}
@media (max-width: 1100px) { .agent-cards { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 700px)  { .agent-cards { grid-template-columns: 1fr; } }

.agent-card {
  display: flex; gap: 12px;
  padding: 14px; border-radius: 12px;
  background: var(--surface); border: 1px solid var(--border);
  cursor: pointer; transition: all 0.15s ease;
  align-items: flex-start;
}
.agent-card:hover {
  border-color: var(--primary);
  background: var(--surface-sunken);
  transform: translateY(-1px);
}
.agent-card.active {
  border-color: transparent;
  background: var(--primary-grad-soft);
  box-shadow: inset 0 0 0 1px var(--border);
}
.agent-card .ac-icon {
  width: 38px; height: 38px; border-radius: 10px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; flex-shrink: 0;
  box-shadow: var(--primary-shadow);
}
.agent-card .ac-body { flex: 1; min-width: 0; }
.agent-card .ac-row1 {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: 8px;
}
.agent-card .ac-name { font-size: 14px; font-weight: 700; color: var(--ink-900); }
.agent-card .ac-cnt {
  font-size: 10.5px; padding: 1px 7px;
  background: var(--surface-sunken); color: var(--ink-700);
  border-radius: var(--radius-pill);
}
.agent-card.active .ac-cnt { background: var(--primary-grad); color: #fff; }
.agent-card .ac-sub {
  font-size: 11px; color: var(--ink-500);
  font-family: var(--font-mono); margin-top: 1px;
}
.agent-card .ac-summary {
  font-size: 12px; color: var(--ink-700); line-height: 1.5;
  margin-top: 4px;
}
.set { padding: 4px 4px 40px; }
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.warn-card {
  display: flex; gap: 14px; align-items: center;
  margin-bottom: 16px;
  background: rgba(245, 158, 11, 0.06);
  border-color: var(--warn);
}
.warn-ic { font-size: 24px; }
.warn-t { font-weight: 600; color: var(--ink-900); }
.warn-d { font-size: 12.5px; color: var(--ink-700); }

/* 配置加载失败 —— 页面内提示 (别让用户以为配置被清空了) */
.err-card {
  display: flex; gap: 14px; align-items: flex-start;
  margin-bottom: 16px;
  background: rgba(239, 68, 68, 0.06);
  border-color: var(--err);
}
.err-ic { font-size: 24px; }
.err-body { display: flex; flex-direction: column; gap: 6px; }
.err-t { font-weight: 600; color: var(--ink-900); }
.err-d { font-size: 12.5px; color: var(--ink-700); }
.err-btn {
  align-self: flex-start;
  background: transparent; border: 1px solid var(--err); color: var(--err);
  padding: 4px 14px; border-radius: var(--radius-pill);
  font-size: 12px; cursor: pointer; font-family: inherit;
}
.err-btn:hover { background: var(--err); color: #fff; }

/* ====== 布局: 左 toc + 右 sections ====== */
.set-layout {
  display: grid;
  /* ⚠️ 260px 而不是 220px (2026-10-28) —— 目录变成**三层**之后,
     「🧩 插件·技能·连接」这一行在 220px 里会被挤成竖排 (一个字一行). */
  grid-template-columns: 260px 1fr;
  gap: 24px;
  align-items: start;
}

.set-toc {
  position: sticky;
  top: 16px;
  max-height: calc(100vh - 32px);
  overflow: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px 8px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.toc-hd {
  font-size: 11px; font-weight: 700; color: var(--ink-500);
  padding: 4px 10px 8px; letter-spacing: 0.04em; text-transform: uppercase;
}
.toc-item, .toc-sub li {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--ink-700);
  font-size: 13px;
  transition: background 0.15s ease, color 0.15s ease;
  user-select: none;
}
.toc-item:hover, .toc-sub li:hover { background: var(--surface-sunken); color: var(--ink-900); }
.toc-item.active, .toc-sub li.active {
  /* 用 3 段渐变 soft 版当底, 跟 Sidebar / Plaza filter 统一 */
  background: var(--primary-grad-soft);
  font-weight: 600;
  box-shadow: inset 0 0 0 1px var(--border);
}
.toc-item.active .toc-lb, .toc-sub li.active .toc-lb {
  background: var(--primary-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}
.toc-item.active .toc-ic, .toc-sub li.active .toc-ic {
  color: var(--primary);
  opacity: 1;
}
.toc-ic { font-size: 14px; width: 18px; text-align: center; flex-shrink: 0; }
.toc-lb { flex: 1; min-width: 0; }
.toc-cnt {
  font-size: 10.5px;
  padding: 1px 7px;
  background: var(--surface-sunken);
  color: var(--ink-500);
  border-radius: var(--radius-pill);
  font-weight: 500;
  flex-shrink: 0;
}
.toc-item.active .toc-cnt, .toc-sub li.active .toc-cnt {
  background: var(--primary-grad-text);
  color: #fff;
}
.toc-sub {
  list-style: none;
  margin: 2px 0 6px;
  padding: 0 0 0 18px;
  display: flex; flex-direction: column; gap: 1px;
}
.toc-sub li { font-size: 12.5px; padding: 5px 10px; }
/* ⚠️ 含子项的 li 必须改成 **grid** (2026-10-28) ——
   li 默认是 flex, 嵌套进来的 ul 会被当成 flex 子项, 宽度被压到 0,
   结果「插件·技能·连接」这些长标签被挤成**竖排** (一个字一行).
   grid 里给嵌套 ul 一个整行位置就正常了. */
.toc-sub li.has-sub {
  display: grid;
  grid-template-columns: 4px 1fr auto;
  align-items: center;
  column-gap: 8px;
}
.toc-sub li.has-sub > .toc-sub3 { grid-column: 1 / -1; }
/* 标签不换行 —— 挤了就省略号, 不能竖排 */
.toc-lb {
  flex: 1; min-width: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
/* ⚠️ 第三层 (2026-10-28) —— 再缩一点 + 字小一号.
   三层挤在窄侧栏里, 不分层的话「插件·技能·连接」和「知识库」
   看起来是并列的, 用户会以为它们是两种能力角色, 而不是资产的三张卡. */
.toc-sub3 {
  margin: 2px 0 4px;
  padding: 0 0 0 12px;
}
.toc-sub3 li { font-size: 11.5px; padding: 4px 8px; }
.toc-dot {
  width: 4px; height: 4px; border-radius: 50%;
  background: currentColor; opacity: 0.5;
  flex-shrink: 0;
}

.set-main { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.set-main > .card { animation: fade-in 0.2s ease; }
@keyframes fade-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

/* ====== groups / rows / inputs (沿用旧版) ====== */
.grp h2 {
  font-size: 16px; font-weight: 700; margin: 0 0 14px; color: var(--ink-900);
  display: flex; align-items: center; gap: 8px;
}
.grp-cnt {
  font-size: 10.5px; padding: 2px 7px; background: var(--surface-sunken);
  color: var(--ink-500); border-radius: var(--radius-pill); font-weight: 500;
}

.sub-grp {
  padding: 16px 0 4px;
  border-top: 1px dashed var(--border);
  margin-top: 4px;
}
.sub-grp:first-of-type { border-top: none; padding-top: 8px; }
.sub-grp h3 {
  font-size: 13px; font-weight: 600;
  color: var(--ink-700);
  margin: 0 0 12px;
  display: flex; align-items: center; gap: 6px;
  scroll-margin-top: 16px;
}
/* ⚠️ 第四层 (2026-10-28) —— 能力墙 → 资产 → 插件·技能·连接 这种三层结构,
   靠字号 + 左边框线把层级拉开: h2=section, h3=能力角色, h4=具体能力, h5=能力内部的分组 */
.sub-grp h4 {
  font-size: 13px; font-weight: 600;
  color: var(--ink-900);
  margin: 0 0 10px;
  display: flex; align-items: center; gap: 6px;
  scroll-margin-top: 16px;
  padding-left: 10px;
  /* ⚠️ 不能用 var(--primary-grad) —— 那是 linear-gradient, border-color 不吃,
     整条左边框会**整个消失** (2026-10-28 踩过). */
  border-left: 3px solid var(--primary);
  border-radius: 2px;
}
.sub-grp h5 {
  font-size: 12px; font-weight: 600;
  color: var(--ink-700);
  margin: 16px 0 8px;
  display: flex; align-items: center; gap: 6px;
  scroll-margin-top: 16px;
}
/* 第三层往下再缩一点 —— 视觉上"嵌"在上一层里 */
.sub-grp.sub3 {
  padding: 14px 0 4px 14px;
  margin-top: 10px;
  border-top: 1px dashed var(--border);
}
.sub-grp.sub3:first-of-type { border-top: none; }
.sub-cnt {
  font-size: 10.5px; padding: 1px 6px;
  background: var(--surface-sunken); color: var(--ink-500);
  border-radius: var(--radius-pill); font-weight: 500;
}
.hint {
  margin-top: 10px; font-size: 12px; color: var(--ink-500); line-height: 1.6;
  background: var(--surface-sunken); border-radius: 8px; padding: 8px 12px;
}
.hint code {
  font-family: var(--font-mono);
  color: var(--primary);
  font-size: 11.5px;
  background: var(--primary-soft);
  padding: 1px 6px;
  border-radius: 4px;
}

.empty-hint {
  display: flex; flex-direction: column; align-items: center;
  padding: 28px 20px; text-align: center;
  background: var(--surface-sunken); border-radius: 10px;
  border: 1px dashed var(--border);
}
.eh-ic { font-size: 32px; margin-bottom: 8px; opacity: 0.6; }
.eh-t { font-size: 14px; font-weight: 600; color: var(--ink-700); margin-bottom: 4px; }
.eh-d { font-size: 12.5px; color: var(--ink-500); }

/* === inline 渲染的 row (knowledgeSource / agents / general) 的样式 — 镜像 SettingRow 的 scoped 块 ===
   原因: Vue scoped CSS 不会穿透到父组件, SettingRow 内的类只能在 SettingRow 自己的 scoped 里生效.
   这三组在 Settings 模板里直接写了 .row / .lbl-col / .inp-col / .act-col / .primary,
   所以这些样式要在 Settings 这边的 scoped 里再放一份 (跟 SettingRow 完全一致). */
.row {
  display: grid; grid-template-columns: 1.4fr 2fr auto;
  gap: 16px; align-items: start;
  padding: 14px 0;
  border-top: 1px dashed var(--border);
}
.row.first { border-top: none; padding-top: 4px; }
@media (max-width: 768px) { .row { grid-template-columns: 1fr; } }

.lbl-col .k { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.lbl-col code {
  font-size: 13px; font-weight: 600;
  background: transparent;
  padding: 0;
  border-radius: 0;
  color: var(--primary);
  font-family: var(--font-body);
  background-image: var(--primary-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.lbl-col .d { font-size: 12px; color: var(--ink-500); margin-top: 4px; line-height: 1.5; }

.secret-tag { font-size: 9.5px; padding: 1px 6px; background: rgba(239, 68, 68, 0.1); color: var(--err); border-radius: var(--radius-pill); font-weight: 600; }
.custom-tag { font-size: 9.5px; padding: 1px 6px; background: var(--primary-soft); color: var(--primary); border-radius: var(--radius-pill); font-weight: 600; }

.inp-col input {
  width: 100%; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: 7px; background: var(--surface); color: var(--ink-900);
  font-size: 13px; font-family: var(--font-mono);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.inp-col input:focus {
  outline: none; border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-soft);
}
.inp-col input:disabled { background: var(--surface-sunken); color: var(--ink-500); }

.secret-wrap { position: relative; }
.secret-wrap input { padding-right: 36px; }
.eye {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  background: transparent; border: 0; cursor: pointer;
  font-size: 14px; padding: 2px 6px;
  color: var(--ink-500);
}
.eye:hover { color: var(--ink-900); }

.switch { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; }
.switch input { display: none; }
.sl {
  width: 40px; height: 22px; background: var(--border-strong);
  border-radius: 999px; position: relative;
  transition: background 0.2s ease;
}
.sl::before {
  content: ''; position: absolute; width: 18px; height: 18px;
  background: #fff; border-radius: 50%; top: 2px; left: 2px;
  transition: transform 0.2s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}
.switch input:checked + .sl { background: var(--primary-grad); }
.switch input:checked + .sl::before { transform: translateX(18px); }
.switch input:disabled + .sl { opacity: 0.5; }
.stxt { font-family: var(--font-mono); font-size: 11px; color: var(--ink-500); min-width: 24px; }

.act-col { display: flex; flex-direction: column; gap: 4px; align-items: stretch; min-width: 70px; }
.primary {
  background: var(--primary-grad); color: #fff; border: 0;
  padding: 6px 14px; border-radius: 7px;
  font-size: 12.5px; font-weight: 600; font-family: inherit; cursor: pointer;
  transition: filter .15s ease, box-shadow .15s ease;
}
.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.primary:not(:disabled):hover {
  filter: brightness(1.05);
  box-shadow: 0 3px 10px rgba(59, 130, 246, 0.25);
  transform: translateY(-1px);
}
.ghost {
  background: transparent; border: 1px solid var(--border);
  padding: 5px 12px; border-radius: 7px;
  color: var(--ink-700); font-size: 12px; cursor: pointer; font-family: inherit;
}
.ghost:hover { border-color: var(--primary); color: var(--primary); }



































/* ===== 数据源 sub-group: 每个 prefix 一个子区 ===== */
.ds-grp {
  margin-top: 14px;
  padding: 14px 14px 12px;
  background: var(--surface-sunken);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg, 10px);
}
.ds-grp .test-row { border-top-color: color-mix(in srgb, var(--border) 60%, transparent); }
.ds-head {
  display: flex; align-items: baseline; gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.ds-icon { font-size: 16px; }
.ds-label { font-weight: 600; color: var(--ink-900); font-size: 13.5px; }
.ds-hint { color: var(--ink-500); font-size: 11.5px; margin-left: 4px; }

.test-row {
  display: flex; align-items: center; gap: 12px;
  margin-top: 8px; padding-top: 12px;
  border-top: 1px solid var(--border);
  flex-wrap: wrap;
}
.test-btn {
  background: var(--surface-sunken); border: 1px solid var(--border);
  padding: 6px 14px; border-radius: 7px;
  font-size: 12.5px; color: var(--ink-700); cursor: pointer; font-family: inherit;
}
.test-btn:hover { border-color: var(--primary); color: var(--primary); }
.test-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.test-result {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: var(--radius-pill);
  font-size: 11.5px; font-family: var(--font-mono);
}
.test-result .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.s-ok { background: rgba(16, 185, 129, 0.1); color: var(--ok); }
.s-warn { background: rgba(245, 158, 11, 0.1); color: var(--warn); }
.s-off { background: rgba(239, 68, 68, 0.1); color: var(--err); }
.det { color: var(--ink-500); font-size: 10.5px; }

.info-card h2 { font-size: 15px; font-weight: 700; margin: 0 0 12px; color: var(--ink-900); }
.tips { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 8px; font-size: 13px; color: var(--ink-700); line-height: 1.6; }
.tips strong { color: var(--ink-900); }

/* ===== 通知: 最近通知 (送达回执) ===== */
.notif-log { margin-top: 18px; }
.notif-log h3 { display: flex; align-items: center; gap: 8px; }
.mini-link {
  margin-left: auto; background: transparent; border: 1px solid var(--border);
  padding: 2px 10px; border-radius: var(--radius-pill);
  font-size: 11px; color: var(--ink-700); cursor: pointer; font-family: inherit;
}
.mini-link:hover { border-color: var(--primary); color: var(--primary); }
.notif-empty { font-size: 12px; color: var(--ink-500); padding: 12px 0; }
/* 取数失败 —— 别跟"真的没有记录"长得一样 (灰色一行 vs 红色一行) */
.notif-empty.err {
  color: var(--err);
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
}
.notif-empty.err .mini-link { margin-left: 0; }
.notif-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.notif-list li {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  border: 1px solid var(--border); border-left: 3px solid var(--border);
  border-radius: var(--radius-sm); padding: 7px 10px; background: var(--surface-soft);
  font-size: 12px;
}
.notif-list li.sent { border-left-color: var(--ok); }
.notif-list li.failed { border-left-color: var(--err); background: rgba(239, 68, 68, 0.06); }
.notif-list li.pending { border-left-color: var(--warn); }
.notif-list li.skipped { border-left-color: var(--ink-500); opacity: 0.7; }
.nl-act { font-weight: 600; color: var(--ink-900); }
.nl-code { font-family: var(--font-mono); font-size: 11px; color: var(--ink-700); }
.nl-chip {
  font-size: 10.5px; font-weight: 600; padding: 1px 8px; border-radius: var(--radius-pill);
}
.nl-chip.sent { background: rgba(16, 185, 129, 0.14); color: var(--ok); }
.nl-chip.failed { background: rgba(239, 68, 68, 0.14); color: var(--err); }
.nl-chip.pending { background: rgba(245, 158, 11, 0.14); color: var(--warn); }
.nl-chip.skipped { background: rgba(100, 116, 139, 0.16); color: var(--ink-600); }
.nl-time { font-size: 11px; color: var(--ink-500); margin-left: auto; }
.nl-err {
  width: 100%; font-size: 11px; color: var(--err); opacity: 0.85;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* ===== 资产市场: 工作区/远端只读展示 ===== */
.workdir {
  margin-top: 10px; padding: 9px 12px; border-radius: var(--radius-sm);
  background: var(--surface-sunken); font-size: 11.5px; color: var(--ink-700);
  display: flex; flex-direction: column; gap: 5px;
}
.workdir code {
  font-family: var(--font-mono); font-size: 11px; color: var(--ink-900);
  background: var(--surface); padding: 1px 6px; border-radius: 4px;
}
.workdir .muted { color: var(--ink-500); font-size: 11px; }

@media (max-width: 900px) {
  .set-layout { grid-template-columns: 1fr; }
  .set-toc { position: static; }
}
</style>
