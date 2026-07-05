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
      <!-- T 字: 横线 y=10-12.5, 竖线 x=12-15, 总宽 ~8 (x=8-16) -->
      <path
        :d="`M8 10 L16 10 L16 12.5 L13.5 12.5 L13.5 28 L10.5 28 L10.5 12.5 L8 12.5 Z`"
        fill="#ffffff"
      />
      <!-- M 字: x=18-30, 简化版 -->
      <path
        :d="`M18 10 L21 10 L24.5 18 L28 10 L30 10 L30 28 L27.5 28 L27.5 15.5 L24.5 22.5 L23 22.5 L20.5 15.5 L20.5 28 L18 28 Z`"
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
