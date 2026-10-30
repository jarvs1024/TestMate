<template>
  <el-drawer :model-value="modelValue" size="760px" direction="rtl"
             :title="mode === 'edit' ? `编辑资产 · ${asset?.name || ''}`
                     : (mode === 'update' ? `更新资产 · ${asset?.name || ''}` : '上传新资产')"
             :close-on-click-modal="false" :with-header="true"
             class="up-drawer" @update:model-value="emit('update:modelValue', $event)">
    <template v-if="!job">
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
                      :placeholder="MCP_TEMPLATE" />
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
              <!-- ⚠️ dml- 前缀只在**新建**时要求 (团队命名约定) ——
                   存量连接器的老名字没前缀, 更新时照样能改 -->
              <template v-if="mode === 'create'">
                <b>连接器名</b>必须以 <code>dml-</code> 开头。
              </template>
              <template v-else>
                <b>连接器名</b>只能用小写字母/数字/连字符（新建时还要 <code>dml-</code> 开头）。
              </template>
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
               ⚠️ 文件名只显示一次 —— 原生 input 旁边那个是重复的. -->
          <div class="file-pick">
            <input ref="fileInput" type="file" class="file-input"
                   accept=".zip,.tar.gz,.tgz" @change="onPickPackage" />
            <button type="button" class="pick-btn" @click="fileInput?.click()">
              <span class="pb-ic">📦</span>选择安装包
            </button>
            <span v-if="pkgFile" class="file-chip">
              {{ pkgFile.name }}
              <!-- ⚠️ 原来是个 <b> —— 只能鼠标点, 键盘用户**清不掉**已选的包.
                   换成真按钮 (type=button, 带 aria-label). -->
              <button type="button" class="file-clear" @click="clearPackage"
                      aria-label="移除已选安装包">×</button>
            </span>
            <span v-else class="pick-hint">未选择文件</span>
          </div>
          <!-- ⚠️ 只报"包名不合法"这种真错误 ——
               "还没选包"是缺项 (底部「还缺」清单会说), 不是错误, 别一上来就标红 -->
          <p v-if="pkgNameError" class="pick-err">{{ pkgNameError }}</p>

          <!-- 包的要求 + 资产 code 合成一块: code 是包名派生的, 挨着来源才说得清 -->
          <div class="pkg-req">
            <span class="pr-ic">📦</span>
            <span class="pr-txt">
              <b>{{ kind.label }}包要求</b>:
              包名以 <code>dml-</code> 开头 (如 dml-weekly-report.zip);
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
                   「上架」按钮**永久置灰**, 而且看不出为什么 (同一个接口在市场页是有红字的,
                   只有这个抽屉是静默的). 现在: 红字说明 + 「重试」按钮 + 兜底分类项. -->
              <div v-if="categoriesError" class="cat-err">
                <span>分类列表加载失败：{{ categoriesError }}。请检查后端服务后点「重试」</span>
                <button type="button" class="cat-retry" @click="loadCategories">重试</button>
              </div>
              <el-select v-model="form.category" class="sel-category" style="width:100%" filterable
                         :loading="categoriesLoading" @change="onCategoryChange">
                <el-option v-for="c in categories" :key="c.name" :value="c.name" :label="c.name">
                  <span>{{ c.name }}</span>
                  <!-- ⚠️ title 兜底 —— 下拉框挤窄时还能 hover 看全文 -->
                  <span class="cat-desc" :title="c.desc">{{ c.desc }}</span>
                </el-option>
                <!-- ⚠️ 兜底项: 分类接口失败时注入「其他」—— 后端本来就认这个分类
                     (market_categories.MISC = "其他", 不认识的分类都归它),
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

          <!-- ⚠️ 2026-10-30 「只改元信息」: 这几项上架表单里**没有**输入框,
               但用户想改的就是它们 (详细说明 / 适用场景 / 安装步骤) ——
               以前只能靠"发新版本"改, 太重了. -->
          <template v-if="mode === 'edit'">
            <el-form-item label="详细说明">
              <el-input v-model="form.description" type="textarea" :rows="4"
                        placeholder="这个资产到底是什么、怎么用 —— 详情页会整段显示" />
            </el-form-item>
            <div class="row-2">
              <el-form-item label="适用场景">
                <el-input v-model="form.use_when" type="textarea" :rows="2"
                          placeholder="什么情况下该用它" />
              </el-form-item>
              <el-form-item label="不适合的场景">
                <el-input v-model="form.not_for" type="textarea" :rows="2"
                          placeholder="什么情况下别用它" />
              </el-form-item>
            </div>
            <el-form-item label="安装步骤">
              <el-input v-model="form.installStepsText" type="textarea" :rows="3"
                        placeholder="一行一条, 如&#10;解压到 ~/.qoder-cn/skills&#10;在 MCP 配置里加上这段" />
              <p class="hint">一行一条 —— 详情页会列成步骤.</p>
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

    <!-- 任务进度: staged(已存本地) → syncing(推送中) → pushed(已同步) / failed -->
    <div v-else class="job-box">
      <div class="job-status">
        <el-icon v-if="job.status === 'pushed'" color="var(--ok)"><CircleCheck /></el-icon>
        <el-icon v-else-if="job.status === 'failed'" color="var(--err)"><CircleClose /></el-icon>
        <el-icon v-else class="is-loading"><Loading /></el-icon>
        <div>
          <div class="job-title">
            {{ job.status === 'pushed'
               ? (reviewState === 'checking' ? '已同步到 GitLab, 正在确认上架状态…'
                  : reviewState === 'pending' ? '已提交, 等待管理员审核' : '已同步到 GitLab')
               : job.status === 'failed' ? '同步失败'
               : job.status === 'staged' ? '已保存到本地, 准备同步…'
               : '正在推送到 GitLab…' }}
          </div>
          <div v-if="job.status === 'pushed'" class="job-sub mono">
            commit {{ job.commit_sha.slice(0, 12) }} · {{ job.git_path }}
          </div>
          <div v-if="job.status === 'pushed' && reviewState === 'pending'" class="job-sub">
            文件已推送, 管理员审核通过后才会出现在市场里
          </div>
          <div v-else-if="job.status === 'staged'" class="job-sub">
            文件已落到本地工作区, 后台正在 commit + push
          </div>
        </div>
      </div>
      <pre v-if="job.error" class="job-err">{{ job.error }}</pre>
      <p v-if="job.status === 'failed'" class="job-hint">
        资产仍在本机工作区, 只是没推到 GitLab. 修掉上面的问题后可重试。
      </p>
      <p v-else class="job-hint">前端列表会在同步完成后自动刷新。</p>
    </div>

    <template #footer>
      <template v-if="!job && step === 'form'">
        <!-- 缺什么一次说清, 不用点一次报一个 -->
        <div class="foot-bar">
          <div class="foot-left">
            <template v-if="missing.length">
              <span class="foot-warn">还缺: {{ missing.join('、') }}</span>
            </template>
            <span v-else class="foot-ok">✓ 该填的都填了</span>
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
      <div v-else-if="!job" class="foot-bar">
        <div class="foot-left">
          <span class="foot-hint">先选一种形态, 就能进对应的配置表单</span>
        </div>
        <div class="foot-right">
          <el-button @click="visible = false">取消</el-button>
        </div>
      </div>
      <template v-else-if="job.status === 'failed'">
        <el-button @click="visible = false">关闭</el-button>
        <el-button type="primary" :loading="submitting" @click="doRetry">重试同步</el-button>
      </template>
      <el-button v-else type="primary" @click="close">{{ job.status === 'pushed' ? '完成' : '关闭' }}</el-button>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { CircleCheck, CircleClose, Loading } from '@element-plus/icons-vue';
