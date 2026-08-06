import axios, { InternalAxiosRequestConfig } from 'axios';
import { ElMessage } from 'element-plus';
import { useUserStore } from '@/stores/user';

// 公共只读看板 (router meta.publicRead) 的 anonymous JWT.
// 后端 get_optional_user 接受任意有效 JWT; sub=0 查不到 user → 返回 anonymous 占位 User.
// 重新生成: 在 backend 容器里
//   python -c "from app.core.security import create_access_token; print(create_access_token('0', {'role':'anonymous','username':'anonymous'})[0])"
const ANONYMOUS_TOKEN = import.meta.env.VITE_ANONYMOUS_READ_TOKEN as string | undefined;

/** 当前路由是不是公共只读看板 (匿名访问, 用 ANONYMOUS_TOKEN 调 API) */
function isPublicReadRoute(): boolean {
  const m = window.location.pathname.match(/^\/code-review-v2/);
  return !!m;
}

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
});

request.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  // publicRead 路由优先用 anonymous token (用户可能也登录了, 但公共路由走匿名保证后端一定放行)
  if (isPublicReadRoute() && ANONYMOUS_TOKEN) {
    config.headers.Authorization = `Bearer ${ANONYMOUS_TOKEN}`;
    return config;
  }
  const userStore = useUserStore();
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
    } else if (status !== 401) {
      ElMessage.error(err.response?.data?.detail || err.message);
    }
    return Promise.reject(err);
  }
);

export default request;
