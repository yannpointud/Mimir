// Utilitaires pour la gestion de l'authentification

export const AUTH_TOKEN_KEY = 'authToken';
export const USER_KEY = 'user';

// Fonction utilitaire pour gérer localStorage de manière sécurisée
const safeLocalStorage = {
  getItem: (key) => {
    try {
      const item = localStorage.getItem(key);
      return item && item !== 'undefined' ? item : null;
    } catch (error) {
      console.error(`Erreur lors de la lecture de ${key}:`, error);
      return null;
    }
  },
  setItem: (key, value) => {
    try {
      localStorage.setItem(key, value);
      return true;
    } catch (error) {
      console.error(`Erreur lors de l'écriture de ${key}:`, error);
      return false;
    }
  },
  removeItem: (key) => {
    try {
      localStorage.removeItem(key);
      return true;
    } catch (error) {
      console.error(`Erreur lors de la suppression de ${key}:`, error);
      return false;
    }
  }
};

// Stockage et récupération du token
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

// Stockage et récupération des informations utilisateur
export const getUser = () => {
  try {
    const userStr = safeLocalStorage.getItem(USER_KEY);
    if (!userStr) return null;

    const user = JSON.parse(userStr);
    // Validation basique de la structure utilisateur
    if (user && typeof user === 'object' && user.user_type) {
      return user;
    }
    return null;
  } catch (error) {
    console.error('Erreur lors du parsing des données utilisateur:', error);
    // Nettoyer les données corrompues
    removeUser();
    return null;
  }
};

export const setUser = (user) => {
  if (!user || typeof user !== 'object') return false;
  try {
    return safeLocalStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch (error) {
    console.error('Erreur lors de la sérialisation des données utilisateur:', error);
    return false;
  }
};

export const removeUser = () => {
  return safeLocalStorage.removeItem(USER_KEY);
};

// Vérification si l'utilisateur est authentifié
export const isAuthenticated = () => {
  const token = getAuthToken();
  const user = getUser();
  return !!(token && user);
};

// Vérification si l'utilisateur est admin
export const isAdmin = () => {
  const user = getUser();
  return user?.user_type === 'admin';
};

// Déconnexion complète
export const logout = () => {
  removeAuthToken();
  removeUser();
};

// Parsing du JWT pour récupérer les informations (sans vérification de signature)
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
    console.error('Erreur lors du parsing du JWT:', error);
    return null;
  }
};

// Vérification si le token est expiré
export const isTokenExpired = (token) => {
  if (!token) return true;

  const payload = parseJWT(token);
  if (!payload || !payload.exp) return true;

  const now = Math.floor(Date.now() / 1000);
  return payload.exp < now;
};

// Vérification et nettoyage automatique des tokens expirés
export const checkAndCleanExpiredAuth = () => {
  const token = getAuthToken();
  if (token && isTokenExpired(token)) {
    logout();
    return false;
  }
  return !!token;
};