import { getAsset, getJob, retryJob, uploadAsset, updateAsset, updateAssetMeta, type AssetItem, type AssetJob, type MarketKind } from '@/api/assets';
import { KIND_META } from './kindMeta';
import { MCP_TEMPLATE } from './mcpConfig';
import { useAssetUploadForm } from './useAssetUploadForm';
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
  /** 入口选定的形态 (市场页下拉选完传进来) —— 空就先进第 ① 步让人选 */
  initialKind?: MarketKind | '';
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void;
  (e: 'done'): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
});

const submitting = ref(false);
const job = ref<AssetJob | null>(null);
/**
 * 轮询取消标志 —— 关掉抽屉 / 组件卸载后立刻停止轮询.
 *
 * ⚠️ 以前关掉抽屉后还在每秒请求, 而且同步完成时会在**别的页面**
 *    弹一句「已同步到 GitLab」—— 用户已经走了, 却被一条无关的提示打断.
 */
let pollCancelled = false;

/**
 * 上传后的**上架状态**:
 *   'checking'  → 刚推完, 还没确认要不要审核 (这时候**不能**说"已同步到 GitLab")
 *   'pending'   → 要审核, 等管理员
 *   'published' → 直接上架了
 *
 * ⚠️ 为什么要多一个 checking: 推送完才知道要不要审核 (要再查一次资产状态),
 *    那一小段时间里如果直接显示"已同步到 GitLab", 会先闪一句**错的结论**,
 *    再变成"等待管理员审核" —— 用户正好读到错的那句就懵了.
 */
