import axios from 'axios';
import { getAuthToken, removeAuthToken, removeUser } from '../utils/auth';
import { apiLogger } from '../utils/logger';

// Base API configuration
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

// Configured axios instance - Cache cleared 2025-09-20
const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000, // 120 seconds for chat (API rate limits)
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor to add JWT token
api.interceptors.request.use(
  (config) => {
    const token = getAuthToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Interceptor to handle authentication errors and logging
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Automatic logging of all API errors
    if (error.response) {
      // Error with server response
      apiLogger.error(`API Error: ${error.config.method?.toUpperCase()} ${error.config.url}`, error, {
        status: error.response.status,
        statusText: error.response.statusText,
        data: error.response.data,
        url: error.config.url,
        method: error.config.method
      });
    } else if (error.request) {
      // Network error (no response)
      apiLogger.error(`Network Error: ${error.config.method?.toUpperCase()} ${error.config.url}`, error, {
        message: error.message,
        code: error.code,
        url: error.config.url,
        method: error.config.method
      });
    } else {
      // Configuration error
      apiLogger.error('Request Configuration Error', error, {
        message: error.message
      });
    }

    // Authentication-specific handling
    if (error.response?.status === 401) {
      // Expired or invalid token
      removeAuthToken();
      removeUser();
      window.location.href = '/admin/login';
    }
    
    return Promise.reject(error);
  }
);

// Chat API service
export const chatAPI = {
  sendMessageStream: (question, sessionId = null, callbacks = {}) => {
    return new Promise((resolve, reject) => {
      const url = `${API_BASE_URL}/chat/stream`;
      const token = getAuthToken();

      const fetchStream = async () => {
        try {
          const response = await fetch(url, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { 'Authorization': `Bearer ${token}` } : {})
            },
            body: JSON.stringify({
              question,
              session_id: sessionId
            })
          });

          if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
          }

          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          let settled = false;

          for (;;) {
            const { done, value } = await reader.read();

            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
              if (line.startsWith('data: ')) {
                const jsonStr = line.slice(6);

                try {
                  const event = JSON.parse(jsonStr);

                  switch (event.type) {
                    case 'start':
                      callbacks.onStart?.(event.session_id);
                      break;

                    case 'chunk':
                      callbacks.onChunk?.(event.content);
                      break;

                    case 'citation':
                      callbacks.onCitation?.(event.citations);
                      break;

                    case 'done':
                      callbacks.onDone?.(event);
                      settled = true;
                      resolve(event);
                      break;

                    case 'error':
                      callbacks.onError?.(event.message);
                      settled = true;
                      reject(new Error(event.message));
                      break;
                  }
                } catch (parseError) {
                  console.error('Failed to parse SSE event:', jsonStr, parseError);
                }
              }
            }
          }

          // Stream ended without a terminal done/error event (e.g. a mid-stream
          // backend disconnect). Settle the Promise so the chat UI does not stay
          // stuck in its loading state forever.
          if (!settled) {
            const err = new Error('Stream closed before completion');
            callbacks.onError?.(err.message);
            reject(err);
          }
        } catch (error) {
          callbacks.onError?.(error.message);
          reject(error);
        }
      };

      fetchStream();
    });
  },

  escalateToHuman: async (sessionId, userEmail, message, chatHistory) => {
    const response = await api.post('/chat/escalate', {
      session_id: sessionId,
      user_email: userEmail,
      question: message,
      chat_history: chatHistory,
    });
    return response.data;
  },
};

