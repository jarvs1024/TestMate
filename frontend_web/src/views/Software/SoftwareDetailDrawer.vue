<template>
  <el-drawer :model-value="modelValue" size="720px" direction="rtl"
             :title="item ? `软件详情 · ${item.name}` : '软件详情'"
             :close-on-click-modal="false" class="sw-drawer"
             @update:model-value="emit('update:modelValue', $event)">
    <div v-if="loading" class="state">正在读取…</div>
    <div v-else-if="!item" class="state">读不到这个软件的详情</div>

    <div v-else class="sw-body">
      <!-- ===== 头部: 图标 / 名称 / 版本 / 状态 ===== -->
      <div class="sw-hd">
        <div class="sw-icon">{{ item.icon || '🧰' }}</div>
        <div class="sw-hd-main">
          <div class="sw-name">{{ item.name }}</div>
          <div class="sw-sub mono">
            {{ item.version || '—' }}
            <template v-if="item.category"> · {{ item.category }}</template>
            <template v-if="item.platform"> · {{ item.platform }}</template>
          </div>
        </div>
        <div class="sw-hd-actions">
          <button class="mini-btn primary" :disabled="!item.download_version"
                  @click="doDownload(item.download_version)">
            ⬇ 下载{{ item.download_version ? ` ${item.download_version}` : '' }}
          </button>
          <button v-if="item.can_edit" class="mini-btn" @click="emit('new-version', item)">
            ↑ 发新版本
          </button>
        </div>
      </div>

      <!-- ⚠️ 状态提示条 —— 「待传文件」「已删除」这类信息必须说出来, 别让人以为一切正常 -->
      <div v-if="item.publish_status === 'awaiting_file'" class="sw-note warn">
        🕐 这个软件的信息填好了, 但文件还没传完 —— 现在还不能下载.
      </div>
      <div v-else-if="item.publish_status === 'hidden'" class="sw-note warn">
        ⚠️ 这个软件已被删除 (文件仍保留在服务器上, 管理员可以彻底清理).
      </div>
      <div v-else-if="!item.download_version" class="sw-note warn">
        ❌ 还没有可下载的文件 —— 发一个新版本并把包传上来.
      </div>

      <!-- ===== 简介 ===== -->
      <p v-if="item.summary" class="sw-summary">{{ item.summary }}</p>

      <!-- ===== 功能清单 ===== -->
      <section v-if="item.features?.length" class="sw-sec">
        <div class="sec-h"><span class="sec-no">1</span>功能</div>
        <ul class="feature-list">
          <li v-for="(f, i) in item.features" :key="i">{{ f }}</li>
        </ul>
      </section>

      <!-- ===== 详情 ===== -->
      <section v-if="item.description" class="sw-sec">
        <div class="sec-h"><span class="sec-no">2</span>详情</div>
        <div class="pre-wrap">{{ item.description }}</div>
      </section>

      <!-- ===== 适用场景 ===== -->
      <section v-if="item.use_when || item.not_for" class="sw-sec">
        <div class="sec-h"><span class="sec-no">3</span>适用场景</div>
        <div v-if="item.use_when" class="use-block ok">
          <span class="ub-tag">适合</span>
          <span class="ub-text pre-wrap">{{ item.use_when }}</span>
        </div>
        <div v-if="item.not_for" class="use-block no">
          <span class="ub-tag">不适合</span>
          <span class="ub-text pre-wrap">{{ item.not_for }}</span>
        </div>
      </section>

      <!-- ===== 版本历史 ===== -->
      <section class="sw-sec">
        <div class="sec-h">
          <span class="sec-no">4</span>版本与更新说明
          <span class="sec-tip">{{ versions.length }} 个版本</span>
        </div>
        <div v-if="!versions.length" class="empty">还没有版本记录</div>
        <div v-for="v in versions" :key="v.id" class="ver-row" :class="v.status">
          <div class="vr-hd">
            <span class="vr-ver mono">{{ v.version }}</span>
            <span class="vr-status" :class="`vs-${v.status}`">{{ statusLabel(v.status) }}</span>
            <span class="vr-size mono">{{ formatSize(v.file_size) }}</span>
            <button v-if="v.status === 'ready'" class="mini-btn" @click="doDownload(v.version)">⬇ 下载</button>
          </div>
          <div class="vr-notes">{{ v.release_notes || '（这次没写更新说明）' }}</div>
          <div class="vr-meta mono">
            {{ v.author || '未知' }} · {{ shortDate(v.created_at) }}
            <template v-if="v.sha256"> · sha256 {{ v.sha256.slice(0, 12) }}…</template>
            <template v-if="v.download_count"> · 已下载 {{ v.download_count }} 次</template>
          </div>
          <!-- ⚠️ 上传失败要把原因说出来 (后端记的 last_error) -->
          <div v-if="v.status === 'failed'" class="vr-err">上传失败: {{ v.last_error || '未知原因' }}</div>
        </div>
      </section>

      <!-- ===== 标签 / 元信息 ===== -->
      <section v-if="item.tags?.length || item.keywords?.length" class="sw-sec">
        <div class="sec-h"><span class="sec-no">5</span>标签</div>
        <div class="ac-tags">
          <span v-for="t in item.tags" :key="t" class="tag">#{{ t }}</span>
          <span v-for="k in item.keywords" :key="'k' + k" class="tag kw">{{ k }}</span>
        </div>
      </section>

      <div class="sw-foot mono">
        上传者 {{ item.author || '未知' }} · 创建 {{ shortDate(item.created_at) }} ·
        更新 {{ shortDate(item.updated_at) }} · 已下载 {{ item.download_count || 0 }} 次
      </div>

      <!-- ===== 危险操作 ===== -->
      <div v-if="item.can_edit" class="sw-danger">
        <button class="mini-btn danger" @click="onDelete">删除这个软件</button>
        <button v-if="isAdmin" class="mini-btn danger" @click="onPurge">彻底清理 (删文件)</button>
        <span class="danger-tip">删除是软删 —— 文件还留在服务器上; 彻底清理才会连文件一起删.</span>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { downloadSoftware, deleteSoftware, purgeSoftware, getSoftware, type SoftwareDetail, type SoftwareVersion } from '@/api/software';
