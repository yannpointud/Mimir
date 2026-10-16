import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { AuthProvider, useAuth, useAuthStatus } from '../../hooks/useAuth';
import { authAPI } from '../../services/api';
import * as authUtils from '../../utils/auth';

// Mock the authentication API
vi.mock('../../services/api', () => ({
  authAPI: {
    login: vi.fn(),
    logout: vi.fn(),
    getCurrentUser: vi.fn(),
    refreshToken: vi.fn(),
  },
}));

// Mock the authentication utilities
vi.mock('../../utils/auth', () => ({
  getAuthToken: vi.fn(),
  setAuthToken: vi.fn(),
  getUser: vi.fn(),
  setUser: vi.fn(),
  logout: vi.fn(),
  checkAndCleanExpiredAuth: vi.fn(),
  isAuthenticated: vi.fn(),
}));

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

// Mock console.error to suppress logs in tests
let consoleSpy;

// Wrapper for tests that require the AuthProvider
const AuthProviderWrapper = ({ children }) => (
  <AuthProvider>{children}</AuthProvider>
);

describe('useAuth - Tests Complets', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    authUtils.getUser.mockReturnValue(null);
    authUtils.isAuthenticated.mockReturnValue(false);
    authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

    // Model the auth utils' real effect on token state. The provider's
    // initial-auth effect depends on `logout` (which depends on
    // isAuthenticated), so it re-runs on every auth toggle and re-derives
    // auth from checkAndCleanExpiredAuth + getCurrentUser — exactly like
    // production. These implementations make the mocks reflect that a stored
    // token means "authenticated" and logout clears it, so the re-run effect
    // does not wipe a just-completed login/logout.
    authUtils.setAuthToken.mockImplementation(() => {
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(true);
    });
    authUtils.setUser.mockImplementation((u) => {
      authAPI.getCurrentUser.mockResolvedValue(u);
    });
    authUtils.logout.mockImplementation(() => {
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('Initialisation du contexte', () => {
    it('devrait lancer une erreur si utilisé en dehors du AuthProvider', () => {
      expect(() => {
        renderHook(() => useAuth());
      }).toThrow('useAuth must be used within an AuthProvider');
    });

    it('devrait initialiser avec les valeurs par défaut', async () => {
      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      // Wait for loading to finish
      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.user).toBeNull();
      expect(result.current.isAuthenticated).toBe(false);
      expect(typeof result.current.login).toBe('function');
      expect(typeof result.current.logout).toBe('function');
      expect(typeof result.current.refreshToken).toBe('function');
    });
  });

  describe('Vérification initiale de l\'authentification', () => {
    it('devrait vérifier l\'authentification au montage avec token valide', async () => {
      const mockUser = { id: 1, username: 'testuser', user_type: 'admin' };
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(true);
      authAPI.getCurrentUser.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(authAPI.getCurrentUser).toHaveBeenCalled();
      expect(authUtils.setUser).toHaveBeenCalledWith(mockUser);
      expect(result.current.user).toEqual(mockUser);
      expect(result.current.isAuthenticated).toBe(true);
    });

    it('devrait gérer l\'absence de token valide', async () => {
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(authAPI.getCurrentUser).not.toHaveBeenCalled();
      expect(result.current.user).toBeNull();
      expect(result.current.isAuthenticated).toBe(false);
    });

    it('devrait gérer les erreurs de vérification d\'authentification', async () => {
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(true);
      authAPI.getCurrentUser.mockRejectedValue(new Error('Token expiré'));

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(consoleSpy).toHaveBeenCalledWith(
        expect.stringContaining('Authentication check failed'),
        expect.objectContaining({ module: 'AuthContext' })
      );
      expect(authUtils.logout).toHaveBeenCalled();
      expect(result.current.isAuthenticated).toBe(false);
    });
  });

  describe('Fonction de connexion', () => {
    it('devrait connecter l\'utilisateur avec succès', async () => {
      // The backend LoginResponse returns access_token + user_type at the top
      // level (no nested user object); the hook builds the stored user from the
      // login username + the returned user_type.
      const mockToken = 'mock-jwt-token';
      const storedUser = { username: 'testuser', user_type: 'admin' };
      const mockResponse = { access_token: mockToken, user_type: 'admin' };

      authAPI.login.mockResolvedValue(mockResponse);
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      let loginResult;
      await act(async () => {
        loginResult = await result.current.login('testuser', 'password123');
      });

      expect(authAPI.login).toHaveBeenCalledWith('testuser', 'password123');
      expect(authUtils.setAuthToken).toHaveBeenCalledWith(mockToken);
      expect(authUtils.setUser).toHaveBeenCalledWith(storedUser);
      expect(loginResult).toEqual({ success: true });
      expect(result.current.user).toEqual(storedUser);
      expect(result.current.isAuthenticated).toBe(true);
    });

    it('devrait gérer les erreurs de connexion', async () => {
      const errorMessage = 'Identifiants incorrects';
      authAPI.login.mockRejectedValue({
        response: { data: { detail: errorMessage } }
      });
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      let loginResult;
      await act(async () => {
        loginResult = await result.current.login('wronguser', 'wrongpassword');
      });

      expect(loginResult).toEqual({
        success: false,
        error: errorMessage
      });
      expect(result.current.isAuthenticated).toBe(false);
      expect(consoleSpy).toHaveBeenCalledWith(
        expect.stringContaining('Login failed'),
        expect.objectContaining({ module: 'AuthContext' })
      );
    });

    it('devrait gérer les erreurs réseau sans détail', async () => {
      authAPI.login.mockRejectedValue(new Error('Network error'));
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      let loginResult;
      await act(async () => {
        loginResult = await result.current.login('testuser', 'password123');
      });

      // getErrorMessage falls back to error.message when there is no
      // response.data.detail, so a bare network Error surfaces its message.
      expect(loginResult).toEqual({
        success: false,
        error: 'Network error'
      });
    });
  });

  describe('Fonction de déconnexion', () => {
    it('devrait déconnecter l\'utilisateur connecté', async () => {
      const mockUser = { id: 1, username: 'testuser', user_type: 'admin' };
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(true);
      authAPI.getCurrentUser.mockResolvedValue(mockUser);
      authAPI.logout.mockResolvedValue({});

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      await act(async () => {
        await result.current.logout();
      });

      expect(authAPI.logout).toHaveBeenCalled();
      expect(authUtils.logout).toHaveBeenCalled();
      expect(result.current.user).toBeNull();
      expect(result.current.isAuthenticated).toBe(false);
    });

    it('devrait déconnecter même si l\'utilisateur n\'est pas connecté', async () => {
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      await act(async () => {
        await result.current.logout();
      });

      expect(authAPI.logout).not.toHaveBeenCalled();
      expect(authUtils.logout).toHaveBeenCalled();
      expect(result.current.isAuthenticated).toBe(false);
    });

    it('devrait gérer les erreurs de déconnexion API', async () => {
      const mockUser = { id: 1, username: 'testuser', user_type: 'admin' };
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(true);
      authAPI.getCurrentUser.mockResolvedValue(mockUser);
      authAPI.logout.mockRejectedValue(new Error('Server error'));

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      await act(async () => {
        await result.current.logout();
      });

      expect(consoleSpy).toHaveBeenCalledWith(
        expect.stringContaining('Logout failed'),
        expect.objectContaining({ module: 'AuthContext' })
      );
      expect(authUtils.logout).toHaveBeenCalled();
      expect(result.current.isAuthenticated).toBe(false);
    });
  });

  describe('Fonction de rafraîchissement de token', () => {
    it('devrait rafraîchir le token avec succès', async () => {
      const newToken = 'new-jwt-token';
      authAPI.refreshToken.mockResolvedValue({ access_token: newToken });
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      let refreshResult;
      await act(async () => {
        refreshResult = await result.current.refreshToken();
      });

      expect(authAPI.refreshToken).toHaveBeenCalled();
      expect(authUtils.setAuthToken).toHaveBeenCalledWith(newToken);
      expect(refreshResult).toBe(true);
    });

    it('devrait gérer l\'échec du rafraîchissement', async () => {
      authAPI.refreshToken.mockRejectedValue(new Error('Token expired'));
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      let refreshResult;
      await act(async () => {
        refreshResult = await result.current.refreshToken();
      });

      expect(consoleSpy).toHaveBeenCalledWith(
        expect.stringContaining('Token refresh failed'),
        expect.objectContaining({ module: 'AuthContext' })
      );
      expect(authUtils.logout).toHaveBeenCalled();
      expect(refreshResult).toBe(false);
    });
  });

  describe('États de chargement', () => {
    it('devrait gérer l\'état de chargement pendant la connexion', async () => {
      let resolveLogin;
      const loginPromise = new Promise((resolve) => {
        resolveLogin = resolve;
      });
      authAPI.login.mockReturnValue(loginPromise);
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      const loginCall = result.current.login('testuser', 'password');

      await waitFor(() => {
        expect(result.current.loading).toBe(true);
      });

      resolveLogin({ access_token: 'token', user: { id: 1, username: 'test', user_type: 'user' } });
      await act(async () => {
        await loginCall;
      });

      expect(result.current.loading).toBe(false);
    });

    it('devrait gérer l\'état de chargement pendant la déconnexion', async () => {
      const mockUser = { id: 1, username: 'testuser', user_type: 'admin' };
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(true);
      authAPI.getCurrentUser.mockResolvedValue(mockUser);

      let resolveLogout;
      const logoutPromise = new Promise((resolve) => {
        resolveLogout = resolve;
      });
      authAPI.logout.mockReturnValue(logoutPromise);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      const logoutCall = result.current.logout();

      await waitFor(() => {
        expect(result.current.loading).toBe(true);
      });

      resolveLogout();
      await act(async () => {
        await logoutCall;
      });

      expect(result.current.loading).toBe(false);
    });
  });

  describe('Flux d\'authentification complexes', () => {
    it('devrait gérer une connexion suivie d\'une déconnexion', async () => {
      const mockToken = 'mock-jwt-token';
      const storedUser = { username: 'testuser', user_type: 'admin' };
      const mockResponse = { access_token: mockToken, user_type: 'admin' };

      authAPI.login.mockResolvedValue(mockResponse);
      authAPI.logout.mockResolvedValue({});
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      // Login
      await act(async () => {
        await result.current.login('testuser', 'password123');
      });

      expect(result.current.isAuthenticated).toBe(true);
      expect(result.current.user).toEqual(storedUser);

      // Logout
      await act(async () => {
        await result.current.logout();
      });

      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
    });

    it('devrait gérer des tentatives de connexion multiples avec échecs', async () => {
      const errorMessage = 'Identifiants incorrects';
      authAPI.login.mockRejectedValue({
        response: { data: { detail: errorMessage } }
      });
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      // First attempt
      let result1;
      await act(async () => {
        result1 = await result.current.login('wrong1', 'wrong1');
      });

      expect(result1.success).toBe(false);
      expect(result.current.isAuthenticated).toBe(false);

      // Second attempt
      let result2;
      await act(async () => {
        result2 = await result.current.login('wrong2', 'wrong2');
      });

      expect(result2.success).toBe(false);
      expect(result.current.isAuthenticated).toBe(false);
      expect(authAPI.login).toHaveBeenCalledTimes(2);
    });

    it('devrait gérer le rafraîchissement de token pendant une session active', async () => {
      const mockToken = 'mock-jwt-token';
      const newToken = 'new-jwt-token';

      authAPI.login.mockResolvedValue({ access_token: mockToken, user_type: 'admin' });
      authAPI.refreshToken.mockResolvedValue({ access_token: newToken });
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProviderWrapper,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      // Initial login
      await act(async () => {
        await result.current.login('testuser', 'password123');
      });

      expect(result.current.isAuthenticated).toBe(true);

      // Token refresh
      let refreshResult;
      await act(async () => {
        refreshResult = await result.current.refreshToken();
      });

      expect(refreshResult).toBe(true);
      expect(authUtils.setAuthToken).toHaveBeenCalledWith(newToken);
      expect(result.current.isAuthenticated).toBe(true);
    });
  });
});

