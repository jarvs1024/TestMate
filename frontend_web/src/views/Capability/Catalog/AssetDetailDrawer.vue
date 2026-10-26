<template>
  <el-drawer :model-value="modelValue" size="620px" direction="rtl"
             @update:model-value="emit('update:modelValue', $event)">
    <template #header>
      <div v-if="item" class="ad-hd">
        <span class="ad-icon">{{ item.icon }}</span>
        <div class="ad-hd-txt">
          <div class="ad-name">
            {{ item.name }}
            <span v-if="item.publish_status === 'unpublished'" class="ad-off">已下架</span>
          </div>
          <!-- ⚠️ 形态 (技能/插件/连接器) 不在这儿显示 —— 挪到下面的「适用项目」块了,
               那一块统一说"这是什么 + 谁能用", 不用在两个地方各说一半. -->
          <div class="ad-meta mono">{{ item.version }} · {{ item.category }}</div>
        </div>
      </div>
    </template>

    <template v-if="item">
      <!-- 上架审核状态 -->
      <el-alert v-if="item.publish_status === 'pending'" type="warning"
                :closable="false" show-icon class="ad-alert"
                title="该资产正在等待管理员审核, 审核通过后才会出现在市场里" />
      <el-alert v-else-if="item.publish_status === 'rejected'" type="error"
                :closable="false" show-icon class="ad-alert"
                :title="'审核未通过: ' + (item.review_note || '未说明原因, 请修改后重新提交')" />

      <!-- 下架申请: 等管理员确认, 确认后资产会被彻底删除 -->
      <el-alert v-if="item.publish_status === 'unpublish_pending'" type="warning"
                :closable="false" show-icon class="ad-alert"
                :title="unpublishPendingText" />
      <!-- 下架提示: 本地还装着, 但远端已下架 -->
      <el-alert v-if="item.publish_status === 'unpublished'" type="warning"
                :closable="false" show-icon class="ad-alert"
                title="该资产已被下架" />

      <!-- ① 安装卡 (吸顶: 无论滚到哪, "下载"和"怎么装"都在眼前) -->
      <div class="ad-install">
        <template v-if="item.kind !== 'mcp'">
          <div class="ins-h">
            <span class="ins-t">⬇ 下载安装包</span>
            <code class="ins-file">{{ item.code }}-{{ item.version }}.zip</code>
          </div>
          <el-button type="primary" class="ins-btn" :loading="busy" @click="doDownload">
            下载
          </el-button>
          <!-- ⚠️ 提示写**通用话术** (2026-10-25 用户要求): 别把某个 Agent 的目录
               写死成主提示 —— 不同 Agent 的安装方式不一样, 主提示只说"下载完怎么用".
               手动安装的参考目录收在下面的折叠里, 想看的人点开看. -->
          <p class="ins-tip">下载后在 Agent 里导入这个压缩包即可安装 (Agent 支持从压缩包导入插件 / 技能)</p>
          <details class="ins-more">
            <summary>手动安装到默认目录 (Qoder)</summary>
            <div class="ins-dir">
              <span class="ins-dir-l">默认安装目录 (Qoder)</span>
              <code>{{ targetDir }}/</code>
            </div>
            <p class="ins-tip">解压到这个目录后, 重启 Qoder 会话即可使用 (其他 Agent 的目录不一样, 以其文档为准)</p>
          </details>
        </template>
        <template v-else>
          <div class="ins-h">
            <span class="ins-t">⚙️ 连接器配置</span>
            <button type="button" class="mini-link" @click="copyMcpConfig">复制 JSON</button>
          </div>
          <p class="ins-tip">
            连接器是配置型资产 —— 它就是一段 MCP 配置.
            复制下面的 JSON, 把里面的 server 条目加到 Agent 的 MCP 配置里即可.
          </p>
        </template>
      </div>

      <p class="ad-summary">{{ item.description || item.summary }}</p>

      <!-- 适用项目: 说清"这是什么形态 + 谁能用" —— 形态挪过来了, 一处说完 -->
      <div class="ad-scope" :class="{ proj: !!item.project }">
        <span class="sc-ic">{{ kindInfo.icon }}</span>
        <span class="sc-txt">
          <b>{{ item.project ? `${item.project} 项目专属` : '通用资产' }} · {{ kindInfo.label }}</b>
          <span v-if="item.project">只对 {{ item.project }} 项目有意义 —— 其他项目用不上</span>
          <span v-else>所有项目都能用</span>
        </span>
      </div>

      <!-- ⚠️ 「适用场景」整块去掉了 (2026-10-25 用户要求):
           上传表单里已经不让人填这个字段 (新建不填 / 更新保留原值),
           页面再单列一块只是把 README 里的内容重复一遍. -->
      <!-- ⚠️ 「不适用」也早就去掉了 (2026-10-24): README 里已经写了, 页面再列一遍是重复. -->

      <!-- 连接器: 只有一段 MCP 配置 (没有 README) -->
      <div v-if="item.kind === 'mcp'" class="ad-block">
        <div class="ad-block-h">
          ⚙️ MCP 配置
          <button type="button" class="mini-link" @click="copyMcpConfig">复制</button>
        </div>
        <pre class="mcp-view mono">{{ mcpConfigText }}</pre>
      </div>

      <!-- 文档正文: SKILL.md (skill) / README.md (plugin) -->
      <div v-else class="ad-block">
        <div class="ad-block-h">
          📄 {{ doc?.filename || (item.kind === 'skill' ? 'SKILL.md' : 'README.md') }}
          <span v-if="docLoading" class="ad-loading">加载中…</span>
        </div>
        <div v-if="doc" class="ad-doc" v-html="docHtml" />
        <div v-else-if="docError" class="ad-doc-empty">{{ docError }}</div>
        <div v-else class="ad-doc-empty">暂无文档内容</div>
      </div>

      <!-- ⚠️ 权限声明 / 安装步骤 的独立区块都去掉了 (2026-10-24):
           权限声明 —— 上传表单里已经不让填了, 留着只会显示"没填"却像是"确认不需要";
           安装步骤 —— README 里本来就有一份, 两处重复. -->


      <div class="ad-tags">
        <span v-for="t in item.tags" :key="t" class="tag">#{{ t }}</span>
      </div>

      <div class="ad-foot mono">
        <span>作者 {{ item.author || '未知' }}</span>
        <span>更新 {{ (item.updated_at || '').slice(0, 10) || '—' }}</span>
      </div>

      <!-- 技术信息: GitLab 路径 / commit / 同步状态 —— 普通用户用不上, 默认收起 -->
      <div class="ad-tech">
        <button type="button" class="tech-toggle" @click="techOpen = !techOpen">
          <span>🔧 技术信息</span>
          <span class="tech-caret">{{ techOpen ? '▾' : '▸' }}</span>
        </button>
        <div v-show="techOpen" class="tech-body">
          <div class="tech-line mono">
            <span>资产号 {{ item.code }}</span>
            <span>下载 {{ item.download_count || 0 }} 次</span>
          </div>
          <div v-if="item.git_path" class="ad-git mono">
            <span class="ad-git-label">GitLab 存储</span>
            <code>{{ item.git_path }}</code>
            <code v-if="item.git_commit_sha">{{ item.git_commit_sha.slice(0, 12) }}</code>
            <a v-if="item.git_web_url" class="ad-git-link" :href="item.git_web_url"
               target="_blank" rel="noopener">↗ 在 GitLab 查看</a>
            <span class="ad-sync-chip" :class="item.sync_status">{{ syncLabel }}</span>
          </div>
        </div>
      </div>

      <div v-if="item.sync_status === 'failed' && item.last_error" class="ad-err">
        <div class="ad-err-h">同步到 GitLab 失败</div>
        <pre>{{ item.last_error }}</pre>
        <p class="ad-err-hint">资产仍在本机工作区, 修复后可重试同步。</p>
      </div>

      <!-- 说明: 动作按钮放在抽屉的**固定底栏** (见文末 #footer) —— 文档再长也点得到 -->
    </template>

    <template #footer>
      <div v-if="item" class="ad-actions">
        <!-- ===== 审核操作 (管理员) ===== -->
        <el-button v-if="canReview && item.publish_status === 'pending'"
                   type="primary" class="ad-btn" :loading="busy" @click="doReview('approve')">
          通过审核
        </el-button>
        <el-button v-if="canReview && item.publish_status === 'pending'"
                   type="warning" plain class="ad-btn" :loading="busy" @click="doReview('reject')">
          驳回
        </el-button>
        <!-- ===== 重新提交 (作者本人) ===== -->
        <el-button v-if="canSubmit && item.publish_status === 'rejected'"
                   type="primary" class="ad-btn" :loading="busy" @click="doSubmit">
          重新提交审核
        </el-button>

        <!-- ===== 下架审核 (仅管理员) =====
             通过 = 资产被彻底删除 (不可恢复), 所以只有管理员能拍板.
             ⚠️ 没有「驳回下架」—— 管理员不点头的话申请就一直挂着, 作者可自行撤销. -->
        <el-button v-if="isAdmin && item.publish_status === 'unpublish_pending'"
                   type="danger" class="ad-btn" :loading="busy" @click="doReviewUnpublish()">
          通过下架并删除
        </el-button>
        <!-- ===== 撤销下架申请 (作者本人) ===== -->
        <el-button v-if="canEdit && item.publish_status === 'unpublish_pending'"
                   class="ad-btn" :loading="busy" @click="doCancelUnpublish">
          撤销下架申请
        </el-button>

        <!-- ⚠️ 「下载」不在这里 —— 它跟"装到哪"放一起了 (见顶部安装卡).
             不做「装到本地 / 重新安装 / 卸载」那一套 —— 服务器不该替用户管磁盘. -->
        <el-button v-if="canEdit" class="ad-btn" @click="emit('edit', item)">发布新版本</el-button>
        <el-button v-if="canEdit && item.publish_status === 'published'"
                   class="ad-btn" type="warning" plain @click="doApplyUnpublish">
          申请下架
        </el-button>
        <el-button v-if="canEdit && item.publish_status === 'unpublished'"
                   class="ad-btn" type="primary" plain @click="doRepublish">
          重新上架
        </el-button>
        <!-- ⚠️ 作者删自己**没上架过**的资产 (待审核 / 被驳回):
             这两种状态的东西从来没对外可见过, 直接删是安全的, 不用走下架审核.
             以前没这条出口 → 作者传错了只能干等, 文件还永久躺在 GitLab 里. -->
        <el-button v-if="canDiscard" class="ad-btn danger" :loading="busy" @click="doDiscard">
          删除
        </el-button>
        <!--
          ⚠️ 这里**没有**「彻底删除」按钮 (2026-10-24 起) ——
             删除是不可逆的动作, 必须走「申请下架 → 管理员确认」, 有人拍板.
        -->
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  cancelUnpublish, deleteAsset, downloadAssetPackage, getAssetDoc, publishAsset,
  reviewAsset, reviewUnpublish, submitForReview,
  unpublishAsset,
  type AssetDoc, type AssetItem,
} from '@/api/assets';
import { useUserStore } from '@/stores/user';
import { renderMarkdown } from '@/utils/markdown';
import { downloadBlob } from '@/utils/download';
import { kindMeta } from './kindMeta';
import { isAuthor } from './identity';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';

