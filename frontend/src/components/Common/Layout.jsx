import { createContext, useContext, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { LogOut, MessageSquare, Shield } from 'lucide-react';
import BrandMark from './BrandMark';
import { APP_NAME, COMPANY_NAME } from '../../config/brand';
import { cn } from '../../utils/helpers';

// DOM node in the top bar where the current page can mount its own actions.
const TopbarSlotContext = createContext(null);

/**
 * Renders its children inside the top bar action area of the Layout.
 * Lets a page (e.g. the chat) own its actions while they sit in the global bar.
 */
export const TopbarActions = ({ children }) => {
  const slot = useContext(TopbarSlotContext);
  return slot ? createPortal(children, slot) : null;
};

const getInitials = (name) => name.slice(0, 2).toUpperCase();

const Layout = ({ children }) => {
  const [slot, setSlot] = useState(null);
  const { user, logout, isAuthenticated } = useAuth();
  const location = useLocation();

  const isUserAdmin = isAuthenticated && user?.user_type === 'admin';
  const username = user?.username || 'Administrateur';

  const navigation = [
    { name: 'Assistant', href: '/', icon: MessageSquare, current: location.pathname === '/' },
    ...(isUserAdmin
      ? [{ name: 'Administration', href: '/admin/documents', icon: Shield, current: location.pathname.startsWith('/admin') }]
      : []),
  ];

  return (
    <TopbarSlotContext.Provider value={slot}>
      <div className="flex h-dvh flex-col bg-canvas">
        <a href="#main" className="skip-link">Aller au contenu</a>

        <header className="relative z-30 flex h-14 shrink-0 items-center gap-2 bg-nav px-3 text-nav-ink sm:gap-4 sm:px-5">
          <Link
            to="/"
            className="flex shrink-0 items-center gap-2.5 rounded-md py-1 pr-1 focus-visible:outline-white"
            aria-label={`${APP_NAME}, ${COMPANY_NAME} : accueil de l'assistant`}
          >
            <BrandMark className="h-7 w-7 text-accent-bright" />
            <span className="font-serif text-[21px] font-semibold leading-none tracking-[-0.01em]">
              {APP_NAME}
            </span>
          </Link>

          <span aria-hidden="true" className="hidden h-6 w-px bg-white/15 sm:block" />
          <span className="hidden max-w-[16rem] truncate text-[13px] font-medium text-nav-muted sm:block">
            {COMPANY_NAME}
          </span>

          {navigation.length > 1 && (
            <nav aria-label="Navigation principale" className="ml-1 flex items-center gap-1 sm:ml-4">
              {navigation.map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    key={item.name}
                    to={item.href}
                    aria-current={item.current ? 'page' : undefined}
                    title={item.name}
                    className={cn(
                      'relative flex h-9 items-center gap-2 rounded-lg px-2.5 text-sm font-medium transition-colors focus-visible:outline-white md:px-3',
                      item.current
                        ? 'bg-nav-raised text-nav-ink'
                        : 'text-nav-muted hover:bg-white/5 hover:text-nav-ink'
                    )}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    <span className="sr-only md:not-sr-only">{item.name}</span>
                    {item.current && (
                      <span aria-hidden="true" className="absolute inset-x-2.5 -bottom-[10px] h-0.5 rounded-full bg-accent-bright" />
                    )}
                  </Link>
                );
              })}
            </nav>
          )}

          <div ref={setSlot} className="ml-auto flex items-center gap-2" />

          {isAuthenticated && (
            <div className="flex items-center gap-1 border-l border-white/10 pl-2 sm:gap-2 sm:pl-4">
              <span
                aria-hidden="true"
                className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-bright/15 text-xs font-semibold text-accent-bright ring-1 ring-inset ring-accent-bright/30"
              >
                {getInitials(username)}
              </span>
              <span className="hidden text-sm font-medium text-nav-ink lg:block">{username}</span>
              <button
                type="button"
                onClick={logout}
                className="flex h-9 w-9 items-center justify-center rounded-lg text-nav-muted transition-colors hover:bg-white/5 hover:text-nav-ink focus-visible:outline-white"
                aria-label="Déconnexion"
                title="Déconnexion"
              >
                <LogOut className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          )}
        </header>

        <main id="main" tabIndex={-1} className="flex min-h-0 flex-1 flex-col outline-none">
          {children}
        </main>
      </div>
    </TopbarSlotContext.Provider>
  );
};

export default Layout;
