import { useState, useEffect, createContext, useContext, useCallback } from 'react';

import { authAPI } from '../services/api';
import {
  setAuthToken,
  getUser,
  setUser,
  logout as utilLogout,
  checkAndCleanExpiredAuth,
  isAuthenticated as utilIsAuthenticated
} from '../utils/auth';
import { getErrorMessage } from '../utils/helpers';

// Authentication context
const AuthContext = createContext(null);

// Hook to use the authentication context
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

// Authentication provider
export const AuthProvider = ({ children }) => {
  const [user, setUserState] = useState(getUser());
  const [loading, setLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(utilIsAuthenticated());

  // Logout function - defined before useEffect
  const logout = useCallback(async () => {
    try {
      setLoading(true);
      // Call logout API if user is logged in
      if (isAuthenticated) {
        await authAPI.logout();
      }
    } catch (error) {
      console.error('Erreur lors de la déconnexion:', getErrorMessage(error));
    } finally {
      // Clean up local data in all cases
      utilLogout();
      setUserState(null);
      setIsAuthenticated(false);
      setLoading(false);
    }
  }, [isAuthenticated]);

  // Initial authentication check
  useEffect(() => {
    const checkAuth = async () => {
      try {
        // Check if token exists and is not expired
        if (checkAndCleanExpiredAuth()) {
          // Verify with server that the token is still valid
          const userData = await authAPI.getCurrentUser();
          if (userData && userData.user_type) {
            setUserState(userData);
            setUser(userData);
            setIsAuthenticated(true);
          } else {
            // Invalid response, log out
            logout();
          }
        } else {
          setIsAuthenticated(false);
          setUserState(null);
        }
      } catch (error) {
        console.error('Erreur lors de la vérification de l\'authentification:', getErrorMessage(error));
        // On error, log out the user
        logout();
      } finally {
        setLoading(false);
      }
    };

    checkAuth();
  }, [logout]);

  // Login function
  const login = async (username, password) => {
    try {
      setLoading(true);
      const response = await authAPI.login(username, password);

      const { access_token, user_type } = response;

      // Create user object with backend data
      const userData = {
        username: username, // Use the username from login
        user_type: user_type
      };

      // Validate received data
      if (!access_token || !user_type) {
        throw new Error('Réponse d\'authentification invalide');
      }

      // Store token and user data
      setAuthToken(access_token);
      setUser(userData);
      setUserState(userData);
      setIsAuthenticated(true);

      return { success: true };
    } catch (error) {
      console.error('Erreur lors de la connexion:', getErrorMessage(error));
      return {
        success: false,
        error: getErrorMessage(error)
      };
    } finally {
      setLoading(false);
    }
  };


  // Token refresh function
  const refreshToken = async () => {
    try {
      const response = await authAPI.refreshToken();
      const { access_token } = response;

      if (!access_token) {
        throw new Error('Token de rafraîchissement invalide');
      }

      setAuthToken(access_token);
      return true;
    } catch (error) {
      console.error('Erreur lors du rafraîchissement du token:', getErrorMessage(error));
      logout();
      return false;
    }
  };

  const value = {
    user,
    loading,
    isAuthenticated,
    login,
    logout,
    refreshToken,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

// Simple hook to check authentication without context
export const useAuthStatus = () => {
  const [isAuthenticated, setIsAuthenticated] = useState(utilIsAuthenticated());

  useEffect(() => {
    const checkAuth = () => {
      setIsAuthenticated(checkAndCleanExpiredAuth());
    };

    // Check on mount
    checkAuth();

    // Check periodically (every minute)
    const interval = setInterval(checkAuth, 60000);

    // Listen for localStorage changes (for cross-tab synchronization)
    const handleStorageChange = (e) => {
      if (e.key === 'authToken' || e.key === 'user') {
        checkAuth();
      }
    };

    window.addEventListener('storage', handleStorageChange);

    return () => {
      clearInterval(interval);
      window.removeEventListener('storage', handleStorageChange);
    };
  }, []);

  return isAuthenticated;
};