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

// Contexte d'authentification
const AuthContext = createContext(null);

// Hook pour utiliser le contexte d'authentification
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

// Provider d'authentification
export const AuthProvider = ({ children }) => {
  const [user, setUserState] = useState(getUser());
  const [loading, setLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(utilIsAuthenticated());

  // Fonction de déconnexion - définie avant useEffect
  const logout = useCallback(async () => {
    try {
      setLoading(true);
      // Appeler l'API de déconnexion si l'utilisateur est connecté
      if (isAuthenticated) {
        await authAPI.logout();
      }
    } catch (error) {
      console.error('Erreur lors de la déconnexion:', getErrorMessage(error));
    } finally {
      // Nettoyer les données locales dans tous les cas
      utilLogout();
      setUserState(null);
      setIsAuthenticated(false);
      setLoading(false);
    }
  }, [isAuthenticated]);

  // Vérification initiale de l'authentification
  useEffect(() => {
    const checkAuth = async () => {
      try {
        // Vérifier si le token existe et n'est pas expiré
        if (checkAndCleanExpiredAuth()) {
          // Vérifier avec le serveur que le token est toujours valide
          const userData = await authAPI.getCurrentUser();
          if (userData && userData.user_type) {
            setUserState(userData);
            setUser(userData);
            setIsAuthenticated(true);
          } else {
            // Réponse invalide, déconnecter
            logout();
          }
        } else {
          setIsAuthenticated(false);
          setUserState(null);
        }
      } catch (error) {
        console.error('Erreur lors de la vérification de l\'authentification:', getErrorMessage(error));
        // En cas d'erreur, déconnecter l'utilisateur
        logout();
      } finally {
        setLoading(false);
      }
    };

    checkAuth();
  }, [logout]);

  // Fonction de connexion
  const login = async (username, password) => {
    try {
      setLoading(true);
      const response = await authAPI.login(username, password);

      const { access_token, user_type } = response;

      // Créer l'objet utilisateur avec les données du backend
      const userData = {
        username: username, // On utilise le username de la connexion
        user_type: user_type
      };

      // Validation des données reçues
      if (!access_token || !user_type) {
        throw new Error('Réponse d\'authentification invalide');
      }

      // Stocker le token et les données utilisateur
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


  // Fonction de rafraîchissement du token
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

// Hook simple pour vérifier l'authentification sans contexte
export const useAuthStatus = () => {
  const [isAuthenticated, setIsAuthenticated] = useState(utilIsAuthenticated());

  useEffect(() => {
    const checkAuth = () => {
      setIsAuthenticated(checkAndCleanExpiredAuth());
    };

    // Vérifier lors du montage
    checkAuth();

    // Vérifier périodiquement (toutes les minutes)
    const interval = setInterval(checkAuth, 60000);

    // Écouter les changements de localStorage (pour la synchronisation entre onglets)
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