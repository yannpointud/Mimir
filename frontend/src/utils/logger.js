/**
 * Conditional Logging System for Mimir Frontend
 * 
 * This module provides a comprehensive logging system that respects
 * the VITE_DEBUG_MODE environment variable for conditional logging.
 * Includes rich context, timing, and error tracking.
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

// Current log level (DEBUG if debug mode, INFO otherwise)
const CURRENT_LOG_LEVEL = DEBUG_MODE ? LOG_LEVELS.DEBUG : LOG_LEVELS.INFO

/**
 * Enhanced logger with conditional output and rich context
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
    if (!ENABLE_LOGS) return
    if (level < CURRENT_LOG_LEVEL) return

    const timestamp = new Date().toISOString()
    const timeSinceStart = Date.now() - this.startTime
    
    const logEntry = {
      timestamp,
      level: levelName,
      module: this.module,
      message,
      timeSinceStart: `${timeSinceStart}ms`,
      url: window.location.href,
      userAgent: navigator.userAgent.split(' ')[0], // Simplified
      ...data
    }

    // Different console methods for different levels
    const consoleMethods = {
      DEBUG: console.debug,
      INFO: console.info,
      WARN: console.warn,
      ERROR: console.error
    }

    const consoleMethod = consoleMethods[levelName] || console.log
    
    // Enhanced formatting with emojis for better visibility
    const emoji = {
      DEBUG: '🔍',
      INFO: 'ℹ️',
      WARN: '⚠️',
      ERROR: '❌'
    }[levelName]

    consoleMethod(`${emoji} ${levelName} [${this.module}] ${message}`, logEntry)
    
    // Send to backend if LOG_TO_FILE is enabled
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

      // Send to backend API
      await axios.post('/api/v1/logs/frontend', logData, {
        timeout: 5000, // 5 second timeout
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
   * Debug level logging - only shown when DEBUG_MODE=true
   */
  debug(message, data = {}) {
    return this._log(LOG_LEVELS.DEBUG, 'DEBUG', message, data)
  }

  /**
   * Info level logging
   */
  info(message, data = {}) {
    return this._log(LOG_LEVELS.INFO, 'INFO', message, data)
  }

  /**
   * Warning level logging
   */
  warn(message, data = {}) {
    return this._log(LOG_LEVELS.WARN, 'WARN', message, data)
  }

  /**
   * Error level logging with stack trace
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

  /**
   * Performance timing helper
   */
  time(label) {
    if (!DEBUG_MODE) return { end: () => {} }
    
    const start = performance.now()
    this.debug(`⏱️ TIMER START: ${label}`)
    
    return {
      end: () => {
        const duration = performance.now() - start
        this.debug(`⏱️ TIMER END: ${label}`, { duration: `${duration.toFixed(2)}ms` })
        return duration
      }
    }
  }

  /**
   * Network request logging helper
   */
  logRequest(method, url, options = {}) {
    const requestId = Math.random().toString(36).substr(2, 9)
    const start = performance.now()
    
    this.debug(`🌐 REQUEST START: ${method} ${url}`, {
      requestId,
      method,
      url,
      headers: options.headers,
      body: options.body ? (typeof options.body === 'string' ? options.body.substring(0, 200) + '...' : '[Object]') : undefined
    })

    return {
      requestId,
      logResponse: (response, error = null) => {
        const duration = performance.now() - start
        
        if (error) {
          this.error(`🌐 REQUEST ERROR: ${method} ${url}`, error, {
            requestId,
            duration: `${duration.toFixed(2)}ms`,
            method,
            url
          })
        } else {
          const level = response?.status >= 400 ? 'warn' : 'debug'
          this[level](`🌐 REQUEST COMPLETE: ${method} ${url}`, {
            requestId,
            status: response?.status,
            statusText: response?.statusText,
            duration: `${duration.toFixed(2)}ms`,
            headers: response?.headers ? response.headers : undefined
          })
        }
      }
    }
  }

  /**
   * Navigation/routing logging
   */
  logNavigation(from, to, trigger = 'user') {
    this.debug(`🧭 NAVIGATION: ${from} → ${to}`, {
      from,
      to,
      trigger,
      timestamp: Date.now()
    })
  }

  /**
   * Component lifecycle logging
   */
  logComponentLifecycle(componentName, event, props = {}) {
    this.debug(`⚛️ COMPONENT ${event.toUpperCase()}: ${componentName}`, {
      component: componentName,
      event,
      props: Object.keys(props).length > 0 ? props : undefined
    })
  }

  /**
   * User interaction logging
   */
  logUserAction(action, element, data = {}) {
    this.debug(`👆 USER ACTION: ${action}`, {
      action,
      element,
      ...data
    })
  }

  /**
   * State change logging
   */
  logStateChange(stateName, oldValue, newValue, source = 'unknown') {
    this.debug(`🔄 STATE CHANGE: ${stateName}`, {
      stateName,
      oldValue,
      newValue,
      source
    })
  }

  /**
   * Error boundary logging
   */
  logErrorBoundary(error, errorInfo) {
    this.error('🚨 ERROR BOUNDARY CAUGHT', error, {
      errorInfo,
      componentStack: errorInfo.componentStack
    })
  }

  /**
   * API error helper
   */
  logApiError(endpoint, method, status, error) {
    this.error(`🔥 API ERROR: ${method} ${endpoint}`, error, {
      endpoint,
      method,
      status,
      timestamp: Date.now()
    })
  }

  /**
   * Cache operation logging
   */
  logCacheOperation(operation, key, hit = null, data = {}) {
    this.debug(`⚡ CACHE ${operation.toUpperCase()}: ${key}`, {
      operation,
      key,
      hit,
      ...data
    })
  }

  /**
   * Performance monitoring
   */
  logPerformance(metric, value, unit = 'ms') {
    this.debug(`📊 PERFORMANCE: ${metric}`, {
      metric,
      value,
      unit,
      timestamp: Date.now()
    })
  }
}

// Create module-specific loggers
export const createLogger = (module) => new Logger(module)

// Default app logger
export const logger = new Logger('App')

// Specialized loggers for common modules
export const apiLogger = new Logger('API')
export const routerLogger = new Logger('Router')
export const componentLogger = new Logger('Components')
export const stateLogger = new Logger('State')

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
    logLevel: Object.keys(LOG_LEVELS)[CURRENT_LOG_LEVEL],
    environment: import.meta.env.MODE
  })
}

// Export configuration for other modules
export const loggerConfig = {
  debugMode: DEBUG_MODE,
  enableLogs: ENABLE_LOGS,
  logLevel: CURRENT_LOG_LEVEL
}

export default logger