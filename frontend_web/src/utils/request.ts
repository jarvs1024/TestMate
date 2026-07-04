import axios from 'axios';
import { ElMessage } from 'element-plus';
import { useUserStore } from '@/stores/user';

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
});

request.interceptors.request.use((config) => {
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
    if (status === 401) {
      const userStore = useUserStore();
      userStore.logout();
      window.location.href = '/login';
    } else {
      ElMessage.error(err.response?.data?.detail || err.message);
    }
    return Promise.reject(err);
  }
);

export default request;