// Authentication API service
export const authAPI = {
  login: async (username, password) => {
    const response = await api.post('/auth/login', {
      username,
      password,
    });
    return response.data;
  },

  logout: async () => {
    const response = await api.post('/auth/logout');
    return response.data;
  },

  refreshToken: async () => {
    const response = await api.post('/auth/refresh');
    return response.data;
  },

  getCurrentUser: async () => {
    const response = await api.get('/auth/me');
    return response.data;
  },

  changePassword: async (currentPassword, newPassword) => {
    const response = await api.post('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    });
    return response.data;
  },
};

// Documents API service
export const documentsAPI = {
  getDocuments: async (page = 1, limit = 10, status = null, search = null) => {
    const offset = (page - 1) * limit; // Convert page to offset
    const params = new URLSearchParams({
      offset: offset.toString(),
      limit: limit.toString(),
    });
    if (status) params.append('status_filter', status);
    if (search) params.append('search', search);

    const response = await api.get(`/documents/?${params}`);
    return response.data;
  },

  getDocument: async (documentId) => {
    const response = await api.get(`/documents/${documentId}`);
    return response.data;
  },

  getDocumentWithChunks: async (documentId) => {
    const response = await api.get(`/documents/${documentId}/full`);
    return response.data;
  },

  downloadDocument: async (documentId) => {
    const response = await api.get(`/documents/${documentId}/download`, {
      responseType: 'blob', // Required for file downloads
    });
    return response;
  },

  getDocumentUrl: (documentId) => {
    // Returns direct URL to open in browser
    return `${API_BASE_URL}/documents/${documentId}/download`;
  },

  uploadDocument: async (file, preserve = false) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('preserve', preserve.toString());

    const response = await api.post('/documents/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      timeout: 120000, // 2 minutes for upload
    });
    return response.data;
  },

  deleteDocument: async (documentId, force = false) => {
    const response = await api.delete(`/documents/${documentId}`, {
      params: { force },
    });
    return response.data;
  },

  togglePreservation: async (documentId, preserve) => {
    const response = await api.patch(`/documents/${documentId}/preserve?preserve=${preserve}`);
    return response.data;
  },

  reprocessDocument: async (documentId) => {
    const response = await api.post(`/documents/${documentId}/reprocess`);
    return response.data;
  },

  getStatistics: async () => {
    const response = await api.get('/documents/stats/overview');
    return response.data;
  },
};

// Administration API service
export const adminAPI = {
  getSystemInfo: async () => {
    const response = await api.get('/admin/system-info');
    return response.data;
  },

  getConfiguration: async () => {
    const response = await api.get('/admin/config');
    return response.data;
  },

  updateConfiguration: async (configUpdates) => {
    const response = await api.put('/admin/config', configUpdates);
    return response.data;
  },

  getCacheStats: async () => {
    const response = await api.get('/admin/cache/stats');
    return response.data;
  },

  clearCache: async (cacheType = 'all') => {
    const response = await api.post(`/admin/cache/clear?cache_type=${cacheType}`);
    return response.data;
  },

  rebuildVectorIndex: async () => {
    const response = await api.post('/admin/vector-store/rebuild');
    return response.data;
  },

  getAuditLog: async (page = 1, limit = 20, userType = null, action = null) => {
    const offset = (page - 1) * limit; // Convert page to offset
    const params = new URLSearchParams({
      offset: offset.toString(),
      limit: limit.toString(),
    });
    if (userType) params.append('user_type_filter', userType);
    if (action) params.append('action_filter', action);

    const response = await api.get(`/admin/audit-log?${params}`);
    return response.data;
  },

  testEmailService: async (testEmail) => {
    const response = await api.post(`/admin/test-email?test_email=${encodeURIComponent(testEmail)}`);
    return response.data;
  },

  getSystemLogs: async (filters = {}) => {
    const params = new URLSearchParams();

    if (filters.level) params.append('level', filters.level);
    if (filters.source) params.append('source', filters.source);
    if (filters.module) params.append('module', filters.module);
    if (filters.search) params.append('search', filters.search);
    if (filters.since) params.append('since', filters.since);
    if (filters.limit) params.append('limit', filters.limit.toString());

    const response = await api.get(`/admin/logs?${params.toString()}`);
    return response.data;
  },
};

// Usage/cost API service (COST-02 admin dashboard)
export const usageAPI = {
  getUsage: async (daysBack = 30) => {
    const response = await api.get(`/admin/usage?days_back=${daysBack}`);
    return response.data;
  },
};

// Health checks API service
export const healthAPI = {
  getHealthStatus: async () => {
    const response = await api.get('/health/');
    return response.data;
  },

  getDatabaseHealth: async () => {
    const response = await api.get('/health/database');
    return response.data;
  },

  getCacheHealth: async () => {
    const response = await api.get('/health/cache');
    return response.data;
  },

  getDiskUsage: async () => {
    const response = await api.get('/health/disk-usage');
    return response.data;
  },
};

export default api;