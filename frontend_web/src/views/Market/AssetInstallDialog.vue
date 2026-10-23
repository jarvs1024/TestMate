<template>
  <el-dialog v-model="visible" title="安装资产" width="560px"
             :close-on-click-modal="false" @open="load">
    <div v-if="loading" class="inst-loading">读取安装信息…</div>

    <template v-else-if="target">
      <div class="inst-head">
        <span class="inst-icon">{{ asset?.icon }}</span>
        <div>
          <div class="inst-name">{{ asset?.name }}</div>
          <div class="inst-meta mono">{{ target.code }} · {{ target.version }}</div>
        </div>
      </div>

      <!-- 权限声明: 安装前必须让用户看清楚 -->
      <div v-if="permRows.length" class="inst-perm">
        <div class="inst-perm-h">⚠️ 该资产需要以下权限</div>
        <div v-for="r in permRows" :key="r.label" class="inst-perm-row">
          <span class="inst-perm-label">{{ r.label }}</span>
          <code v-for="v in r.values" :key="v" class="inst-perm-val">{{ v }}</code>
        </div>
      </div>
      <div v-else class="inst-perm none">该资产不读写文件、不联网、不执行外部命令。</div>

      <div v-if="asset?.install_steps?.length" class="inst-steps">
        <div class="inst-h">安装步骤</div>
        <ol><li v-for="(s, i) in asset.install_steps" :key="i">{{ s }}</li></ol>
      </div>

      <div class="inst-h">安装包</div>
      <div class="inst-pkg">
        <div class="inst-pkg-row">
          <span class="inst-pkg-label">文件</span>
          <code class="inst-pkg-val mono">{{ pkgName }}</code>
        </div>
        <div class="inst-pkg-row">
          <span class="inst-pkg-label">解压到</span>
          <code class="inst-pkg-val mono">{{ target.target }}/</code>
        </div>
      </div>

      <div class="inst-note">
        下载后自行解压到上面那个目录即可 —— 解压出来的文件会被 Qoder 直接识别。
        需要一条命令搞定? 点「复制安装命令」。
      </div>

      <el-alert v-if="error" type="error" :closable="false" class="inst-err"
                :title="error" show-icon />
      <el-alert v-if="done" type="success" :closable="false" class="inst-err"
                :title="doneMsg" show-icon />

      <!-- 装不上: 当场说清原因, 别让用户点了才知道 -->
      <el-alert v-if="target && !target.installable" type="warning" :closable="false"
                class="inst-err" :title="target.install_block_reason" show-icon />
    </template>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button :disabled="!installCmd" @click="copyCmd">复制安装命令</el-button>
      <el-button type="primary" :loading="installing"
                 :disabled="!target || !target.installable" @click="doInstall">
        下载安装包
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import {
  downloadAssetPackage, getInstallTarget, installAsset,
  type AssetItem, type InstallTarget,
} from '@/api/assets';
import { downloadBlob } from '@/utils/download';

const props = defineProps<{ modelValue: boolean; asset: AssetItem | null }>();
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'done'): void }>();

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
});

const target = ref<InstallTarget | null>(null);
const loading = ref(false);
const installing = ref(false);
const error = ref('');
const doneMsg = ref('');
const done = ref(false);

/** 下载下来的文件名 */
const pkgName = computed(() => {
  const t = target.value;
  return t ? `${t.code}-${t.version}.zip` : '';
});

/** 手抄命令: 不想点下载的人可以照着敲 */
const installCmd = computed(() => {
  const t = target.value;
  if (!t) return '';
  const base = window.location.origin;
  const url = `${base}/api/v1/assets/${encodeURIComponent(t.code)}/versions/${encodeURIComponent(t.version)}/download`;
  return [
    `# 取包 (需要 TestMate token: POST /api/v1/auth/login 拿 access_token)`,
    `curl -fL -H "Authorization: Bearer $TOKEN" "${url}" -o ${t.code}-${t.version}.zip`,
    `mkdir -p "${t.target}"`,
    `unzip -oq ${t.code}-${t.version}.zip -d "${t.target}"`,
  ].join('\n');
});

async function copyCmd() {
  const cmd = installCmd.value;
  if (!cmd) return;
  try {
    await navigator.clipboard.writeText(cmd);
    ElMessage.success('安装命令已复制');
  } catch {
    // 剪贴板不可用 (非安全上下文) —— 退回到选中文本
    ElMessage.warning('浏览器不允许写剪贴板, 请手动选中复制');
  }
}

