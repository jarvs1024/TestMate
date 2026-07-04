<template>
  <div class="tm-preview">
    <div class="head">
      <div class="lights">
        <span class="r"></span>
        <span class="y"></span>
        <span class="g"></span>
      </div>
      <div class="url">
        <span class="url-text">{{ title }}</span>
        <span v-if="subtitle" class="url-sub">— {{ subtitle }}</span>
      </div>
      <div class="actions">
        <slot name="actions" />
      </div>
    </div>
    <div class="body">
      <slot />
    </div>
    <div v-if="$slots.footer" class="foot">
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>();
</script>

<style scoped>
.tm-preview {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-md);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: var(--surface-sunken);
  border-bottom: 1px solid var(--border);
}
.lights { display: flex; gap: 6px; }
.lights span {
  width: 11px; height: 11px; border-radius: 50%;
  display: inline-block;
}
.lights .r { background: #ff5f57; }
.lights .y { background: #febc2e; }
.lights .g { background: #28c840; }

.url {
  flex: 1;
  text-align: center;
  font-size: 12.5px;
  color: var(--ink-700);
  font-family: var(--font-mono);
  letter-spacing: 0.2px;
}
.url-text { font-weight: 600; }
.url-sub { color: var(--ink-500); margin-left: 4px; }

.actions { display: flex; gap: 4px; }

.body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.foot {
  border-top: 1px solid var(--border);
  background: var(--surface-sunken);
  padding: 10px 14px;
  font-size: 12.5px;
  color: var(--ink-500);
}
</style>
