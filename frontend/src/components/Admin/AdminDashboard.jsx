import { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { documentsAPI, healthAPI } from '../../services/api';
import { getErrorMessage, safeFormatNumber, safeGetProperty } from '../../utils/helpers';
import {
  FileText,
  BarChart3,
  RefreshCw,
  AlertCircle,
  Activity
} from 'lucide-react';

const AdminDashboard = () => {
  const location = useLocation();
  const [systemStats, setSystemStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(new Date());
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  // Page header configuration
  const pageInfo = {
    '/admin/documents': {
      title: 'Gestion des Documents',
      description: 'Index et statut des documents du système'
    },
    '/admin/upload': {
      title: 'Upload de Documents',
      description: 'Ajouter de nouveaux documents au système'
    },
    '/admin/config': {
      title: 'Configuration Système',
      description: 'Consultation en lecture seule des paramètres système'
    },
    '/admin/monitoring': {
      title: 'Monitoring Système',
      description: 'État de santé et performance en temps réel'
    },
    '/admin/analytics': {
      title: 'Analytics & Usage',
      description: 'Analyse des performances et de l\'utilisation'
    }
  };

  // Get current page information
  const currentPageInfo = pageInfo[location.pathname] || {
    title: 'Panneau d\'Administration',
    description: 'Gestion du système documentaire Mimir'
  };


  // Load system statistics
  const loadSystemStats = async () => {
    try {
      setLoading(true);
      const [docsStats, healthStatus] = await Promise.all([
        documentsAPI.getStatistics(),
        healthAPI.getHealthStatus()
      ]);

      setSystemStats({
        documents: docsStats,
        health: healthStatus
      });

      setError(null);
    } catch (error) {
      console.error('Erreur lors du chargement des statistiques:', error);
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  };

  // Load data on mount
  useEffect(() => {
    loadSystemStats();
  }, []);

  // Optimized automatic refresh
  useEffect(() => {
    let interval;

    // Smart polling function
    const startPolling = () => {
      interval = setInterval(() => {
        // Only if the page is visible
        if (!document.hidden) {
          handleRefresh(); // Utilise handleRefresh pour déclencher aussi les enfants
        }
      }, 60000); // 60 seconds
    };

    // Start polling
    startPolling();

    // Handle page visibility
    const handleVisibilityChange = () => {
      if (document.hidden) {
        // Page hidden, stop polling
        if (interval) {
          clearInterval(interval);
          interval = null;
        }
      } else {
        // Page visible, restart polling and refresh immediately
        handleRefresh(); // Utilise handleRefresh pour déclencher aussi les enfants
        if (!interval) {
          startPolling();
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      if (interval) clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  // Manual refresh
  const handleRefresh = () => {
    loadSystemStats();
    setRefreshTrigger(prev => prev + 1);
  };

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-4 py-4 sm:px-6">
        <div className="max-w-7xl flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              {currentPageInfo.title}
            </h1>
            <p className="text-sm text-gray-600 mt-1">
              {currentPageInfo.description}
            </p>
          </div>
          <div className="flex items-center space-x-3">
            <span className="text-xs text-gray-500">
              Dernière mise à jour : {lastRefresh.toLocaleTimeString()}
            </span>
            <button
              onClick={handleRefresh}
              disabled={loading}
              className="btn-secondary text-sm"
              title="Actualiser les données"
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
              Actualiser
            </button>
          </div>
        </div>

        {/* Quick statistics */}
        {systemStats && (
          <div className="max-w-7xl mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
            {/* Total documents */}
            <div className="bg-blue-50 rounded-md p-2">
              <div className="flex items-center">
                <FileText className="h-4 w-4 text-blue-600" />
                <span className="ml-1.5 text-xs font-medium text-blue-900">Documents</span>
              </div>
              <p className="text-lg font-bold text-blue-900 mt-0.5">
                {safeFormatNumber(safeGetProperty(systemStats, 'documents.total_documents', 0))}
              </p>
            </div>

            {/* Indexed documents */}
            <div className="bg-green-50 rounded-md p-2">
              <div className="flex items-center">
                <BarChart3 className="h-4 w-4 text-green-600" />
                <span className="ml-1.5 text-xs font-medium text-green-900">Indexés</span>
              </div>
              <p className="text-lg font-bold text-green-900 mt-0.5">
                {safeFormatNumber(safeGetProperty(systemStats, 'documents.indexed', 0))}
              </p>
            </div>

            {/* Processing */}
            <div className="bg-yellow-50 rounded-md p-2">
              <div className="flex items-center">
                <RefreshCw className="h-4 w-4 text-yellow-600" />
                <span className="ml-1.5 text-xs font-medium text-yellow-900">En cours</span>
              </div>
              <p className="text-lg font-bold text-yellow-900 mt-0.5">
                {safeFormatNumber(
                  safeGetProperty(systemStats, 'documents.pending', 0) +
                  safeGetProperty(systemStats, 'documents.indexing', 0)
                )}
              </p>
            </div>

            {/* Documents with errors */}
            <div className="bg-red-50 rounded-md p-2">
              <div className="flex items-center">
                <AlertCircle className="h-4 w-4 text-red-600" />
                <span className="ml-1.5 text-xs font-medium text-red-900">Erreurs</span>
              </div>
              <p className="text-lg font-bold text-red-900 mt-0.5">
                {safeFormatNumber(safeGetProperty(systemStats, 'documents.error', 0))}
              </p>
            </div>

            {/* System status */}
            <div className={`rounded-md p-2 ${
              safeGetProperty(systemStats, 'health.status') === 'healthy'
                ? 'bg-green-50'
                : 'bg-red-50'
            }`}>
              <div className="flex items-center">
                <Activity className={`h-4 w-4 ${
                  safeGetProperty(systemStats, 'health.status') === 'healthy'
                    ? 'text-green-600'
                    : 'text-red-600'
                }`} />
                <span className={`ml-1.5 text-xs font-medium ${
                  safeGetProperty(systemStats, 'health.status') === 'healthy'
                    ? 'text-green-900'
                    : 'text-red-900'
                }`}>
                  Système
                </span>
              </div>
              <p className={`text-lg font-bold mt-0.5 ${
                safeGetProperty(systemStats, 'health.status') === 'healthy'
                  ? 'text-green-900'
                  : 'text-red-900'
              }`}>
                {safeGetProperty(systemStats, 'health.status') === 'healthy' ? 'OK' : 'Erreur'}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Global error message */}
      {error && (
        <div className="bg-red-50 border-l-4 border-red-400 p-4 mx-4 mt-4 max-w-7xl">
          <div className="flex">
            <div className="ml-3">
              <p className="text-sm text-red-700">{error}</p>
            </div>
            <button
              onClick={() => setError(null)}
              className="ml-auto text-red-400 hover:text-red-600"
            >
              ×
            </button>
          </div>
        </div>
      )}


      {/* Main content */}
      <div className="flex-1 overflow-hidden">
        <div className="h-full overflow-y-auto admin-scroll">
          <Outlet context={{ onRefresh: handleRefresh, refreshTrigger, onUploadSuccess: handleRefresh }} />
        </div>
      </div>
    </div>
  );
};

export default AdminDashboard;