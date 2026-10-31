<template>
  <!-- ⚠️ 2026-10-31 (第十五轮): 加上全局 `card` —— 白底/圆角/阴影跟首页能力墙一致.
       容器样式在 styles/main.css 的 .asset-card, 跟「插件·技能·连接」共用一份. -->
  <div class="card asset-card"
       role="button" :tabindex="0"
       @click="emit('open', item)"
       @keydown.enter="emit('open', item)"
       @keydown.space.prevent="emit('open', item)">
    <div class="ac-hd">
      <div class="ac-icon">{{ item.icon || '🧰' }}</div>
      <div class="ac-title">
        <!-- ⚠️ 名字在 CSS 里是 ellipsis 截断的 —— 补个 title, 鼠标悬停能看到全名 -->
        <div class="ac-name" :title="item.name">{{ item.name }}</div>
        <!-- ⚠️ 版本行同理: 分类名一长就被截掉, 悬停给全的 -->
        <div class="ac-ver" :title="verTitle">{{ item.version || '—' }}<template v-if="item.category"> · {{ item.category }}</template></div>
      </div>
      <!-- 状态是**每张卡片自己的属性** —— 不做成视图筛选 -->
      <div class="ac-badges">
        <!-- ⚠️ 可见文字走 platformLabel —— 以前直接显示 'windows',
             跟上传表单里的 'Windows' 两种写法 (后端存的仍是小写原值) -->
        <span v-if="item.platform" class="ac-badge plat"
              :title="`适用平台: ${platformLabel(item.platform)}`">{{ platformIcon(item.platform) }} {{ platformLabel(item.platform) }}</span>
        <span v-if="item.publish_status === 'awaiting_file'" class="ac-badge pending"
              title="信息填好了, 文件还没传完 —— 现在还不能下载">🕐 待传文件</span>
        <span v-else-if="item.publish_status === 'hidden'" class="ac-badge off"
              title="已被删除 (文件仍保留在服务器上)">⚠️ 已删除</span>
        <span v-else-if="!item.download_version" class="ac-badge failed"
              title="还没有可下载的文件">❌ 无文件</span>
      </div>
    </div>

    <p class="ac-summary">{{ item.summary || '（还没写简介）' }}</p>

    <!-- 功能清单 —— 软件库最该被看见的东西: 它能干什么 -->
    <ul v-if="item.features?.length" class="ac-features">
      <li v-for="(f, i) in item.features.slice(0, 3)" :key="i">{{ f }}</li>
      <li v-if="item.features.length > 3" class="more">还有 {{ item.features.length - 3 }} 项…</li>
    </ul>

    <div class="ac-tags">
      <span v-for="t in (item.tags || []).slice(0, 3)" :key="t" class="tag">#{{ t }}</span>
    </div>

    <!-- ⚠️ 2026-10-31 (第十五轮): 底部跟首页能力墙卡**同一个结构** (指标 + CTA 箭头) -->
    <div class="ac-foot">
      <div class="ac-meta">
        <span class="meta-item" :title="`已下载 ${item.download_count || 0} 次`">⬇ {{ item.download_count || 0 }}</span>
        <!-- ⚠️ 2026-10-31 (第十六轮): 作者**只显示用户名** (去掉 @twsc.com.cn) ——
             邮箱后缀每张卡都一样, 摊出来既占地方又吵. 全账号挂 title, 悬停还能看到. -->
        <span class="meta-item" :title="item.author || ''">{{ displayAuthor(item.author) || '未知' }}</span>
        <span class="meta-item">· {{ shortDate(item.updated_at) }}</span>
      </div>
      <div class="ac-cta">查看详情<span class="cta-arrow">›</span></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { SoftwareItem } from '@/api/software';
import { fmtDate } from '@/utils/format';
import { displayAuthor } from '@/utils/author';
import { platformLabel } from './softwareForm';

const props = defineProps<{ item: SoftwareItem }>();
const emit = defineEmits<{ (e: 'open', item: SoftwareItem): void }>();

/** 版本行的完整文字 —— 卡片上会被截断, 悬停时用 title 补全 */
const verTitle = computed(() =>
  [props.item.version || '—', props.item.category].filter(Boolean).join(' · '),
);