import { useUserStore } from '@/stores/user';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';
import { formatSize } from './softwareForm';

const props = defineProps<{ modelValue: boolean; code: string | null }>();
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void;
  (e: 'changed'): void;
  (e: 'new-version', item: SoftwareDetail): void;
}>();

const item = ref<SoftwareDetail | null>(null);
const versions = ref<SoftwareVersion[]>([]);
const loading = ref(false);

const userStore = useUserStore();
const isAdmin = computed(() => userStore.user?.role === 'admin');

function errText(e: unknown, fallback: string): string {
  return httpErrorText(errorStatus(e), errorDetail(e), fallback);
}

async function load() {
  if (!props.code) return;
  loading.value = true;
  try {
    const d = await getSoftware(props.code);
    item.value = d;
    versions.value = d.versions || [];
  } catch (e: any) {
    ElMessage.error(errText(e, '读取软件详情失败'));
  } finally {
    loading.value = false;
  }
}

watch(() => [props.modelValue, props.code], ([open]) => {
  if (open) load();
});

async function doDownload(version: string) {
  if (!item.value || !version) return;
  try {
    await downloadSoftware(item.value.code, version);
  } catch (e: any) {
    ElMessage.error(errText(e, '拿下载票据失败'));
  }
}

async function onDelete() {
  if (!item.value) return;
  try {
    await ElMessageBox.confirm(
      `确定删除「${item.value.name}」吗? (文件仍保留在服务器上, 管理员可以彻底清理)`,
      '删除软件',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    );
  } catch {
    return; // 用户取消
  }
  try {
    await deleteSoftware(item.value.code);
    ElMessage.success('已删除');
    emit('changed');
    emit('update:modelValue', false);
  } catch (e: any) {
    ElMessage.error(errText(e, '删除失败'));
  }
}

async function onPurge() {
  if (!item.value) return;
  try {
    await ElMessageBox.confirm(
      `彻底清理会**删掉服务器上的文件本体**, 不可恢复。确定清理「${item.value.name}」吗?`,
      '彻底清理',
      { type: 'error', confirmButtonText: '彻底清理', cancelButtonText: '取消' },
    );
  } catch {
    return;
  }
  try {
    const r = await purgeSoftware(item.value.code);
    ElMessage.success(`已彻底清理 (${r.deleted_files || 0} 个版本的文件)`);
    emit('changed');
    emit('update:modelValue', false);
  } catch (e: any) {
    ElMessage.error(errText(e, '彻底清理失败'));
  }
}

function shortDate(iso: string | null): string {
  if (!iso) return '—';
  return iso.slice(0, 10);
}

