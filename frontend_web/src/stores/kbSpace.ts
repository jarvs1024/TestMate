/**
 * RAGFlow 用户空间 (一把 API key 一个租户空间) 的当前选择.
 *
 * ⚠️ 选择存在 localStorage —— 刷新页面后仍是同一个空间, 不然用户每次进来
 *    都要重新切一次 (概览/数据集默认显示的是默认空间).
 * ⚠️ 保存的 id 可能已失效 (空间被删/换环境) —— load() 时对不上就退回默认空间,
 *    而不是让所有 KB 请求 404.
 */
import { computed, ref } from 'vue';
import { defineStore } from 'pinia';
import { listKbSpaces, type KbSpace } from '@/api/kb';

export const KB_SPACE_STORAGE_KEY = 'testmate:kb-space';

export const useKbSpaceStore = defineStore('kbSpace', () => {
  const spaces = ref<KbSpace[]>([]);
  const currentId = ref(localStorage.getItem(KB_SPACE_STORAGE_KEY) || '');
  const loaded = ref(false);

  const currentName = computed(
    () => spaces.value.find((s) => s.id === currentId.value)?.name || '未配置空间',
  );
  //: 未指定空间的请求用最早建的空间 —— 后端 default_id 也是它
  const defaultId = computed(() => spaces.value[0]?.id || '');

  async function load() {
    const r = await listKbSpaces();
    spaces.value = r?.items || [];
    const ids = new Set(spaces.value.map((s) => s.id));
    if (!ids.has(currentId.value)) {
      currentId.value = r?.default_id || defaultId.value || spaces.value[0]?.id || '';
    }
    if (currentId.value) localStorage.setItem(KB_SPACE_STORAGE_KEY, currentId.value);
    else localStorage.removeItem(KB_SPACE_STORAGE_KEY);
    loaded.value = true;
  }

  function switchTo(id: string) {
    if (!spaces.value.some((s) => s.id === id)) return false;
    currentId.value = id;
    localStorage.setItem(KB_SPACE_STORAGE_KEY, id);
    return true;
  }

  return { spaces, currentId, currentName, defaultId, loaded, load, switchTo };
});
