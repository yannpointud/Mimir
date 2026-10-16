import { useState, useEffect, useCallback } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  Activity,
  Search,
  Download,
  Clock,
  Server,
  Monitor,
  AlertCircle,
  Info,
  AlertTriangle,
  Bug
} from 'lucide-react';

import LoadingSpinner from '../Common/LoadingSpinner';
import { adminAPI } from '../../services/api';
import { getErrorMessage, formatRelativeDate, cn } from '../../utils/helpers';
import { createLogger } from '../../utils/logger';

const logger = createLogger('LogViewer');

const LogViewer = () => {
  const { refreshTrigger } = useOutletContext();
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  // Filters state
  const [filters, setFilters] = useState({
    level: 'ALL',
    source: 'ALL',
    module: '',
    search: '',
    limit: 50
  });

  // Summary data
  const [summary, setSummary] = useState(null);

  // Separate state for search input to enable debouncing
  const [searchInput, setSearchInput] = useState(filters.search);

  // Load logs with current filters (new identity whenever a filter changes)
  const loadLogs = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await adminAPI.getSystemLogs(filters);
      setLogs(response.logs || []);
      setSummary(response.summary || {});
      setLastUpdate(new Date());

    } catch (error) {
      logger.error('Failed to load the logs', error);
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [filters]);

  // Load on mount, on every filter change and on each global refresh
  useEffect(() => {
    loadLogs();
  }, [loadLogs, refreshTrigger]);

  // Debounced search effect
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput !== filters.search) {
        setFilters(prev => ({ ...prev, search: searchInput }));
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [searchInput, filters.search]);

  // Handle filter changes for dropdowns (immediate)
  const handleFilterChange = (newFilters) => {
    setFilters(prev => ({ ...prev, ...newFilters }));
  };

  // Handle search input change (debounced)
  const handleSearchChange = (searchValue) => {
    setSearchInput(searchValue);
  };


  // Get level icon and color
  const getLevelDisplay = (level) => {
    const levelMap = {
      'DEBUG': { icon: Bug, className: 'badge-neutral' },
      'INFO': { icon: Info, className: 'badge-accent' },
      'WARN': { icon: AlertTriangle, className: 'badge-warning' },
      'WARNING': { icon: AlertTriangle, className: 'badge-warning' },
      'ERROR': { icon: AlertCircle, className: 'badge-danger' },
      'CRITICAL': { icon: AlertCircle, className: 'badge-danger font-semibold' }
    };

    return levelMap[level] || { icon: Info, className: 'badge-neutral' };
  };

  // Get source icon
  const getSourceIcon = (source) => {
    return source === 'backend' ? Server : Monitor;
  };

  // Format timestamp
  const formatTimestamp = (timestamp) => {
    try {
      const date = new Date(timestamp);
      return date.toLocaleString('fr-FR');
    } catch {
      return timestamp;
    }
  };

  // Export logs
  const exportLogs = () => {
    try {
      const dataStr = JSON.stringify(logs, null, 2);
      const dataBlob = new Blob([dataStr], { type: 'application/json' });
      const url = URL.createObjectURL(dataBlob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `system-logs-${new Date().toISOString().split('T')[0]}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      logger.error('Failed to export the logs', error);
    }
  };

  if (loading && !logs.length) {
    return (
      <div className="card flex flex-col items-center justify-center gap-4 py-16">
        <LoadingSpinner size="lg" />
        <p className="text-sm text-ink-muted">Chargement des logs système...</p>
      </div>
    );
  }

  return (
    <section className="card overflow-hidden">
      {/* Header */}
      <div className="card-header flex-wrap">
        <div>
          <h2 className="card-title">
            <Activity className="h-4 w-4 text-accent" aria-hidden="true" />
            Logs système
          </h2>
          <p className="mt-0.5 text-[13px] text-ink-muted">Logs backend et frontend en temps réel</p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdate && (
            <span className="text-xs text-ink-muted">
              Mis à jour {formatRelativeDate(lastUpdate.toISOString()).toLowerCase()}
            </span>
          )}
          <button
            type="button"
            onClick={exportLogs}
            disabled={!logs.length}
            className="btn-secondary btn-sm"
            title="Exporter les logs"
          >
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            Exporter
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="grid grid-cols-2 gap-3 border-b border-line-soft bg-sunken/50 px-5 py-4 lg:grid-cols-[1fr_1fr_2fr_1fr]">
        {/* Level */}
        <div>
          <label htmlFor="logs-level" className="field-label text-xs">Niveau</label>
          <select
            id="logs-level"
            value={filters.level}
            onChange={(e) => handleFilterChange({ level: e.target.value })}
            className="select h-9"
          >
            <option value="ALL">Tous</option>
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARN">WARN</option>
            <option value="ERROR">ERROR</option>
          </select>
        </div>

        {/* Source */}
        <div>
          <label htmlFor="logs-source" className="field-label text-xs">Source</label>
          <select
            id="logs-source"
            value={filters.source}
            onChange={(e) => handleFilterChange({ source: e.target.value })}
            className="select h-9"
          >
            <option value="ALL">Toutes</option>
            <option value="backend">Backend</option>
            <option value="frontend">Frontend</option>
          </select>
        </div>

        {/* Search */}
        <div className="col-span-2 lg:col-span-1">
          <label htmlFor="logs-search" className="field-label text-xs">Recherche</label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" aria-hidden="true" />
            <input
              id="logs-search"
              type="search"
              placeholder="Rechercher dans les messages..."
              value={searchInput}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="input-field h-9 pl-9"
            />
          </div>
        </div>

        {/* Limit */}
        <div className="col-span-2 lg:col-span-1">
          <label htmlFor="logs-limit" className="field-label text-xs">Limite</label>
          <select
            id="logs-limit"
            value={filters.limit}
            onChange={(e) => handleFilterChange({ limit: parseInt(e.target.value) })}
            className="select h-9"
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={200}>200</option>
          </select>
        </div>
      </div>

      {/* Summary */}
      {summary && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line-soft px-5 py-2.5 text-xs text-ink-muted tabular">
          <span>
            {summary.total_logs_count} logs disponibles
            ({summary.backend_logs_count} backend, {summary.frontend_logs_count} frontend)
          </span>
          <span>{logs.length} logs affichés</span>
        </div>
      )}

      {/* Error message */}
      {error && (
        <div className="px-5 pt-4">
          <div role="alert" className="alert-danger">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <div>
              <p className="font-semibold">Erreur de chargement</p>
              <p className="mt-0.5">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Logs list */}
      {logs.length === 0 ? (
        <div className="flex flex-col items-center px-6 py-14 text-center">
          <Activity className="h-8 w-8 text-ink-faint" aria-hidden="true" />
          <p className="mt-3 text-sm text-ink-muted">Aucun log trouvé avec les filtres actuels</p>
        </div>
      ) : (
        <ul className={cn('max-h-[620px] divide-y divide-line-soft overflow-y-auto transition-opacity', loading && 'opacity-60')}>
          {logs.map((log, index) => {
            const levelDisplay = getLevelDisplay(log.level);
            const SourceIcon = getSourceIcon(log.source);
            const LevelIcon = levelDisplay.icon;

            return (
              <li key={index} className="px-5 py-3 transition-colors hover:bg-sunken/60">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className={cn('w-[84px] justify-center', levelDisplay.className)}>
                    <LevelIcon className="h-3 w-3" aria-hidden="true" />
                    {log.level}
                  </span>
                  <span className="flex min-w-0 items-center gap-1.5 font-mono text-xs font-medium text-ink">
                    <SourceIcon className="h-3.5 w-3.5 shrink-0 text-ink-faint" aria-label={log.source} />
                    <span className="truncate">{log.module}</span>
                  </span>
                  <span className="ml-auto flex items-center gap-1 font-mono text-2xs text-ink-muted tabular">
                    <Clock className="h-3 w-3" aria-hidden="true" />
                    {formatTimestamp(log.timestamp)}
                  </span>
                </div>
                <p className="mt-1.5 break-words text-[13px] leading-relaxed text-ink sm:pl-[96px]">
                  {log.message}
                </p>
                {log.details && Object.keys(log.details).length > 0 && (
                  <details className="group mt-1.5 sm:pl-[96px]">
                    <summary className="cursor-pointer select-none text-xs font-medium text-accent-ink hover:underline">
                      Détails
                    </summary>
                    <pre className="mt-2 overflow-x-auto rounded-lg border border-line-soft bg-sunken p-3 font-mono text-xs leading-relaxed text-ink-muted">
                      {JSON.stringify(log.details, null, 2)}
                    </pre>
                  </details>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
};

export default LogViewer;