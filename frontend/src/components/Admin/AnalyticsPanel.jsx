import { useState, useEffect, useCallback } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  AlertCircle,
  BarChart3,
  ChevronRight,
  Cpu,
  Euro,
  HardDrive,
  MemoryStick,
  RefreshCw
} from 'lucide-react';

import LoadingSpinner from '../Common/LoadingSpinner';
import { adminAPI, usageAPI } from '../../services/api';
import { getErrorMessage, cn } from '../../utils/helpers';
import { getBudgetStatus } from '../../utils/budget';

const CHART_DAYS = 14;
const CHART_HEIGHT_PX = 112;

// Formats a euro amount with French decimal comma, 2 decimal places. Non-zero
// spend below one cent (typical for a few questions) reads "< 0,01", not "0,00".
const formatEuro = (value) => {
  const num = typeof value === 'number' ? value : 0;
  if (num > 0 && num < 0.01) {
    return '< 0,01';
  }
  return num.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const formatNumber = (value) => (value || 0).toLocaleString('fr-FR');

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
  return { normal: 'bg-success', warning: 'bg-warning', exceeded: 'bg-danger' }[status];
};

const budgetBadgeClass = (usage) => {
  const status = getBudgetStatus(usage.spent_today_eur, usage.daily_budget_eur);
  return { normal: 'badge-success', warning: 'badge-warning', exceeded: 'badge-danger' }[status];
};

const budgetBadgeCopy = (usage) => {
  const status = getBudgetStatus(usage.spent_today_eur, usage.daily_budget_eur);
  return {
    normal: 'Sous contrôle',
    warning: 'Approche du plafond',
    exceeded: 'Plafond atteint : nouvelles requêtes bloquées',
  }[status];
};

// One answer = one call of the generation model; embedding calls are excluded.
const isGenerationModel = (model) => !model.includes('embed');

// Ledger dates are UTC calendar days: offset 0 is today.
const utcDay = (offsetDays) => {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() - offsetDays);
  return date.toISOString().slice(0, 10);
};

const formatDayLabel = (isoDate) =>
  new Date(`${isoDate}T00:00:00Z`).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', timeZone: 'UTC' });

/**
 * Derives activity figures from the AI cost ledger (/admin/usage), the only
 * source that records every streamed answer.
 */
const buildActivity = (usage) => {
  const perDay = {};
  usage.history
    .filter(row => isGenerationModel(row.model))
    .forEach((row) => {
      const day = perDay[row.date] || { questions: 0, tokens: 0 };
      day.questions += row.calls;
      day.tokens += row.tokens;
      perDay[row.date] = day;
    });

  const sumSince = (field, days) => Object.entries(perDay)
    .filter(([date]) => date >= utcDay(days - 1))
    .reduce((total, [, day]) => total + day[field], 0);

  const questions30 = sumSince('questions', 30);

  return {
    today: usage.today_by_model
      .filter(row => isGenerationModel(row.model))
      .reduce((total, row) => total + row.calls, 0),
    week: sumSince('questions', 7),
    month: questions30,
    tokensPerQuestion: questions30 > 0 ? Math.round(sumSince('tokens', 30) / questions30) : 0,
    cost30: usage.history.reduce((total, row) => total + row.cost_eur, 0),
    days: Array.from({ length: CHART_DAYS }, (_, index) => {
      const date = utcDay(CHART_DAYS - 1 - index);
      return { date, questions: perDay[date]?.questions || 0 };
    }),
  };
};

const formatGigabytes = (bytes) => `${(bytes / 1024 ** 3).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} Go`;

// Resource load colour: calm until 70 %, warning until 90 %, then danger
const loadTone = (percent) => (percent >= 90 ? 'bg-danger' : percent >= 70 ? 'bg-warning' : 'bg-accent');