const props = defineProps<{
  modelValue: boolean;
  item: AssetItem | null;
  canEdit?: boolean;
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void;
  (e: 'edit', item: AssetItem): void;
  (e: 'changed'): void;
  /** 资产被删除了 —— 父组件不要再拿它去刷新 (会 404) */
  (e: 'deleted'): void;
}>();

const doc = ref<AssetDoc | null>(null);
const docLoading = ref(false);
const docError = ref('');
const busy = ref(false);
/** 技术信息 (GitLab 路径/commit/同步状态) 默认收起 —— 普通用户用不上 */
const techOpen = ref(false);
/** 连接器的 MCP 配置 (格式化后展示) */
const mcpConfigText = computed(() => {
  const cfg = props.item?.mcp_config;
  if (!cfg) return '';
  try {
    return JSON.stringify(cfg, null, 2);
  } catch {
    return String(cfg);
  }
});
async function copyMcpConfig() {
  const text = mcpConfigText.value;
  if (!text) {
    ElMessage.warning('这个连接器没有 MCP 配置');
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success('MCP 配置已复制');
  } catch {
    ElMessage.error('复制失败, 请手动选中复制');
  }
}

const userStore = useUserStore();
/** 审核人是管理员 */
const isAdmin = computed(() => userStore.user?.role === 'admin');
/** 能不能审 —— 管理员, 或被授权的审核人 (item.can_review 由后端算).
 *  ⚠️ 之前只看 isAdmin, 团队里被授权的审核人点不了审核按钮. */
