<template>
  <el-dialog v-model="visible" title="安装资产" width="560px"
             :close-on-click-modal="false" @open="load">
    <div v-if="loading" class="inst-loading">读取安装目标…</div>

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

      <div class="inst-h">选择安装方式</div>
      <div class="inst-channels">
        <label class="inst-chan" :class="{ disabled: !target.server_channel_available }">
          <input type="radio" value="server" v-model="channel"
                 :disabled="!target.server_channel_available" />
          <div class="inst-chan-body">
            <div class="inst-chan-t">装到服务器配置的目录</div>
            <div class="inst-chan-d mono">{{ target.target }}</div>
            <div v-if="!target.server_channel_available" class="inst-chan-warn">
              服务端安装通道已关闭
            </div>
          </div>
        </label>

        <label class="inst-chan" :class="{ disabled: !canFrontend }">
          <input type="radio" value="frontend" v-model="channel" :disabled="!canFrontend" />
          <div class="inst-chan-body">
            <div class="inst-chan-t">装到我的本机目录</div>
            <div class="inst-chan-d">
              {{ canFrontend ? '浏览器会弹出目录选择器, 由你指定安装位置'
                              : '当前浏览器不支持 File System Access API (仅 Chrome / Edge 可用)' }}
            </div>
          </div>
        </label>
      </div>

      <div v-if="channel === 'frontend'" class="inst-note">
        前端通道每次安装都需重新授权目录 —— 浏览器出于安全不会记住授权。
        本通道**不解压**, 直接写后端提供的明文文件。
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
        开始安装
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import {
  getAssetBundle, getInstallTarget, installAsset,
  type AssetItem, type InstallTarget,
} from '@/api/assets';
import {
  base64ToArrayBuffer, pickDirectory, supportsFileSystemAccess, writeFileInto,
} from '@/utils/fileSystemAccess';

const props = defineProps<{ modelValue: boolean; asset: AssetItem | null }>();
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'done'): void }>();

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
});

const target = ref<InstallTarget | null>(null);
const channel = ref<'server' | 'frontend'>('server');
const loading = ref(false);
const installing = ref(false);
const error = ref('');
const doneMsg = ref('');
const done = ref(false);

const canFrontend = computed(() => supportsFileSystemAccess());

/** 手抄命令: 给不能用 File System Access API 的浏览器 (非 Chromium) 一条退路 */
const installCmd = computed(() => {
  const t = target.value;
  if (!t) return '';
  const base = window.location.origin;
  const url = `${base}/api/v1/assets/${encodeURIComponent(t.code)}/versions/${encodeURIComponent(t.version)}/download`;
  const dir = t.kind === 'skill'
    ? `${t.skill_dir_host || '~/.qoder-cn/skills'}/${t.code}`
    : `${t.plugin_dir_host || '~/.qoder-cn/plugins/cache/qoder-marketplace'}/${t.code}/${t.version}`;
  return [
    `# 取包 (需要 TestMate token: POST /api/v1/auth/login 拿 access_token)`,
    `curl -fL -H "Authorization: Bearer $TOKEN" "${url}" -o ${t.code}-${t.version}.zip`,
    `mkdir -p "${dir}"`,
    `unzip -oq ${t.code}-${t.version}.zip -d "${dir}"`,
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
    channel.value = target.value.server_channel_available ? 'server' : 'frontend';
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '读取安装目标失败';
  } finally {
    loading.value = false;
  }
}

watch(() => props.asset?.code, () => { if (visible.value) load(); });

/** 在目录句柄里创建多级目录并写文件 */
async function writeFile(
  dir: any, relPath: string, data: BlobPart,
): Promise<void> {
  await writeFileInto(dir, relPath, data);
}

async function doInstall() {
  const a = props.asset;
  const t = target.value;
  if (!a || !t) return;
  installing.value = true;
  error.value = '';
  done.value = false;
  try {
    if (channel.value === 'server') {
      const r = await installAsset(a.code, t.version, { channel: 'server' });
      doneMsg.value = `已安装到 ${r.install_path || t.target}`;
    } else {
      if (!window.showDirectoryPicker) {
        throw new Error('当前浏览器不支持 File System Access API');
      }
      const dir = await pickDirectory();
      const bundle = await getAssetBundle(a.code);
      for (const f of bundle.files) {
        const data: BlobPart = f.encoding === 'base64'
          ? base64ToArrayBuffer(f.content)
          : f.content;
        await writeFile(dir, f.path, data);
      }
      const r = await installAsset(a.code, t.version, {
        channel: 'frontend',
        installPath: dir.name,
      });
      doneMsg.value = `已安装 ${bundle.total} 个文件到 ${dir.name}`;
      void r;
    }
    done.value = true;
    ElMessage.success('安装完成');
    emit('done');
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      error.value = '已取消';
    } else {
      error.value = e?.response?.data?.detail || e?.message || '安装失败';
    }
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

.inst-channels { display: flex; flex-direction: column; gap: 8px; }
.inst-chan {
  display: flex; gap: 9px; align-items: flex-start;
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 10px 12px; cursor: pointer; transition: all 0.15s ease;
}
.inst-chan:hover:not(.disabled) { border-color: var(--primary); }
.inst-chan.disabled { opacity: 0.55; cursor: not-allowed; }
.inst-chan input { margin-top: 3px; }
.inst-chan-t { font-size: 13px; font-weight: 600; color: var(--ink-900); }
.inst-chan-d { font-size: 11px; color: var(--ink-500); margin-top: 3px; word-break: break-all; }
.inst-chan-warn { font-size: 11px; color: var(--err); margin-top: 3px; }

.inst-note {
  margin-top: 10px; font-size: 11.5px; color: var(--ink-500);
  background: var(--surface-sunken); padding: 8px 10px; border-radius: var(--radius-sm);
}
.inst-err { margin-top: 12px; }
</style>
