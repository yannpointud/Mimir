import { useEffect, useState } from 'react';
import { FileSearch, Mail, Quote } from 'lucide-react';
import MessageInput from './MessageInput';
import BrandMark from '../Common/BrandMark';
import { healthAPI } from '../../services/api';
import { COMPANY_NAME } from '../../config/brand';
import { cn } from '../../utils/helpers';
import { createLogger } from '../../utils/logger';

const logger = createLogger('ChatHome');

const FEATURES = [
  {
    icon: Quote,
    title: 'Réponses sourcées',
    text: 'Chaque réponse s\'appuie sur la documentation interne et cite ses sources.',
  },
  {
    icon: FileSearch,
    title: 'Vérifiez à la source',
    text: 'Cliquez sur un numéro de citation pour lire le passage exact du document.',
  },
];

const FeatureIcon = ({ icon: Icon }) => (
  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-soft text-accent">
    <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
  </span>
);

/**
 * Live service status from the public health endpoint: tells the user the
 * assistant is up and how many documents it can draw on.
 */
const ServiceStatus = () => {
  const [health, setHealth] = useState(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    const loadHealth = async () => {
      try {
        setHealth(await healthAPI.getHealthStatus());
      } catch (error) {
        logger.error('Health check failed', error);
        setUnreachable(true);
      }
    };
    loadHealth();
  }, []);

  if (!health && !unreachable) return null;

  const isHealthy = !unreachable && health.status === 'healthy';
  const label = unreachable
    ? 'Serveur injoignable'
    : isHealthy
      ? `Opérationnel · ${health.checks.database.document_count} documents dans la base`
      : 'Service dégradé';

  return (
    <span
      role="status"
      className={cn(
        'inline-flex animate-fade-in items-center gap-2 rounded-full border bg-surface px-3 py-1 text-xs font-medium',
        isHealthy ? 'border-success/25 text-success-ink' : 'border-warning/30 text-warning-ink'
      )}
    >
      <span className="relative flex h-2 w-2" aria-hidden="true">
        {isHealthy && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-50" />}
        <span className={cn('relative inline-flex h-2 w-2 rounded-full', isHealthy ? 'bg-success' : 'bg-warning')} />
      </span>
      {label}
    </span>
  );
};

/**
 * Landing screen of a conversation: shown while the session only holds the
 * welcome message. The first question switches the page to the thread view.
 */
const ChatHome = ({ welcomeText, onSendMessage, onContactHuman, disabled }) => {
  return (
    <div className="relative min-h-0 flex-1 overflow-y-auto bg-[radial-gradient(ellipse_70%_55%_at_50%_0%,rgb(var(--accent)/0.07),transparent)]">
      {/* Decorative dot grid fading out from the top */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[460px] bg-[radial-gradient(rgb(var(--ink)/0.11)_1px,transparent_1px)] [background-size:22px_22px] [mask-image:radial-gradient(ellipse_55%_75%_at_50%_0%,black,transparent)]"
      />

      <div className="relative mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-4 py-10 sm:px-6 sm:py-14">
        <div className="animate-slide-up">
          <div className="flex flex-wrap items-center gap-2">
            <span className="badge-accent py-1 pl-2 pr-3">
              <BrandMark className="h-3.5 w-3.5" />
              Assistant documentaire · {COMPANY_NAME}
            </span>
            <ServiceStatus />
          </div>

          <h1 className="mt-6 text-balance font-serif text-[34px] font-semibold leading-[1.1] tracking-[-0.015em] text-ink sm:text-[46px]">
            Une question sur <span className="font-medium italic text-accent">vos documents</span>&nbsp;?
          </h1>
          {welcomeText && (
            <p className="mt-4 max-w-2xl text-base leading-relaxed text-ink-muted sm:text-[17px]">
              {welcomeText}
            </p>
          )}

          <div className="mt-8">
            <MessageInput
              variant="hero"
              onSendMessage={onSendMessage}
              disabled={disabled}
            />
          </div>

          <ul className="mt-8 grid gap-3 sm:grid-cols-3">
            {FEATURES.map(({ icon, title, text }) => (
              <li key={title} className="rounded-xl border border-line bg-surface p-4 shadow-xs">
                <FeatureIcon icon={icon} />
                <p className="mt-3 text-sm font-semibold text-ink">{title}</p>
                <p className="mt-1 text-[13px] leading-relaxed text-ink-muted">{text}</p>
              </li>
            ))}
            <li>
              <button
                type="button"
                onClick={onContactHuman}
                className="group flex h-full w-full flex-col items-start rounded-xl border border-line bg-surface p-4 text-left shadow-xs transition duration-150 hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-card"
              >
                <FeatureIcon icon={Mail} />
                <span className="mt-3 block text-sm font-semibold text-ink group-hover:text-accent-ink">
                  Un humain si besoin <span aria-hidden="true" className="inline-block transition-transform group-hover:translate-x-0.5">→</span>
                </span>
                <span className="mt-1 block text-[13px] leading-relaxed text-ink-muted">
                  Transmettez la conversation à l&apos;équipe support en un clic.
                </span>
              </button>
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default ChatHome;
