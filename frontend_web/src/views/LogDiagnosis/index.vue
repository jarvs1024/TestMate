<template>
  <div class="bg-white rounded-2xl shadow-floating p-8 min-h-full">
    <h2 class="text-xl font-semibold m-0 mb-1">📊 PCIe / 串口 log 极速诊断</h2>
    <p class="text-sm text-slate-500 mb-6">
      上传 log → AI 提取 assert → 对比历史缺陷图谱 → 三段式根因结论(P0 demo)
    </p>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- 左:输入 -->
      <div class="space-y-4">
        <div>
          <label class="text-sm font-medium text-slate-700 block mb-2">环境变量(可选)</label>
          <el-input
            v-model="environment"
            type="textarea"
            :rows="3"
            placeholder='例:{"firmware": "v1.2.3", "nand": "Micron B47R"}'
          />
        </div>

        <div>
          <label class="text-sm font-medium text-slate-700 block mb-2">log 内容(必填)</label>
          <el-input
            v-model="logContent"
            type="textarea"
            :rows="14"
            placeholder="粘贴 PCIe trace / 串口 log / kernel log..."
            class="font-mono text-xs"
          />
        </div>

        <div class="flex gap-2">
          <el-button
            type="primary"
            size="default"
            :loading="diagnosing"
            :disabled="!logContent.trim()"
            @click="onDiagnose"
          >
            🚀 开始诊断
          </el-button>
          <el-button size="default" @click="onClear">清空</el-button>
          <el-button size="default" @click="onLoadSample">填入示例 log</el-button>
        </div>
      </div>

      <!-- 右:AI 输出 -->
      <div class="bg-slate-900 rounded-xl overflow-hidden flex flex-col">
        <div class="px-4 py-2 bg-slate-800 text-slate-300 text-xs flex items-center justify-between">
          <span>🤖 AI 诊断输出</span>
          <span v-if="diagnosing" class="text-emerald-400">● 流式中</span>
          <span v-else-if="result" class="text-slate-500">已完成</span>
        </div>
        <pre
          class="flex-1 p-4 text-emerald-300 font-mono text-xs overflow-auto m-0 leading-relaxed"
          style="min-height: 400px; white-space: pre-wrap; word-break: break-word;"
        >{{ result || '// 点击「开始诊断」,AI 结论会流式渲染到这里...' }}</pre>
        <div v-if="error" class="px-4 py-2 bg-rose-900 text-rose-200 text-xs">
          ❌ {{ error }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useUserStore } from '@/stores/user';

const userStore = useUserStore();
const environment = ref('{"firmware": "v1.2.3", "nand": "Micron B47R"}');
const logContent = ref('');
const diagnosing = ref(false);
const result = ref('');
const error = ref('');

const SAMPLE_LOG = `[  123.456] nvme nvme0: I/O 234 QID 4 timeout, completion polled
[  123.458] blk_update_request: I/O error, dev nvme0n1, sector 1234567
[  123.460] BUG: unable to handle kernel NULL pointer dereference at 0000000000000040
[  123.461] PGD 0 P4D 0
[  123.462] Oops: 0002 [#1] SMP NOPTI
[  123.463] CPU: 2 PID: 1234 Comm: fio Tainted: G           OE     5.15.0-test
[  123.464] Hardware name: QEMU Standard PC
[  123.465] RIP: 0010:nvme_irq+0x3a/0x120
[  123.466] Call Trace:
[  123.467]  <IRQ>
[  123.468]  __handle_irq_event_percpu+0x4f/0x180
[  123.469]  handle_irq_event+0x34/0x70
[  123.470]  handle_edge_irq+0x9e/0x230
[  123.471]  __common_interrupt+0x4a/0xd0
[  123.472]  </IRQ>
[  123.473] ---[ end trace 0xdeadbeef12345678 ]---`;

function onLoadSample() {
  logContent.value = SAMPLE_LOG;
}

function onClear() {
  logContent.value = '';
  result.value = '';
  error.value = '';
}

async function onDiagnose() {
  if (!logContent.value.trim()) return;
  diagnosing.value = true;
  result.value = '';
  error.value = '';

  let envObj: any = {};
  try {
    if (environment.value.trim()) envObj = JSON.parse(environment.value);
  } catch {
    error.value = '环境变量 JSON 格式错误,忽略';
  }

  try {
    const resp = await fetch('/api/v1/diagnose/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${userStore.token}`,
      },
      body: JSON.stringify({
        log_content: logContent.value,
        environment: envObj,
      }),
    });

    if (!resp.ok || !resp.body) {
      error.value = `请求失败:HTTP ${resp.status}`;
      diagnosing.value = false;
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6).trim();
        try {
          const obj = JSON.parse(payload);
          if (obj.type === 'error') {
            error.value = obj.content;
          } else if (obj.type === 'done') {
            // 完成
          } else {
            result.value += obj.content;
          }
        } catch {
          // 忽略非 JSON
        }
      }
    }
  } catch (e: any) {
    error.value = e.message || '请求出错';
  } finally {
    diagnosing.value = false;
  }
}
</script>
