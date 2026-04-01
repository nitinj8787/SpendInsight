import axios from 'axios';

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
});

export const getTransactions = () => client.get('/transactions/');

export const getAnalytics = () => client.get('/analytics/');

export const uploadFile = (file) => {
  const formData = new FormData();
  formData.append('file', file);
  return client.post('/upload/', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};

export default client;
