/**
 * Frontend logger.
 *
 * Warnings and errors always reach the browser console. VITE_ENABLE_LOGS
 * enables info logs, VITE_DEBUG_MODE adds debug logs, and VITE_LOG_TO_FILE
 * forwards every emitted entry to the backend (POST /api/v1/logs/frontend).
 */

// Environment configuration
const DEBUG_MODE = import.meta.env.VITE_DEBUG_MODE === 'true'
const ENABLE_LOGS = import.meta.env.VITE_ENABLE_LOGS === 'true'
const LOG_TO_FILE = import.meta.env.VITE_LOG_TO_FILE === 'true'

// Log levels
const LOG_LEVELS = {
  DEBUG: 0,
  INFO: 1,
  WARN: 2,
  ERROR: 3
}

// Lowest level emitted: warnings and errors are never filtered out
const MIN_LOG_LEVEL = !ENABLE_LOGS
  ? LOG_LEVELS.WARN
  : DEBUG_MODE ? LOG_LEVELS.DEBUG : LOG_LEVELS.INFO

// Method names, resolved at call time so test spies on console still apply
const CONSOLE_METHODS = {
  DEBUG: 'debug',
  INFO: 'info',
  WARN: 'warn',
  ERROR: 'error'
}

const EMOJIS = {
  DEBUG: '🔍',
  INFO: 'ℹ️',
  WARN: '⚠️',
  ERROR: '❌'
}

/**
 * Module-scoped logger with a standardized console format
 */
class Logger {
  constructor(module = 'App') {
    this.module = module
    this.startTime = Date.now()
  }

  /**
   * Core logging method with standardized format
   */
  _log(level, levelName, message, data = {}) {
    if (level < MIN_LOG_LEVEL) return

    const logEntry = {
      timestamp: new Date().toISOString(),
      level: levelName,
      module: this.module,
      message,
      timeSinceStart: `${Date.now() - this.startTime}ms`,
      url: window.location.href,
      userAgent: navigator.userAgent.split(' ')[0], // Simplified
      ...data
    }

    console[CONSOLE_METHODS[levelName]](`${EMOJIS[levelName]} ${levelName} [${this.module}] ${message}`, logEntry)

    if (LOG_TO_FILE) {
      this._sendToBackend(logEntry).catch(() => {
        // Silently ignore API errors to avoid infinite loops
      })
    }

    return logEntry
  }

  /**
   * Send log entry to backend API for file storage
   */
  async _sendToBackend(logEntry) {
    try {
      // Import axios dynamically to avoid circular dependencies
      const axios = (await import('axios')).default

      // Prepare log data for backend API
      const logData = {
        timestamp: logEntry.timestamp,
        level: logEntry.level,
        module: logEntry.module,
        message: logEntry.message
      }

      // Only add optional fields if they have values
      if (logEntry.url) logData.url = logEntry.url
      if (logEntry.userAgent) logData.userAgent = logEntry.userAgent
      if (logEntry.timeSinceStart) logData.timeSinceStart = logEntry.timeSinceStart

      // Only add extra_data if there are actually extra fields
      const extraFields = Object.fromEntries(
        Object.entries(logEntry).filter(([key]) =>
          !['timestamp', 'level', 'module', 'message', 'url', 'userAgent', 'timeSinceStart'].includes(key)
        )
      )

      if (Object.keys(extraFields).length > 0) {
        logData.extra_data = extraFields
      }

      await axios.post('/api/v1/logs/frontend', logData, {
        timeout: 5000,
        headers: {
          'Content-Type': 'application/json'
        }
      })
    } catch (error) {
      // Don't log API errors to avoid infinite loops
      // Just silently fail - console logs will still work
    }
  }

  /**
   * Debug level logging: needs VITE_ENABLE_LOGS and VITE_DEBUG_MODE
   */
  debug(message, data = {}) {
    return this._log(LOG_LEVELS.DEBUG, 'DEBUG', message, data)
  }

  /**
   * Info level logging: needs VITE_ENABLE_LOGS
   */
  info(message, data = {}) {
    return this._log(LOG_LEVELS.INFO, 'INFO', message, data)
  }

  /**
   * Warning level logging, always emitted
   */
  warn(message, data = {}) {
    return this._log(LOG_LEVELS.WARN, 'WARN', message, data)
  }

  /**
   * Error level logging with stack trace, always emitted
   */
  error(message, error = null, data = {}) {
    const errorData = { ...data }

    if (error) {
      errorData.error = {
        name: error.name,
        message: error.message,
        stack: error.stack,
        ...(error.cause && { cause: error.cause })
      }
    }

    return this._log(LOG_LEVELS.ERROR, 'ERROR', message, errorData)
  }
}

// Create module-specific loggers
export const createLogger = (module) => new Logger(module)

// Logger of the global error handlers below
const logger = new Logger('App')

export const apiLogger = new Logger('API')

// Global error handler for uncaught errors
window.addEventListener('error', (event) => {
  logger.error('🚨 UNCAUGHT ERROR', event.error, {
    message: event.message,
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno
  })
})

// Global unhandled promise rejection handler
window.addEventListener('unhandledrejection', (event) => {
  logger.error('🚨 UNHANDLED PROMISE REJECTION', null, {
    reason: event.reason,
    promise: '[Promise object]'
  })
})

// Initial log to show system is active
if (DEBUG_MODE) {
  logger.info('🚀 MIMIR FRONTEND LOGGER INITIALIZED', {
    debugMode: DEBUG_MODE,
    enableLogs: ENABLE_LOGS,
    logLevel: Object.keys(LOG_LEVELS)[MIN_LOG_LEVEL],
    environment: import.meta.env.MODE
  })
}
