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
/* 跟父页面 .row 样式保持一致, 抽到全局; 这里不重复 */
</style>
