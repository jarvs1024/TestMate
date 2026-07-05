<!--
  单条 setting 行: key + description + 编辑控件 + 保存/取消.
  控件类型由 item.value_type 决定: bool -> switch, secret -> password + eye, int -> number, 其它 -> text.
  v-model 走 drafts[item.key] (父组件维护); 父组件通过 @update 调用 setDraft.
-->
<template>
  <div class="row" :class="{ first: isFirst }">
    <div class="lbl-col">
      <div class="k">
        <code>{{ item.key }}</code>
        <span v-if="item.is_secret" class="secret-tag">secret</span>
        <span v-if="!item.is_default" class="custom-tag">已定制</span>
      </div>
      <div class="d">{{ item.description }}</div>
    </div>
    <div class="inp-col">
      <label v-if="item.value_type === 'bool'" class="switch">
        <input
          type="checkbox"
          :checked="!!draft"
          :disabled="!isAdmin"
          @change="$emit('update', item.key, ($event.target as HTMLInputElement).checked)"
        />
        <span class="sl"></span>
        <span class="stxt">{{ draft ? 'ON' : 'OFF' }}</span>
      </label>
      <div v-else-if="item.value_type === 'secret'" class="secret-wrap">
        <input
          :type="show ? 'text' : 'password'"
          :value="secretDisplay"
          :placeholder="item.is_default ? '(使用 .env 默认值)' : '已设置, 留空不改'"
          :disabled="!isAdmin"
          @input="$emit('update', item.key, ($event.target as HTMLInputElement).value)"
        />
        <button
          class="eye"
          type="button"
          @click="$emit('toggle-show', item.key)"
          :title="show ? '隐藏' : '显示'"
        >{{ show ? '🙈' : '👁' }}</button>
      </div>
      <input
        v-else
        :type="item.value_type === 'int' ? 'number' : 'text'"
        :value="draft"
        :placeholder="item.description"
        :disabled="!isAdmin"
        @input="$emit('update', item.key, ($event.target as HTMLInputElement).value)"
      />
    </div>
    <div class="act-col" v-if="isAdmin">
      <button
        class="primary"
        :disabled="!dirty || saving"
        @click="$emit('save', item)"
      >{{ saving ? '保存中…' : '保存' }}</button>
      <button v-if="dirty" class="ghost" @click="$emit('revert', item)">取消</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { SettingItem } from '@/api/settings';

defineProps<{
  item: SettingItem;
  isFirst: boolean;
  isAdmin: boolean;
  draft: any;
  dirty: boolean;
  show: boolean;        // 当前 secret 是否明文显示
  saving: boolean;      // 当前 key 是否在保存中
  secretDisplay: string; // secret 控件里的 display value (masked 后的)
}>();

defineEmits<{
  (e: 'update', key: string, v: any): void;
  (e: 'toggle-show', key: string): void;
  (e: 'save', item: SettingItem): void;
  (e: 'revert', item: SettingItem): void;
}>();
</script>

<style scoped>
/* === 跟父 Settings 拆出来: 这些类只用在 SettingRow 模板内部, 放父 scoped 会被 Vue scope 隔开 === */
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
  /* 加渐变下划线强调, 跟胶囊/按钮的渐变方向一致 */
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
  /* 清新版: 单层 focus ring */
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
  /* 单色柔和投影 + 上抬 */
  box-shadow: 0 3px 10px rgba(59, 130, 246, 0.25);
  transform: translateY(-1px);
}
.ghost {
  background: transparent; border: 1px solid var(--border);
  padding: 5px 12px; border-radius: 7px;
  color: var(--ink-700); font-size: 12px; cursor: pointer; font-family: inherit;
}
.ghost:hover { border-color: var(--primary); color: var(--primary); }
</style>

