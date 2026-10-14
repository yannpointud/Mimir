import { useState, useEffect, useCallback } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { documentsAPI, healthAPI } from '../../services/api';
import { getErrorMessage, safeFormatNumber, safeGetProperty, cn } from '../../utils/helpers';
import {
  FileText,
  Upload,
  Settings,
  Activity,
  TrendingUp,
  RefreshCw,
  AlertCircle,
  X
} from 'lucide-react';

const SECTIONS = [
  {
    href: '/admin/documents',
    name: 'Documents',
    icon: FileText,
    title: 'Documents',
    description: 'Index et statut des documents de la base documentaire'
  },
  {
    href: '/admin/upload',
    name: 'Importer',
    icon: Upload,
    title: 'Importer des documents',
    description: 'Ajoutez de nouveaux fichiers à la base documentaire'
  },
  {
    href: '/admin/config',
    name: 'Configuration',
    icon: Settings,
    title: 'Configuration',
    description: 'Paramètres système en lecture seule et sécurité du compte'
  },
  {
    href: '/admin/monitoring',
    name: 'Monitoring',
    icon: Activity,
    title: 'Monitoring',
    description: 'État de santé des services et journaux en temps réel'
  },
  {
    href: '/admin/analytics',
    name: 'Analytics',
    icon: TrendingUp,
    title: 'Analytics',
    description: 'Utilisation, performances et coûts IA'
  }
];

const StatTile = ({ label, value, tone = 'neutral' }) => {
  const dot = {
    neutral: 'bg-ink-faint',
    accent: 'bg-accent',
    success: 'bg-success',
    warning: 'bg-warning',
    danger: 'bg-danger',
  }[tone];

  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3 shadow-xs">
      <p className="flex items-center gap-2 text-xs font-medium text-ink-muted">
        <span className={cn('h-1.5 w-1.5 rounded-full', dot)} aria-hidden="true" />
        {label}
      </p>
      <p className="mt-1 font-serif text-[26px] font-semibold leading-tight text-ink tabular">{value}</p>
    </div>
  );
};

