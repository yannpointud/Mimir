import { useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { ArrowLeft, Eye, EyeOff, AlertCircle } from 'lucide-react';

import LoadingSpinner from '../Common/LoadingSpinner';
import BrandMark from '../Common/BrandMark';
import { APP_NAME, COMPANY_NAME } from '../../config/brand';

import { useAuth } from '../../hooks/useAuth';

const AdminLogin = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { login, isAuthenticated, loading } = useAuth();

  // Redirect if already logged in
  if (isAuthenticated && !loading) {
    return <Navigate to="/admin" replace />;
  }

  // Show loading during initial verification
  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-canvas">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!username.trim() || !password) {
      setError('Veuillez remplir tous les champs');
      return;
    }

    setIsSubmitting(true);

    try {
      const result = await login(username.trim(), password);

      if (!result.success) {
        setError(result.error || 'Erreur de connexion');
      }
    } catch (error) {
      setError('Une erreur inattendue s\'est produite');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="grid min-h-dvh bg-canvas lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      {/* Brand panel */}
      <aside className="relative hidden overflow-hidden bg-nav text-nav-ink lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -right-40 -top-40 h-[520px] w-[520px] rounded-full border-[56px] border-accent-bright/[0.07]"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-24 -left-24 h-72 w-72 rounded-full bg-accent/30 blur-3xl"
        />

        <div className="relative flex items-center gap-3">
          <BrandMark className="h-8 w-8 text-accent-bright" />
          <span className="font-serif text-2xl font-semibold">{APP_NAME}</span>
          <span className="h-6 w-px bg-white/15" aria-hidden="true" />
          <span className="text-sm font-medium text-nav-muted">{COMPANY_NAME}</span>
        </div>

        <div className="relative max-w-md">
          <p className="font-serif text-[34px] font-semibold leading-[1.15] tracking-[-0.01em]">
            Votre documentation, des réponses sourcées.
          </p>
          <p className="mt-4 text-[15px] leading-relaxed text-nav-muted">
            Administrez la base documentaire, suivez la santé du système et maîtrisez les coûts IA.
          </p>
        </div>

        <p className="relative text-xs text-nav-muted">
          Accès réservé aux administrateurs autorisés · Toutes les connexions sont enregistrées
        </p>
      </aside>

      {/* Form */}
      <main className="flex flex-col justify-center px-4 py-12 sm:px-8">
        <div className="mx-auto w-full max-w-sm animate-slide-up">
          <div className="flex items-center gap-2.5 lg:hidden">
            <BrandMark className="h-7 w-7 text-accent" />
            <span className="font-serif text-xl font-semibold text-ink">{APP_NAME}</span>
            <span className="text-[13px] text-ink-muted">· {COMPANY_NAME}</span>
          </div>

          <h1 className="mt-8 font-serif text-[30px] font-semibold leading-tight text-ink lg:mt-0">
            Administration Mimir
          </h1>
          <p className="mt-2 text-sm text-ink-muted">
            Connectez-vous pour accéder au panneau d&apos;administration
          </p>

          {/* Error message */}
          {error && (
            <div role="alert" className="alert-danger mt-6">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <div>
                <p className="font-semibold">Erreur de connexion</p>
                <p className="mt-0.5">{error}</p>
              </div>
            </div>
          )}

          {/* Login form */}
          <form className="mt-8 space-y-5" onSubmit={handleSubmit}>
            {/* Username */}
            <div>
              <label htmlFor="username" className="field-label">
                Nom d&apos;utilisateur
              </label>
              <input
                id="username"
                name="username"
                type="text"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="input-field h-11"
                placeholder="Entrez votre nom d'utilisateur"
                disabled={isSubmitting}
              />
            </div>

            {/* Password */}
            <div>
              <label htmlFor="password" className="field-label">
                Mot de passe
              </label>
              <div className="relative">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input-field h-11 pr-11"
                  placeholder="Entrez votre mot de passe"
                  disabled={isSubmitting}
                />
                <button
                  type="button"
                  className="absolute right-1.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-md text-ink-faint hover:bg-sunken hover:text-ink"
                  onClick={() => setShowPassword(!showPassword)}
                  disabled={isSubmitting}
                  aria-label={showPassword ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <Eye className="h-4 w-4" aria-hidden="true" />
                  )}
                </button>
              </div>
            </div>

            {/* Login button */}
            <button
              type="submit"
              disabled={isSubmitting}
              className="btn-primary btn-lg w-full"
            >
              {isSubmitting ? (
                <>
                  <LoadingSpinner size="sm" className="text-current" />
                  Connexion en cours...
                </>
              ) : (
                'Se connecter'
              )}
            </button>
          </form>

          <p className="mt-6 text-xs text-ink-muted lg:hidden">
            Accès réservé aux administrateurs autorisés · Toutes les connexions sont enregistrées
          </p>

          {/* Back link */}
          <Link
            to="/"
            className="mt-8 inline-flex items-center gap-1.5 text-sm font-medium text-accent-ink underline-offset-2 hover:underline"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Retour au chat
          </Link>
        </div>
      </main>
    </div>
  );
};

export default AdminLogin;