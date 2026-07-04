import { createApp } from 'vue';
import { createPinia } from 'pinia';
import ElementPlus from 'element-plus';
import 'element-plus/dist/index.css';
import App from './App.vue';
import router from './router';
import { useThemeStore } from './stores/theme';
import './styles/main.css';

const app = createApp(App);
const pinia = createPinia();
app.use(pinia);

// 必须在 router 注册前 init, 否则首屏会闪
useThemeStore().init();

app.use(router);
app.use(ElementPlus);
app.mount('#app');
