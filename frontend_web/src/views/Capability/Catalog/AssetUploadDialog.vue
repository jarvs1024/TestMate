<template>
  <!-- ⚠️ size 用 min(900px, 94vw) —— 表单两列 (基础信息 / 详细说明) 要放得下 (2026-11-03) -->
  <el-drawer :model-value="modelValue" size="min(900px, 94vw)" direction="rtl"
             :title="mode === 'edit' ? `编辑资产 · ${asset?.name || ''}`
                     : (mode === 'update' ? `更新资产 · ${asset?.name || ''}` : '上传新资产')"
             :close-on-click-modal="false" :with-header="true"
             class="up-drawer" @update:model-value="emit('update:modelValue', $event)">
    <template v-if="!job && !uploading && !uploadError">
      <!-- ============ 第 ① 步: 选形态 (没定类型时先问一句) ============ -->
      <div v-if="step === 'pick'" class="kind-pick">
        <div class="kp-lead">
          <b>先选资产形态</b>
          <span>三种形态的配置方式完全不同 —— 选完直接进对应的表单。</span>
        </div>
        <button v-for="k in KIND_META" :key="k.value" type="button"
                class="kp-card" @click="chooseKind(k.value)">
          <span class="kp-ic">{{ k.icon }}</span>
          <span class="kp-main">
            <span class="kp-title">{{ k.label }}<i>{{ k.code }}</i></span>
            <span class="kp-tag">{{ k.tagline }}</span>
            <ul class="kp-needs">
              <li v-for="n in k.needs" :key="n">{{ n }}</li>
            </ul>
          </span>
          <span class="kp-go">开始配置 →</span>
        </button>
      </div>

      <el-form v-else label-position="top" class="up-form">
        <!-- 步骤条: 选形态 → 填配置 (形态在第 ① 步就定了, 这里只是显示进度) -->
        <div v-if="mode === 'create'" class="flow-steps">
          <span class="fs done">① 选形态</span>
          <span class="fs-arrow">→</span>
          <span class="fs on">② 填配置</span>
        </div>

        <!-- 类型头: 现在配的是哪种形态, 一眼可见, 也能随时换 -->
        <div class="type-bar">
          <span class="tb-ic">{{ kind.icon }}</span>
          <span class="tb-body">
            <b>{{ kind.label }}<i>{{ kind.code }}</i></b>
            <span class="tb-hint">{{ kind.formHint }}</span>
          </span>
          <button v-if="mode === 'create'" type="button" class="tb-change"
                  @click="step = 'pick'">更换类型</button>
        </div>
        <!-- ⚠️ 2026-10-30 「只改元信息」模式 —— 一句说明, 免得用户以为还能改包 -->
        <div v-if="mode === 'edit'" class="edit-note">
          ✎ 这里只改说明信息 —— 安装包和版本号不动.
          要换安装包请用「发布新版本」.
        </div>
        <!-- ============ ① 连接器配置 / 安装包 (放最前) ============ -->
        <!-- 连接器是**配置型**资产: 只有一段 MCP 配置, 没有安装包也没有 README -->
        <section v-if="isMcp" class="up-sec">
          <div class="sec-h"><span class="sec-no">1</span>MCP 配置<span class="sec-tip">必填</span></div>
          <!-- ⚠️ 错误只在下面的 mcp-bar 里显示一处 (以前 form-item 和 mcp-bar 各显示一遍) -->
          <el-form-item label="">
            <el-input v-model="mcpConfigText" type="textarea" :rows="11" class="mcp-json"
                      :placeholder="mcpTemplate" />
          </el-form-item>
          <div class="mcp-bar">
            <button type="button" class="mini-btn" @click="formatMcp">格式化</button>
            <button type="button" class="mini-btn" @click="useMcpTemplate">用模板</button>
            <span class="mcp-msg" :class="mcpHintState">
              {{ mcpHint }}
            </span>
          </div>
          <p class="hint">
            连接器是配置型资产 —— Agent 按这段配置来连 (mcpServers → 每个连接器给
            <code>command</code>+<code>args</code> 或 <code>url</code>)。
            详情页会原样展示这份配置, 用户照着加到自己的 MCP 配置里。
          </p>

          <!-- 资产 code: 从 MCP 配置里的连接器名**自动派生** —— 只展示, 不让填 -->
          <div v-if="mode !== 'edit'" class="pkg-req">
            <span class="pr-ic">🔌</span>
            <span class="pr-txt">
              <b>连接器名</b>只能用小写字母/数字/连字符分段。
            </span>
            <span class="pr-code">
              <span class="pc-label">资产 code</span>
              <code class="pc-val">{{ (hasSource && form.code) || '（填好配置后自动生成）' }}</code>
              <span class="pc-hint">自动取 MCP 配置里的连接器名</span>
              <span v-if="codeFieldError" class="cv-err">{{ codeFieldError }}</span>
            </span>
          </div>
        </section>

        <!-- ⚠️ 2026-10-30 「只改元信息」: **不碰安装包** ——
             那一段是"发新版本"才要的 (必须重新传包) ——
             走 _stage_asset_locked 的 else 分支会 rmtree 掉 files/, 把别人的包删了. -->
        <section v-else-if="mode !== 'edit'" class="up-sec">
          <div class="sec-h"><span class="sec-no">1</span>安装包<span class="sec-tip">必填</span></div>
          <!-- 选文件: 隐藏原生 input (系统默认按钮跟整页风格不搭), 换成统一风格的自定义按钮.
               ⚠️ 文件名只显示一次 —— 原生 input 旁边那个是重复的.
               ⚠️ 2026-11-04: 整块做成虚线选择区 + 主色实心按钮, 跟软件库上传抽屉同一套交互
                  (拖进来松手也能选) —— 以前只有一个描边小按钮, 用户看不出这里要传包. -->
          <div class="file-pick" :class="{ dragging }"
               @dragover.prevent="dragging = true"
               @dragleave.prevent="dragging = false"
               @drop.prevent="onDropPackage">
            <input ref="fileInput" type="file" class="file-input"
                   :accept="packageAccept" @change="onPickPackage" />
            <button type="button" class="pick-btn mini-btn primary" @click="fileInput?.click()">
              <span class="pb-ic">📦</span>选择安装包
            </button>
            <span v-if="pkgFile" class="file-chip">
              {{ pkgFile.name }}
              <!-- ⚠️ 原来是个 <b> —— 只能鼠标点, 键盘用户**清不掉**已选的包.
                   换成真按钮 (type=button, 带 aria-label). -->
              <button type="button" class="file-clear" @click="clearPackage"
                      aria-label="移除已选安装包">×</button>
            </span>
            <span v-else class="pick-hint">未选择文件 —— 也可以把文件拖进来</span>
          </div>
          <!-- ⚠️ 只报"包名不合法"这种真错误 ——
               "还没选包"是缺项 (底部「还缺」清单会说), 不是错误, 别一上来就标红 -->
          <p v-if="pkgNameError" class="pick-err">{{ pkgNameError }}</p>

          <!-- 包的要求 + 资产 code 合成一块: code 是包名派生的, 挨着来源才说得清 -->
          <div class="pkg-req">
            <span class="pr-ic">📦</span>
            <span class="pr-txt">
              <b>{{ kind.label }}包要求</b>:
              包名使用小写字母/数字/连字符分段, 并与资产 code 一致;
              <template v-if="kind.pkgNeed">{{ kind.pkgNeed }}。</template>
              压缩包会在服务端解压后推送到 GitLab。
            </span>
            <span class="pr-code">
              <span class="pc-label">资产 code</span>
              <code class="pc-val">{{ (hasSource && form.code) || '（选好包后自动生成）' }}</code>
              <span class="pc-hint">自动取安装包名</span>
              <span v-if="codeFieldError" class="cv-err">{{ codeFieldError }}</span>
            </span>
          </div>

          <!-- 包体检: 选好包就当场验, 不用填完一整张表单才被 422 拦下 -->
          <div v-if="previewing" class="pv-box checking">正在体检安装包…</div>
          <div v-else-if="preview" class="pv-box" :class="previewBad ? 'bad' : 'ok'">
            <div class="pv-h">
              <span class="pv-icon">{{ previewBad ? '❌' : '✅' }}</span>
              <span>{{ previewBad ? '这个包装不上, 请调整后重试' : '体检通过' }}</span>
            </div>
            <div class="pv-meta mono">
              {{ preview.total_files }} 个文件
              · 展示文档 {{ preview.doc_file || '缺失' }}
              <template v-if="preview.installable">· 可一键安装</template>
              <template v-else>· {{ preview.block_reason }}</template>
            </div>
            <ul v-if="previewIssues.length" class="pv-list">
              <li v-for="(i, idx) in previewIssues" :key="'i' + idx">✗ {{ i }}</li>
            </ul>
            <!-- ⚠️ 体检结果用 ?. 兜底 —— 后端返回的形状不完整时 (比如网关截断),
                 读 undefined.length 会把整个抽屉炸白屏, 宁可少显示一段也不能崩 -->
            <ul v-if="preview.warnings?.length" class="pv-list warn">
              <li v-for="(w, idx) in preview.warnings" :key="'w' + idx">⚠ {{ w }}</li>
            </ul>
            <details v-if="preview.files?.length" class="pv-files">
              <summary>文件清单 ({{ preview.files.length }})</summary>
              <code v-for="f in preview.files" :key="f">{{ f }}</code>
            </details>
          </div>
        </section>

        <!-- ============ ② 基础信息 ============ -->
        <section class="up-sec">
          <div class="sec-h"><span class="sec-no">{{ basicNo }}</span>基础信息</div>
          <!-- ① 名称 (必填) + 图标 —— 卡片上最先看到的两样 -->
          <div class="row-2">
            <el-form-item label="名称" required>
              <el-input v-model="form.name" maxlength="60" show-word-limit
                        placeholder="展示名, 中文即可 (卡片上的标题), 如 SSD 日志医生" />
            </el-form-item>
            <el-form-item label="图标">
              <div ref="iconWrap" class="icon-pick">
                <button type="button" class="icon-btn" @click="iconPanel = !iconPanel">
                  <span class="icon-cur">{{ form.icon || '🧩' }}</span>
                  <span class="icon-caret">▾</span>
                </button>
                <div v-if="iconPanel" class="icon-panel">
                  <button v-for="ic in iconChoices" :key="ic" type="button"
                          class="icon-cell" :class="{ on: ic === form.icon }"
                          @click="chooseIcon(ic)">{{ ic }}</button>
                </div>
              </div>
              <p class="hint">自动分配 · 不会跟现有资产重复</p>
            </el-form-item>
          </div>

          <!-- ② 一句话简介 (必填) -->
          <el-form-item label="一句话简介" required>
            <el-input v-model="form.summary" type="textarea" :rows="2" maxlength="200" show-word-limit
                      placeholder="一句话说清它干什么 (卡片副标题 + 搜索都用这句), 如 贴日志即可定位 assert 与超时点" />
          </el-form-item>

          <!-- ③ 分类 (必填) + 适用项目 (选填) —— 都是"归类", 并排一行 -->
          <div class="row-2">
            <el-form-item label="分类" required>
              <!-- ⚠️ 分类接口失败时**必须说清楚** (2026-10-30):
                   以前 catch 把失败吞成空数组 → 下拉是空的 → 页脚挂着「还缺: 分类」→
                   「上架」按钮**永久置灰**, 而且看不出为什么 (同一个接口在扩展页是有红字的,
                   只有这个抽屉是静默的). 现在: 红字说明 + 「重试」按钮 + 兜底分类项. -->
              <div v-if="categoriesError" class="cat-err">
                <span>{{ categoriesError }}。请检查后端服务后点「重试」</span>
                <button type="button" class="cat-retry" @click="loadCategories">重试</button>
              </div>
              <el-select v-model="form.category" class="sel-category" style="width:100%" filterable
                         placeholder="请选择分类"
                         :loading="categoriesLoading" @change="onCategoryChange">
                <el-option v-for="c in categories" :key="c.name" :value="c.name" :label="c.name">
                  <span>{{ c.name }}</span>
                  <!-- ⚠️ title 兜底 —— 下拉框挤窄时还能 hover 看全文 -->
                  <span class="cat-desc" :title="c.desc">{{ c.desc }}</span>
                </el-option>
                <!-- ⚠️ 兜底项: 分类接口失败时注入「其他」—— 后端本来就认这个分类
                     (ext_categories.MISC = "其他", 不认识的分类都归它),
                     保证下拉**永不为空**, 「上架」按钮不会永久卡死.
                     正常返回时**不注入** (表里本来就有「其他」). -->
                <el-option v-if="categoriesError && !hasMiscCategory" value="其他" label="其他" />
              </el-select>
              <!-- ⚠️ 分类是**按协作角色**分的, 不是按流程阶段 ——
                   说清楚"该怎么选", 否则大家会按"这活儿在流程第几步"去选, 选得五花八门. -->
              <p class="hint">
                按这个资产<strong>替你干什么</strong>来选: 兜住质量 / 提效 / 守流程 / 管协同 —— 别按"流程第几步"选
              </p>
            </el-form-item>
            <el-form-item label="适用项目">
              <!-- ⚠️ 必须给中文 placeholder —— Element Plus 默认是英文 "Select",
                   整个界面都是中文, 夹一个英文下拉框很扎眼 (跟软件库那边一个毛病) -->
              <el-select v-model="form.project" class="sel-project" style="width:100%" placeholder="通用">
                <!-- ⚠️ `label` 是选中后输入框里显示的字 —— 必须短;
                     长的解释放 slot 里(只在下拉列表那一行显示) -->
                <el-option value="" label="通用">
                  <span>通用</span>
                  <span class="cat-desc">所有项目都能用</span>
                </el-option>
                <el-option v-for="p in projectOptions" :key="p" :value="p" :label="`${p} 项目`">
                  <span>{{ p }} 项目</span>
                  <span class="cat-desc">只有 {{ p }} 项目用得上</span>
                </el-option>
              </el-select>
              <p class="hint">通用的所有人都能用; 项目特有的会在卡片上标出来</p>
            </el-form-item>
          </div>

          <!-- ④ 版本 (必填) —— 短字段, 别拉满整行 -->
          <!-- ⚠️ 2026-10-30 「只改元信息」: 版本号**不在这里改** ——
               改版本 = 发新版本 (要重新传包). 这里藏掉, 免得用户改了却不生效. -->
          <el-form-item v-if="mode !== 'edit'" label="版本 (semver)" required :error="versionError">
            <el-input v-model="form.version" placeholder="1.0.0" style="max-width: 220px" />
            <p v-if="mode === 'update'" class="hint">发新版本建议 +1 (如 1.0.0 → 1.1.0)</p>
          </el-form-item>

          <!-- ⚠️ 2026-11-03 (第二十二轮): 这几项**上架时也能填**了.
               ⚠️ 以前 (2026-10-30) 只有「只改元信息」模式才有输入框, 新建/发新版本没有 ——
                  于是**新上架的资产这几个字段恒为空** → 以后进「编辑」看到 4 个空框,
                  而详情页明明有一大段说明 (那段其实来自包里的 SKILL.md) →
                  用户看到的"编辑页和上架内容对不上".
               ✅ 现在: 新建 (create) 也能填; 发新版本 (update) **不显示** ——
                  那条路的元信息字段一律保留原值 (见下面的 submit).
               ✅ 详情页也跟着显示这几项 (见 AssetDetailDrawer) —— 填了什么就显示什么. -->
          <template v-if="mode !== 'update'">
            <el-form-item label="详细说明">
              <el-input v-model="form.description" type="textarea" :rows="4"
                        placeholder="这个资产到底是什么、怎么用 —— 详情页会整段显示" />
            </el-form-item>
            <el-form-item label="推荐问法">
              <el-input v-model="form.use_when" type="textarea" :rows="3"
                        placeholder="一行一条, 写成你会直接对 Agent 说的话&#10;如: 帮我看下 6100 项目本周的 SSD 测试结果" />
              <p class="hint">一行一条 —— 详情页逐条展示, 可一键复制.</p>
            </el-form-item>
          </template>
        </section>

        <!-- ============ ③ 进阶信息 (默认收起) ============ -->
        <section class="up-sec">
          <button type="button" class="sec-toggle" @click="advOpen = !advOpen">
            <span class="sec-no">{{ advNo }}</span>进阶信息
            <span class="sec-hint">可展开 · 补充标签与搜索关键词</span>
            <span class="sec-caret">{{ advOpen ? '▾' : '▸' }}</span>
          </button>
          <div v-show="advOpen" class="adv-body">
            <div class="row-2">
              <el-form-item label="标签 (逗号分隔)">
                <el-input v-model="tagsText" placeholder="逗号分隔, 如 日志, 诊断, 速查 (卡片上显示)" />
              </el-form-item>
            </div>
            <el-form-item label="搜索关键词 (逗号分隔)">
              <el-input v-model="keywordsText" placeholder="同义词/技术词, 逗号分隔, 如 ssd, nvme, dmesg (搜不到时靠它)" />
            </el-form-item>
          </div>
        </section>
      </el-form>
    </template>

    <!-- 任务进度: 上传 → staged → syncing(乌龟爬行) → pushed 冲线 / failed 坐下 -->
    <div v-else class="job-box">
      <AssetSyncProgress
        :phase="syncView.phase" :percent="syncView.percent" :title="syncView.title"
        :sub="syncView.sub" :stamp="syncView.stamp" :reason="syncView.reason"
        :hint="syncView.hint" :detail="syncView.detail"
        :saved-on-server="syncView.savedOnServer" />
      <div v-if="job && job.status === 'pushed' && job.commit_sha" class="job-meta mono">
        commit {{ job.commit_sha.slice(0, 12) }} · {{ job.git_path }}
      </div>
      <p v-if="job && job.status === 'pushed' && reviewState === 'pending'" class="job-hint">
        {{ mode === 'edit'
            ? '资料已保存; 安装包仍在上一次提交的审核队列里'
            : (job.commit_sha
                ? '文件已推送, 管理员审核通过后才会出现在扩展库里'
                : '内容已提交, 审核通过后会自动发布到扩展库') }}
      </p>
      <p v-else-if="job && job.status === 'pushed' && reviewState === 'rejected'" class="job-hint">
        资料已保存到暂存区; 资产仍是驳回状态, 改好安装包后可重新提交审核。
      </p>
      <p v-else-if="job && job.status === 'pushed'" class="job-hint">
        前端列表会在同步完成后自动刷新。
      </p>
    </div>

    <template #footer>
      <template v-if="!job && !uploading && !uploadError && step === 'form'">
        <!-- 缺什么一次说清, 不用点一次报一个 -->
        <div class="foot-bar">
          <div class="foot-left">
            <template v-if="missing.length">
              <span class="foot-warn">还缺: {{ missing.join('、') }}</span>
            </template>
            <!-- ⚠️ 字段齐了但体检没过 (重名 / 包装不上) 时要说清为什么按钮点不了,
                 不能一边挂着「该填的都填了」一边置灰 -->
            <span v-else-if="canSubmit" class="foot-ok">✓ 该填的都填了</span>
            <span v-else class="foot-warn">体检未通过，请按上方问题修正后再上架</span>
          </div>
          <div class="foot-right">
            <el-button @click="visible = false">取消</el-button>
            <el-button type="primary" :loading="submitting" :disabled="!canSubmit"
                       @click="submit">
              {{ mode === 'edit' ? '保存修改' : (mode === 'update' ? '提交新版本' : '上架') }}
            </el-button>
          </div>
        </div>
      </template>
      <!-- 还在第 ① 步 (选形态) —— 没东西可提交, 只给个「返回」 -->
      <div v-else-if="!job && !uploading && !uploadError" class="foot-bar">
        <div class="foot-left">
          <span class="foot-hint">先选一种形态, 就能进对应的配置表单</span>
        </div>
        <div class="foot-right">
          <el-button @click="visible = false">取消</el-button>
        </div>
      </div>
      <!-- 上传请求本身失败: 表单内容都还在, 直接可重提 -->
      <template v-else-if="uploadError">
        <el-button @click="backToForm">返回表单</el-button>
        <el-button type="primary" @click="retryUpload">重新提交</el-button>
      </template>
      <!-- 上传中 / 自动重试中: 只能关闭 (关掉即停轮询) -->
      <template v-else-if="uploading || (job && job.status === 'failed' && job.next_retry_at)">
        <el-button @click="close">关闭</el-button>
      </template>
      <template v-else-if="job && job.status === 'failed'">
        <el-button @click="close">关闭</el-button>
        <el-button type="primary" :loading="submitting" @click="doRetry">重试同步</el-button>
      </template>
      <el-button v-else type="primary" @click="close">{{ job && job.status === 'pushed' ? '完成' : '关闭' }}</el-button>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { getAsset, getJob, retryJob, uploadAsset, updateAsset, updateAssetMeta, type AssetItem, type ExtKind } from '@/api/assets';
