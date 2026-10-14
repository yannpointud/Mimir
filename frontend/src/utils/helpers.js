import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

// Utility to merge CSS classes with Tailwind
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

/**
 * Escape HTML special characters so a string renders as inert literal text.
 * The '&' replacement MUST run first, otherwise the entities produced by the
 * following replacements would be double-escaped.
 *
 * @param {*} str - Value to escape (coerced to String)
 * @returns {string} HTML-escaped string safe for innerHTML insertion
 */
export const escapeHtml = (str) =>
  String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

// The backend serializes naive UTC datetimes (datetime.utcnow().isoformat(),
// no offset): read those as UTC instead of local time.
const NAIVE_ISO_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

const parseServerDate = (dateString) =>
  new Date(NAIVE_ISO_DATETIME.test(dateString) ? `${dateString}Z` : dateString);

// Date formatting
export const formatDate = (dateString) => {
  if (!dateString) return 'N/A';

  const date = parseServerDate(dateString);
  if (isNaN(date.getTime())) return 'Date invalide';

  return new Intl.DateTimeFormat('fr-FR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date);
};

// Relative date formatting
export const formatRelativeDate = (dateString) => {
  if (!dateString) return 'N/A';

  const date = parseServerDate(dateString);
  if (isNaN(date.getTime())) return 'Date invalide';

  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'À l\'instant';
  if (diffMins < 60) return `Il y a ${diffMins} min`;
  if (diffHours < 24) return `Il y a ${diffHours}h`;
  if (diffDays < 7) return `Il y a ${diffDays} jour${diffDays > 1 ? 's' : ''}`;

  return formatDate(dateString);
};

// File size formatting
export const formatFileSize = (bytes) => {
  if (bytes === 0) return '0 B';

  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

// Number formatting with spaces
export const formatNumber = (num) => {
  return new Intl.NumberFormat('fr-FR').format(num);
};

// Unique ID generation
export const generateId = () => {
  return Math.random().toString(36).substring(2) + Date.now().toString(36);
};

// Session ID generation
export const generateSessionId = () => {
  return 'session-' + generateId();
};

// Email validation
export const isValidEmail = (email) => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
};

// Text truncation
export const truncateText = (text, maxLength = 100) => {
  if (!text || text.length <= maxLength) return text;
  return text.substring(0, maxLength).trim() + '...';
};

// Extract filename without extension
export const getFileNameWithoutExtension = (fileName) => {
  return fileName.replace(/\.[^/.]+$/, '');
};

// Get file extension
export const getFileExtension = (fileName) => {
  return fileName.split('.').pop().toLowerCase();
};

// Check if file type is supported
export const isSupportedFileType = (fileName) => {
  const supportedExtensions = ['pdf', 'docx', 'txt', 'md'];
  const extension = getFileExtension(fileName);
  return supportedExtensions.includes(extension);
};

// Function debounce
export const debounce = (func, wait) => {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
};

// Function throttle
export const throttle = (func, limit) => {
  let inThrottle;
  return function(...args) {
    if (!inThrottle) {
      func.apply(this, args);
      inThrottle = true;
      setTimeout(() => inThrottle = false, limit);
    }
  };
};

// Copy text to clipboard
export const copyToClipboard = async (text) => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (error) {
    console.error('Erreur lors de la copie:', error);
    // Fallback for older browsers
    try {
      const textArea = document.createElement('textarea');
      textArea.value = text;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
      return true;
    } catch (fallbackError) {
      console.error('Erreur lors de la copie (fallback):', fallbackError);
      return false;
    }
  }
};

// Create mailto link with content
export const createMailtoLink = (to, subject, body) => {
  const params = new URLSearchParams();
  if (subject) params.append('subject', subject);
  if (body) params.append('body', body);

  return `mailto:${to}?${params.toString()}`;
};

// API error handling
export const getErrorMessage = (error) => {
  if (error.response?.data?.detail) {
    return error.response.data.detail;
  }
  // Backend ErrorResponse shape: { error_code, error_message } (main.py handlers)
  if (typeof error.response?.data?.error_message === 'string') {
    return error.response.data.error_message;
  }
  if (error.response?.data?.message) {
    return error.response.data.message;
  }
  if (error.message) {
    return error.message;
  }
  return 'Une erreur inattendue s\'est produite';
};

// Document status translation
export const translateDocumentStatus = (status) => {
  const translations = {
    'pending': 'En attente',
    'indexing': 'Indexation en cours',
    'indexed': 'Indexé',
    'error': 'Erreur'
  };
  return translations[status] || status;
};

// Status colors
export const getStatusColor = (status) => {
  const colors = {
    'pending': 'badge-neutral',
    'indexing': 'badge-accent',
    'indexed': 'badge-success',
    'error': 'badge-danger'
  };
  return colors[status] || 'badge-neutral';
};

// Robust handling of null/undefined values for display
export const safeDisplayValue = (value, fallback = 'N/A') => {
  if (value === null || value === undefined) return fallback;
  if (typeof value === 'string' && value.trim() === '') return fallback;
  if (typeof value === 'number' && isNaN(value)) return fallback;
  return value;
};

// Robust statistics formatting
export const safeFormatNumber = (value, fallback = 0) => {
  const safeValue = safeDisplayValue(value, fallback);
  return typeof safeValue === 'number' ? formatNumber(safeValue) : safeValue;
};

// Robust object data handling
export const safeGetProperty = (obj, path, fallback = null) => {
  try {
    return path.split('.').reduce((current, key) => {
      return current && current[key] !== undefined ? current[key] : fallback;
    }, obj);
  } catch (error) {
    console.warn(`Erreur lors de l'accès à la propriété ${path}:`, error);
    return fallback;
  }
};

// Robust document data validation
export const validateDocumentData = (document) => {
  return {
    ...document,
    id: safeDisplayValue(document?.id, 'unknown'),
    filename: safeDisplayValue(document?.filename, 'Fichier sans nom'),
    status: safeDisplayValue(document?.status, 'unknown'),
    created_at: safeDisplayValue(document?.created_at, new Date().toISOString()),
    chunk_count: safeDisplayValue(document?.chunk_count, 0),
    preserve: Boolean(document?.preserve)
  };
};