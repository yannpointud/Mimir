import { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  Activity,
  Search,
  Filter,
  Download,
  Clock,
  Server,
  Monitor,
  AlertCircle,
  Info,
  AlertTriangle,
  Bug,
  CheckCircle
} from 'lucide-react';

import LoadingSpinner from '../Common/LoadingSpinner';
import { adminAPI } from '../../services/api';
import { getErrorMessage, formatRelativeDate, safeDisplayValue } from '../../utils/helpers';

const LogViewer = ({ onRefresh }) => {
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

  // Flag to avoid triggering filter effect on initial load
  const [isInitialized, setIsInitialized] = useState(false);

  // Load logs with current filters
  const loadLogs = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await adminAPI.getSystemLogs(filters);
      setLogs(response.logs || []);
      setSummary(response.summary || {});
      setLastUpdate(new Date());

    } catch (error) {
      console.error('Erreur lors du chargement des logs:', getErrorMessage(error));
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  // Initial load
  useEffect(() => {
    loadLogs();
  }, []);

  // Listen to parent refreshTrigger for global refresh
  useEffect(() => {
    if (refreshTrigger > 0) {
      loadLogs();
    }
  }, [refreshTrigger]);

  // Debounced search effect
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput !== filters.search) {
        setFilters(prev => ({ ...prev, search: searchInput }));
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [searchInput, filters.search]);

  // Automatic filter application (excluding initial load)
  useEffect(() => {
    if (!isInitialized) {
      setIsInitialized(true);
      return;
    }

    loadLogs();
  }, [filters.level, filters.source, filters.limit, filters.search]);

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
      'DEBUG': { icon: Bug, color: 'text-gray-600', bg: 'bg-gray-100' },
      'INFO': { icon: Info, color: 'text-blue-600', bg: 'bg-blue-100' },
      'WARN': { icon: AlertTriangle, color: 'text-yellow-600', bg: 'bg-yellow-100' },
      'WARNING': { icon: AlertTriangle, color: 'text-yellow-600', bg: 'bg-yellow-100' },
      'ERROR': { icon: AlertCircle, color: 'text-red-600', bg: 'bg-red-100' },
      'CRITICAL': { icon: AlertCircle, color: 'text-red-700', bg: 'bg-red-200' }
    };

    return levelMap[level] || { icon: Info, color: 'text-gray-600', bg: 'bg-gray-100' };
  };

  // Get source icon
  const getSourceIcon = (source) => {
    return source === 'backend' ? Server : Monitor;
  };

  // Format timestamp
  const formatTimestamp = (timestamp) => {
    try {
      const date = new Date(timestamp);
      return date.toLocaleString();
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
      console.error('Erreur lors de l\'export:', error);
    }
  };

  if (loading && !logs.length) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <LoadingSpinner size="lg" />
          <p className="mt-4 text-gray-600">Chargement des logs système...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="card p-6">
      {/* Header with filters */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center">
          <Activity className="h-5 w-5 text-gray-600 mr-2" />
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Logs Système</h3>
            <p className="text-sm text-gray-600 mt-1">
              Logs backend et frontend en temps réel
            </p>
          </div>
        </div>
        <div className="flex items-center space-x-3">
          {lastUpdate && (
            <span className="text-xs text-gray-500">
              Dernière maj : {formatRelativeDate(lastUpdate.toISOString())}
            </span>
          )}
          <button
            onClick={exportLogs}
            disabled={!logs.length}
            className="btn-secondary text-sm"
            title="Exporter les logs"
          >
            <Download className="h-4 w-4 mr-1" />
            Export
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
        {/* Level */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Niveau
          </label>
          <select
            value={filters.level}
            onChange={(e) => handleFilterChange({ level: e.target.value })}
            className="input text-sm"
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
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Source
          </label>
          <select
            value={filters.source}
            onChange={(e) => handleFilterChange({ source: e.target.value })}
            className="input text-sm"
          >
            <option value="ALL">Toutes</option>
            <option value="backend">Backend</option>
            <option value="frontend">Frontend</option>
          </select>
        </div>

        {/* Search */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Recherche
          </label>
          <div className="relative">
            <Search className="h-4 w-4 text-gray-400 absolute left-3 top-1/2 transform -translate-y-1/2" />
            <input
              type="text"
              placeholder="Rechercher..."
              value={searchInput}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="input text-sm pl-10"
            />
          </div>
        </div>

        {/* Limit */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Limite
          </label>
          <select
            value={filters.limit}
            onChange={(e) => handleFilterChange({ limit: parseInt(e.target.value) })}
            className="input text-sm"
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
        <div className="mb-4 p-3 bg-gray-50 rounded-lg">
          <div className="flex items-center justify-between text-sm text-gray-600">
            <span>
              {summary.total_logs_count} logs disponibles
              ({summary.backend_logs_count} backend, {summary.frontend_logs_count} frontend)
            </span>
            <span>
              {logs.length} logs affichés
            </span>
          </div>
        </div>
      )}

      {/* Error message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
          <div className="flex">
            <AlertCircle className="h-5 w-5 text-red-600 mr-2" />
            <div>
              <h3 className="text-sm font-medium text-red-900">Erreur de chargement</h3>
              <p className="text-sm text-red-700 mt-1">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Logs list */}
      {logs.length === 0 ? (
        <div className="p-8 text-center">
          <Activity className="h-8 w-8 text-gray-400 mx-auto mb-2" />
          <p className="text-gray-600">Aucun log trouvé avec les filtres actuels</p>
        </div>
      ) : (
        <div className="divide-y divide-gray-200">
          {logs.map((log, index) => {
            const levelDisplay = getLevelDisplay(log.level);
            const SourceIcon = getSourceIcon(log.source);
            const LevelIcon = levelDisplay.icon;

            return (
              <div key={index} className="p-4 hover:bg-gray-50 transition-colors">
                <div className="flex items-start space-x-3">
                  {/* Level badge */}
                  <div className={`flex items-center px-2 py-1 rounded-full ${levelDisplay.bg} ${levelDisplay.color}`}>
                    <LevelIcon className="h-3 w-3 mr-1" />
                    <span className="text-xs font-medium">{log.level}</span>
                  </div>

                  {/* Source icon */}
                  <div className="flex items-center">
                    <SourceIcon className={`h-4 w-4 ${log.source === 'backend' ? 'text-green-600' : 'text-blue-600'}`} />
                  </div>

                  {/* Log content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2">
                        <span className="text-sm font-medium text-gray-900">
                          {log.module}
                        </span>
                        <span className="text-xs text-gray-500">
                          {log.source}
                        </span>
                      </div>
                      <div className="flex items-center text-xs text-gray-500">
                        <Clock className="h-3 w-3 mr-1" />
                        {formatTimestamp(log.timestamp)}
                      </div>
                    </div>
                    <p className="text-sm text-gray-700 mt-1">
                      {log.message}
                    </p>
                    {log.details && Object.keys(log.details).length > 0 && (
                      <details className="mt-2">
                        <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">
                          Détails...
                        </summary>
                        <pre className="text-xs text-gray-600 mt-1 bg-gray-100 p-2 rounded overflow-x-auto">
                          {JSON.stringify(log.details, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default LogViewer;