import { KIND_META } from './kindMeta';
import { useAssetUploadForm } from './useAssetUploadForm';
import { useAssetSync } from './useAssetSync';
import { parseSyncError } from './syncProgress';
import AssetSyncProgress from './AssetSyncProgress.vue';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';

const props = defineProps<{
  modelValue: boolean;
  /**
   * create = 新建资产; update = 发新版本; edit = **只改元信息** (2026-10-30).
   *
   * ⚠️ edit 与 update 的区别: update 必须重新传安装包, 版本号也会变;
   *    edit 只改说明文字 —— 安装包和版本号都不动.
   */
  mode: 'create' | 'update' | 'edit';
  asset?: AssetItem | null;
  /** 入口选定的形态 (扩展页下拉选完传进来) —— 空就先进第 ① 步让人选 */
  initialKind?: ExtKind | '';
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void;
  (e: 'done'): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
});

/** 进阶信息默认收起 (大部分人只填基础信息) */
const advOpen = ref(false);

/**
 * 表单状态、校验与同步逻辑 —— 全在 composable 里.
 *
 * 为什么抽出去 (2026-10-25): 这些是最容易出 bug 的部分 (code 与包名同步 /
 * 缺项清单 / 图标不重复), 埋在组件里时**没法单测**, 只能靠 e2e 兜.
 */
