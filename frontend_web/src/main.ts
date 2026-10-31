import { createApp } from 'vue';
import { createPinia } from 'pinia';
import ElementPlus from 'element-plus';
import 'element-plus/dist/index.css';
import App from './App.vue';
import router from './router';
import { useThemeStore } from './stores/theme';
import { loadPlatformInfo } from './stores/platform';
// 关键: 用 JS import, Vite 会把 tokens.css 内联进 bundle
// 之前用 CSS @import, Vite build 时不内联, 变量全失效
import './styles/tokens.css';
import './styles/main.css';

const app = createApp(App);
const pinia = createPinia();
app.use(pinia);

// 必须在 router 注册前 init, 否则首屏会闪
useThemeStore().init();

// ⚠️ 平台名称 / 副标题 / 版本号 —— 设置项驱动 (general.platform_*).
//    页头 / 登录页 / 标签页标题都要用, 所以在**启动时加载一次**,
//    别让每个组件各自去发一遍请求.
//    失败不阻塞启动 —— 各处有兜底默认值.
void loadPlatformInfo();

app.use(router);
app.use(ElementPlus);
app.mount('#app');
