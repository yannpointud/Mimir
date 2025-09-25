import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  getAuthToken,
  setAuthToken,
  removeAuthToken,
  getUser,
  setUser,
  removeUser,
  isAuthenticated,
  isAdmin,
  logout,
  parseJWT,
  isTokenExpired,
  checkAndCleanExpiredAuth
} from '../../utils/auth';

// Mock localStorage
Object.defineProperty(window, 'localStorage', {
  value: {
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
  },
  writable: true,
});

describe('Auth Utils Simple Tests', () => {
  let mockLocalStorage;

  beforeEach(() => {
    vi.clearAllMocks();
    mockLocalStorage = {};

    window.localStorage.getItem.mockImplementation((key) => mockLocalStorage[key] || null);
    window.localStorage.setItem.mockImplementation((key, value) => {
      mockLocalStorage[key] = value;
    });
    window.localStorage.removeItem.mockImplementation((key) => {
      delete mockLocalStorage[key];
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('Token Management', () => {
    it('should set and get token', () => {
      const token = 'test-token-123';
      setAuthToken(token);
      expect(window.localStorage.setItem).toHaveBeenCalledWith('authToken', token);

      mockLocalStorage.authToken = token;
      const retrievedToken = getAuthToken();
      expect(retrievedToken).toBe(token);
    });

    it('should remove token', () => {
      removeAuthToken();
      expect(window.localStorage.removeItem).toHaveBeenCalledWith('authToken');
    });

    it('should return null for undefined token', () => {
      mockLocalStorage.authToken = 'undefined';
      expect(getAuthToken()).toBeNull();
    });
  });

  describe('User Management', () => {
    it('should set and get user', () => {
      const user = { id: 1, username: 'test', user_type: 'admin' };
      setUser(user);
      expect(window.localStorage.setItem).toHaveBeenCalledWith('user', JSON.stringify(user));

      mockLocalStorage.user = JSON.stringify(user);
      const retrievedUser = getUser();
      expect(retrievedUser).toEqual(user);
    });

    it('should remove user', () => {
      removeUser();
      expect(window.localStorage.removeItem).toHaveBeenCalledWith('user');
    });

    it('should return null for undefined user', () => {
      mockLocalStorage.user = 'undefined';
      expect(getUser()).toBeNull();
    });
  });

  describe('Authentication Status', () => {
    it('should identify authenticated user', () => {
      mockLocalStorage.authToken = 'token';
      mockLocalStorage.user = JSON.stringify({ id: 1, user_type: 'admin' });
      expect(isAuthenticated()).toBe(true);
    });

    it('should identify unauthenticated user', () => {
      expect(isAuthenticated()).toBe(false);
    });
  });

  describe('Admin Status', () => {
    it('should identify admin user', () => {
      mockLocalStorage.user = JSON.stringify({ user_type: 'admin' });
      expect(isAdmin()).toBe(true);
    });

    it('should identify non-admin user', () => {
      mockLocalStorage.user = JSON.stringify({ user_type: 'user' });
      expect(isAdmin()).toBe(false);
    });

    it('should return false for no user', () => {
      expect(isAdmin()).toBe(false);
    });
  });

  describe('Logout', () => {
    it('should clear all auth data', () => {
      logout();
      expect(window.localStorage.removeItem).toHaveBeenCalledWith('authToken');
      expect(window.localStorage.removeItem).toHaveBeenCalledWith('user');
    });
  });

  describe('JWT Parsing', () => {
    it('should parse valid JWT', () => {
      const payload = { userId: 1, exp: Math.floor(Date.now() / 1000) + 3600 };
      const token = 'header.' + btoa(JSON.stringify(payload)) + '.signature';

      const result = parseJWT(token);
      expect(result).toEqual(payload);
    });

    it('should return null for invalid JWT', () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const result = parseJWT('invalid.token');
      expect(result).toBeNull();
      consoleSpy.mockRestore();
    });
  });

  describe('Token Expiration', () => {
    it('should detect expired token', () => {
      const expiredPayload = { exp: Math.floor(Date.now() / 1000) - 3600 };
      const token = 'header.' + btoa(JSON.stringify(expiredPayload)) + '.signature';
      expect(isTokenExpired(token)).toBe(true);
    });

    it('should detect valid token', () => {
      const validPayload = { exp: Math.floor(Date.now() / 1000) + 3600 };
      const token = 'header.' + btoa(JSON.stringify(validPayload)) + '.signature';
      expect(isTokenExpired(token)).toBe(false);
    });

    it('should treat null token as expired', () => {
      expect(isTokenExpired(null)).toBe(true);
    });
  });

  describe('Auth Cleanup', () => {
    it('should clean expired token', () => {
      const expiredPayload = { exp: Math.floor(Date.now() / 1000) - 3600 };
      const token = 'header.' + btoa(JSON.stringify(expiredPayload)) + '.signature';
      mockLocalStorage.authToken = token;

      const result = checkAndCleanExpiredAuth();
      expect(result).toBe(false);
      expect(window.localStorage.removeItem).toHaveBeenCalledWith('authToken');
    });

    it('should keep valid token', () => {
      const validPayload = { exp: Math.floor(Date.now() / 1000) + 3600 };
      const token = 'header.' + btoa(JSON.stringify(validPayload)) + '.signature';
      mockLocalStorage.authToken = token;

      const result = checkAndCleanExpiredAuth();
      expect(result).toBe(true);
    });
  });
});