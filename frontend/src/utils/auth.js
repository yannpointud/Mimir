// Authentication management utilities

import { createLogger } from './logger';

const logger = createLogger('Auth');

export const AUTH_TOKEN_KEY = 'authToken';
export const USER_KEY = 'user';

// Utility function for safe localStorage handling
const safeLocalStorage = {
  getItem: (key) => {
    try {
      const item = localStorage.getItem(key);
      return item && item !== 'undefined' ? item : null;
    } catch (error) {
      logger.error(`Failed to read ${key} from localStorage`, error);
      return null;
    }
  },
  setItem: (key, value) => {
    try {
      localStorage.setItem(key, value);
      return true;
    } catch (error) {
      logger.error(`Failed to write ${key} to localStorage`, error);
      return false;
    }
  },
  removeItem: (key) => {
    try {
      localStorage.removeItem(key);
      return true;
    } catch (error) {
      logger.error(`Failed to remove ${key} from localStorage`, error);
      return false;
    }
  }
};

// Token storage and retrieval
export const getAuthToken = () => {
  return safeLocalStorage.getItem(AUTH_TOKEN_KEY);
};

export const setAuthToken = (token) => {
  if (!token) return false;
  return safeLocalStorage.setItem(AUTH_TOKEN_KEY, token);
};

export const removeAuthToken = () => {
  return safeLocalStorage.removeItem(AUTH_TOKEN_KEY);
};

// User information storage and retrieval
export const getUser = () => {
  try {
    const userStr = safeLocalStorage.getItem(USER_KEY);
    if (!userStr) return null;

    const user = JSON.parse(userStr);
    // Basic validation of user structure
    if (user && typeof user === 'object' && user.user_type) {
      return user;
    }
    return null;
  } catch (error) {
    logger.error('Failed to parse the stored user', error);
    // Clean up corrupted data
    removeUser();
    return null;
  }
};

export const setUser = (user) => {
  if (!user || typeof user !== 'object') return false;
  try {
    return safeLocalStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch (error) {
    logger.error('Failed to serialize the user', error);
    return false;
  }
};

export const removeUser = () => {
  return safeLocalStorage.removeItem(USER_KEY);
};

// Check if the user is authenticated
export const isAuthenticated = () => {
  const token = getAuthToken();
  const user = getUser();
  return !!(token && user);
};

// Check if the user is admin
export const isAdmin = () => {
  const user = getUser();
  return user?.user_type === 'admin';
};

// Full logout
export const logout = () => {
  removeAuthToken();
  removeUser();
};

// Parse JWT to retrieve information (without signature verification)
export const parseJWT = (token) => {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    );
    return JSON.parse(jsonPayload);
  } catch (error) {
    logger.error('Failed to parse the JWT', error);
    return null;
  }
};

// Check if the token is expired
export const isTokenExpired = (token) => {
  if (!token) return true;

  const payload = parseJWT(token);
  if (!payload || !payload.exp) return true;

  const now = Math.floor(Date.now() / 1000);
  return payload.exp < now;
};

// Automatic check and cleanup of expired tokens
export const checkAndCleanExpiredAuth = () => {
  const token = getAuthToken();
  if (token && isTokenExpired(token)) {
    logout();
    return false;
  }
  return !!token;
};