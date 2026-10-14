import { Link, Navigate } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import LoadingSpinner from './LoadingSpinner';

const ProtectedRoute = ({ children }) => {
  const { isAuthenticated, loading, user } = useAuth();

  // Show loading spinner during auth verification
  if (loading) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-canvas">
        <LoadingSpinner size="lg" />
        <p className="text-sm text-ink-muted">Vérification de l&apos;authentification...</p>
      </div>
    );
  }

  // Redirect to login page if not authenticated
  if (!isAuthenticated) {
    return <Navigate to="/admin/login" replace />;
  }

  // Verify the user has admin privileges
  if (user && user.user_type !== 'admin') {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-canvas px-4">
        <div className="card w-full max-w-md p-8 text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-danger-soft text-danger">
            <ShieldAlert className="h-6 w-6" aria-hidden="true" />
          </span>
          <h1 className="mt-5 font-serif text-xl font-semibold text-ink">Accès non autorisé</h1>
          <p className="mt-2 text-sm text-ink-muted">
            Vous n&apos;avez pas les droits nécessaires pour accéder à cette page.
          </p>
          <Link to="/" className="btn-primary mt-6">
            Retour à l&apos;accueil
          </Link>
        </div>
      </div>
    );
  }

  return children;
};

export default ProtectedRoute;