const {
  form, tagsText, keywordsText, mcpConfigText, step, hasSource,
  fileInput, pkgFile, preview, previewing, iconPanel, dragging,
  categories, categoriesError, categoriesLoading, projectOptions, rules,
  isMcp, isEdit, kind, mcpHint, mcpHintState, mcpTemplate, codeFieldError,
  versionError, pkgNameError,
  previewBad, previewIssues, iconChoices, missing, canSubmit,
  formatMcp, useMcpTemplate, loadCategories,
  onCategoryChange, chooseIcon, clearPackage, onPickPackage, onDropPackage,
  chooseKind, reset,
} = useAssetUploadForm({
  mode: () => props.mode,
  asset: () => props.asset,
  initialKind: () => props.initialKind || '',
  open: () => props.modelValue,
});

/**
 * 同步状态机 —— 上传进度 / 阶段映射 / 自动重试 / 终态失败 (2026-11-16).
 * ⚠️ 关抽屉时 isOpen 变 false → 轮询立即停, 不会在别的页面弹提示.
 */
const {
  job, submitting, reviewState, uploadError, syncView,
  beginUpload, noteUploadProgress, failUpload, clearUploadFailure,
  acceptJob, doRetry: retrySync, reset: resetSync,
} = useAssetSync({
  isOpen: () => props.modelValue,
  fetchJob: getJob,
  fetchAsset: getAsset,
  requestRetry: retryJob,
  editingMeta: () => props.mode === 'edit',
  onDone: (j, review) => {
    if (props.mode === 'edit') {
      // ⚠️ 编辑信息不再送审 —— 在架资产跟管理员直改一样提示"已同步";
      //    待审/驳回只保存资料, 状态没变, 不能说成"重新提交了一遍".
      if (review === 'rejected') {
        ElMessage.warning(`${j.code} 修改已保存, 资产仍处于驳回状态 (改好安装包后可重新提交审核)`);
      } else if (review === 'pending') {
        ElMessage.success(`${j.code} 修改已保存, 仍在等待管理员审核`);
      } else {
        ElMessage.success(`${j.code} 修改已同步到 GitLab`);
      }
    } else {
      ElMessage.success(
        review === 'pending'
          ? `${j.code} 已提交, 等待管理员审核`
          : `${j.code} 已同步到 GitLab`,
      );
    }
    emit('done');
  },
  onTerminalFailure: (j) => {
    ElMessage.error('同步失败：' + parseSyncError(j.error).reason);
  },
});

