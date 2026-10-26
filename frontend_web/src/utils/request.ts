import axios, { InternalAxiosRequestConfig } from 'axios';
import { ElMessage } from 'element-plus';
import { useUserStore } from '@/stores/user';
import { httpErrorText } from '@/utils/httpError';

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
  // ⚠️ 这里只列**真实存在**的 publicRead 路径 —— '/plaza' 现在只是路由表里的 redirect,
  //    URL 不会停留在 /plaza, 留着那个判断等于永远命中不了的死代码.
  return (
    p === '/' ||
    p.startsWith('/code-review')
  );
}

/**
 * 这个请求带的是**用户自己的 token** 吗?
 *
 * ⚠️ publicRead 路由 (首页 / 代码检视) 匿名访问时带的是 ANONYMOUS_TOKEN ——
 *    那种 401 是后端/环境配置问题 (用户压根没登录), 不能把人踢去登录页.
 *    只有"带着用户 token 还 401"才说明用户的 token 过期/失效 → 该清会话.
 */
function hasUserToken(config: any): boolean {
  const headers = config?.headers;
  if (!headers) return false;
  const raw = typeof headers.get === 'function'
    ? headers.get('Authorization')
    : (headers.Authorization ?? headers.authorization);
  if (typeof raw !== 'string' || !raw) return false;
  const bearer = raw.startsWith('Bearer ') ? raw.slice(7).trim() : raw.trim();
  if (!bearer) return false;
  return bearer !== ANONYMOUS_TOKEN;
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
    // ⚠️ 401 = 登录态失效.
    //    · 非 publicRead 路由: 一律清会话 + 跳登录 (老行为).
    //    · publicRead 路由 (首页 / 代码检视): **只有带着用户 token** 才处理 ——
    //      匿名访问 (带 ANONYMOUS_TOKEN) 的 401 是后端配置问题, 跟用户无关.
    //      以前这里对 publicRead 一律放行 → token 过期后用户停在首页,
    //      首页的鉴权请求 401 被静默 catch, 页面仍显示"已登录",
    //      待办静默消失, 用户以为"今天没待办".
    if (status === 401 && (!isPublicReadRoute() || hasUserToken(err.config))) {
      const userStore = useUserStore();
      userStore.logout();
      window.location.href = '/login';
    } else if (status !== 401 && !err.config?.silent) {
      // ⚠️ silent: 调用方自己会兜底降级的请求 (比如首页给卡片取指标数字),
      //    失败时**不要**弹全局错误 —— 否则首页一进来就弹一个"ragflow error",
      //    卡片却好好地显示着降级文案, 像是出了故障.
      // ⚠️ 502/503 这类必须翻成人话 —— 原始报文是 "Request failed with status code 502",
      //    用户完全看不出"页面能开但后端没跑"这个关键信息.
      ElMessage.error(httpErrorText(status, err.response?.data?.detail));
    }
    return Promise.reject(err);
  }
);

export default request;
