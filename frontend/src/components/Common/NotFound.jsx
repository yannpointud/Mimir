import { Link } from 'react-router-dom';
import { ArrowLeft, MessageSquare } from 'lucide-react';
import BrandMark from './BrandMark';
import { APP_NAME, COMPANY_NAME } from '../../config/brand';

const NotFound = () => {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <header className="flex h-14 items-center gap-2.5 px-5">
        <BrandMark className="h-7 w-7 text-accent" />
        <span className="font-serif text-[21px] font-semibold text-ink">{APP_NAME}</span>
        <span className="text-[13px] text-ink-muted">· {COMPANY_NAME}</span>
      </header>

      <main className="flex flex-1 items-center justify-center px-4 pb-20">
        <div className="w-full max-w-md animate-slide-up text-center">
          <p className="font-serif text-[88px] font-semibold leading-none tracking-tight text-accent/90 tabular">
            404
          </p>
          <h1 className="mt-4 font-serif text-2xl font-semibold text-ink">
            Page introuvable
          </h1>
          <p className="mt-2 text-ink-muted">
            Désolé, la page que vous recherchez n&apos;existe pas ou a été déplacée.
          </p>

          <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
            <Link to="/" className="btn-primary">
              <MessageSquare className="h-4 w-4" aria-hidden="true" />
              Retour à l&apos;assistant
            </Link>
            <button type="button" onClick={() => window.history.back()} className="btn-secondary">
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              Page précédente
            </button>
          </div>

          <p className="mt-10 text-sm text-ink-muted">
            Vous êtes administrateur ?{' '}
            <Link to="/admin" className="font-medium text-accent-ink underline decoration-accent/40 underline-offset-2 hover:decoration-accent">
              Accéder à l&apos;administration
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
};

export default NotFound;