const canReview = computed(() => isAdmin.value || !!props.item?.can_review);
/** 能不能重新提交审核 —— 资产作者本人 (或管理员) */
const canSubmit = computed(() => {
  const a = props.item;
  if (!a) return false;
  if (isAdmin.value) return true;
  // ⚠️ 走 isAuthor (短名/全邮箱都认) —— 用户名是邮箱式, 存量资产 author 可能还是短名
  return isAuthor(a.author, userStore.user?.username);
});

/**
 * 作者能不能直接删掉这个资产 —— 只限**还没上架过**的 (待审核 / 被驳回).
 *
 * ⚠️ 这两种状态的东西从来没对外可见过 (可见性只放行在架的 + 作者自己的),
 *    所以作者直接删是安全的, 不需要走下架审核.
 *    在架的资产**仍然不行**: 那种必须走「申请下架 → 管理员确认」, 有人拍板.
 */
const canDiscard = computed(() => {
  const a = props.item;
  if (!a) return false;
  const ps = a.publish_status;
  if (ps !== 'pending' && ps !== 'rejected') return false;
  if (isAdmin.value) return true;
  // ⚠️ 走 isAuthor (短名/全邮箱都认) —— 别写 `author === me`
  return isAuthor(a.author, userStore.user?.username);
});