const ResourceGauge = ({ icon: Icon, label, percent, detail }) => (
  <div>
    <div className="flex items-baseline justify-between gap-3">
      <p className="flex items-center gap-1.5 text-sm text-ink-muted">
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        {label}
      </p>
      <p className="font-serif text-2xl font-semibold text-ink tabular">{Math.round(percent)} %</p>
    </div>
    <div
      className="mt-2 h-2 overflow-hidden rounded-full bg-line-soft"
      role="meter"
      aria-label={`${label} utilisé`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(percent)}
    >
      <div className={cn('h-full rounded-full', loadTone(percent))} style={{ width: `${percent}%` }} />
    </div>
    <p className="mt-1.5 text-xs text-ink-muted tabular">{detail}</p>
  </div>
);

const StatTile = ({ label, value, hint }) => (
  <div className="rounded-xl border border-line-soft bg-sunken/60 px-4 py-3">
    <p className="text-xs font-medium text-ink-muted">{label}</p>
    <p className="mt-1 font-serif text-[28px] font-semibold leading-tight text-ink tabular">{value}</p>
    <p className="mt-0.5 text-xs text-ink-muted">{hint}</p>
  </div>
);

const QuestionsChart = ({ days }) => {
  const max = Math.max(1, ...days.map(day => day.questions));
  const summary = days.map(day => `${formatDayLabel(day.date)} : ${day.questions}`).join(', ');

  return (
    <figure>
      <figcaption className="eyebrow">Questions par jour · {CHART_DAYS} derniers jours</figcaption>
      <div className="mt-4 flex items-end gap-1.5" role="img" aria-label={`Questions par jour : ${summary}`}>
        {days.map((day, index) => {
          const isToday = index === days.length - 1;
          const height = day.questions > 0 ? Math.max((day.questions / max) * CHART_HEIGHT_PX, 6) : 2;
          return (
            <div key={day.date} className="group flex flex-1 flex-col items-center justify-end" style={{ height: CHART_HEIGHT_PX + 18 }}>
              <span className={cn('mb-1 text-2xs font-medium text-ink-muted tabular', day.questions === 0 && 'invisible')}>
                {day.questions}
              </span>
              <div
                className={cn(
                  'w-full max-w-[40px] rounded-t-[5px] transition-colors',
                  day.questions === 0 ? 'bg-line' : isToday ? 'bg-accent' : 'bg-accent/40 group-hover:bg-accent/70'
                )}
                style={{ height }}
                title={`${formatDayLabel(day.date)} : ${day.questions} question${day.questions > 1 ? 's' : ''}`}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex gap-1.5 border-t border-line-soft pt-2" aria-hidden="true">
        {days.map((day, index) => {
          // On narrow screens only every third day (counted back from today) is labelled
          const labelledOnMobile = (days.length - 1 - index) % 3 === 0;
          return (
            <span
              key={day.date}
              className={cn(
                'flex min-w-0 flex-1 justify-center whitespace-nowrap text-2xs text-ink-muted tabular',
                !labelledOnMobile && 'invisible sm:visible',
                index === days.length - 1 && 'font-semibold text-ink'
              )}
            >
              {formatDayLabel(day.date)}
            </span>
          );
        })}
      </div>
    </figure>
  );
};

const AnalyticsPanel = () => {
  const { refreshTrigger } = useOutletContext();
  const [usageData, setUsageData] = useState(null);
  const [systemData, setSystemData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [systemError, setSystemError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  // AI cost ledger: fast, and the reference for spend and activity
  const loadUsage = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setUsageData(await usageAPI.getUsage());
      setLastUpdate(new Date());
    } catch (error) {
      console.error('Erreur lors du chargement des analytics:', getErrorMessage(error));
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, []);

  // Live server resources (fast endpoint, read straight from the host)
  const loadSystem = useCallback(async () => {
    try {
      setSystemError(null);
      setSystemData(await adminAPI.getSystemInfo());
    } catch (error) {
      console.error('Erreur lors du chargement des ressources serveur:', getErrorMessage(error));
      setSystemError(getErrorMessage(error));
    }
  }, []);

  // Load on mount and on each global refresh
  useEffect(() => {
    loadUsage();
    loadSystem();
  }, [loadUsage, loadSystem, refreshTrigger]);

  if (loading && !usageData) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24">
        <LoadingSpinner size="lg" />
        <p className="text-sm text-ink-muted">Chargement des analytics...</p>
      </div>
    );
  }

  const activity = usageData && buildActivity(usageData);

  return (
    <div className="space-y-6">
      {/* Error message */}
      {error && (
        <div role="alert" className="alert-danger">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-semibold">Erreur de chargement des coûts</p>
            <p className="mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {usageData && (
        <>
          {/* Coûts IA - spend gauge (focal), today by model, 30-day history (COST-02) */}
          <section className="card overflow-hidden">
            <div className="card-header">
              <h2 className="card-title">
                <Euro className="h-4 w-4 text-accent" aria-hidden="true" />
                Coûts IA
              </h2>
              <span className={cn('badge-dot', budgetBadgeClass(usageData))}>
                {budgetBadgeCopy(usageData)}
              </span>
            </div>

            <div className="grid lg:grid-cols-5">
              {/* Gauge - focal point: spend vs daily cap */}
              <div className="border-b border-line-soft p-5 lg:col-span-2 lg:border-b-0 lg:border-r">
                <p className="text-sm text-ink-muted">Dépense du jour</p>
                <p className="mt-2 font-serif text-[34px] font-semibold leading-none text-ink tabular">
                  {formatEuro(usageData.spent_today_eur)} €
                  <span className="ml-2 font-sans text-base font-normal text-ink-muted">
                    / {formatEuro(usageData.daily_budget_eur)} €
                  </span>
                </p>
                <div
                  className="mt-5 h-2.5 w-full overflow-hidden rounded-full bg-line-soft"
                  role="meter"
                  aria-label="Part du plafond quotidien consommée"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(budgetGaugeWidthPct(usageData))}
                >
                  <div
                    className={cn('h-full rounded-full', budgetGaugeFillClass(usageData))}
                    style={{ width: `${budgetGaugeWidthPct(usageData)}%` }}
                  />
                </div>
                <p className="mt-2 text-xs text-ink-muted tabular">
                  {Math.round(budgetGaugeWidthPct(usageData))} % du plafond quotidien consommé
                </p>
                <p className="mt-5 flex items-baseline justify-between border-t border-line-soft pt-4 text-sm">
                  <span className="text-ink-muted">Dépense sur 30 jours</span>
                  <span className="font-semibold text-ink tabular">{formatEuro(activity.cost30)} €</span>
                </p>
              </div>

              {/* Today by model and 30-day history */}
              <div className="space-y-5 p-5 lg:col-span-3">
                <div>
                  <p className="eyebrow mb-2">Aujourd&apos;hui par modèle</p>
                  {usageData.today_by_model.length > 0 ? (
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-line text-xs text-ink-muted">
                          <th className="py-2 text-left font-medium">Modèle</th>
                          <th className="py-2 text-right font-medium">Appels</th>
                          <th className="py-2 text-right font-medium">Tokens</th>
                          <th className="py-2 text-right font-medium">Coût (€)</th>
                        </tr>
                      </thead>
                      <tbody className="tabular">
                        {usageData.today_by_model.map((row) => (
                          <tr key={row.model} className="border-b border-line-soft last:border-0">
                            <td className="py-2 font-mono text-xs text-ink">{row.model}</td>
                            <td className="py-2 text-right text-ink-muted">{formatNumber(row.calls)}</td>
                            <td className="py-2 text-right text-ink-muted">{formatNumber(row.total_tokens)}</td>
                            <td className="py-2 text-right font-medium text-ink">{formatEuro(row.cost_eur)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <div className="rounded-lg bg-sunken px-4 py-3">
                      <p className="text-sm font-medium text-ink">Aucune consommation aujourd&apos;hui</p>
                      <p className="mt-0.5 text-xs text-ink-muted">
                        Aucun appel Mistral n&apos;a encore été enregistré pour la journée en cours.
                      </p>
                    </div>
                  )}
                </div>

                <details className="group">
                  <summary className="eyebrow flex cursor-pointer select-none items-center gap-1.5 hover:text-ink">
                    <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" aria-hidden="true" />
                    Historique (30 jours)
                    <span className="font-normal normal-case tracking-normal">· {usageData.history.length} lignes</span>
                  </summary>
                  {usageData.history.length > 0 ? (
                    <div className="mt-2 max-h-72 overflow-y-auto">
                      <table className="w-full text-sm">
                        <thead className="sticky top-0 bg-surface">
                          <tr className="border-b border-line text-xs text-ink-muted">
                            <th className="py-2 text-left font-medium">Date</th>
                            <th className="py-2 text-left font-medium">Modèle</th>
                            <th className="py-2 text-right font-medium">Appels</th>
                            <th className="py-2 text-right font-medium">Tokens</th>
                            <th className="py-2 text-right font-medium">Coût (€)</th>
                          </tr>
                        </thead>
                        <tbody className="tabular">
                          {usageData.history.map((row, idx) => (
                            <tr key={`${row.date}-${row.model}-${idx}`} className="border-b border-line-soft last:border-0">
                              <td className="py-2 text-ink-muted">{row.date}</td>
                              <td className="py-2 font-mono text-xs text-ink">{row.model}</td>
                              <td className="py-2 text-right text-ink-muted">{formatNumber(row.calls)}</td>
                              <td className="py-2 text-right text-ink-muted">{formatNumber(row.tokens)}</td>
                              <td className="py-2 text-right font-medium text-ink">{formatEuro(row.cost_eur)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="mt-2 text-sm text-ink-muted">
                      Aucun historique disponible sur les 30 derniers jours.
                    </p>
                  )}
                </details>
              </div>
            </div>
          </section>

          {/* Activity from the ledger */}
          <section className="card">
            <div className="card-header flex-wrap">
              <h2 className="card-title">
                <BarChart3 className="h-4 w-4 text-accent" aria-hidden="true" />
                Activité
              </h2>
              <span className="text-xs text-ink-muted">Une question = une réponse générée par le modèle</span>
            </div>
            <div className="card-body space-y-6">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatTile label="Questions aujourd'hui" value={formatNumber(activity.today)} hint="Depuis minuit (UTC)" />
                <StatTile label="Questions sur 7 jours" value={formatNumber(activity.week)} hint="Semaine glissante" />
                <StatTile label="Questions sur 30 jours" value={formatNumber(activity.month)} hint="Mois glissant" />
                <StatTile label="Tokens par question" value={formatNumber(activity.tokensPerQuestion)} hint="Moyenne sur 30 jours" />
              </div>
              <QuestionsChart days={activity.days} />
            </div>
          </section>
        </>
      )}

      {/* Live server resources */}
      <section className="card">
        <div className="card-header">
          <h2 className="card-title">
            <Cpu className="h-4 w-4 text-accent" aria-hidden="true" />
            Ressources du serveur
          </h2>
          {systemData && (
            <span className="text-xs text-ink-muted">
              {systemData.platform.system} {systemData.platform.machine} · {systemData.application.environment}
            </span>
          )}
        </div>
        {systemError ? (
          <div className="p-5">
            <div className="alert-danger">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <p>{systemError}</p>
            </div>
          </div>
        ) : !systemData ? (
          <div className="flex items-center gap-3 px-5 py-6 text-sm text-ink-muted">
            <LoadingSpinner size="sm" />
            Lecture des ressources…
          </div>
        ) : (
          <div className="grid gap-5 p-5 sm:grid-cols-3">
            <ResourceGauge
              icon={Cpu}
              label="Processeur"
              percent={systemData.hardware.cpu_percent}
              detail={`${systemData.hardware.cpu_count} cœurs`}
            />
            <ResourceGauge
              icon={MemoryStick}
              label="Mémoire"
              percent={systemData.hardware.memory.percent}
              detail={`${formatGigabytes(systemData.hardware.memory.used)} / ${formatGigabytes(systemData.hardware.memory.total)}`}
            />
            <ResourceGauge
              icon={HardDrive}
              label="Disque"
              percent={systemData.hardware.disk.percent}
              detail={`${formatGigabytes(systemData.hardware.disk.free)} libres`}
            />
          </div>
        )}
      </section>

      {/* Last refresh */}
      <p className="flex items-center gap-2 text-xs text-ink-muted">
        <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
        Dernière actualisation : {lastUpdate ? lastUpdate.toLocaleTimeString('fr-FR') : 'Jamais'}
      </p>
    </div>
  );
};

export default AnalyticsPanel;