/** 上传请求还在飞 (响应回来前没有 job) —— 这时候显示进度条而不是表单 */
const uploading = computed(() => submitting.value && !job.value && !uploadError.value);

/**
 * 区块编号 —— 条件渲染的块不占号.
 *
 * ⚠️ 2026-10-30: 编辑模式**没有安装包那一段** → 「基础信息」要顶到 ①,
 *    否则页面上会出现 "2 / 3" 这种跳号 (看着像漏了一节).
 */
const basicNo = computed(() => (isEdit.value && !isMcp.value ? 1 : 2));
const advNo = computed(() => basicNo.value + 1);
const packageAccept = computed(() => rules.value?.package.suffixes.join(',') || '');

/**
 * 分类表里有没有「其他」—— 用来决定失败时**要不要**再注入一个兜底项.
 *
 * ⚠️ 后端本来就把「其他」当正式分类 (ext_categories.MISC),
 *    正常返回时表里就有它 —— 再插一个会出现两个「其他」.
 */
const hasMiscCategory = computed(() =>
  categories.value.some((c) => c.name === '其他'));

watch(() => props.modelValue, (open) => {
  // ⚠️ 抽屉关掉 (点 X / 取消 / 关闭按钮) 都要停掉后台轮询 ——
  //    不然同步完成时会在别的页面弹「已同步到 GitLab」.
  if (!open) { resetSync(); return; }
  reset();                 // 表单状态/校验/分类/项目/图标 全部重置
  resetSync();             // 任务进度 / 失败态 / 自动重试倒计时 全部重置
  advOpen.value = false;
});