function shortDate(iso: string | null): string {
  // ⚠️ 以前是 `iso.slice(0, 10)` —— 直接截字符串, 显示的是 **UTC 那一天**,
  //    跟页面上其它按本地时区显示的时间对不上 (晚上更新的资产差一天).
  return fmtDate(iso);
}

function platformIcon(p: string): string {
  if (p === 'windows') return '🪟';
  if (p === 'linux') return '🐧';
  if (p === 'macos') return '🍎';
  return '💻';
}
</script>

<style scoped>
/* ⚠️ 卡片样式**跟「插件·技能·连接」共用同一套类名与视觉** (asset-card / ac-hd /
   ac-summary / ac-tags / ac-meta) —— 两个页面要看起来是一套东西, 不是两个系统.
   差异只在软件特有的字段 (平台 / 功能清单).
   ⚠️ 容器样式 (.asset-card) 在 2026-10-31 (第十五轮) 挪到 styles/main.css ——
   跟首页能力墙的白底卡片对齐 (圆角/阴影/悬停上浮/蓝色光环), 但尺寸更紧凑.
   以前这里是**抄的一份** —— 改一处忘另一处就会漂移 (已经发生过). */
.ac-hd { display: flex; align-items: flex-start; gap: 10px; }
.ac-icon {
  width: 34px; height: 34px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: flex; align-items: center; justify-content: center;
  font-size: 17px;
  flex-shrink: 0;
  box-shadow: var(--primary-shadow);
}
.ac-title { flex: 1; min-width: 0; }
.ac-name {
  font-size: 14px; font-weight: 700; color: var(--ink-900); line-height: 1.25;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ac-ver {
  font-size: 10.5px; color: var(--ink-500); margin-top: 2px;
  font-family: var(--font-mono);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.ac-badges {
  display: flex; align-items: center; gap: 5px; flex-wrap: wrap;
  justify-content: flex-end; flex-shrink: 0; max-width: 46%;
}
.ac-badge {
  display: inline-flex; align-items: center;
  padding: 3px 8px; border-radius: var(--radius-pill);
  font-size: 10.5px; font-weight: 600; white-space: nowrap;
}
.ac-badge.pending { background: rgba(245, 158, 11, 0.12); color: var(--warn); }
.ac-badge.failed { background: rgba(239, 68, 68, 0.12); color: var(--err); }
.ac-badge.off { background: rgba(107, 114, 128, 0.14); color: var(--ink-600, #6b7280); }
/* 平台: 中性蓝 —— 跟状态徽标(红/黄/灰)区分开 */
.ac-badge.plat { background: rgba(20, 184, 166, 0.14); color: var(--primary-2); }

.ac-summary {
  margin: 0;
  font-size: 12.5px;
  color: var(--ink-700);
  line-height: 1.55;
  flex: 1;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 功能清单 —— 一行一条, 超出就省略 */
.ac-features {
  margin: 0;
  padding-left: 16px;
  font-size: 11.5px;
  color: var(--ink-600, #6b7280);
  line-height: 1.6;
}
.ac-features li { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ac-features li.more { list-style: none; margin-left: -16px; color: var(--ink-500); font-size: 10.5px; }

.ac-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.tag {
  font-size: 10px;
  color: var(--ink-500);
  background: var(--surface-sunken);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
}

/* 底部: 指标 + CTA —— 跟首页能力墙卡 (.cc-foot) 同一个结构 */
.ac-foot {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
}
.ac-meta {
  display: flex; gap: 5px; flex-wrap: wrap;
  font-size: 10px;
  color: var(--ink-500);
  font-family: var(--font-mono);
  min-width: 0;
}
.ac-cta {
  font-size: 12px; font-weight: 600; color: var(--primary);
  white-space: nowrap; flex-shrink: 0;
  display: inline-flex; align-items: center; gap: 2px;
}
.cta-arrow { font-size: 14px; line-height: 1; }
.asset-card:hover .ac-cta { color: var(--primary-2); }
.meta-item { display: inline-flex; align-items: center; gap: 3px; }
</style>