describe('useAuthStatus - Tests Complets', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    authUtils.isAuthenticated.mockReturnValue(false);
    authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('devrait initialiser avec le statut d\'authentification actuel', () => {
    authUtils.isAuthenticated.mockReturnValue(true);
    authUtils.checkAndCleanExpiredAuth.mockReturnValue(true);

    const { result } = renderHook(() => useAuthStatus());

    expect(result.current).toBe(true);
  });

  it('devrait vérifier périodiquement l\'authentification', () => {
    authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

    const { result } = renderHook(() => useAuthStatus());

    expect(result.current).toBe(false);

    // Simulate a state change
    authUtils.checkAndCleanExpiredAuth.mockReturnValue(true);

    // Advance the timer by 60 seconds
    act(() => {
      vi.advanceTimersByTime(60000);
    });

    expect(authUtils.checkAndCleanExpiredAuth).toHaveBeenCalledTimes(2);
  });

  it('devrait écouter les changements de localStorage', () => {
    const { result } = renderHook(() => useAuthStatus());

    expect(result.current).toBe(false);

    // Simulate a storage event
    authUtils.checkAndCleanExpiredAuth.mockReturnValue(true);

    act(() => {
      const storageEvent = new StorageEvent('storage', {
        key: 'authToken',
        newValue: 'new-token',
      });
      window.dispatchEvent(storageEvent);
    });

    expect(authUtils.checkAndCleanExpiredAuth).toHaveBeenCalled();
  });

  it('devrait ignorer les changements de localStorage non pertinents', () => {
    const initialCallCount = authUtils.checkAndCleanExpiredAuth.mock.calls.length;

    renderHook(() => useAuthStatus());

    act(() => {
      const storageEvent = new StorageEvent('storage', {
        key: 'otherKey',
        newValue: 'some-value',
      });
      window.dispatchEvent(storageEvent);
    });

    // Should not have called checkAndCleanExpiredAuth additionally
    expect(authUtils.checkAndCleanExpiredAuth.mock.calls.length).toBe(initialCallCount + 1);
  });

  it('devrait nettoyer les listeners au démontage', () => {
    const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener');
    const clearIntervalSpy = vi.spyOn(global, 'clearInterval');

    const { unmount } = renderHook(() => useAuthStatus());

    unmount();

    expect(removeEventListenerSpy).toHaveBeenCalledWith('storage', expect.any(Function));
    expect(clearIntervalSpy).toHaveBeenCalled();
  });

  it('devrait réagir aux changements de la clé user dans localStorage', () => {
    renderHook(() => useAuthStatus());

    authUtils.checkAndCleanExpiredAuth.mockReturnValue(true);

    act(() => {
      const storageEvent = new StorageEvent('storage', {
        key: 'user',
        newValue: JSON.stringify({ id: 1, username: 'test', user_type: 'user' }),
      });
      window.dispatchEvent(storageEvent);
    });

    expect(authUtils.checkAndCleanExpiredAuth).toHaveBeenCalled();
  });

  describe('Scénarios de synchronisation multi-onglets', () => {
    it('devrait se synchroniser quand un autre onglet se connecte', () => {
      const { result } = renderHook(() => useAuthStatus());

      expect(result.current).toBe(false);

      // Simulate another tab logging in
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(true);

      act(() => {
        const storageEvent = new StorageEvent('storage', {
          key: 'authToken',
          newValue: 'new-auth-token',
        });
        window.dispatchEvent(storageEvent);
      });

      expect(authUtils.checkAndCleanExpiredAuth).toHaveBeenCalled();
    });

    it('devrait se synchroniser quand un autre onglet se déconnecte', () => {
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(true);
      const { result } = renderHook(() => useAuthStatus());

      expect(result.current).toBe(true);

      // Simulate another tab logging out
      authUtils.checkAndCleanExpiredAuth.mockReturnValue(false);

      act(() => {
        const storageEvent = new StorageEvent('storage', {
          key: 'authToken',
          newValue: null,
        });
        window.dispatchEvent(storageEvent);
      });

      expect(authUtils.checkAndCleanExpiredAuth).toHaveBeenCalled();
    });
  });

  describe('Gestion des timers et performances', () => {
    it('devrait vérifier l\'authentification toutes les minutes', () => {
      renderHook(() => useAuthStatus());

      // Initial check
      expect(authUtils.checkAndCleanExpiredAuth).toHaveBeenCalledTimes(1);

      // After 30 seconds, no new check
      act(() => {
        vi.advanceTimersByTime(30000);
      });
      expect(authUtils.checkAndCleanExpiredAuth).toHaveBeenCalledTimes(1);

      // After 60 seconds, a new check
      act(() => {
        vi.advanceTimersByTime(30000);
      });
      expect(authUtils.checkAndCleanExpiredAuth).toHaveBeenCalledTimes(2);

      // After 2 minutes, a third check
      act(() => {
        vi.advanceTimersByTime(60000);
      });
      expect(authUtils.checkAndCleanExpiredAuth).toHaveBeenCalledTimes(3);
    });

    it('ne devrait pas créer de fuites mémoire avec plusieurs instances', () => {
      const setIntervalSpy = vi.spyOn(global, 'setInterval');
      const clearIntervalSpy = vi.spyOn(global, 'clearInterval');

      // Create multiple instances
      const hook1 = renderHook(() => useAuthStatus());
      const hook2 = renderHook(() => useAuthStatus());
      const hook3 = renderHook(() => useAuthStatus());

      expect(setIntervalSpy).toHaveBeenCalledTimes(3);

      // Unmount the instances
      hook1.unmount();
      hook2.unmount();
      hook3.unmount();

      expect(clearIntervalSpy).toHaveBeenCalledTimes(3);
    });
  });
});