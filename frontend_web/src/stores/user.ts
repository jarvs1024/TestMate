import { defineStore } from 'pinia';
import axios from 'axios';

export interface UserInfo {
  id: number;
  username: string;
  role: 'admin' | 'tester' | 'viewer';
}

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('testmate:token') || '',
    user: JSON.parse(localStorage.getItem('testmate:user') || 'null') as UserInfo | null,
  }),
  getters: {
    isLoggedIn: (state) => !!state.token,
    isAdmin: (state) => state.user?.role === 'admin',
  },
  actions: {
    async login(username: string, password: string) {
      const { data } = await axios.post('/api/v1/auth/login', { username, password });
      this.token = data.access_token;
      localStorage.setItem('testmate:token', this.token);
      // 拉 me
      const me = await axios.get('/api/v1/auth/me', {
        headers: { Authorization: `Bearer ${this.token}` },
      });
      this.user = me.data;
      localStorage.setItem('testmate:user', JSON.stringify(this.user));
    },
    logout() {
      this.token = '';
      this.user = null;
      localStorage.removeItem('testmate:token');
      localStorage.removeItem('testmate:user');
    },
  },
});
