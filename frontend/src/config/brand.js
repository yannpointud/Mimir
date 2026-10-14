/**
 * Customer branding read at build time.
 *
 * VITE_COMPANY_NAME is shown next to the Mimir wordmark. The fallback keeps
 * Docker builds branded, since .env files are excluded from the build context.
 */
export const COMPANY_NAME = import.meta.env.VITE_COMPANY_NAME ?? 'Arch-IT';

export const APP_NAME = 'Mimir';