function splitList(s: string): string[] {
  // 与软件库 splitTags / 后端 ext_policy 一致: 中英文逗号、顿号、分号都拆, 去空去重
  return Array.from(new Set(
    (s || '').split(/[,;、，\s]+/).map((x) => x.trim()).filter(Boolean),
  ));
}

/**
 * MCP 配置文本 → 对象 (解析不了就返回 null = "不改这一项").
 *
 * ⚠️ 解析失败**不能**把配置整个丢掉 —— 后端拿到 null 会保留老配置,
 *    用户以为改了, 实际没改. 但也不能把半截 JSON 发过去 (后端会 422).
 *    所以: 解析不了就发 null (保留原值), 并由上面的校验拦住不让提交.
 */
function parseMcpOrNull(text: string): Record<string, unknown> | null {
  const t = (text || '').trim();
  if (!t) return null;
  try {
    const v = JSON.parse(t);
    return (v && typeof v === 'object') ? v : null;
  } catch {
    return null;
  }
}

/**
 * 点图标面板**外面** → 收起面板.
 *
 * ⚠️ 跟扩展页的形态菜单一个做法 (见 Catalog/index.vue 的 onDocClick):
 *    面板连同按钮都在 .icon-pick 里, 点它不算"外面" ——
 *    不然点一下按钮会被"外面点击"和"按钮自己"各处理一次, 面板开了又关。
 *
 * ⚠️⚠️ 必须用**捕获阶段** (第三个参数 true):
 *    element-plus 的抽屉内容层带 `@click.stop` —— 冒泡阶段的事件根本到不了
 *    document, 用默认的冒泡监听的话, 抽屉里点外面**永远收不到**,
 *    面板就关不掉 (抽屉外反而能关 —— 更迷惑)。
 */
const iconWrap = ref<HTMLElement | null>(null);
function onDocClick(e: MouseEvent) {
  if (!iconPanel.value) return;
  if (iconWrap.value && iconWrap.value.contains(e.target as Node)) return;
  iconPanel.value = false;
}
onMounted(() => document.addEventListener('click', onDocClick, true));
onUnmounted(() => {
  document.removeEventListener('click', onDocClick, true);
});

