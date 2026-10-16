import { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  Activity,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  XCircle,
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
import { getErrorMessage, formatRelativeDate, safeDisplayValue, cn } from '../../utils/helpers';
import { createLogger } from '../../utils/logger';

const logger = createLogger('StatusBar');

const CacheGauge = ({ title, stats, onClear, disabled }) => (
  <div>
    <div className="flex items-center justify-between">
      <span className="text-sm font-medium text-ink">{title}</span>
      <button
        type="button"
        onClick={onClear}
        disabled={disabled}
        className="text-xs font-medium text-danger underline-offset-2 hover:underline disabled:opacity-50"
      >
        Vider
      </button>
    </div>
    <div className="mt-2 flex items-center justify-between text-xs text-ink-muted tabular">
      <span>Utilisation</span>
      <span>
        {safeDisplayValue(stats.size, 0)}/{safeDisplayValue(stats.max_size, 0)}
        {' '}({Math.round(safeDisplayValue(stats.utilization, 0))}%)
      </span>
    </div>
    <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-line-soft" aria-hidden="true">
      <div
        className="h-full rounded-full bg-accent"
        style={{ width: `${safeDisplayValue(stats.utilization, 0)}%` }}
      />
    </div>
  </div>
);

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
      logger.error('Failed to load the monitoring data', error);
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
      logger.error('Failed to clear the cache', error);
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
      logger.error('Failed to rebuild the index', error);
      setError(getErrorMessage(error));
    } finally {
      setRebuildingIndex(false);
    }
  };

  // Normalize the different status shapes (object with `healthy`, boolean, string)
  const isServiceHealthy = (status) => {
    if (typeof status === 'object' && status !== null && 'healthy' in status) {
      return status.healthy;
    }
    if (typeof status === 'boolean') {
      return status;
    }
    return status === 'healthy' || status === 'ok';
  };

  const getStatusLabel = (status) => {
    if (typeof status === 'object' && status !== null && 'healthy' in status) {
      return status.healthy ? 'OK' : 'Erreur';
    }
    if (typeof status === 'boolean') {
      return status ? 'OK' : 'Erreur';
    }
    return typeof status === 'object' ? status.status : status;
  };

  const SERVICE_META = {
    database: { label: 'Base de données', icon: Database },
    faiss: { label: 'Index vectoriel', icon: BarChart3 },
    vector_store: { label: 'Index vectoriel', icon: Search },
    llm: { label: 'Service LLM', icon: Wifi },
    llm_api: { label: 'Service LLM', icon: Wifi },
    cache: { label: 'Cache', icon: HardDrive },
    email_service: { label: 'Service e-mail', icon: Mail },
  };

  // Short factual detail shown under each service name, from the health payload
  const getServiceDetail = (service, status) => {
    if (typeof status !== 'object' || status === null) return null;
    if (service === 'database' && status.document_count != null) return `${status.document_count} documents`;
    if ((service === 'llm_api' || service === 'llm') && status.model) return `${status.provider || ''} · ${status.model}`;
    if (status.vectors) return `${status.vectors} vecteurs`;
    return null;
  };

  if (loading && !healthData) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24">
        <LoadingSpinner size="lg" />
        <p className="text-sm text-ink-muted">Chargement du monitoring...</p>
      </div>
    );
  }

  const isHealthy = healthData?.status === 'healthy';

  return (
    <div className="space-y-6">
      {/* Error message */}
      {error && (
        <div role="alert" className="alert-danger">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-semibold">Erreur de monitoring</p>
            <p className="mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Global status */}
      {healthData && (
        <div
          className={cn(
            'flex items-center gap-4 rounded-xl border px-5 py-4',
            isHealthy ? 'border-success/25 bg-success-soft' : 'border-danger/25 bg-danger-soft'
          )}
        >
          <span
            className={cn(
              'flex h-10 w-10 shrink-0 items-center justify-center rounded-full',
              isHealthy ? 'bg-success text-white' : 'bg-danger text-white'
            )}
          >
            {isHealthy ? <CheckCircle className="h-5 w-5" aria-hidden="true" /> : <XCircle className="h-5 w-5" aria-hidden="true" />}
          </span>
          <div className="min-w-0">
            <h2 className={cn('font-semibold', isHealthy ? 'text-success-ink' : 'text-danger-ink')}>
              {isHealthy ? 'Système opérationnel' : 'Problème détecté'}
            </h2>
            <p className={cn('text-sm', isHealthy ? 'text-success-ink/80' : 'text-danger-ink/80')}>
              Dernière vérification : {formatRelativeDate(healthData.timestamp)}
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* System services */}
        {healthData?.checks && (
          <section className="card">
            <div className="card-header">
              <h2 className="card-title">
                <Cpu className="h-4 w-4 text-accent" aria-hidden="true" />
                Services système
              </h2>
            </div>

            <ul className="divide-y divide-line-soft">
              {Object.entries(healthData.checks).map(([service, status]) => {
                const meta = SERVICE_META[service] || { label: service, icon: Activity };
                const Icon = meta.icon;
                const healthy = isServiceHealthy(status);
                const detail = getServiceDetail(service, status);
                return (
                  <li key={service} className="flex items-center gap-3 px-5 py-3">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-sunken text-ink-muted">
                      <Icon className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-ink">{meta.label}</p>
                      {detail && <p className="truncate text-xs text-ink-muted">{detail}</p>}
                    </div>
                    <span className={cn('badge-dot', healthy ? 'badge-success' : 'badge-danger')}>
                      {getStatusLabel(status)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {/* Cache statistics */}
        {cacheStats && (
          <section className="card">
            <div className="card-header">
              <h2 className="card-title">
                <HardDrive className="h-4 w-4 text-accent" aria-hidden="true" />
                Cache système
              </h2>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => clearCache('all')}
                  disabled={clearingCache || rebuildingIndex}
                  className="btn-danger-ghost btn-sm"
                  title="Vider tout le cache"
                >
                  {clearingCache ? (
                    <LoadingSpinner size="sm" className="h-3.5 w-3.5 text-current" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  Vider
                </button>
                <button
                  type="button"
                  onClick={rebuildVectorIndex}
                  disabled={rebuildingIndex || clearingCache}
                  className="btn-secondary btn-sm"
                  title="Reconstruire l'index vectoriel FAISS"
                >
                  {rebuildingIndex ? (
                    <LoadingSpinner size="sm" className="h-3.5 w-3.5" />
                  ) : (
                    <Wrench className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  Reconstruire l&apos;index
                </button>
              </div>
            </div>

            <div className="card-body space-y-5">
              {/* Main cache */}
              {cacheStats.main_cache && (
                <CacheGauge title="Cache principal" stats={cacheStats.main_cache} onClear={() => clearCache('main')} disabled={clearingCache} />
              )}

              {/* Chat cache */}
              {cacheStats.chat_cache && (
                <CacheGauge title="Cache chat" stats={cacheStats.chat_cache} onClear={() => clearCache('chat')} disabled={clearingCache} />
              )}

              {/* Global statistics */}
              {cacheStats.global_stats && (
                <div className="grid grid-cols-2 gap-3 border-t border-line-soft pt-4">
                  <div className="rounded-lg bg-sunken px-4 py-3">
                    <p className="text-xs text-ink-muted">Taux de réussite</p>
                    <p className="mt-0.5 font-serif text-2xl font-semibold text-ink tabular">
                      {Math.round(safeDisplayValue(cacheStats.global_stats.hit_ratio, 0) * 100)}%
                    </p>
                  </div>
                  <div className="rounded-lg bg-sunken px-4 py-3">
                    <p className="text-xs text-ink-muted">Requêtes totales</p>
                    <p className="mt-0.5 font-serif text-2xl font-semibold text-ink tabular">
                      {safeDisplayValue(cacheStats.global_stats.total_requests, 0)}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </section>
        )}
      </div>

      {/* System logs - Full width */}
      <LogViewer />

      {/* Automatic update information */}
      <p className="flex items-center gap-2 text-xs text-ink-muted">
        <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
        Cette page se met à jour automatiquement toutes les 60 secondes.
        Dernière actualisation : {lastUpdate ? lastUpdate.toLocaleTimeString('fr-FR') : 'Jamais'}
      </p>
    </div>
  );
};

export default StatusBar;