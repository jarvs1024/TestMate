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
          <div class="ad-meta mono">{{ item.kind }} · {{ item.version }} · {{ item.category }}</div>
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

      <!-- 下架提示: 本地还装着, 但远端已下架 -->
      <el-alert v-if="item.publish_status === 'unpublished'" type="warning"
                :closable="false" show-icon class="ad-alert"
                title="该资产已被下架" />

      <p class="ad-summary">{{ item.description || item.summary }}</p>

      <div class="ad-block">
        <div class="ad-block-h ok">✓ 适用场景</div>
        <div class="ad-block-b">{{ item.use_when || '—' }}</div>
      </div>
      <div class="ad-block">
        <div class="ad-block-h warn">✗ 不适用</div>
        <div class="ad-block-b">{{ item.not_for || '—' }}</div>
      </div>

      <!-- 文档正文: SKILL.md (skill) / README.md (plugin) -->
      <div class="ad-block">
        <div class="ad-block-h">
          📄 {{ doc?.filename || (item.kind === 'skill' ? 'SKILL.md' : 'README.md') }}
          <span v-if="docLoading" class="ad-loading">加载中…</span>
        </div>
        <div v-if="doc" class="ad-doc" v-html="docHtml" />
        <div v-else-if="docError" class="ad-doc-empty">{{ docError }}</div>
        <div v-else class="ad-doc-empty">暂无文档内容</div>
      </div>

      <!-- 权限声明 -->
      <div class="ad-block ad-perm" :class="{ 'is-empty': permRows.length === 0 }">
        <div class="ad-block-h perm">
          🔐 权限声明
          <span v-if="permRows.length" class="perm-count">{{ permRows.length }} 项</span>
          <span v-else class="perm-none">无</span>
        </div>
        <div v-if="permRows.length === 0" class="ad-block-b muted">
          该资产不读写本地文件、不发起网络请求、不执行外部命令。
        </div>
        <ul v-else class="perm-list">
          <li v-for="r in permRows" :key="r.label">
            <span class="perm-label">{{ r.label }}</span>
            <code v-for="v in r.values" :key="v" class="perm-val">{{ v }}</code>
          </li>
        </ul>
      </div>

      <div v-if="item.install_steps?.length" class="ad-block">
        <div class="ad-block-h">安装步骤</div>
        <ol class="steps">
          <li v-for="(s, i) in item.install_steps" :key="i">{{ s }}</li>
        </ol>
      </div>

      <div class="ad-tags">
        <span v-for="t in item.tags" :key="t" class="tag">#{{ t }}</span>
      </div>

      <div class="ad-foot mono">
        <span>作者 {{ item.author || '未知' }}</span>
        <span>更新 {{ (item.updated_at || '').slice(0, 10) || '—' }}</span>
        <span>安装 {{ item.install_count }}</span>
      </div>

      <div v-if="item.git_path" class="ad-git mono">
        <span class="ad-git-label">GitLab 存储</span>
        <code>{{ item.git_path }}</code>
        <code v-if="item.git_commit_sha">{{ item.git_commit_sha.slice(0, 12) }}</code>
        <a v-if="item.git_web_url" class="ad-git-link" :href="item.git_web_url"
           target="_blank" rel="noopener">↗ 在 GitLab 查看</a>
        <span class="ad-sync-chip" :class="item.sync_status">{{ syncLabel }}</span>
      </div>

      <div v-if="item.sync_status === 'failed' && item.last_error" class="ad-err">
        <div class="ad-err-h">同步到 GitLab 失败</div>
        <pre>{{ item.last_error }}</pre>
        <p class="ad-err-hint">资产仍在本机工作区, 修复后可重试同步。</p>
      </div>

      <div class="ad-actions">
        <!-- ===== 审核操作 (管理员) ===== -->
        <el-button v-if="isAdmin && item.publish_status === 'pending'"
                   type="primary" class="ad-btn" :loading="busy" @click="doReview('approve')">
          通过审核
        </el-button>
        <el-button v-if="isAdmin && item.publish_status === 'pending'"
                   type="warning" plain class="ad-btn" :loading="busy" @click="doReview('reject')">
          驳回
        </el-button>
        <!-- ===== 重新提交 (作者本人) ===== -->
        <el-button v-if="canSubmit && item.publish_status === 'rejected'"
                   type="primary" class="ad-btn" :loading="busy" @click="doSubmit">
          重新提交审核
        </el-button>

        <!-- 安装 = 下载安装包, 自己解压.
             不做「装到本地 / 重新安装 / 卸载」那一套 —— 服务器不该替用户管磁盘. -->
        <el-button
          v-if="item.kind !== 'mcp'"
          type="primary"
          class="ad-btn" :loading="busy" @click="doDownload"
        >下载</el-button>
        <el-button v-else disabled class="ad-btn">连接器不支持下载</el-button>
        <el-button v-if="canEdit" class="ad-btn" @click="emit('edit', item)">更新版本</el-button>
        <el-button v-if="canEdit" class="ad-btn" :type="unpub ? 'primary' : 'warning'"
                   plain @click="togglePublish">
          {{ unpub ? '重新上架' : '下架' }}
        </el-button>
        <el-button v-if="canEdit" class="ad-btn danger" @click="doDelete">
          彻底删除
        </el-button>
        <span v-if="item.updatable" class="ad-upd">已安装旧版本, 可更新</span>
      </div>

      <div class="ad-proto-note">
        资产真实存储在 GitLab 仓库; 上传与更新会生成新的 commit, 历史版本可在 git 中回溯。
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  deleteAsset, downloadAssetPackage, getAssetDoc, installAsset, publishAsset,
  reviewAsset, submitForReview,
  unpublishAsset,
  type AssetDoc, type AssetItem,
} from '@/api/assets';
import { useUserStore } from '@/stores/user';
import { renderMarkdown } from '@/utils/markdown';
import { downloadBlob } from '@/utils/download';

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

