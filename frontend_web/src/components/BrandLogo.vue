<template>
  <div class="brand-logo" :style="`--size:${size}px`" aria-label="TestMate">
    <svg :viewBox="`0 0 ${VB} ${VB}`" :width="size" :height="size" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <linearGradient :id="`lg-bg-${uid}`" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#3B82F6"/>
          <stop offset="100%" stop-color="#0d9488"/>
        </linearGradient>
      </defs>
      <rect x="0" y="0" :width="VB" :height="VB" rx="10" :fill="`url(#lg-bg-${uid})`"/>
      <!-- M 字母路径 (viewBox 38 内, 缩放使用) -->
      <path
        :d="`M9.5 28 L9.5 10 L14 10 L19 19.5 L24 10 L28.5 10 L28.5 28 L24 28 L24 17 L20 24.5 L18 24.5 L14 17 L14 28 Z`"
        fill="#ffffff"
      />
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
const { size = 38 } = defineProps<{ size?: number }>();
const VB = 38;
const uid = computed(() => Math.random().toString(36).slice(2, 8));
</script>

<style scoped>
.brand-logo {
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 6px 16px rgba(59, 130, 246, 0.25);
}
</style>
