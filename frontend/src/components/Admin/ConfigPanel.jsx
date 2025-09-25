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
import { getErrorMessage } from '../../utils/helpers';

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

  // Charger la configuration et les informations système
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

  // Basculer l'affichage des valeurs sensibles
  const toggleSensitive = (key) => {
    setShowSensitive(prev => ({
      ...prev,
      [key]: !prev[key]
    }));
  };

  // Vérifier si une clé est sensible
  const isSensitiveKey = (key) => {
    const lowerKey = key.toLowerCase();

    // Exceptions : ces clés contiennent des mots sensibles mais ne sont pas secrètes
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

    // Combinaisons sensibles (plus précises)
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

  // Masquer les valeurs sensibles
  const maskValue = (key, value) => {
    if (!isSensitiveKey(key) || showSensitive[key]) {
      return value;
    }

    if (typeof value === 'string' && value.length > 4) {
      return '•'.repeat(value.length - 4) + value.slice(-4);
    }

    return '••••••••';
  };

  // Organiser la configuration par catégories
  const organizeConfig = (config) => {
    if (!config) return {};

    // Fusionner database_config et application_config
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

    // Supprimer les catégories vides
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
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <LoadingSpinner size="lg" />
          <p className="mt-4 text-gray-600">Chargement de la configuration...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 max-w-7xl h-full">

      {/* Password change section */}
      <div className="card p-6 mb-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
          <Lock className="h-5 w-5 mr-2" />
          Changer le mot de passe administrateur
        </h3>

        {passwordSuccess && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-3 mb-4 flex items-center">
            <Check className="h-5 w-5 text-green-600 mr-2" />
            <span className="text-sm text-green-800">{passwordSuccess}</span>
          </div>
        )}

        {passwordError && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4 flex items-center">
            <AlertTriangle className="h-5 w-5 text-red-600 mr-2" />
            <span className="text-sm text-red-800">{passwordError}</span>
          </div>
        )}

        <form onSubmit={handlePasswordChange} className="space-y-4 max-w-md">
          {/* Current password */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Mot de passe actuel
            </label>
            <div className="relative">
              <input
                type={showPasswords.current ? 'text' : 'password'}
                value={passwordForm.currentPassword}
                onChange={(e) => setPasswordForm(prev => ({ ...prev, currentPassword: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 pr-10"
                required
              />
              <button
                type="button"
                onClick={() => setShowPasswords(prev => ({ ...prev, current: !prev.current }))}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {showPasswords.current ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {/* New password */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Nouveau mot de passe
            </label>
            <div className="relative">
              <input
                type={showPasswords.new ? 'text' : 'password'}
                value={passwordForm.newPassword}
                onChange={(e) => setPasswordForm(prev => ({ ...prev, newPassword: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 pr-10"
                required
                minLength={8}
              />
              <button
                type="button"
                onClick={() => setShowPasswords(prev => ({ ...prev, new: !prev.new }))}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {showPasswords.new ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {/* Confirm password */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Confirmer le nouveau mot de passe
            </label>
            <div className="relative">
              <input
                type={showPasswords.confirm ? 'text' : 'password'}
                value={passwordForm.confirmPassword}
                onChange={(e) => setPasswordForm(prev => ({ ...prev, confirmPassword: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 pr-10"
                required
                minLength={8}
              />
              <button
                type="button"
                onClick={() => setShowPasswords(prev => ({ ...prev, confirm: !prev.confirm }))}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {showPasswords.confirm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={passwordChanging}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center"
          >
            {passwordChanging ? (
              <>
                <LoadingSpinner size="sm" />
                <span className="ml-2">Modification en cours...</span>
              </>
            ) : (
              'Changer le mot de passe'
            )}
          </button>
        </form>
      </div>

      {/* Avertissement lecture seule */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
        <div className="flex">
          <Info className="h-5 w-5 text-blue-600 mr-2 mt-0.5" />
          <div>
            <h3 className="text-sm font-medium text-blue-900">Mode lecture seule</h3>
            <p className="text-sm text-blue-700 mt-1">
              Cette interface affiche la configuration actuelle en lecture seule.
              Les modifications doivent être effectuées via les variables d&apos;environnement ou le fichier de configuration.
            </p>
          </div>
        </div>
      </div>

      {/* Message d'erreur */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
          <div className="flex">
            <AlertTriangle className="h-5 w-5 text-red-600 mr-2" />
            <div>
              <h3 className="text-sm font-medium text-red-900">Erreur de chargement</h3>
              <p className="text-sm text-red-700 mt-1">{error}</p>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Informations système */}
        {systemInfo && (
          <div className="card p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
              <Server className="h-5 w-5 mr-2" />
              Informations Système
            </h3>

            <div className="space-y-4">
              {/* Système d'exploitation */}
              <div className="flex justify-between items-center py-2 border-b border-gray-100">
                <span className="text-sm font-medium text-gray-600">Système</span>
                <span className="text-sm text-gray-900">
                  {systemInfo.platform?.system} {systemInfo.platform?.release}
                </span>
              </div>

              {/* Architecture */}
              <div className="flex justify-between items-center py-2 border-b border-gray-100">
                <span className="text-sm font-medium text-gray-600">Architecture</span>
                <span className="text-sm text-gray-900">
                  {systemInfo.platform?.machine}
                </span>
              </div>

              {/* Version Python */}
              <div className="flex justify-between items-center py-2 border-b border-gray-100">
                <span className="text-sm font-medium text-gray-600">Python</span>
                <span className="text-sm text-gray-900">
                  {systemInfo.platform?.python_version}
                </span>
              </div>

              {/* Mémoire */}
              {systemInfo.hardware?.memory && (
                <div className="flex justify-between items-center py-2 border-b border-gray-100">
                  <span className="text-sm font-medium text-gray-600 flex items-center">
                    <Cpu className="h-4 w-4 mr-1" />
                    Mémoire
                  </span>
                  <span className="text-sm text-gray-900">
                    {Math.round(systemInfo.hardware.memory.total / (1024**3))} GB
                    {systemInfo.hardware.memory.available && (
                      <span className="text-gray-500 ml-1">
                        ({Math.round(systemInfo.hardware.memory.available / (1024**3))} GB libre)
                      </span>
                    )}
                  </span>
                </div>
              )}

              {/* Espace disque */}
              {systemInfo.hardware?.disk && (
                <div className="flex justify-between items-center py-2 border-b border-gray-100">
                  <span className="text-sm font-medium text-gray-600 flex items-center">
                    <HardDrive className="h-4 w-4 mr-1" />
                    Espace disque
                  </span>
                  <span className="text-sm text-gray-900">
                    {Math.round(systemInfo.hardware.disk.total / (1024**3))} GB
                    {systemInfo.hardware.disk.free && (
                      <span className="text-gray-500 ml-1">
                        ({Math.round(systemInfo.hardware.disk.free / (1024**3))} GB libre)
                      </span>
                    )}
                  </span>
                </div>
              )}

              {/* Version de l'application */}
              {systemInfo.application?.version && (
                <div className="flex justify-between items-center py-2">
                  <span className="text-sm font-medium text-gray-600">Version Mimir</span>
                  <span className="text-sm text-gray-900 font-mono">
                    {systemInfo.application.version}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Configuration par catégories */}
        <div className="space-y-6">
          {Object.entries(categorizedConfig).map(([category, configs]) => (
            <div key={category} className="card p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">
                {category}
              </h3>

              <div className="space-y-3">
                {Object.entries(configs).map(([key, value]) => (
                  <div key={key} className="flex justify-between items-center py-2 border-b border-gray-100 last:border-b-0">
                    <span className="text-sm font-medium text-gray-600">
                      {key}
                    </span>
                    <div className="flex items-center">
                      <span className="text-sm text-gray-900 font-mono mr-2">
                        {maskValue(key, String(value))}
                      </span>
                      {isSensitiveKey(key) && (
                        <button
                          onClick={() => toggleSensitive(key)}
                          className="text-gray-400 hover:text-gray-600"
                          title={showSensitive[key] ? 'Masquer' : 'Afficher'}
                        >
                          {showSensitive[key] ? (
                            <EyeOff className="h-4 w-4" />
                          ) : (
                            <Eye className="h-4 w-4" />
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Légende */}
      <div className="mt-8 bg-gray-50 rounded-lg p-4">
        <h4 className="text-sm font-medium text-gray-900 mb-2">Légende</h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm text-gray-600">
          <div className="flex items-center">
            <Eye className="h-4 w-4 mr-2" />
            <span>Cliquez pour afficher/masquer les valeurs sensibles</span>
          </div>
          <div className="flex items-center">
            <Settings className="h-4 w-4 mr-2" />
            <span>Configuration en lecture seule</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ConfigPanel;