async function submit() {
  if (missing.value.length) {
    ElMessage.warning('还缺: ' + missing.value.join('、'));
    return;
  }
  beginUpload();
  // ⚠️ 2026-10-30 「只改元信息」: 走**另一条**路 (PATCH) ——
  //    updateAsset 是"发新版本", 必须传包, 版本号也会变.
  if (props.mode === 'edit') {
    try {
      const created = await updateAssetMeta(form.code.trim(), {
        name: form.name.trim(),
        summary: form.summary.trim(),
        description: form.description,
        use_when: form.use_when,
        category: form.category,
        project: form.project || '',
        icon: form.icon || '🧩',
        tags: splitList(tagsText.value),
        keywords: splitList(keywordsText.value),
        // 连接器: 只传 MCP 配置 (非连接器传 null = 不改)
        mcp_config: isMcp.value ? parseMcpOrNull(mcpConfigText.value) : null,
      });
      await acceptJob(created);
    } catch (e: any) {
      ElMessage.error('保存失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
      submitting.value = false;
    }
    return;
  }
  const payload = {
    code: form.code.trim(),
    kind: form.kind,
    name: form.name.trim(),
    version: form.version.trim() || '1.0.0',
    summary: form.summary.trim(),
    // ⚠️ 2026-11-03 (第二十二轮): 这几项现在**上架时也能填**了 (表单里有输入框了).
    //    发新版本 (update) 那一路**不显示**这几项 → 一律保留原值 (从 asset 取),
    //    别让"没填"把老资产的字段清空。
    description: props.mode === 'update' ? (props.asset?.description || '') : form.description,
    use_when: props.mode === 'update' ? (props.asset?.use_when || '') : form.use_when,
    // 「不适合的场景」已下线 —— 发新版本保留老值, 新建一律为空
    not_for: props.mode === 'update' ? (props.asset?.not_for || '') : '',
    category: form.category,
    // 适用项目: 空 = 通用; 不在项目列表里的后端会归一成通用
    project: form.project || '',
    icon: form.icon || '🧩',
    tags: splitList(tagsText.value),
    keywords: splitList(keywordsText.value),
    install_steps: props.mode === 'update'
      ? [...(props.asset?.install_steps || [])]
      : [],
    // ⚠️ 权限声明不再由表单填 (2026-10-24) —— 固定空, 审核直接看包里的内容
    permissions: {},
    featured: props.mode === 'update' ? !!props.asset?.featured : false,
    // 连接器: 只传 MCP 配置, 不传包
    mcp_config: isMcp.value ? mcpConfigText.value : '',
    package: isMcp.value ? null : pkgFile.value,
    files: [] as File[],
  };
  const onProgress = (e: { loaded: number; total?: number }) =>
    noteUploadProgress(e.loaded, e.total || 0);
  try {
    const created = props.mode === 'update'
      ? await updateAsset(form.code, payload, { onUploadProgress: onProgress })
      : await uploadAsset(payload, { onUploadProgress: onProgress });
    await acceptJob(created);
  } catch (e: any) {
    // 请求本身失败 (还没生成 job) —— 表单内容还在, 进度条停在当前位置
    failUpload(httpErrorText(errorStatus(e), errorDetail(e)));
  }
}

/** 上传失败后返回表单 —— 已填内容全部保留 */
function backToForm() {
  clearUploadFailure();
}

/** 上传失败后原地重试 —— 不再让用户重填一遍 */
function retryUpload() {
  clearUploadFailure();
  void submit();
}

async function doRetry() {
  if (!job.value) return;
  submitting.value = true;
  try {
    await retrySync(job.value);
  } catch (e: any) {
    ElMessage.error('重试失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
    submitting.value = false;
  }
}

function close() {
  // 轮询靠 isOpen() 判断 —— 抽屉一关立即停
  visible.value = false;
  if (fileInput.value) fileInput.value.value = '';
}
</script>

<style scoped>
/* ===== 抽屉 ===== */
.up-drawer :deep(.el-drawer__body) { padding-top: 4px; }

/* ===== 第 ① 步: 选形态 ===== */
.kind-pick { padding: 4px 2px 0; }
.kp-lead {
  display: flex; flex-direction: column; gap: 2px;
  margin-bottom: 12px; font-size: 12.5px; color: var(--ink-500);
}
.kp-lead b { font-size: 14px; color: var(--ink-900); }
.kp-card {
  display: flex; align-items: flex-start; gap: 12px; width: 100%;
  padding: 12px 14px; margin-bottom: 10px; text-align: left;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-card); cursor: pointer; font-family: inherit;
  transition: all 0.15s ease;
}
.kp-card:hover { border-color: var(--primary); box-shadow: var(--shadow-md); }
.kp-ic { font-size: 26px; line-height: 1.2; }
.kp-main { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0; }
.kp-title { font-size: 14px; font-weight: 700; color: var(--ink-900); }
.kp-title i {
  font-style: normal; font-size: 11px; font-weight: 500; color: var(--ink-500);
  margin-left: 6px;
}
.kp-tag { font-size: 12px; color: var(--ink-700); line-height: 1.5; }
.kp-needs { margin: 2px 0 0; padding-left: 18px; }
.kp-needs li { font-size: 11.5px; color: var(--ink-500); line-height: 1.7; }
.kp-go { align-self: center; font-size: 12.5px; color: var(--ink-500); white-space: nowrap; }
.kp-card:hover .kp-go { color: var(--primary); }

/* ===== 步骤条 + 类型头 ===== */
.flow-steps {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--ink-500); margin-bottom: 10px;
}
.flow-steps .fs.on { color: var(--primary); font-weight: 700; }
.flow-steps .fs.done { color: var(--ok); }
.flow-steps .fs-arrow { color: var(--ink-500); }
.type-bar {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px; margin-bottom: 14px;
  background: var(--surface-sunken); border: 1px solid var(--border);
  border-radius: var(--radius-card);
}
.tb-ic { font-size: 22px; line-height: 1; }
.tb-body { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.tb-body b { font-size: 13.5px; color: var(--ink-900); }
.tb-body i {
  font-style: normal; font-size: 11px; font-weight: 500; color: var(--ink-500);
  margin-left: 6px;
}
.tb-hint { font-size: 11.5px; color: var(--ink-500); }
/* ⚠️ 2026-10-30 「只改元信息」模式的一句说明 ——
   免得用户以为还能改安装包 (那儿确实没有上传框了). */
.edit-note {
  padding: 9px 12px; margin-bottom: 14px;
  border-radius: var(--radius-card);
  background: rgba(59, 130, 246, 0.07);
  border: 1px solid rgba(59, 130, 246, 0.25);
  font-size: 12px; color: var(--ink-700); line-height: 1.6;
}
.tb-change {
  background: var(--surface); border: 1px solid var(--border);
  color: var(--ink-700); border-radius: var(--radius-pill);
  padding: 4px 12px; font-size: 11.5px; cursor: pointer; font-family: inherit;
}
.tb-change:hover { border-color: var(--primary); color: var(--primary); }

/* ===== 分区 ===== */
.up-sec {
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 12px 14px 2px; margin-bottom: 14px; background: var(--surface);
}
.sec-h, .sec-toggle {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; font-weight: 700; color: var(--ink-900); margin-bottom: 10px;
}
.sec-toggle {
  width: 100%; background: none; border: 0; padding: 0 0 10px;
  cursor: pointer; font-family: inherit; text-align: left;
}
.sec-no {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 50%;
  background: var(--primary); color: #fff; font-size: 11px; font-weight: 700;
}
.sec-tip {
  font-size: 10.5px; font-weight: 600; color: var(--err);
  background: rgba(239, 68, 68, 0.1); padding: 1px 6px; border-radius: var(--radius-pill);
}
.sec-caret { margin-left: auto; color: var(--ink-500); font-size: 11px; }
/* 「可展开」提示 —— 进阶信息默认收起, 得让人知道里面有东西 */
.sec-hint { font-size: 11px; font-weight: 500; color: var(--ink-500); }
.adv-body { padding-bottom: 4px; }

/* 分类下拉里的说明文字 (选项右侧灰字)
   ⚠️ 2026-10-29: 原来这里用 `float: right` + `max-width: 320px` + ellipsis ——
      ① float 在 Element 的选项结构里根本不生效, 位置是乱的;
      ② max-width + ellipsis 把说明**硬截断**成「…」, 用户根本读不到.
      现在: 去掉 float 和 max-width, 让文字自然排下去 (文案也同步改短了),
      真被挤窄了还有 title 兜底能看到全文.

   ⚠️ `display: inline-block` 是必须的 —— Element 的下拉项本身带
      `white-space:nowrap; overflow:hidden; text-overflow:ellipsis`,
      截断发生在**选项行**这一层. 如果说明只是 inline 元素, 省略号会落在
      整行的尾巴上 (把分类名切掉); 改成 inline-block + 自己的 max-width 之后,
      省略号只落在**说明**上, 分类名永远完整. */
.cat-desc {
  display: inline-block; vertical-align: bottom;
  color: var(--ink-500); font-size: 11px;
  margin-left: 12px; max-width: 260px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}

.up-form :deep(.el-form-item) { margin-bottom: 14px; }
.row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; align-items: start; }

