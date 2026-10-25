import { defineStore } from 'pinia';
import axios from 'axios';

export interface UserInfo {
  id: number;
  username: string;
  role: 'admin' | 'tester' | 'viewer';
}

/** localStorage 里的键名 —— 跟登录页 (views/Login/index.vue) 保持一致 */
const TOKEN_KEY = 'testmate:token';
const USER_KEY = 'testmate:user';
/** 登录页用它预填用户名 (值 = 用户名) */
const LAST_USERNAME_KEY = 'testmate:last-username';
/** 需要密码的账号名 (值 = 用户名) —— 登录页据此决定要不要展开密码框 */
const NEEDS_PASSWORD_KEY = 'testmate:needs-password';

/**
 * 读 localStorage 里存的用户信息.
 *
 * ⚠️ 必须包 try/catch —— 裸 JSON.parse 一旦遇到坏数据 (被别的脚本写坏 /
 *    手动改过 / 写了一半) 就直接抛, 而这段在 store 的 state 初始化里,
 *    抛了就是**整个应用白屏**, 连带登录页都打不开.
 *    解析失败按「未登录」处理, 并顺手把那个坏 key 删掉 (免得每次启动都重来一遍).
 */
function readStoredUser(): UserInfo | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as UserInfo | null;
  } catch {
    localStorage.removeItem(USER_KEY);
    return null;
  }
}

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: readStoredUser(),
  }),
  getters: {
    isLoggedIn: (state) => !!state.token,
    isAdmin: (state) => state.user?.role === 'admin',
  },
  actions: {
    /**
     * 登录.
     *
     * ⚠️ password 可以为空 —— 账号必须**管理员先建过**, 但建号时没设密码的
     *    账号是免密登录的 (设了密码的 / 管理员账号则必须给密码).
     *    空密码走后端就是免密那条路.
     */
    async login(username: string, password?: string) {
      try {
        const { data } = await axios.post('/api/v1/auth/login', {
          username,
          password: password ?? '',
        });
        const token: string = data.access_token;
        // ⚠️ 先把 /me 拿到手, 再落盘 token/user ——
        //    以前是"先写 token 再拉 me", /me 一失败就留下**半登录态**:
        //    token 已经是新账号的, 但 this.user 还是上一个账号的 →
        //    顶栏显示 A 的名字, 请求带 B 的 token, isAdmin 取的却是 A 的 role.
        const resp = await axios.get('/api/v1/auth/me', {
          headers: { Authorization: `Bearer ${token}` },
        });
        this.token = token;
        this.user = resp.data;
        localStorage.setItem(TOKEN_KEY, token);
        localStorage.setItem(USER_KEY, JSON.stringify(this.user));
      } catch (e) {
        // ⚠️ 失败时**只回滚会话**(token / user), 不动"记住用户名" ——
        //    记住用户名是给用户省打字用的, 密码打错一次就把它抹掉,
        //    等于废掉了这个功能. 真正登出 (logout) 时才清.
        this.clearSession();
        throw e;
      }
    },
    /**
     * 清会话 (token + user) —— 但**不动**"记住用户名"那两个 key.
     *
     * 登录失败回滚用这个; 真正的"退出登录"用 logout().
     */
    clearSession() {
      this.token = '';
      this.user = null;
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    },
    logout() {
      this.clearSession();
      // ⚠️ 登录页的这两个"记住"也必须一起清 ——
      //    否则共用机器上, 下一个人打开登录页时用户名已经预填、
      //    免密账号连密码框都不会展开, 直接回车就进了上一个同事的号.
      localStorage.removeItem(LAST_USERNAME_KEY);
      localStorage.removeItem(NEEDS_PASSWORD_KEY);
    },
  },
});
