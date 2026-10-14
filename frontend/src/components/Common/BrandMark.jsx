import { cn } from '../../utils/helpers';

/**
 * Mimir logo mark: a well seen from above. Drawn with currentColor so the
 * caller picks the tint (bright on the dark top bar, accent elsewhere).
 */
const BrandMark = ({ className = '' }) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
    className={cn('h-6 w-6 shrink-0', className)}
  >
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
    <circle cx="12" cy="12" r="3.6" fill="currentColor" />
  </svg>
);

export default BrandMark;