/* 包的要求条 —— 放在上传区正下方, 每个形态内容不同 */
.pkg-req {
  display: flex; align-items: flex-start; gap: 8px; flex-wrap: wrap;
  padding: 8px 10px; margin: 0 0 8px;
  background: var(--surface-sunken); border: 1px solid var(--border);
  border-radius: var(--radius-sm); font-size: 11.5px; line-height: 1.7;
  color: var(--ink-700);
}
.pkg-req .pr-ic { font-size: 14px; line-height: 1.3; }
.pkg-req .pr-txt { flex: 1 1 240px; min-width: 0; }
.pkg-req .pr-txt b { color: var(--ink-900); }
/* 资产 code: 跟要求同一个块 —— 它是包名派生的, 挨着来源才说得清 */
.pkg-req .pr-code {
  display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px;
  flex-basis: 100%; padding-top: 6px; margin-top: 2px;
  border-top: 1px dashed var(--border);
}
.pkg-req .pc-label { font-size: 11.5px; font-weight: 600; color: var(--ink-700); }
.pkg-req .pc-val {
  font-family: var(--font-mono); font-size: 12px; color: var(--ink-900);
  background: var(--surface); padding: 1px 7px; border-radius: 4px;
}
.pkg-req .pc-hint { font-size: 11px; color: var(--ink-500); }
.pkg-req .cv-err { flex-basis: 100%; font-size: 11.5px; color: var(--err); }
.pkg-req code {
  font-family: var(--font-mono); font-size: 11px;
  background: var(--surface-soft); padding: 1px 4px; border-radius: 4px;
}

/* ===== 图标选择 ===== */
.icon-pick { position: relative; }
.icon-btn {
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--surface-sunken); padding: 5px 10px; cursor: pointer;
  font-family: inherit; font-size: 16px; min-width: 74px;
}
.icon-caret { font-size: 10px; color: var(--ink-500); }
.icon-panel {
  position: absolute; z-index: 20; top: 38px; left: 0;
  display: grid; grid-template-columns: repeat(8, 1fr); gap: 2px;
  max-height: 260px; overflow-y: auto;
  /* ⚠️ 不透明 —— 半透明毛玻璃底会透出下面的表单文字, 读不清 */
  background: linear-gradient(var(--surface), var(--surface)), var(--bg-base);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 6px; box-shadow: var(--shadow-md);
}
.icon-cell {
  width: 26px; height: 26px; border: 0; background: none; cursor: pointer;
  border-radius: 4px; font-size: 15px; line-height: 1;
}
.icon-cell:hover { background: var(--surface-sunken); }
.icon-cell.on { background: rgba(59, 130, 246, 0.16); }

