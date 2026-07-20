import { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  TrendingUp,
  Users,
  Activity,
  Clock,
  BarChart3,
  AlertCircle,
  CheckCircle,
  RefreshCw,
  Database,
  Cpu,
  HardDrive,
  Zap,
  Globe,
  MessageCircle,
  Timer,
  Shield,
  AlertTriangle,
  UserCheck,
  Hash,
  Euro
} from 'lucide-react';

import LoadingSpinner from '../Common/LoadingSpinner';
import { adminAPI, usageAPI } from '../../services/api';
import { getErrorMessage, formatRelativeDate, safeDisplayValue } from '../../utils/helpers';

// Pure helper: maps spend-vs-cap ratio to a three-state budget status.
// Defensive on cap <= 0 (returns 'normal' rather than dividing by zero).
export const getBudgetStatus = (spent, cap) => {
  if (!cap || cap <= 0) {
    return 'normal';
  }
  const ratio = spent / cap;
  if (ratio >= 1.0) {
    return 'exceeded';
  }
  if (ratio >= 0.8) {
    return 'warning';
  }
  return 'normal';
};

// Formats a euro amount with French decimal comma, 2 decimal places.
const formatEuro = (value) => {
  const num = typeof value === 'number' ? value : 0;
  return num.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

// Gauge fill width capped at 100%, per the UI-SPEC contract.
const budgetGaugeWidthPct = (usage) => {
  if (!usage || !usage.daily_budget_eur || usage.daily_budget_eur <= 0) {
    return 0;
  }
  return Math.min(usage.spent_today_eur / usage.daily_budget_eur, 1) * 100;
};

// Gauge fill / badge color per budget state (green/yellow/red triptych).
const budgetGaugeFillClass = (usage) => {
  const status = getBudgetStatus(usage.spent_today_eur, usage.daily_budget_eur);
  return { normal: 'bg-green-600', warning: 'bg-yellow-500', exceeded: 'bg-red-600' }[status];
};

const budgetBadgeTextClass = (usage) => {
  const status = getBudgetStatus(usage.spent_today_eur, usage.daily_budget_eur);
  return { normal: 'text-green-600', warning: 'text-yellow-600', exceeded: 'text-red-600' }[status];
};

const budgetBadgeCopy = (usage) => {
  const status = getBudgetStatus(usage.spent_today_eur, usage.daily_budget_eur);
  return {
    normal: 'Sous contrôle',
    warning: 'Approche du plafond',
    exceeded: 'Plafond atteint — nouvelles requêtes bloquées',
  }[status];
};

const AnalyticsPanel = () => {
  const { onRefresh, refreshTrigger } = useOutletContext();
  const [analyticsData, setAnalyticsData] = useState(null);
  const [chatMetrics, setChatMetrics] = useState(null);
  const [usageData, setUsageData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  // Load analytics data
  const loadAnalyticsData = async () => {
    try {
      setLoading(true);
      setError(null);

      const [analytics, chatData, usage] = await Promise.all([
        adminAPI.getUsageAnalytics(),
        adminAPI.getChatMetrics(),
        usageAPI.getUsage()
      ]);

      setAnalyticsData(analytics);
      setChatMetrics(chatData);
      setUsageData(usage);
      setLastUpdate(new Date());

    } catch (error) {
      console.error('Erreur lors du chargement des analytics:', getErrorMessage(error));
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAnalyticsData();
  }, []);

  // Listen to parent refreshTrigger for global refresh
  useEffect(() => {
    if (refreshTrigger > 0) {
      loadAnalyticsData();
    }
  }, [refreshTrigger]);

  // Get the status icon
  const getStatusIcon = (status) => {
    switch (status) {
      case 'healthy':
      case 'ok':
        return <CheckCircle className="h-5 w-5 text-green-600" />;
      case 'warning':
        return <AlertCircle className="h-5 w-5 text-yellow-600" />;
      case 'error':
      case 'unhealthy':
        return <AlertCircle className="h-5 w-5 text-red-600" />;
      default:
        return <Clock className="h-5 w-5 text-gray-600" />;
    }
  };

  // Format percentages
  const formatPercentage = (value) => {
    return value ? `${Math.round(value)}%` : '0%';
  };

  // Format numbers
  const formatNumber = (value) => {
    return value ? value.toLocaleString() : '0';
  };

  if (loading && !analyticsData) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <LoadingSpinner size="lg" />
          <p className="mt-4 text-gray-600">Chargement des analytics...</p>
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
            <AlertCircle className="h-5 w-5 text-red-600 mr-2" />
            <div>
              <h3 className="text-sm font-medium text-red-900">Erreur d'analytics</h3>
              <p className="text-sm text-red-700 mt-1">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Main metrics - Row 1 */}
      {(chatMetrics || analyticsData?.overview) && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          {/* Requests per hour */}
          {chatMetrics && (
            <div className="card p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">Requêtes/heure</p>
                  <p className="text-3xl font-bold text-blue-600">
                    {chatMetrics.requests_last_hour || 0}
                  </p>
                </div>
                <Timer className="h-8 w-8 text-blue-600" />
              </div>
              <p className="text-xs text-gray-500 mt-2">
                Dernière heure
              </p>
            </div>
          )}

          {/* Requests 24h */}
          {analyticsData?.overview && (
            <div className="card p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">Requêtes 24h</p>
                  <p className="text-3xl font-bold text-blue-600">
                    {formatNumber(analyticsData.overview.total_requests_24h)}
                  </p>
                </div>
                <MessageCircle className="h-8 w-8 text-blue-600" />
              </div>
              <p className="text-xs text-gray-500 mt-2">
                Dernières 24 heures
              </p>
            </div>
          )}

          {/* Requests 7 days */}
          {analyticsData?.overview && (
            <div className="card p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">Requêtes 7j</p>
                  <p className="text-3xl font-bold text-blue-600">
                    {formatNumber(analyticsData.overview.total_requests_7d)}
                  </p>
                </div>
                <CheckCircle className="h-8 w-8 text-blue-600" />
              </div>
              <p className="text-xs text-gray-500 mt-2">
                7 derniers jours
              </p>
            </div>
          )}

          {/* Response time */}
          {chatMetrics && (
            <div className="card p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">Temps réponse</p>
                  <p className="text-3xl font-bold text-purple-600">
                    {chatMetrics.avg_response_time_ms || 0}s
                  </p>
                </div>
                <Clock className="h-8 w-8 text-purple-600" />
              </div>
              <p className="text-xs text-gray-500 mt-2">
                Moyenne actuelle
              </p>
            </div>
          )}
        </div>
      )}

      {/* Secondary metrics - Row 2 */}
      {chatMetrics && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          {/* Success rate */}
          <div className="card p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Taux succès</p>
                <p className="text-3xl font-bold text-green-600">
                  {chatMetrics.success_rate || 0}%
                </p>
              </div>
              <Shield className="h-8 w-8 text-green-600" />
            </div>
            <p className="text-xs text-gray-500 mt-2">
              Fiabilité système
            </p>
          </div>

          {/* Errors per hour */}
          <div className="card p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Erreurs/heure</p>
                <p className="text-3xl font-bold text-red-600">
                  {chatMetrics.errors_last_hour || 0}
                </p>
              </div>
              <AlertTriangle className="h-8 w-8 text-red-600" />
            </div>
            <p className="text-xs text-gray-500 mt-2">
              Incidents récents
            </p>
          </div>

          {/* Active sessions */}
          <div className="card p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Sessions actives</p>
                <p className="text-3xl font-bold text-purple-600">
                  {chatMetrics.active_sessions || 0}
                </p>
              </div>
              <UserCheck className="h-8 w-8 text-purple-600" />
            </div>
            <p className="text-xs text-gray-500 mt-2">
              Utilisateurs connectés
            </p>
          </div>

          {/* Tokens per request */}
          <div className="card p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Tokens/requête</p>
                <p className="text-3xl font-bold text-purple-600">
                  {chatMetrics.avg_tokens_per_request || 0}
                </p>
              </div>
              <Hash className="h-8 w-8 text-purple-600" />
            </div>
            <p className="text-xs text-gray-500 mt-2">
              Consommation moyenne
            </p>
          </div>
        </div>
      )}

      {/* Trends and Performance */}
      {(analyticsData?.trends || analyticsData?.performance) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          {/* Growth trends */}
          <div className="card p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
              <TrendingUp className="h-5 w-5 mr-2" />
              Tendances de croissance
            </h3>
            <div className="space-y-4">
              {analyticsData.trends && (
                <>
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-gray-600">Croissance 24h</span>
                    <span className="font-medium text-green-600">
                      {formatPercentage(analyticsData.trends.requests_growth_24h)}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-gray-600">Croissance 7j</span>
                    <span className="font-medium text-green-600">
                      {formatPercentage(analyticsData.trends.requests_growth_7d)}
                    </span>
                  </div>
                </>
              )}
              {analyticsData.performance && (
                <>
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-gray-600">Temps réponse 24h</span>
                    <span className="font-medium">{safeDisplayValue(analyticsData.performance.avg_response_time_24h, 0)}s</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-gray-600">Temps réponse 7j</span>
                    <span className="font-medium">{safeDisplayValue(analyticsData.performance.avg_response_time_7d, 0)}s</span>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Performance and success rate */}
          <div className="card p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
              <BarChart3 className="h-5 w-5 mr-2" />
              Performance et fiabilité
            </h3>
            <div className="space-y-4">
              {analyticsData.performance && (
                <>
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-gray-600">Taux succès 24h</span>
                    <span className="font-medium text-green-600">
                      {formatPercentage(analyticsData.performance.success_rate_24h)}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-gray-600">Taux succès 7j</span>
                    <span className="font-medium text-green-600">
                      {formatPercentage(analyticsData.performance.success_rate_7d)}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-gray-600">Pic d'usage</span>
                    <span className="font-medium">{analyticsData.performance.peak_usage_time}</span>
                  </div>
                </>
              )}
              {analyticsData.system && (
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Score santé</span>
                  <span className="font-medium text-blue-600">{analyticsData.system.health_score}%</span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Resources and tokens */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Token consumption */}
        {analyticsData?.resources && (
          <div className="card p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
              <Zap className="h-5 w-5 mr-2" />
              Consommation tokens
            </h3>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600">Tokens 24h</span>
                <span className="font-medium">{formatNumber(analyticsData.resources.total_tokens_24h)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600">Tokens 7j</span>
                <span className="font-medium">{formatNumber(analyticsData.resources.total_tokens_7d)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600">Moyenne/jour</span>
                <span className="font-medium">{formatNumber(analyticsData.resources.avg_tokens_per_day)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600">Estimation mensuelle</span>
                <span className="font-medium text-orange-600">{formatNumber(analyticsData.resources.estimated_monthly_tokens)}</span>
              </div>
            </div>
          </div>
        )}

        {/* System status */}
        {analyticsData?.system && (
          <div className="card p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
              <Cpu className="h-5 w-5 mr-2" />
              État système
            </h3>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600 flex items-center">
                  <Activity className="h-4 w-4 mr-1" />
                  Uptime estimé
                </span>
                <span className="font-medium text-green-600">{analyticsData.system.uptime_estimate}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600 flex items-center">
                  <AlertCircle className="h-4 w-4 mr-1" />
                  Taux erreur 24h
                </span>
                <span className="font-medium text-red-600">{formatPercentage(analyticsData.system.error_rate_24h)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600 flex items-center">
                  <CheckCircle className="h-4 w-4 mr-1" />
                  Score santé
                </span>
                <span className="font-medium text-blue-600">{analyticsData.system.health_score}%</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600 flex items-center">
                  <HardDrive className="h-4 w-4 mr-1" />
                  Taille logs
                </span>
                <span className="font-medium">{analyticsData.system.log_file_sizes ? Object.keys(analyticsData.system.log_file_sizes).length : 0} fichiers</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Coûts IA - spend gauge (focal), today by model, 30-day history (COST-02) */}
      <div className="card p-6 mb-8">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
          <Euro className="h-5 w-5 mr-2 text-primary-600" />
          Coûts IA
        </h3>

        {loading && !usageData && (
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <LoadingSpinner size="md" />
              <p className="mt-2 text-sm text-gray-600">Chargement des coûts...</p>
            </div>
          </div>
        )}

        {!loading && error && !usageData && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <div className="flex">
              <AlertCircle className="h-5 w-5 text-red-600 mr-2" />
              <div>
                <h4 className="text-sm text-red-900">Erreur de chargement des coûts</h4>
                <p className="text-sm text-red-700 mt-1">
                  Impossible de charger les données de coûts. Réessayez dans quelques instants.
                </p>
              </div>
            </div>
          </div>
        )}

        {usageData && (
          <>
            {/* Gauge - focal point: spend vs daily cap */}
            <div className="mb-6">
              <p className="text-sm text-gray-600 mb-2">Dépense du jour</p>
              <div className="flex items-end justify-between mb-2">
                <p className="text-3xl font-semibold text-primary-600">
                  {formatEuro(usageData.spent_today_eur)} € / {formatEuro(usageData.daily_budget_eur)} €
                </p>
                <span className={`text-xs ${budgetBadgeTextClass(usageData)}`}>
                  {budgetBadgeCopy(usageData)}
                </span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-3">
                <div
                  className={`h-3 rounded-full ${budgetGaugeFillClass(usageData)}`}
                  style={{ width: `${budgetGaugeWidthPct(usageData)}%` }}
                />
              </div>
            </div>

            {/* Today by model - secondary, recessive (smaller text, no accent) */}
            <div className="mb-6">
              {usageData.today_by_model && usageData.today_by_model.length > 0 ? (
                <table className="w-full text-sm text-gray-600">
                  <thead>
                    <tr className="text-xs text-gray-500 border-b border-gray-200">
                      <th className="text-left py-2">Modèle</th>
                      <th className="text-right py-2">Appels</th>
                      <th className="text-right py-2">Tokens</th>
                      <th className="text-right py-2">Coût (€)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usageData.today_by_model.map((row) => (
                      <tr key={row.model} className="border-b border-gray-100">
                        <td className="py-2">{row.model}</td>
                        <td className="text-right py-2">{formatNumber(row.calls)}</td>
                        <td className="text-right py-2">{formatNumber(row.total_tokens)}</td>
                        <td className="text-right py-2">{formatEuro(row.cost_eur)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="text-center py-4">
                  <p className="text-sm text-gray-600">Aucune consommation aujourd'hui</p>
                  <p className="text-xs text-gray-500 mt-1">
                    Aucun appel Mistral n'a encore été enregistré pour la journée en cours.
                  </p>
                </div>
              )}
            </div>

            {/* 30-day history - secondary, recessive (smaller text, no accent) */}
            <div>
              <p className="text-xs text-gray-500 mb-2">Historique (30 jours)</p>
              {usageData.history && usageData.history.length > 0 ? (
                <table className="w-full text-sm text-gray-600">
                  <thead>
                    <tr className="text-xs text-gray-500 border-b border-gray-200">
                      <th className="text-left py-2">Date</th>
                      <th className="text-left py-2">Modèle</th>
                      <th className="text-right py-2">Appels</th>
                      <th className="text-right py-2">Tokens</th>
                      <th className="text-right py-2">Coût (€)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usageData.history.map((row, idx) => (
                      <tr key={`${row.date}-${row.model}-${idx}`} className="border-b border-gray-100">
                        <td className="py-2">{row.date}</td>
                        <td className="py-2">{row.model}</td>
                        <td className="text-right py-2">{formatNumber(row.calls)}</td>
                        <td className="text-right py-2">{formatNumber(row.tokens)}</td>
                        <td className="text-right py-2">{formatEuro(row.cost_eur)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-sm text-gray-600 text-center py-4">
                  Aucun historique disponible sur les 30 derniers jours.
                </p>
              )}
            </div>
          </>
        )}
      </div>

      {/* Automatic update information */}
      <div className="mt-6 bg-gray-50 rounded-lg p-4">
        <div className="flex items-center text-sm text-gray-600">
          <RefreshCw className="h-4 w-4 mr-2" />
          <span>
            Cette page se met à jour automatiquement toutes les 30 secondes.
            Dernière actualisation : {lastUpdate ? lastUpdate.toLocaleTimeString() : 'Jamais'}
          </span>
        </div>
      </div>
    </div>
  );
};

export default AnalyticsPanel;