const reviewState = ref<'checking' | 'pending' | 'published'>('checking');
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
  fileInput, pkgFile, preview, previewing, iconPanel,
  categories, categoriesError, categoriesLoading, projectOptions,
  isMcp, isEdit, kind, mcpHint, mcpHintState, codeFieldError,
  versionError, pkgNameError,
  previewBad, previewIssues, iconChoices, missing, canSubmit,
  formatMcp, useMcpTemplate, loadCategories,
  onCategoryChange, chooseIcon, clearPackage, onPickPackage,
  chooseKind, reset,
} = useAssetUploadForm({
  mode: () => props.mode,
  asset: () => props.asset,
  initialKind: () => props.initialKind || '',
  open: () => props.modelValue,
});

/**
 * 区块编号 —— 条件渲染的块不占号.
 *
 * ⚠️ 2026-10-30: 编辑模式**没有安装包那一段** → 「基础信息」要顶到 ①,
 *    否则页面上会出现 "2 / 3" 这种跳号 (看着像漏了一节).
 */
const basicNo = computed(() => (isEdit.value && !isMcp.value ? 1 : 2));
const advNo = computed(() => basicNo.value + 1);

/**
 * 分类表里有没有「其他」—— 用来决定失败时**要不要**再注入一个兜底项.
 *
 * ⚠️ 后端本来就把「其他」当正式分类 (market_categories.MISC),
 *    正常返回时表里就有它 —— 再插一个会出现两个「其他」.
 */
const hasMiscCategory = computed(() =>
  categories.value.some((c) => c.name === '其他'));

watch(() => props.modelValue, (open) => {
  // ⚠️ 抽屉关掉 (点 X / 取消 / 关闭按钮) 都要停掉后台轮询 ——
  //    不然同步完成时会在别的页面弹「已同步到 GitLab」.
  if (!open) { pollCancelled = true; return; }
  reset();                 // 表单状态/校验/分类/项目/图标 全部重置
  job.value = null;
  submitting.value = false;
  reviewState.value = 'checking';
  advOpen.value = false;
});

function splitList(s: string): string[] {
  return s.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
}

/** 安装步骤: 一行一条 */
function splitLines(s: string): string[] {
  return (s || '').split('\n').map((x) => x.trim()).filter(Boolean);
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
 * ⚠️ 跟市场页的形态菜单一个做法 (见 Market/index.vue 的 onDocClick):
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
  pollCancelled = true;   // 组件没了 → 轮询也停
  document.removeEventListener('click', onDocClick, true);
});