function statusLabel(s: string): string {
  if (s === 'ready') return '可下载';
  if (s === 'uploading') return '上传中';
  if (s === 'failed') return '上传失败';
  return '待传文件';
}
</script>

<style scoped>
.sw-body { display: flex; flex-direction: column; gap: 14px; }
.state { padding: 30px 0; text-align: center; color: var(--ink-500); font-size: 13px; }

.sw-hd { display: flex; gap: 12px; align-items: flex-start; }
.sw-icon {
  width: 42px; height: 42px; border-radius: 11px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: flex; align-items: center; justify-content: center;
  font-size: 21px; flex-shrink: 0; box-shadow: var(--primary-shadow);
}
.sw-hd-main { flex: 1; min-width: 0; }
.sw-name { font-size: 17px; font-weight: 700; color: var(--ink-900); line-height: 1.25; }
.sw-sub { font-size: 11.5px; color: var(--ink-500); margin-top: 3px; }
.sw-hd-actions { display: flex; gap: 7px; flex-shrink: 0; }

.sw-note {
  padding: 8px 11px; border-radius: var(--radius-sm); font-size: 12px;
  background: rgba(245, 158, 11, 0.10); color: var(--warn);
  border: 1px solid rgba(245, 158, 11, 0.25);
}

.sw-summary { margin: 0; font-size: 13px; color: var(--ink-700); line-height: 1.6; }

.sw-sec { display: flex; flex-direction: column; gap: 8px; }
.sec-h {
  display: flex; align-items: center; gap: 7px;
  font-size: 12px; font-weight: 700; color: var(--ink-900);
}
.sec-no {
  width: 17px; height: 17px; border-radius: 5px;
  background: var(--surface-sunken); color: var(--ink-600, #6b7280);
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700;
}
.sec-tip { font-size: 10.5px; color: var(--ink-500); font-weight: 400; margin-left: auto; }

.feature-list { margin: 0; padding-left: 18px; font-size: 12.5px; color: var(--ink-700); line-height: 1.75; }
.pre-wrap { white-space: pre-wrap; word-break: break-word; font-size: 12.5px; color: var(--ink-700); line-height: 1.65; }

.use-block { display: flex; gap: 8px; align-items: flex-start; font-size: 12.5px; }
.ub-tag {
  flex-shrink: 0; padding: 2px 7px; border-radius: var(--radius-pill);
  font-size: 10.5px; font-weight: 600;
}
.use-block.ok .ub-tag { background: rgba(16, 185, 129, 0.12); color: var(--ok); }
.use-block.no .ub-tag { background: rgba(239, 68, 68, 0.10); color: var(--err); }
.ub-text { color: var(--ink-700); line-height: 1.6; }

.ver-row {
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 9px 11px; display: flex; flex-direction: column; gap: 5px;
  background: var(--surface-soft);
}
.ver-row.vs-failed, .ver-row.failed { border-color: rgba(239, 68, 68, 0.35); }
.vr-hd { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.vr-ver { font-size: 12.5px; font-weight: 700; color: var(--ink-900); }
.vr-status { font-size: 10.5px; padding: 2px 7px; border-radius: var(--radius-pill); font-weight: 600; }
.vs-ready { background: rgba(16, 185, 129, 0.12); color: var(--ok); }
.vs-awaiting_file { background: rgba(245, 158, 11, 0.12); color: var(--warn); }
.vs-uploading { background: rgba(59, 130, 246, 0.12); color: var(--primary); }
.vs-failed { background: rgba(239, 68, 68, 0.10); color: var(--err); }
.vr-size { font-size: 10.5px; color: var(--ink-500); margin-left: auto; }
.vr-notes { font-size: 12.5px; color: var(--ink-700); line-height: 1.6; white-space: pre-wrap; }
.vr-meta { font-size: 10px; color: var(--ink-500); }
.vr-err { font-size: 11px; color: var(--err); }

.empty { font-size: 12px; color: var(--ink-500); }

.ac-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.tag {
  font-size: 10px; color: var(--ink-500); background: var(--surface-sunken);
  padding: 2px 6px; border-radius: var(--radius-sm); font-family: var(--font-mono);
}
.tag.kw { color: var(--primary-2); }

.sw-foot { font-size: 10.5px; color: var(--ink-500); border-top: 1px dashed var(--border); padding-top: 9px; }

.sw-danger {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding-top: 10px; border-top: 1px solid var(--border);
}
.danger-tip { font-size: 10.5px; color: var(--ink-500); }
</style>