const unpub = computed(() => props.item?.publish_status === 'unpublished');

const userStore = useUserStore();
/** 审核人是管理员 */
const isAdmin = computed(() => userStore.user?.role === 'admin');
/** 能不能重新提交审核 —— 资产作者本人 (或管理员) */
const canSubmit = computed(() => {
  const a = props.item;
  if (!a) return false;
  if (isAdmin.value) return true;
  return (a.author || '').trim().toLowerCase()
    === (userStore.user?.username || '').trim().toLowerCase();
});

const docHtml = computed(() => renderMarkdown(doc.value?.content || ''));

const syncLabel = computed(() => {
  switch (props.item?.sync_status) {
    case 'staged': return '🕐 待同步';
    case 'pushed': return '✓ 已同步到 GitLab';
    case 'failed': return '❌ 同步失败';
    default: return '—';
  }
});

const permRows = computed(() => {
  const p = props.item?.permissions || {};
  return [
    { label: '读取文件', values: p.filesystem_read || [] },
    { label: '写入文件', values: p.filesystem_write || [] },
    { label: '访问网络', values: p.network || [] },
    { label: '执行命令', values: p.process_exec || [] },
    { label: '读取凭据', values: p.secrets || [] },
  ].filter((r) => r.values.length > 0);
});

async function loadDoc(code: string) {
  docLoading.value = true;
  docError.value = '';
  doc.value = null;
  try {
    doc.value = await getAssetDoc(code);
  } catch (e: any) {
    docError.value = e?.response?.data?.detail || e?.message || '文档读取失败';
  } finally {
    docLoading.value = false;
  }
}

watch(() => props.item?.code, (c) => {
  if (c && props.modelValue) loadDoc(c);
}, { immediate: true });

watch(() => props.modelValue, (open) => {
  if (open && props.item?.code) loadDoc(props.item.code);
});

/** 建议的解压目录 (Qoder 标准布局, ~ 表示家目录) */
const targetDir = computed(() => {
  const it = props.item;
  if (!it) return '';
  return it.kind === 'skill'
    ? `~/.qoder-cn/skills/${it.code}`
    : `~/.qoder-cn/plugins/cache/qoder-marketplace/${it.code}/${it.version}`;
});

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
    // 记一笔 —— 卡片上的「安装 N」靠它
    await installAsset(it.code, it.version);
    ElMessage.success(
      `已下载 ${it.code}-${it.version}.zip, 解压到 ${targetDir.value}/ 即完成安装`,
    );
    emit('changed');
  } catch (e: any) {
    ElMessage.error('下载失败: ' + (e?.response?.data?.detail || e?.message));
  } finally {
    busy.value = false;
  }
}

async function togglePublish() {
  if (!props.item) return;
  const code = props.item.code;
  const name = props.item.name;
  if (!unpub.value) {
    try {
      await ElMessageBox.confirm(
        `下架 ${name}? 下架后其他人的列表里将不再显示, 但已安装的用户会看到"已下架"提示。`,
        '下架资产', { type: 'warning', confirmButtonText: '下架', cancelButtonText: '取消' },
      );
    } catch {
      return;
    }
  }
  busy.value = true;
  try {
    if (unpub.value) {
      await publishAsset(code);
      ElMessage.success('已重新上架');
    } else {
      await unpublishAsset(code);
      ElMessage.success('已下架');
    }
    emit('changed');
  } catch (e: any) {
    ElMessage.error('操作失败: ' + (e?.response?.data?.detail || e?.message));
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
    ElMessage.error('审核失败: ' + (e?.response?.data?.detail || e?.message));
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
    ElMessage.error('提交失败: ' + (e?.response?.data?.detail || e?.message));
  } finally {
    busy.value = false;
  }
}

/** 彻底删除 —— 不可恢复, 要求手打 code 确认 */
async function doDelete() {
  if (!props.item) return;
  const code = props.item.code;
  const name = props.item.name;
  try {
    await ElMessageBox.prompt(
      `删除「${name}」不可恢复: GitLab 上的文件、索引与安装记录都会一并消失。\n`
      + `已安装的用户本机文件不会被清理。\n请输入资产 code「${code}」以确认。`,
      '彻底删除资产',
      {
        type: 'error',
        confirmButtonText: '确认删除',
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
    const r = await deleteAsset(code, '用户从市场页删除');
    ElMessage.success(
      `已删除${r.removed_installs ? `, 清理 ${r.removed_installs} 条安装记录` : ''}`,
    );
    emit('update:modelValue', false);
    emit('deleted');
    emit('changed');
  } catch (e: any) {
    ElMessage.error('删除失败: ' + (e?.response?.data?.detail || e?.message));
  } finally {
    busy.value = false;
  }
}
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

.ad-actions { display: flex; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
.ad-btn { flex: 1; min-width: 120px; }
.ad-btn.danger { color: var(--err); border-color: rgba(239, 68, 68, 0.4); }
.ad-btn.danger:hover { border-color: var(--err); background: rgba(239, 68, 68, 0.08); color: var(--err); }
.ad-upd { font-size: 11px; color: var(--warn); font-weight: 600; }

.ad-proto-note {
  margin-top: 12px; font-size: 11px; color: var(--ink-500);
  background: var(--surface-sunken); padding: 8px 10px; border-radius: var(--radius-sm);
}
</style>