const permRows = computed(() => {
  const p = props.asset?.permissions || {};
  return [
    { label: '读取文件', values: p.filesystem_read || [] },
    { label: '写入文件', values: p.filesystem_write || [] },
    { label: '访问网络', values: p.network || [] },
    { label: '执行命令', values: p.process_exec || [] },
    { label: '读取凭据', values: p.secrets || [] },
  ].filter((r) => r.values.length > 0);
});

async function load() {
  if (!props.asset) return;
  loading.value = true;
  error.value = '';
  done.value = false;
  doneMsg.value = '';
  try {
    target.value = await getInstallTarget(props.asset.code);
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '读取安装信息失败';
  } finally {
    loading.value = false;
  }
}

watch(() => props.asset?.code, () => { if (visible.value) load(); });

async function doInstall() {
  const a = props.asset;
  const t = target.value;
  if (!a || !t) return;
  installing.value = true;
  error.value = '';
  done.value = false;
  try {
    // 下载端点要带 token, 不能直接开链接 → 先取成 blob 再触发保存
    const blob = await downloadAssetPackage(a.code, t.version);
    downloadBlob(blob, `${a.code}-${t.version}.zip`);
    // 记一笔安装 —— 用户主动下载就是要装, 徽标要跟上
    await installAsset(a.code, t.version, { installPath: t.target });
    doneMsg.value = `已下载 ${a.code}-${t.version}.zip, 解压到 ${t.target}/ 即完成安装`;
    done.value = true;
    ElMessage.success('安装包已下载');
    emit('done');
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '下载失败';
  } finally {
    installing.value = false;
  }
}
</script>

<style scoped>
.inst-loading { padding: 30px 0; text-align: center; color: var(--ink-500); font-size: 13px; }
.inst-head { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.inst-icon {
  width: 38px; height: 38px; border-radius: 10px; font-size: 19px;
  background: var(--primary-grad-soft); display: flex; align-items: center; justify-content: center;
}
.inst-name { font-size: 15px; font-weight: 700; color: var(--ink-900); }
.inst-meta { font-size: 11px; color: var(--ink-500); margin-top: 2px; }

.inst-perm {
  background: rgba(245, 158, 11, 0.07);
  border: 1px solid rgba(245, 158, 11, 0.25);
  border-radius: var(--radius-card); padding: 10px 12px; margin-bottom: 14px;
}
.inst-perm.none {
  background: var(--surface-sunken); border-color: var(--border);
  color: var(--ink-500); font-size: 12px;
}
.inst-perm-h { font-size: 12px; font-weight: 700; color: var(--warn); margin-bottom: 7px; }
.inst-perm-row { display: flex; align-items: baseline; gap: 7px; flex-wrap: wrap; margin-bottom: 4px; }
.inst-perm-label { font-size: 11px; color: var(--ink-500); min-width: 52px; }
.inst-perm-val {
  font-family: var(--font-mono); font-size: 11px;
  background: var(--surface); border: 1px solid var(--border);
  padding: 1px 6px; border-radius: var(--radius-sm); color: var(--ink-700);
}

.inst-steps { margin-bottom: 14px; }
.inst-h { font-size: 12px; font-weight: 700; color: var(--ink-700); margin-bottom: 7px; }
.inst-steps ol { margin: 0; padding-left: 18px; }
.inst-steps li { font-size: 12px; color: var(--ink-700); line-height: 1.7; }

.inst-pkg {
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 10px 12px; background: var(--surface-sunken);
}
.inst-pkg-row { display: flex; align-items: baseline; gap: 8px; margin-bottom: 5px; }
.inst-pkg-row:last-child { margin-bottom: 0; }
.inst-pkg-label { font-size: 11px; color: var(--ink-500); min-width: 42px; }
.inst-pkg-val {
  font-size: 11.5px; color: var(--ink-700); background: var(--surface);
  border: 1px solid var(--border); padding: 1px 6px; border-radius: var(--radius-sm);
  word-break: break-all;
}

.inst-note {
  margin-top: 10px; font-size: 11.5px; color: var(--ink-500);
  background: var(--surface-sunken); padding: 8px 10px; border-radius: var(--radius-sm);
}
.inst-err { margin-top: 12px; }
</style>