.hint { margin: 2px 0 0; font-size: 11.5px; color: var(--ink-500); }
/* ===== MCP 配置编辑器 ===== */
.mcp-json :deep(textarea) {
  font-family: var(--font-mono); font-size: 12px; line-height: 1.6;
}
.mcp-bar { display: flex; align-items: center; gap: 8px; margin: 2px 0 6px; }
.mcp-bar button {
  background: var(--surface-sunken); border: 1px solid var(--border);
  color: var(--ink-700); border-radius: var(--radius-pill);
  padding: 3px 12px; font-size: 11.5px; cursor: pointer; font-family: inherit;
}
.mcp-bar button:hover { border-color: var(--primary); color: var(--primary); }
.mcp-msg { font-size: 11.5px; color: var(--ok); }
.mcp-msg.bad { color: var(--err); }
/* ⚠️ 还没填配置 = 缺项, 不是错误 —— 别用红色 (也别用绿色, 那像在说"通过了") */
.mcp-msg.idle { color: var(--ink-600, #6b7280); }
.warn-hint { color: var(--warn); }
.guide {
  margin: 0 0 12px; padding: 8px 10px; font-size: 11.5px; line-height: 1.7;
  color: var(--ink-700); background: var(--surface-sunken); border-radius: var(--radius-sm);
}
.guide code {
  font-family: var(--font-mono); font-size: 11px;
  background: var(--surface); padding: 1px 5px; border-radius: 4px;
}
.perm-note { margin: 0 0 10px; padding: 7px 9px; background: var(--surface-sunken);
  border-radius: var(--radius-sm); line-height: 1.6; }
/* ⚠️ 原生 file input 的系统按钮跟整页风格不搭 —— 藏起来, 用自定义按钮 */
.file-input { display: none; }
/* 选择区: 跟软件库上传抽屉同一套 (虚线框 + 拖放高亮) */
.file-pick {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin-bottom: 10px; padding: 11px 12px;
  border: 1px dashed var(--border); border-radius: var(--radius-sm);
  background: var(--surface-soft);
}
.file-pick.dragging {
  border-color: var(--primary);
  background: rgba(59, 130, 246, .06);
}
/* 按钮外观直接复用全局 .mini-btn.primary (跟「＋ 上传资产」完全一致);
   这里只留图标字号, 别再复写颜色/圆角/内边距. */
.pick-btn .pb-ic { font-size: 14px; }
.pick-hint { font-size: 12.5px; color: var(--ink-500); }
.pick-err { margin: -4px 0 10px; font-size: 11.5px; color: var(--err); }
.hint code {
  font-family: var(--font-mono); font-size: 11px;
  background: var(--surface-sunken); padding: 1px 5px; border-radius: 4px;
}
.file-chip {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px; font-family: var(--font-mono);
  background: var(--surface-sunken); color: var(--ink-700);
  padding: 3px 8px; border-radius: var(--radius-sm);
}
/* ⚠️ 清除按钮: 原来是 <b> —— 只能鼠标点. 现在是真 button, 得把浏览器默认样式复位:
   去掉边框/背景/内边距, 键盘焦点还要看得见 (focus-visible 加 outline). */
.file-clear {
  background: none; border: 0; padding: 0 2px; margin: 0;
  font-family: inherit; font-size: 12px; line-height: 1;
  color: var(--ink-500); cursor: pointer; border-radius: 3px;
}
.file-clear:hover { color: var(--err); }
.file-clear:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }

/* ===== 分类加载失败 (2026-10-30) =====
   ⚠️ 以前失败是**静默**的 (catch 吞成空数组) → 用户只看到「还缺: 分类」,
      「上架」按钮永远灰着, 却不知道为什么. 现在红字说清楚 + 给一个「重试」. */
.cat-err {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-bottom: 6px; padding: 6px 10px;
  font-size: 11.5px; line-height: 1.6; color: var(--err);
  background: rgba(239, 68, 68, 0.07);
  border: 1px solid rgba(239, 68, 68, 0.28);
  border-radius: var(--radius-sm);
}
.cat-err > span { flex: 1; min-width: 200px; }
.cat-retry {
  background: var(--surface); border: 1px solid var(--err); color: var(--err);
  padding: 2px 12px; border-radius: var(--radius-pill);
  font-size: 11.5px; cursor: pointer; font-family: inherit;
}
.cat-retry:hover { background: var(--err); color: #fff; }
.cat-retry:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }

/* ===== 底部固定条 ===== */
.foot-bar { display: flex; align-items: center; gap: 12px; }
.foot-left { flex: 1; min-width: 0; }
.foot-warn { font-size: 11.5px; color: var(--warn); }
.foot-ok { font-size: 11.5px; color: var(--ok); }
.foot-right { display: flex; gap: 8px; }

.job-box { padding: 8px 0; }
.job-meta { font-size: 11px; color: var(--ink-500); margin-top: 10px; }
.job-hint { margin-top: 10px; font-size: 11.5px; color: var(--ink-500); }

/* ===== 包体检结果 ===== */
.pv-box {
  margin-top: 10px; padding: 9px 12px; border-radius: var(--radius-sm);
  font-size: 12px; border: 1px solid var(--border); background: var(--surface-sunken);
}
.pv-box.checking { color: var(--ink-500); }
.pv-box.ok { background: rgba(16, 185, 129, 0.07); border-color: rgba(16, 185, 129, 0.28); }
.pv-box.bad { background: rgba(239, 68, 68, 0.07); border-color: rgba(239, 68, 68, 0.3); }
.pv-h { display: flex; align-items: center; gap: 6px; font-weight: 700; color: var(--ink-900); }
.pv-box.ok .pv-h { color: var(--ok); }
.pv-box.bad .pv-h { color: var(--err); }
.pv-icon { font-size: 13px; }
.pv-meta { margin-top: 4px; font-size: 11px; color: var(--ink-500); }
.pv-list { margin: 6px 0 0; padding-left: 16px; font-size: 11.5px; color: var(--err); }
.pv-list.warn { color: var(--warn); }
.pv-files { margin-top: 6px; font-size: 11px; color: var(--ink-500); }
.pv-files summary { cursor: pointer; }
.pv-files code {
  display: block; font-family: var(--font-mono); font-size: 10.5px;
  color: var(--ink-700); padding: 1px 0;
}
</style>
