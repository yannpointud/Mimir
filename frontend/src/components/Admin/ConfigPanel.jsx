import { useState, useEffect } from 'react';
import {
  Settings,
  AlertTriangle,
  Info,
  Eye,
  EyeOff,
  Server,
  Cpu,
  HardDrive,
  Lock,
  Check
} from 'lucide-react';

import LoadingSpinner from '../Common/LoadingSpinner';

import { adminAPI, authAPI } from '../../services/api';
import { getErrorMessage, cn } from '../../utils/helpers';

const ConfigPanel = () => {
  const [config, setConfig] = useState(null);
  const [systemInfo, setSystemInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showSensitive, setShowSensitive] = useState({});

  // Password change state
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  });
  const [showPasswords, setShowPasswords] = useState({
    current: false,
    new: false,
    confirm: false,
  });
  const [passwordChanging, setPasswordChanging] = useState(false);
  const [passwordSuccess, setPasswordSuccess] = useState(null);
  const [passwordError, setPasswordError] = useState(null);

  // Load configuration and system information
  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);

      const [configData, systemData] = await Promise.all([
        adminAPI.getConfiguration(),
        adminAPI.getSystemInfo()
      ]);

      setConfig(configData);
      setSystemInfo(systemData);

    } catch (error) {
      console.error('Erreur lors du chargement de la configuration:', error);
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  // Handle password change submission
  const handlePasswordChange = async (e) => {
    e.preventDefault();
    setPasswordError(null);
    setPasswordSuccess(null);

    // Frontend validation
    if (passwordForm.newPassword.length < 8) {
      setPasswordError('Le nouveau mot de passe doit contenir au moins 8 caractères');
      return;
    }
    if (passwordForm.newPassword !== passwordForm.confirmPassword) {
      setPasswordError('Les mots de passe ne correspondent pas');
      return;
    }

    try {
      setPasswordChanging(true);
      await authAPI.changePassword(passwordForm.currentPassword, passwordForm.newPassword);
      setPasswordSuccess('Mot de passe modifié avec succès');
      setPasswordForm({ currentPassword: '', newPassword: '', confirmPassword: '' });
    } catch (err) {
      const data = err.response?.data;
      const errMsg = data?.error_message;
      if (typeof errMsg === 'object' && errMsg.errors) {
        setPasswordError(errMsg.errors.join('. '));
      } else if (typeof errMsg === 'string') {
        setPasswordError(errMsg);
      } else {
        setPasswordError(getErrorMessage(err));
      }
    } finally {
      setPasswordChanging(false);
    }
  };

  // Toggle display of sensitive values
  const toggleSensitive = (key) => {
    setShowSensitive(prev => ({
      ...prev,
      [key]: !prev[key]
    }));
  };

  // Check if a key is sensitive
  const isSensitiveKey = (key) => {
    const lowerKey = key.toLowerCase();

    // Exceptions: these keys contain sensitive words but are not secret
    const exceptions = [
      'api_version',
      'version',
      'model',
      'provider',
      'endpoint',
      'url'
    ];

    if (exceptions.some(exception => lowerKey.includes(exception))) {
      return false;
    }

    // Sensitive combinations (more precise)
    const sensitiveCombinations = [
      'api_key',
      'api-key',
      'apikey',
      'secret',
      'password',
      'token',
      'private_key',
      'private-key',
      'auth_key',
      'auth-key'
    ];

    return sensitiveCombinations.some(combination =>
      lowerKey.includes(combination)
    );
  };

  // Mask sensitive values
  const maskValue = (key, value) => {
    if (!isSensitiveKey(key) || showSensitive[key]) {
      return value;
    }

    if (typeof value === 'string' && value.length > 4) {
      return '•'.repeat(value.length - 4) + value.slice(-4);
    }

    return '••••••••';
  };

  // Organize configuration by categories
  const organizeConfig = (config) => {
    if (!config) return {};

    // Merge database_config and application_config
    const flatConfig = {
      ...(config.database_config || {}),
      ...(config.application_config || {})
    };

    const categories = {
      'Application': {},
      'Base de données': {},
      'LLM & IA': {},
      'Sécurité': {},
      'Email': {},
      'Stockage': {},
      'Monitoring': {},
      'Autres': {}
    };

    Object.entries(flatConfig).forEach(([key, value]) => {
      const lowerKey = key.toLowerCase();

      if (lowerKey.includes('database') || lowerKey.includes('db') || lowerKey.includes('sqlite')) {
        categories['Base de données'][key] = value;
      } else if (lowerKey.includes('llm') || lowerKey.includes('mistral') || lowerKey.includes('ai') || lowerKey.includes('embed')) {
        categories['LLM & IA'][key] = value;
      } else if (lowerKey.includes('jwt') || lowerKey.includes('auth') || lowerKey.includes('security') || lowerKey.includes('password')) {
        categories['Sécurité'][key] = value;
      } else if (lowerKey.includes('smtp') || lowerKey.includes('mail') || lowerKey.includes('email')) {
        categories['Email'][key] = value;
      } else if (lowerKey.includes('storage') || lowerKey.includes('path') || lowerKey.includes('dir') || lowerKey.includes('file')) {
        categories['Stockage'][key] = value;
      } else if (lowerKey.includes('log') || lowerKey.includes('monitor') || lowerKey.includes('health')) {
        categories['Monitoring'][key] = value;
      } else if (lowerKey.includes('api') || lowerKey.includes('app') || lowerKey.includes('version') || lowerKey.includes('port')) {
        categories['Application'][key] = value;
      } else {
        categories['Autres'][key] = value;
      }
    });

    // Remove empty categories
    Object.keys(categories).forEach(category => {
      if (Object.keys(categories[category]).length === 0) {
        delete categories[category];
      }
    });

    return categories;
  };

  const categorizedConfig = organizeConfig(config);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24">
        <LoadingSpinner size="lg" />
        <p className="text-sm text-ink-muted">Chargement de la configuration...</p>
      </div>
    );
  }

  const passwordFields = [
    { key: 'current', field: 'currentPassword', label: 'Mot de passe actuel', autoComplete: 'current-password' },
    { key: 'new', field: 'newPassword', label: 'Nouveau mot de passe', autoComplete: 'new-password', minLength: 8 },
    { key: 'confirm', field: 'confirmPassword', label: 'Confirmer le nouveau mot de passe', autoComplete: 'new-password', minLength: 8 },
  ];

  const systemRows = systemInfo ? [
    { label: 'Système', value: `${systemInfo.platform?.system} ${systemInfo.platform?.release}` },
    { label: 'Architecture', value: systemInfo.platform?.machine },
    { label: 'Python', value: systemInfo.platform?.python_version },
    systemInfo.hardware?.memory && {
      label: 'Mémoire',
      icon: Cpu,
      value: `${Math.round(systemInfo.hardware.memory.total / (1024**3))} Go`,
      extra: systemInfo.hardware.memory.available && `${Math.round(systemInfo.hardware.memory.available / (1024**3))} Go libres`,
    },
    systemInfo.hardware?.disk && {
      label: 'Espace disque',
      icon: HardDrive,
      value: `${Math.round(systemInfo.hardware.disk.total / (1024**3))} Go`,
      extra: systemInfo.hardware.disk.free && `${Math.round(systemInfo.hardware.disk.free / (1024**3))} Go libres`,
    },
    systemInfo.application?.version && { label: 'Version Mimir', value: systemInfo.application.version, mono: true },
  ].filter(Boolean) : [];

  return (
    <div className="grid items-start gap-6 lg:grid-cols-3">
      <div className="space-y-6">
        {/* Password change section */}
        <section className="card">
          <div className="card-header">
            <h2 className="card-title">
              <Lock className="h-4 w-4 text-accent" aria-hidden="true" />
              Mot de passe administrateur
            </h2>
          </div>

          <form onSubmit={handlePasswordChange} className="card-body space-y-4">
            {passwordSuccess && (
              <div role="status" className="alert-success">
                <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{passwordSuccess}</span>
              </div>
            )}

            {passwordError && (
              <div role="alert" className="alert-danger">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{passwordError}</span>
              </div>
            )}

            {passwordFields.map(({ key, field, label, autoComplete, minLength }) => (
              <div key={key}>
                <label htmlFor={`password-${key}`} className="field-label">
                  {label}
                </label>
                <div className="relative">
                  <input
                    id={`password-${key}`}
                    type={showPasswords[key] ? 'text' : 'password'}
                    value={passwordForm[field]}
                    onChange={(e) => setPasswordForm(prev => ({ ...prev, [field]: e.target.value }))}
                    className="input-field pr-10"
                    autoComplete={autoComplete}
                    required
                    minLength={minLength}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPasswords(prev => ({ ...prev, [key]: !prev[key] }))}
                    className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-md text-ink-faint hover:bg-sunken hover:text-ink"
                    aria-label={showPasswords[key] ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
                  >
                    {showPasswords[key] ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
                  </button>
                </div>
                {key === 'new' && <p className="field-hint">8 caractères minimum.</p>}
              </div>
            ))}

            <button
              type="submit"
              disabled={passwordChanging}
              className="btn-primary w-full"
            >
              {passwordChanging ? (
                <>
                  <LoadingSpinner size="sm" className="text-current" />
                  Modification en cours...
                </>
              ) : (
                'Changer le mot de passe'
              )}
            </button>
          </form>
        </section>

        {/* System information */}
        {systemInfo && (
          <section className="card">
            <div className="card-header">
              <h2 className="card-title">
                <Server className="h-4 w-4 text-accent" aria-hidden="true" />
                Informations système
              </h2>
            </div>
            <dl className="divide-y divide-line-soft px-5">
              {systemRows.map(({ label, value, extra, icon: Icon, mono }) => (
                <div key={label} className="flex items-baseline justify-between gap-4 py-3 text-sm">
                  <dt className="flex items-center gap-1.5 text-ink-muted">
                    {Icon && <Icon className="h-3.5 w-3.5" aria-hidden="true" />}
                    {label}
                  </dt>
                  <dd className={cn('text-right font-medium text-ink', mono && 'font-mono text-[13px]')}>
                    {value}
                    {extra && <span className="ml-1 font-normal text-ink-muted">({extra})</span>}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        )}
      </div>

      <div className="space-y-6 lg:col-span-2">
        {/* Read-only warning */}
        <div className="alert-info">
          <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-semibold">Mode lecture seule</p>
            <p className="mt-0.5">
              Cette interface affiche la configuration actuelle. Les modifications se font via les variables
              d&apos;environnement ou le fichier de configuration. Les valeurs sensibles sont masquées :
              cliquez sur <Eye className="inline h-3.5 w-3.5 align-[-2px]" aria-label="l'icône œil" /> pour les afficher.
            </p>
          </div>
        </div>

        {/* Error message */}
        {error && (
          <div role="alert" className="alert-danger">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <div>
              <p className="font-semibold">Erreur de chargement</p>
              <p className="mt-0.5">{error}</p>
            </div>
          </div>
        )}

        {/* Configuration by categories */}
        <div className="gap-6 xl:columns-2">
          {Object.entries(categorizedConfig).map(([category, configs]) => (
            <section key={category} className="card mb-6 break-inside-avoid overflow-hidden">
              <div className="card-header py-3">
                <h2 className="card-title">
                  <Settings className="h-4 w-4 text-ink-faint" aria-hidden="true" />
                  {category}
                </h2>
                <span className="badge-neutral tabular">{Object.keys(configs).length}</span>
              </div>

              <dl className="divide-y divide-line-soft">
                {Object.entries(configs).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between gap-4 px-5 py-2.5">
                    <dt className="min-w-0 truncate font-mono text-xs text-ink-muted" title={key}>
                      {key}
                    </dt>
                    <dd className="flex min-w-0 items-center gap-1">
                      <span className="truncate font-mono text-[13px] font-medium text-ink" title={isSensitiveKey(key) && !showSensitive[key] ? undefined : String(value)}>
                        {maskValue(key, String(value))}
                      </span>
                      {isSensitiveKey(key) && (
                        <button
                          type="button"
                          onClick={() => toggleSensitive(key)}
                          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-faint hover:bg-sunken hover:text-ink"
                          title={showSensitive[key] ? 'Masquer' : 'Afficher'}
                          aria-label={`${showSensitive[key] ? 'Masquer' : 'Afficher'} ${key}`}
                        >
                          {showSensitive[key] ? (
                            <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
                          ) : (
                            <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                          )}
                        </button>
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
};

export default ConfigPanel;