const AdminDashboard = () => {
  const location = useLocation();
  const [systemStats, setSystemStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(new Date());
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  // Get current page information
  const currentSection = SECTIONS.find(section => section.href === location.pathname) || {
    title: 'Panneau d\'administration',
    description: 'Gestion du système documentaire Mimir'
  };

  // Load system statistics (stable identity: only uses state setters)
  const loadSystemStats = useCallback(async () => {
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
  }, []);

  // Manual refresh: reload the stats and signal the child pages
  const handleRefresh = useCallback(() => {
    loadSystemStats();
    setRefreshTrigger(prev => prev + 1);
  }, [loadSystemStats]);

  // Load data on mount
  useEffect(() => {
    loadSystemStats();
  }, [loadSystemStats]);

  // Optimized automatic refresh
  useEffect(() => {
    let interval;

    // Smart polling function
    const startPolling = () => {
      interval = setInterval(() => {
        // Only if the page is visible
        if (!document.hidden) {
          handleRefresh(); // Also triggers the child pages
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
        handleRefresh(); // Also triggers the child pages
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
  }, [handleRefresh]);

  const isHealthy = safeGetProperty(systemStats, 'health.status') === 'healthy';
  const inProgress = safeGetProperty(systemStats, 'documents.by_status.pending', 0) + safeGetProperty(systemStats, 'documents.by_status.indexing', 0);
  const errorCount = safeGetProperty(systemStats, 'documents.by_status.error', 0);

  return (
    <div className="admin-scroll relative min-h-0 flex-1 overflow-y-auto">
      {/* Section tabs */}
      <div className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur supports-[backdrop-filter]:bg-surface/85">
        <nav
          aria-label="Administration"
          className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-3 [scrollbar-width:none] sm:px-6 [&::-webkit-scrollbar]:hidden"
        >
          {SECTIONS.map((section) => {
            const Icon = section.icon;
            const isCurrent = location.pathname === section.href;
            return (
              <Link
                key={section.href}
                to={section.href}
                aria-current={isCurrent ? 'page' : undefined}
                className={cn(
                  'relative flex h-12 shrink-0 items-center gap-2 px-3 text-sm font-medium transition-colors',
                  isCurrent ? 'text-ink' : 'text-ink-muted hover:text-ink'
                )}
              >
                <Icon className={cn('h-4 w-4', isCurrent ? 'text-accent' : 'text-ink-faint')} aria-hidden="true" />
                {section.name}
                <span
                  aria-hidden="true"
                  className={cn(
                    'absolute inset-x-2 bottom-0 h-0.5 rounded-full transition-colors',
                    isCurrent ? 'bg-accent' : 'bg-transparent'
                  )}
                />
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="mx-auto max-w-7xl px-4 pb-16 pt-7 sm:px-6 lg:pt-9">
        {/* Header */}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="page-title">{currentSection.title}</h1>
            <p className="mt-1.5 text-sm text-ink-muted">{currentSection.description}</p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-ink-muted tabular">
              Mis à jour à {lastRefresh.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}
            </span>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={loading}
              className="btn-secondary btn-sm"
              title="Actualiser les données"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} aria-hidden="true" />
              Actualiser
            </button>
          </div>
        </div>

        {/* Quick statistics: tiles render immediately (dash until loaded) so the page never shifts */}
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5" aria-busy={!systemStats}>
          <StatTile
            label="Documents"
            value={systemStats ? safeFormatNumber(safeGetProperty(systemStats, 'documents.total_documents', 0)) : '—'}
            tone="accent"
          />
          <StatTile
            label="Indexés"
            value={systemStats ? safeFormatNumber(safeGetProperty(systemStats, 'documents.by_status.indexed', 0)) : '—'}
            tone="success"
          />
          <StatTile
            label="En cours"
            value={systemStats ? safeFormatNumber(inProgress) : '—'}
            tone={inProgress > 0 ? 'warning' : 'neutral'}
          />
          <StatTile
            label="Erreurs"
            value={systemStats ? safeFormatNumber(errorCount) : '—'}
            tone={errorCount > 0 ? 'danger' : 'neutral'}
          />
          {systemStats ? (
            <div
              className={cn(
                'col-span-2 rounded-xl border px-4 py-3 shadow-xs sm:col-span-1',
                isHealthy ? 'border-success/25 bg-success-soft' : 'border-danger/25 bg-danger-soft'
              )}
            >
              <p className={cn('flex items-center gap-2 text-xs font-medium', isHealthy ? 'text-success-ink' : 'text-danger-ink')}>
                <span className="relative flex h-1.5 w-1.5" aria-hidden="true">
                  {isHealthy && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />}
                  <span className={cn('relative inline-flex h-1.5 w-1.5 rounded-full', isHealthy ? 'bg-success' : 'bg-danger')} />
                </span>
                Système
              </p>
              <p className={cn('mt-1 font-serif text-[26px] font-semibold leading-tight', isHealthy ? 'text-success-ink' : 'text-danger-ink')}>
                {isHealthy ? 'Opérationnel' : 'Erreur'}
              </p>
            </div>
          ) : (
            <div className="col-span-2 sm:col-span-1">
              <StatTile label="Système" value="—" />
            </div>
          )}
        </div>

        {/* Global error message */}
        {error && (
          <div role="alert" className="alert-danger mt-6">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <p className="flex-1">{error}</p>
            <button
              type="button"
              onClick={() => setError(null)}
              className="-my-1 -mr-2 flex h-7 w-7 items-center justify-center rounded-md hover:bg-danger/10"
              aria-label="Fermer le message d'erreur"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        )}

        {/* Page content */}
        <div className="mt-8">
          <Outlet context={{ onRefresh: handleRefresh, refreshTrigger, onUploadSuccess: handleRefresh }} />
        </div>
      </div>
    </div>
  );
};

export default AdminDashboard;
