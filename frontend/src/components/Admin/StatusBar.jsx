import { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  Activity,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  Database,
  Cpu,
  HardDrive,
  Wifi,
  BarChart3,
  Trash2,
  Search,
  Mail,
  Wrench
} from 'lucide-react';

import LoadingSpinner from '../Common/LoadingSpinner';
import LogViewer from './LogViewer';

import { healthAPI, adminAPI } from '../../services/api';
import { getErrorMessage, formatRelativeDate, safeDisplayValue } from '../../utils/helpers';

const StatusBar = () => {
  const { onRefresh, refreshTrigger } = useOutletContext();
  const [healthData, setHealthData] = useState(null);
  const [cacheStats, setCacheStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [clearingCache, setClearingCache] = useState(false);
  const [rebuildingIndex, setRebuildingIndex] = useState(false);

  // Load monitoring data
  const loadMonitoringData = async () => {
    try {
      setLoading(true);
      setError(null);

      const [health, cache] = await Promise.all([
        healthAPI.getHealthStatus(),
        adminAPI.getCacheStats()
      ]);

      setHealthData(health);
      setCacheStats(cache);
      setLastUpdate(new Date());

    } catch (error) {
      console.error('Erreur lors du chargement du monitoring:', getErrorMessage(error));
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMonitoringData();
  }, []);

  // Listen to parent refreshTrigger for global refresh
  useEffect(() => {
    if (refreshTrigger > 0) {
      loadMonitoringData();
    }
  }, [refreshTrigger]);

  // Clear the cache
  const clearCache = async (cacheType = 'all') => {
    try {
      setClearingCache(true);
      await adminAPI.clearCache(cacheType);

      // Reload statistics
      await loadMonitoringData();
      onRefresh?.();

    } catch (error) {
      console.error('Erreur lors du vidage du cache:', getErrorMessage(error));
      setError(getErrorMessage(error));
    } finally {
      setClearingCache(false);
    }
  };

  // Rebuild the vector index
  const rebuildVectorIndex = async () => {
    try {
      setRebuildingIndex(true);
      await adminAPI.rebuildVectorIndex();

      // Reload statistics
      await loadMonitoringData();
      onRefresh?.();

    } catch (error) {
      console.error('Erreur lors du rebuild de l\'index:', getErrorMessage(error));
      setError(getErrorMessage(error));
    } finally {
      setRebuildingIndex(false);
    }
  };

  // Get the status icon
  const getStatusIcon = (status) => {
    // Handle objects with healthy property (boolean)
    if (typeof status === 'object' && status !== null && 'healthy' in status) {
      return status.healthy ?
        <CheckCircle className="h-5 w-5 text-green-600" /> :
        <XCircle className="h-5 w-5 text-red-600" />;
    }

    // Handle direct booleans
    if (typeof status === 'boolean') {
      return status ?
        <CheckCircle className="h-5 w-5 text-green-600" /> :
        <XCircle className="h-5 w-5 text-red-600" />;
    }

    // Handle strings (existing format)
    switch (status) {
      case 'healthy':
      case 'ok':
        return <CheckCircle className="h-5 w-5 text-green-600" />;
      case 'warning':
        return <AlertTriangle className="h-5 w-5 text-yellow-600" />;
      case 'error':
      case 'unhealthy':
        return <XCircle className="h-5 w-5 text-red-600" />;
      default:
        return <Clock className="h-5 w-5 text-gray-600" />;
    }
  };

  // Get background color for status
  const getStatusBgColor = (status) => {
    switch (status) {
      case 'healthy':
      case 'ok':
        return 'bg-green-50 border-green-200';
      case 'warning':
        return 'bg-yellow-50 border-yellow-200';
      case 'error':
      case 'unhealthy':
        return 'bg-red-50 border-red-200';
      default:
        return 'bg-gray-50 border-gray-200';
    }
  };

  if (loading && !healthData) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <LoadingSpinner size="lg" />
          <p className="mt-4 text-gray-600">Chargement du monitoring...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 max-w-7xl h-full">

      {/* Error message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
          <div className="flex">
            <AlertTriangle className="h-5 w-5 text-red-600 mr-2" />
            <div>
              <h3 className="text-sm font-medium text-red-900">Erreur de monitoring</h3>
              <p className="text-sm text-red-700 mt-1">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Global status */}
      {healthData && (
        <div className={`border rounded-lg p-6 mb-6 ${getStatusBgColor(healthData.status)}`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center">
              {getStatusIcon(healthData.status)}
              <div className="ml-3">
                <h3 className="text-lg font-semibold text-gray-900">
                  Statut Global : {healthData.status === 'healthy' ? 'Système Opérationnel' : 'Problème Détecté'}
                </h3>
                <p className="text-sm text-gray-600">
                  Dernière vérification : {formatRelativeDate(healthData.timestamp)}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* System services */}
        {healthData?.checks && (
          <div className="card p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
              <Cpu className="h-5 w-5 mr-2" />
              Services Système
            </h3>

            <div className="space-y-3">
              {Object.entries(healthData.checks).map(([service, status]) => (
                <div key={service} className="flex justify-between items-center py-3 border-b border-gray-100 last:border-b-0">
                  <div className="flex items-center">
                    {service === 'database' && <Database className="h-4 w-4 mr-2 text-gray-500" />}
                    {service === 'faiss' && <BarChart3 className="h-4 w-4 mr-2 text-gray-500" />}
                    {service === 'vector_store' && <Search className="h-4 w-4 mr-2 text-gray-500" />}
                    {service === 'llm' && <Wifi className="h-4 w-4 mr-2 text-gray-500" />}
                    {service === 'llm_api' && <Wifi className="h-4 w-4 mr-2 text-gray-500" />}
                    {service === 'cache' && <HardDrive className="h-4 w-4 mr-2 text-gray-500" />}
                    {service === 'email_service' && <Mail className="h-4 w-4 mr-2 text-gray-500" />}
                    <span className="text-sm font-medium text-gray-900 capitalize">
                      {service === 'faiss' ? 'Index Vectoriel' :
                       service === 'vector_store' ? 'Index Vectoriel' :
                       service === 'llm' ? 'Service LLM' :
                       service === 'llm_api' ? 'Service LLM' :
                       service === 'database' ? 'Base de Données' :
                       service === 'cache' ? 'Cache' :
                       service === 'email_service' ? 'Service Email' : service}
                    </span>
                  </div>
                  <div className="flex items-center">
                    <span className="mr-2 text-sm text-gray-600">
                      {typeof status === 'object' && status !== null && 'healthy' in status
                        ? (status.healthy ? 'OK' : 'Erreur')
                        : (typeof status === 'boolean'
                          ? (status ? 'OK' : 'Erreur')
                          : (typeof status === 'object' ? status.status : status))}
                    </span>
                    {typeof status === 'object' && status.vectors && (
                      <span className="mr-2 text-xs text-gray-500">
                        ({status.vectors} vecteurs)
                      </span>
                    )}
                    {getStatusIcon(status)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Cache statistics */}
        {cacheStats && (
          <div className="card p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900 flex items-center">
                <HardDrive className="h-5 w-5 mr-2" />
                Cache Système
              </h3>
              <div className="flex gap-2">
                <button
                  onClick={() => clearCache('all')}
                  disabled={clearingCache || rebuildingIndex}
                  className="btn-danger text-sm"
                  title="Vider tout le cache"
                >
                  {clearingCache ? (
                    <LoadingSpinner size="sm" className="mr-2" />
                  ) : (
                    <Trash2 className="h-4 w-4 mr-2" />
                  )}
                  Vider
                </button>
                <button
                  onClick={rebuildVectorIndex}
                  disabled={rebuildingIndex || clearingCache}
                  className="btn-secondary text-sm"
                  title="Reconstruire l'index vectoriel FAISS"
                >
                  {rebuildingIndex ? (
                    <LoadingSpinner size="sm" className="mr-2" />
                  ) : (
                    <Wrench className="h-4 w-4 mr-2" />
                  )}
                  Rebuild Index
                </button>
              </div>
            </div>

            <div className="space-y-4">
              {/* Main cache */}
              {cacheStats.main_cache && (
                <div>
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm font-medium text-gray-700">Cache Principal</span>
                    <button
                      onClick={() => clearCache('main')}
                      disabled={clearingCache}
                      className="text-xs text-red-600 hover:text-red-700"
                    >
                      Vider
                    </button>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-600">Utilisation</span>
                      <span className="text-gray-900">
                        {safeDisplayValue(cacheStats.main_cache.size, 0)}/{safeDisplayValue(cacheStats.main_cache.max_size, 0)}
                        ({Math.round(safeDisplayValue(cacheStats.main_cache.utilization, 0))}%)
                      </span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div
                        className="bg-blue-600 h-2 rounded-full"
                        style={{ width: `${safeDisplayValue(cacheStats.main_cache.utilization, 0)}%` }}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Chat cache */}
              {cacheStats.chat_cache && (
                <div>
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm font-medium text-gray-700">Cache Chat</span>
                    <button
                      onClick={() => clearCache('chat')}
                      disabled={clearingCache}
                      className="text-xs text-red-600 hover:text-red-700"
                    >
                      Vider
                    </button>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-600">Utilisation</span>
                      <span className="text-gray-900">
                        {safeDisplayValue(cacheStats.chat_cache.size, 0)}/{safeDisplayValue(cacheStats.chat_cache.max_size, 0)}
                        ({Math.round(safeDisplayValue(cacheStats.chat_cache.utilization, 0))}%)
                      </span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div
                        className="bg-green-600 h-2 rounded-full"
                        style={{ width: `${safeDisplayValue(cacheStats.chat_cache.utilization, 0)}%` }}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Global statistics */}
              {cacheStats.global_stats && (
                <div className="pt-3 border-t border-gray-200">
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div className="text-center">
                      <div className="text-lg font-semibold text-green-600">
                        {Math.round(safeDisplayValue(cacheStats.global_stats.hit_ratio, 0) * 100)}%
                      </div>
                      <div className="text-gray-600">Taux de réussite</div>
                    </div>
                    <div className="text-center">
                      <div className="text-lg font-semibold text-blue-600">
                        {safeDisplayValue(cacheStats.global_stats.total_requests, 0)}
                      </div>
                      <div className="text-gray-600">Requêtes totales</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* System logs - Full width */}
      <LogViewer onRefresh={onRefresh} />

      {/* Automatic update information */}
      <div className="mt-6 bg-gray-50 rounded-lg p-4">
        <div className="flex items-center text-sm text-gray-600">
          <RefreshCw className="h-4 w-4 mr-2" />
          <span>
            Cette page se met à jour automatiquement toutes les 60 secondes.
            Dernière actualisation : {lastUpdate ? lastUpdate.toLocaleTimeString() : 'Jamais'}
          </span>
        </div>
      </div>
    </div>
  );
};

export default StatusBar;