/** 作者删掉自己没上架过的资产 */
async function doDiscard() {
  const it = props.item;
  if (!it) return;
  try {
    await ElMessageBox.confirm(
      `确定删除「${it.name}」吗？它还没上架过, 删除后 GitLab 上的文件也会一起清掉, 不可恢复。`,
      '删除未上架的资产',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    );
  } catch {
    return;   // 用户取消了
  }
  busy.value = true;
  try {
    await deleteAsset(it.code, '作者删除未上架的资产');
    ElMessage.success('已删除');
    emit('deleted');
    emit('changed');
  } catch (e: any) {
    ElMessage.error('删除失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
  } finally {
    busy.value = false;
  }
}

const docHtml = computed(() => renderMarkdown(doc.value?.content || ''));

/** 待下架审核时的提示 —— 管理员看到的是"等你拍板", 作者看到的是"等管理员确认" */
const unpublishPendingText = computed(() => {
  const it = props.item;
  if (!it) return '';
  const who = it.author || '发布者';
  if (isAdmin.value) {
    return `「${who}」申请下架这个资产 —— 通过后资产会被彻底删除 (不可恢复)`;
  }
  return '已申请下架, 等管理员确认 —— 确认后资产会被彻底删除';
});

const syncLabel = computed(() => {
  switch (props.item?.sync_status) {
    case 'staged': return '🕐 待同步';
    case 'pushed': return '✓ 已同步到 GitLab';
    case 'failed': return '❌ 同步失败';
    default: return '—';
  }
});


// 请求序号: 快速切资产时, 慢的旧文档响应会覆盖新文档 (抽屉里显示的是上一个资产的说明).
// 另外两个 watch (切资产 / 开抽屉) 还会触发重复请求 —— 序号保证只有最后一次的结果算数.
let docSeq = 0;
async function loadDoc(code: string) {
  const seq = ++docSeq;
  // ⚠️ 连接器没有文档 (只有一段 MCP 配置) —— 别去请求, 否则 404 会弹红条
  if (props.item?.kind === 'mcp') {
    doc.value = null;
    docError.value = '';
    docLoading.value = false;
    return;
  }
  docLoading.value = true;
  docError.value = '';
  doc.value = null;
  try {
    const d = await getAssetDoc(code);
    if (seq !== docSeq) return;   // 已有更新的请求在飞, 丢弃本次
    doc.value = d;
  } catch (e: any) {
    if (seq !== docSeq) return;   // 过期请求的失败不该改页面
    docError.value = httpErrorText(errorStatus(e), errorDetail(e), '文档读取失败');
  } finally {
    if (seq === docSeq) docLoading.value = false;
  }
}

watch(() => props.item?.code, (c) => {
  if (c && props.modelValue) loadDoc(c);
}, { immediate: true });

watch(() => props.modelValue, (open) => {
  if (open && props.item?.code) loadDoc(props.item.code);
});

/**
 * 手动安装的**参考目录** (2026-10-25: 降级成次要信息).
 *
 * ⚠️ 主提示已改成通用话术 ("在 Agent 里导入压缩包即可安装") ——
 *    不同 Agent 的安装方式/目录不一样, 把某个 Agent 的路径写死在主提示上
 *    会误导用别的 Agent 的人. 这个路径只当"手动装的话放这儿"供参考.
 * ⚠️ 路径本身是 **Qoder 专用**的 (别的 Agent 不是这个目录) ——
 *    所以标签上写明「默认安装目录 (Qoder)」, 别让人以为所有资产都装在这儿.
 */
const targetDir = computed(() => {
  const it = props.item;
  if (!it) return '';
  return it.kind === 'skill'
    ? `~/.qoder-cn/skills/${it.code}`
    : `~/.qoder-cn/plugins/cache/qoder-marketplace/${it.code}/${it.version}`;
});

/** 形态元信息 (图标 + 中文名) —— 头部不显示了, 挪到「适用项目」块里 */
const kindInfo = computed(() => kindMeta(props.item?.kind));

/**
 * 下载安装包 —— 落到浏览器的默认下载目录, 用户自己解压.
 *
 * ⚠️ 不做"装到本地": 浏览器写盘要用户逐次授权家目录 (权限问题太多),
 *    服务端写盘又要求服务器能操作用户磁盘 (权限边界不清).
 *    下载是最省心、也最没有争议的一条路.
 */
async function doDownload() {
  const it = props.item;
  if (!it) return;
  busy.value = true;
  try {
    const blob = await downloadAssetPackage(it.code, it.version);
    downloadBlob(blob, `${it.code}-${it.version}.zip`);
    // ⚠️ 不记任何安装状态 —— 安装只是下载, 后端不知道用户到底装没装,
    //    记了也是虚假语义 ("已安装" 徽标会骗人)
    ElMessage.success(
      `已下载 ${it.code}-${it.version}.zip —— 在 Agent 里导入这个压缩包即可安装`,
    );
  } catch (e: any) {
    ElMessage.error('下载失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
  } finally {
    busy.value = false;
  }
}

/**
 * **申请下架** —— 不可逆的动作, 所以:
 *   1. 要手打资产 code 确认 (跟"彻底删除"一样的门槛)
 *   2. 提交后不是立刻删, 而是进「待下架审核」, 等管理员拍板
 *
 * 为什么不是点了就删: 市场是**共享**的 —— 资产下架了别人第二天就装不上,
 * 得有人确认 (管理员通过后资产会被彻底删除).
 */
async function doApplyUnpublish() {
  const it = props.item;
  if (!it) return;
  const code = it.code;
  const name = it.name;
  try {
    await ElMessageBox.prompt(
      `申请下架「${name}」?\n`
      + `下架是「不可逆」的: 管理员确认后资产会被彻底删除 —— `
      + `GitLab 上的文件、索引与记录都会消失。\n`
      + `请输入资产 code「${code}」以确认。`,
      '申请下架',
      {
        type: 'warning',
        confirmButtonText: '提交下架申请',
        cancelButtonText: '取消',
        inputPlaceholder: code,
        inputValidator: (v: string) => (v || '').trim() === code || '输入与 code 不一致',
      },
    );
  } catch {
    return;  // 用户取消
  }
  busy.value = true;
  try {
    await unpublishAsset(code, code, '申请下架');
    ElMessage.success('下架申请已提交, 等管理员确认');
    emit('changed');
  } catch (e: any) {
    ElMessage.error('申请失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
  } finally {
    busy.value = false;
  }
}

/**
 * 管理员审核下架申请: 通过 = 彻底删除.
 *
 * ⚠️ 没有「驳回」—— 管理员不点头的话申请就一直挂着, 作者可以自己撤销.
 */
async function doReviewUnpublish() {
  const it = props.item;
  if (!it) return;
  const code = it.code;
  const name = it.name;
  try {
    await ElMessageBox.confirm(
      `确认通过「${name}」的下架申请?\n`
      + `通过后资产会被「彻底删除」: GitLab 上的文件、索引与记录都会消失, 不可恢复。\n`
      + `已下载到用户本机的安装包不会被清理。`,
      '通过下架申请',
      { type: 'error', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    );
  } catch {
    return;
  }
  busy.value = true;
  try {
    await reviewUnpublish(code, 'approve');
    ElMessage.success('已通过下架申请, 资产已删除');
    emit('update:modelValue', false);
    emit('deleted');
    emit('changed');
  } catch (e: any) {
    ElMessage.error('审核失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
  } finally {
    busy.value = false;
  }
}

/** 作者撤销自己的下架申请 */
async function doCancelUnpublish() {
  const it = props.item;
  if (!it) return;
  try {
    await ElMessageBox.confirm(
      `撤销「${it.name}」的下架申请? 撤销后资产保持上架, 不用等管理员处理。`,
      '撤销下架申请',
      { type: 'info', confirmButtonText: '撤销申请', cancelButtonText: '取消' },
    );
  } catch {
    return;
  }
  busy.value = true;
  try {
    await cancelUnpublish(it.code, '作者撤销下架申请');
    ElMessage.success('已撤销, 资产保持上架');
    emit('changed');
  } catch (e: any) {
    ElMessage.error('撤销失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
  } finally {
    busy.value = false;
  }
}

/** 重新上架 (已下架的资产恢复在架) */
async function doRepublish() {
  const it = props.item;
  if (!it) return;
  busy.value = true;
  try {
    await publishAsset(it.code);
    ElMessage.success('已重新上架');
    emit('changed');
  } catch (e: any) {
    ElMessage.error('操作失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
  } finally {
    busy.value = false;
  }
}

/** 管理员审核: 通过 / 驳回 */
async function doReview(decision: 'approve' | 'reject') {
  if (!props.item) return;
  const code = props.item.code;
  const name = props.item.name;
  let comment = '';
  if (decision === 'reject') {
    try {
      const r = await ElMessageBox.prompt(
        `驳回「${name}」需要给发布者一个理由 (会显示在资产详情里, 并通知钉钉群)`,
        '驳回上架',
        {
          type: 'warning', confirmButtonText: '驳回', cancelButtonText: '取消',
          inputPlaceholder: '例如: 权限声明与实际行为不符, 请补充后重提',
          inputValidator: (v: string) => (v || '').trim() ? true : '请填写驳回理由',
        },
      );
      comment = r.value || '';
    } catch {
      return;  // 用户取消
    }
  } else {
    try {
      await ElMessageBox.confirm(
        `确认通过「${name}」的审核? 通过后它会出现在市场里。`,
        '通过审核',
        { type: 'success', confirmButtonText: '通过', cancelButtonText: '取消' },
      );
    } catch {
      return;
    }
  }
  busy.value = true;
  try {
    await reviewAsset(code, decision, comment);
    ElMessage.success(decision === 'approve' ? '已通过审核, 资产已上架' : '已驳回, 理由已通知发布者');
    emit('changed');
  } catch (e: any) {
    ElMessage.error('审核失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
  } finally {
    busy.value = false;
  }
}

/** 作者把被驳回的资产重新提交审核 */
async function doSubmit() {
  if (!props.item) return;
  busy.value = true;
  try {
    await submitForReview(props.item.code, '修改后重新提交');
    ElMessage.success('已重新提交, 等待管理员审核');
    emit('changed');
  } catch (e: any) {
    ElMessage.error('提交失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
  } finally {
    busy.value = false;
  }
}

/*
 * ⚠️ 这里**没有**「彻底删除」函数了 (2026-10-24 起).
 *    删除是不可逆的动作, 必须走「申请下架 → 管理员确认」, 有人拍板:
 *      作者: 申请下架 (打 code 确认) → 资产进「待下架审核」
 *      管理员: 通过 → 资产被彻底删除 / 驳回 → 恢复在架
 *    后端的 DELETE /{code} 还在, 但**只允许管理员**用 (运维清理), 前端不暴露.
 */
</script>

<style scoped>
.ad-hd { display: flex; align-items: center; gap: 10px; }
.ad-icon {
  width: 36px; height: 36px; border-radius: 10px; font-size: 18px;
  background: var(--primary-grad); display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; box-shadow: var(--primary-shadow);
}
.ad-hd-txt { min-width: 0; }
.ad-name { font-size: 15px; font-weight: 700; color: var(--ink-900); display: flex; align-items: center; gap: 8px; }
.ad-off {
  font-size: 10.5px; font-weight: 600; color: var(--warn);
  background: rgba(245, 158, 11, 0.14); padding: 2px 7px; border-radius: var(--radius-pill);
}
.ad-meta { font-size: 11px; color: var(--ink-500); margin-top: 2px; }

.ad-alert { margin-bottom: 12px; }
.ad-summary {
  margin: 0 0 14px; font-size: 13px; color: var(--ink-700); line-height: 1.65; white-space: pre-wrap;
}

/* 适用项目 (通用 / 项目专属) */
.ad-scope {
  display: flex; align-items: flex-start; gap: 9px;
  padding: 9px 12px; margin-bottom: 14px;
  background: var(--surface-sunken); border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.ad-scope.proj { border-color: rgba(20, 184, 166, 0.35); }
.ad-scope .sc-ic { font-size: 15px; line-height: 1.3; }
.ad-scope .sc-txt { display: flex; flex-direction: column; gap: 2px; }
.ad-scope .sc-txt b { font-size: 12.5px; color: var(--ink-900); }
.ad-scope .sc-txt span { font-size: 11.5px; color: var(--ink-500); }
.ad-scope.proj .sc-txt b { color: var(--primary-2); }

.ad-block { margin-bottom: 14px; }
.ad-block-h {
  font-size: 12px; font-weight: 700; color: var(--ink-700);
  padding-bottom: 5px; border-bottom: 1px dashed var(--border); margin-bottom: 7px;
  display: flex; align-items: center; gap: 8px;
}
.ad-block-h.ok { color: var(--ok); }
.ad-block-h.warn { color: var(--warn); }
.ad-block-h.perm { color: var(--ink-900); }
.ad-block-b { font-size: 12.5px; color: var(--ink-700); line-height: 1.6; }
.ad-block-b.muted { color: var(--ink-500); font-style: italic; }
.ad-loading { font-size: 11px; color: var(--ink-500); font-weight: 400; }

/* 文档正文 — 内容已由 DOMPurify 消毒 */
.ad-doc {
  font-size: 13px; color: var(--ink-700); line-height: 1.7;
  max-height: 320px; overflow-y: auto;
  background: var(--surface-sunken); border-radius: var(--radius-sm);
  padding: 12px 14px;
}
.ad-doc :deep(h1) { font-size: 16px; font-weight: 700; color: var(--ink-900); margin: 0 0 10px; }
.ad-doc :deep(h2) { font-size: 14px; font-weight: 700; color: var(--ink-900); margin: 14px 0 7px; }
.ad-doc :deep(h3) { font-size: 13px; font-weight: 700; color: var(--ink-900); margin: 12px 0 6px; }
.ad-doc :deep(p) { margin: 0 0 8px; }
.ad-doc :deep(ul), .ad-doc :deep(ol) { margin: 0 0 8px; padding-left: 20px; }
.ad-doc :deep(li) { margin-bottom: 3px; }
.ad-doc :deep(code) {
  font-family: var(--font-mono); font-size: 11.5px;
  background: var(--surface); border: 1px solid var(--border);
  padding: 1px 5px; border-radius: 4px;
}
.ad-doc :deep(pre) {
  background: var(--surface); border: 1px solid var(--border);
  padding: 9px 11px; border-radius: var(--radius-sm); overflow-x: auto;
}
.ad-doc :deep(pre code) { background: transparent; border: 0; padding: 0; }
.ad-doc :deep(table) { border-collapse: collapse; width: 100%; margin-bottom: 8px; }
.ad-doc :deep(th), .ad-doc :deep(td) {
  border: 1px solid var(--border); padding: 4px 7px; font-size: 12px; text-align: left;
}
.ad-doc :deep(a) { color: var(--primary); }
.ad-doc-empty {
  font-size: 12px; color: var(--ink-500); font-style: italic;
  background: var(--surface-sunken); padding: 10px 12px; border-radius: var(--radius-sm);
}
.mcp-view {
  margin: 0; padding: 10px 12px; border-radius: var(--radius-sm);
  background: var(--surface-sunken); border: 1px solid var(--border);
  font-family: var(--font-mono); font-size: 11.5px; line-height: 1.65;
  color: var(--ink-800); white-space: pre-wrap; word-break: break-all;
  max-height: 320px; overflow: auto;
}

.ad-perm {
  background: rgba(245, 158, 11, 0.07);
  border: 1px solid rgba(245, 158, 11, 0.25);
  border-radius: var(--radius-card); padding: 10px 12px;
}
.ad-perm.is-empty { background: var(--surface-sunken); border-color: var(--border); }
.perm-count {
  font-size: 10.5px; font-weight: 600;
  background: rgba(245, 158, 11, 0.16); color: var(--warn);
  padding: 2px 7px; border-radius: var(--radius-pill);
}
.perm-none { font-size: 10.5px; color: var(--ok); font-weight: 600; }
.perm-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.perm-list li { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.perm-label { font-size: 11px; color: var(--ink-500); min-width: 52px; flex-shrink: 0; }
.perm-val {
  font-family: var(--font-mono); font-size: 11px;
  background: var(--surface); border: 1px solid var(--border);
  padding: 1px 6px; border-radius: var(--radius-sm); color: var(--ink-700);
}

.steps { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 5px; }
.steps li { font-size: 12.5px; color: var(--ink-700); line-height: 1.6; }

.ad-tags { display: flex; flex-wrap: wrap; gap: 5px; margin: 4px 0 12px; }
.tag {
  font-size: 10.5px; color: var(--ink-500);
  background: var(--surface-sunken); padding: 2px 7px;
  border-radius: var(--radius-sm); font-family: var(--font-mono);
}

.ad-foot {
  display: flex; gap: 14px; flex-wrap: wrap;
  font-size: 11px; color: var(--ink-500);
  padding-top: 10px; border-top: 1px dashed var(--border);
}

.ad-git {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-top: 12px; font-size: 11px;
}
.ad-git-label { color: var(--ink-500); }
.ad-git code {
  background: var(--surface-sunken); border: 1px solid var(--border);
  padding: 2px 7px; border-radius: var(--radius-sm); color: var(--ink-700);
}
.ad-sync-chip { padding: 2px 8px; border-radius: var(--radius-pill); font-size: 10.5px; font-weight: 600; }
.ad-sync-chip.staged { background: rgba(245, 158, 11, 0.14); color: var(--warn); }
.ad-sync-chip.pushed { background: rgba(16, 185, 129, 0.12); color: var(--ok); }
.ad-sync-chip.failed { background: rgba(239, 68, 68, 0.12); color: var(--err); }
.ad-git-link {
  font-size: 11px; color: var(--primary); text-decoration: none;
  border-bottom: 1px dashed currentColor;
}
.ad-git-link:hover { color: var(--ink-900); }

.ad-err {
  margin-top: 10px; padding: 10px 12px;
  background: rgba(239, 68, 68, 0.07);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: var(--radius-sm);
}
.ad-err-h { font-size: 12px; font-weight: 700; color: var(--err); margin-bottom: 5px; }
.ad-err pre { margin: 0; font-size: 11px; color: var(--ink-700); white-space: pre-wrap; word-break: break-word; }
.ad-err-hint { margin: 6px 0 0; font-size: 11px; color: var(--ink-500); }

/* ===== 安装卡 (吸顶: 下载 + 装到哪, 永远在眼前) ===== */
.ad-install {
  position: sticky; top: 0; z-index: 5;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-card); padding: 11px 13px; margin-bottom: 12px;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.02);
}
.ins-h { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.ins-t { font-size: 12.5px; font-weight: 700; color: var(--ink-900); }
.ins-file {
  font-family: var(--font-mono); font-size: 11px; color: var(--ink-500);
  margin-left: auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ins-btn { width: 100%; }
.ins-dir {
  display: flex; align-items: baseline; gap: 6px; margin-top: 9px;
  font-size: 11.5px; color: var(--ink-600);
}
.ins-dir-l { flex-shrink: 0; }
.ins-dir code {
  font-family: var(--font-mono); font-size: 11px; color: var(--ink-800);
  background: var(--surface-sunken); padding: 2px 6px; border-radius: 4px;
  word-break: break-all;
}
.ins-tip { margin: 7px 0 0; font-size: 11px; color: var(--ink-500); line-height: 1.6; }
.ins-tip code { font-family: var(--font-mono); font-size: 10.5px; }
/* 手动安装目录 (折叠) —— 主提示是通用话术, 这里是给要手动装的人看的参考 */
.ins-more { margin-top: 7px; }
.ins-more > summary {
  font-size: 11px; color: var(--ink-500); cursor: pointer;
  list-style: none; user-select: none;
}
.ins-more > summary::-webkit-details-marker { display: none; }
.ins-more > summary::before { content: '▸ '; }
.ins-more[open] > summary::before { content: '▾ '; }
.ins-more > summary:hover { color: var(--ink-700); }
.ins-more .ins-dir { margin-top: 6px; }

/* ===== 技术信息 (折叠) ===== */
.ad-tech { margin: 4px 0 8px; }
.tech-toggle {
  display: flex; align-items: center; gap: 8px; width: 100%;
  background: none; border: 0; padding: 7px 0; cursor: pointer;
  font-family: inherit; font-size: 12px; color: var(--ink-600);
}
.tech-toggle:hover { color: var(--ink-900); }
.tech-caret { margin-left: auto; color: var(--ink-500); font-size: 11px; }
.tech-body { padding: 2px 0 8px; }
.tech-line {
  display: flex; gap: 14px; font-size: 11.5px; color: var(--ink-600); margin-bottom: 7px;
}

.ad-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ad-btn { flex: 1; min-width: 120px; }
.ad-btn.danger { color: var(--err); border-color: rgba(239, 68, 68, 0.4); }
.ad-btn.danger:hover { border-color: var(--err); background: rgba(239, 68, 68, 0.08); color: var(--err); }
.ad-upd { font-size: 11px; color: var(--warn); font-weight: 600; }

.ad-proto-note {
  margin-top: 12px; font-size: 11px; color: var(--ink-500);
  background: var(--surface-sunken); padding: 8px 10px; border-radius: var(--radius-sm);
}
</style>
