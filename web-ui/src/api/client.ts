import axios from 'axios';

const API_BASE = 'http://localhost:8000';

export const apiClient = axios.create({ baseURL: API_BASE });

apiClient.interceptors.request.use((config) => {
  const apiKey = localStorage.getItem('agent_platform_api_key');
  if (apiKey) config.headers['X-API-Key'] = apiKey;
  return config;
});

apiClient.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      window.location.href = '/settings';
    }
    return Promise.reject(error);
  }
);
