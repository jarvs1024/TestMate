import axios, { InternalAxiosRequestConfig } from 'axios';
import { ElMessage } from 'element-plus';
import { useUserStore } from '@/stores/user';

// 公共只读路由 (publicRead) 的 anonymous JWT.
// 后端 get_optional_user 接受任意有效 JWT; sub=0 查不到 user → 返回 anonymous 占位 User.
// 重新生成: 在 backend 容器里
//   python -c "from app.core.security import create_access_token; print(create_access_token('0', {'role':'anonymous','username':'anonymous'})[0])"
const ANONYMOUS_TOKEN = import.meta.env.VITE_ANONYMOUS_READ_TOKEN as string | undefined;

/**
 * 当前路由是不是公共只读 (匿名访问, 用 ANONYMOUS_TOKEN 调 API).
 *
 * 2026-10-25: 首页能力墙也开放匿名只读 —— 首页要能看见"平台上有什么",
 * 进详情页才要登录. 代码检视看板维持匿名可看.
 *
 * ⚠️ 这里用**路径前缀**判断, 不用 router meta ——
 *    axios 拦截器不能 import router (会跟路由懒加载形成循环依赖).
 */
function isPublicReadRoute(): boolean {
  const p = window.location.pathname;
  return (
    p === '/' ||
    p === '/plaza' ||
    p.startsWith('/plaza/') ||
    p.startsWith('/code-review')
  );
}

/**
 * axios 配置扩展: `silent: true` = 失败不弹全局错误提示.
 *
 * 用于**调用方自己会兜底降级**的请求 (首页给卡片取指标数字:
 * RAGFlow 没配 / ReviewAgent 没起 时失败是常态, 卡片该显示降级文案,
 * 而不是弹一个"环境故障"的红条).
 */
declare module 'axios' {
  export interface AxiosRequestConfig {
    silent?: boolean;
  }
}

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
});

request.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const userStore = useUserStore();
  // publicRead 路由 (代码检视): 登录用 user token (保留登录态体验: ack 按钮等);
  //  未登录用 ANONYMOUS_TOKEN (后端 get_optional_user 解码 sub=0 → anonymous user, 仍能调 review-agent/pr-agent GET)
  if (isPublicReadRoute()) {
    if (userStore.token) {
      config.headers.Authorization = `Bearer ${userStore.token}`;
    } else if (ANONYMOUS_TOKEN) {
      config.headers.Authorization = `Bearer ${ANONYMOUS_TOKEN}`;
    }
    return config;
  }
  if (userStore.token) {
    config.headers.Authorization = `Bearer ${userStore.token}`;
  }
  return config;
});

request.interceptors.response.use(
  (resp) => resp.data,
  (err) => {
    const status = err.response?.status;
    // publicRead 路由的 401 不能踢去 /login (匿名访问本来就没登录, 401 是后端配置问题, 不是用户问题)
    if (status === 401 && !isPublicReadRoute()) {
      const userStore = useUserStore();
      userStore.logout();
      window.location.href = '/login';
    } else if (status !== 401 && !err.config?.silent) {
      // ⚠️ silent: 调用方自己会兜底降级的请求 (比如首页给卡片取指标数字),
      //    失败时**不要**弹全局错误 —— 否则首页一进来就弹一个"ragflow error",
      //    卡片却好好地显示着降级文案, 像是出了故障.
      ElMessage.error(err.response?.data?.detail || err.message);
    }
    return Promise.reject(err);
  }
);

export default request;
