// Utilities for safe local storage management

import { createLogger } from './logger';

const logger = createLogger('Storage');

// Utility function for safe sessionStorage handling
export const safeSessionStorage = {
  getItem: (key) => {
    try {
      const item = sessionStorage.getItem(key);
      return item && item !== 'undefined' ? item : null;
    } catch (error) {
      logger.error(`Failed to read ${key} from sessionStorage`, error);
      return null;
    }
  },

  setItem: (key, value) => {
    try {
      sessionStorage.setItem(key, value);
      return true;
    } catch (error) {
      logger.error(`Failed to write ${key} to sessionStorage`, error);
      return false;
    }
  },

  removeItem: (key) => {
    try {
      sessionStorage.removeItem(key);
      return true;
    } catch (error) {
      logger.error(`Failed to remove ${key} from sessionStorage`, error);
      return false;
    }
  },

  // JSON object handling
  getJSON: (key, fallback = null) => {
    try {
      const item = safeSessionStorage.getItem(key);
      if (!item) return fallback;

      const parsed = JSON.parse(item);
      return parsed;
    } catch (error) {
      logger.error(`Failed to parse the JSON of ${key}`, error);
      // Clean up corrupted data
      safeSessionStorage.removeItem(key);
      return fallback;
    }
  },

  setJSON: (key, value) => {
    if (value === null || value === undefined) {
      return safeSessionStorage.removeItem(key);
    }

    try {
      const serialized = JSON.stringify(value);
      return safeSessionStorage.setItem(key, serialized);
    } catch (error) {
      logger.error(`Failed to serialize the JSON of ${key}`, error);
      return false;
    }
  }
};

// Chat history management
export const chatHistoryStorage = {
  // Safety limits
  MAX_MESSAGES: 50,
  MAX_MESSAGE_SIZE: 50000, // 50KB per message

  getHistory: (sessionId) => {
    const key = `chat_history_${sessionId}`;
    const messages = safeSessionStorage.getJSON(key, []);

    // Validate and clean messages
    if (!Array.isArray(messages)) {
      logger.warn('Corrupted chat history, resetting it');
      chatHistoryStorage.clearHistory(sessionId);
      return [];
    }

    // Filter and validate messages
    const validMessages = messages.filter(msg => {
      return msg &&
             typeof msg === 'object' &&
             msg.id &&
             msg.type &&
             msg.content &&
             msg.timestamp;
    });

    return validMessages;
  },

  saveHistory: (sessionId, messages) => {
    if (!sessionId || !Array.isArray(messages)) return false;

    // Limit the number of messages
    const limitedMessages = messages.slice(-chatHistoryStorage.MAX_MESSAGES);

    // Strip chunk_text from sources to reduce storage size.
    // The modal fetches full content via API, so chunk_text is not needed in storage.
    const lightMessages = limitedMessages.map(msg => {
      if (!msg.sources || msg.sources.length === 0) return msg;
      return {
        ...msg,
        sources: msg.sources.map((source) => {
          const lightSource = { ...source };
          delete lightSource.chunk_text;
          delete lightSource.text;
          return lightSource;
        })
      };
    });

    // Validate message size
    const validMessages = lightMessages.filter(msg => {
      const size = JSON.stringify(msg).length;
      if (size > chatHistoryStorage.MAX_MESSAGE_SIZE) {
        logger.warn('Oversized message dropped from the history', { messageId: msg.id });
        return false;
      }
      return true;
    });

    const key = `chat_history_${sessionId}`;
    return safeSessionStorage.setJSON(key, validMessages);
  },

  clearHistory: (sessionId) => {
    const key = `chat_history_${sessionId}`;
    return safeSessionStorage.removeItem(key);
  },

  // Automatic cleanup of old sessions
  cleanupOldSessions: (maxAgeHours = 24) => {
    try {
      const cutoffTime = Date.now() - (maxAgeHours * 60 * 60 * 1000);

      for (let i = 0; i < sessionStorage.length; i++) {
        const key = sessionStorage.key(i);
        if (key && key.startsWith('chat_history_')) {
          // Extract session ID and check age
          const sessionId = key.replace('chat_history_', '');
          const messages = chatHistoryStorage.getHistory(sessionId);

          if (messages.length > 0) {
            const lastMessage = messages[messages.length - 1];
            const lastTimestamp = new Date(lastMessage.timestamp).getTime();

            if (lastTimestamp < cutoffTime) {
              chatHistoryStorage.clearHistory(sessionId);
            }
          }
        }
      }
    } catch (error) {
      logger.error('Failed to clean up the old chat sessions', error);
    }
  }
};

// Chat session management
export const chatSessionStorage = {
  getCurrentSessionId: () => {
    return safeSessionStorage.getItem('current_session_id');
  },

  setCurrentSessionId: (sessionId) => {
    if (!sessionId) return false;
    return safeSessionStorage.setItem('current_session_id', sessionId);
  },

  clearCurrentSession: () => {
    return safeSessionStorage.removeItem('current_session_id');
  }
};