async function submit() {
  if (missing.value.length) {
    ElMessage.warning('还缺: ' + missing.value.join('、'));
    return;
  }
  submitting.value = true;
  // ⚠️ 2026-10-30 「只改元信息」: 走**另一条**路 (PATCH) ——
  //    updateAsset 是"发新版本", 必须传包, 版本号也会变.
  if (props.mode === 'edit') {
    try {
      const created = await updateAssetMeta(form.code.trim(), {
        name: form.name.trim(),
        summary: form.summary.trim(),
        description: form.description,
        use_when: form.use_when,
        not_for: form.not_for,
        category: form.category,
        project: form.project || '',
        icon: form.icon || '🧩',
        tags: splitList(tagsText.value),
        keywords: splitList(keywordsText.value),
        install_steps: splitLines(form.installStepsText),
        // 连接器: 只传 MCP 配置 (非连接器传 null = 不改)
        mcp_config: isMcp.value ? parseMcpOrNull(mcpConfigText.value) : null,
      });
      job.value = created;
      await poll(created.id);
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
    // ⚠️ 详细说明 / 不适用 / 安装步骤 / 设为精选 已经不在表单里填了 ——
    //    更新版本时**保留原值** (从 asset 取), 别让"没填"把老资产的字段清空。
    description: props.mode === 'update' ? (props.asset?.description || '') : '',
    use_when: form.use_when,
    not_for: props.mode === 'update' ? (props.asset?.not_for || '') : '',
    category: form.category,
    // 适用项目: 空 = 通用; 不在项目列表里的后端会归一成通用
    project: form.project || '',
    icon: form.icon || '🧩',
    tags: splitList(tagsText.value),
    keywords: splitList(keywordsText.value),
    install_steps: props.mode === 'update' ? [...(props.asset?.install_steps || [])] : [],
    // ⚠️ 权限声明不再由表单填 (2026-10-24) —— 固定空, 审核直接看包里的内容
    permissions: {},
    featured: props.mode === 'update' ? !!props.asset?.featured : false,
    // 连接器: 只传 MCP 配置, 不传包
    mcp_config: isMcp.value ? mcpConfigText.value : '',
    package: isMcp.value ? null : pkgFile.value,
    files: [] as File[],
  };
  try {
    const created = props.mode === 'update'
      ? await updateAsset(form.code, payload)
      : await uploadAsset(payload);
    job.value = created;
    await poll(created.id);
  } catch (e: any) {
    ElMessage.error('提交失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
    submitting.value = false;
  }
}

async function poll(id: number) {
  // ⚠️ 提交请求还在飞的时候用户可能已经把抽屉关了 —— 那就别再轮询了
  //    (不然 poll 一进来就把取消标志清掉, 又在关着的抽屉背后继续轮询).
  if (!props.modelValue) return;
  pollCancelled = false;
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    if (pollCancelled) return;
    try {
      const j = await getJob(id);
      if (pollCancelled) return;
      job.value = j;
      if (j.status === 'pushed' || j.status === 'failed') {
        submitting.value = false;
        if (j.status === 'pushed') {
          // 上架可能要过审核 —— 查一下资产现在的状态再给提示
          // ⚠️ 查的过程中**不下结论** (reviewState 停在 checking) ——
          //    先闪一句「已同步到 GitLab」再改成「等待管理员审核」是错的.
          reviewState.value = 'checking';
          try {
            const a = await getAsset(j.code);
            reviewState.value = a.publish_status === 'pending' ? 'pending' : 'published';
          } catch {
            reviewState.value = 'published';
          }
          ElMessage.success(
            reviewState.value === 'pending'
              ? `${j.code} 已提交, 等待管理员审核`
              : `${j.code} 已同步到 GitLab`,
          );
          emit('done');
        } else {
          ElMessage.error('同步到 GitLab 失败');
        }
        return;
      }
    } catch {
      /* 轮询失败继续等 */
    }
  }
  if (pollCancelled) return;
  submitting.value = false;
}

async function doRetry() {
  if (!job.value) return;
  submitting.value = true;
  try {
    job.value = await retryJob(job.value.id);
    await poll(job.value.id);
  } catch (e: any) {
    ElMessage.error('重试失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
    submitting.value = false;
  }
}

function close() {
  pollCancelled = true;   // 抽屉关了 → 停掉后台轮询
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
.file-pick { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.pick-btn {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 7px 14px;
  color: var(--ink-700); font-size: 13px; cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
}
.pick-btn:hover { border-color: var(--primary); color: var(--primary); }
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
.job-status { display: flex; align-items: center; gap: 12px; }
.job-status .el-icon { font-size: 26px; }
.job-title { font-size: 14px; font-weight: 700; color: var(--ink-900); }
.job-sub { font-size: 11px; color: var(--ink-500); margin-top: 3px; }
.job-err {
  margin-top: 12px; padding: 10px; background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.25); border-radius: var(--radius-sm);
  font-size: 11.5px; color: var(--err); white-space: pre-wrap; word-break: break-all;
}
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
