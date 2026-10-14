import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { cn } from '../../utils/helpers';

const SIZES = {
  sm: 'max-w-md',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-6xl',
};

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Accessible dialog shell shared by every overlay of the app.
 *
 * Rendered in a portal on document.body so no ancestor stacking context or
 * transform can clip it. Handles Escape, focus trapping, body scroll lock and
 * focus restoration on close.
 *
 * @param {Object} props
 * @param {boolean} props.isOpen - Whether the dialog is displayed.
 * @param {Function} props.onClose - Called on Escape, overlay click or close button.
 * @param {React.ReactNode} props.title - Dialog heading (labels the dialog).
 * @param {React.ReactNode} [props.description] - Secondary line under the title.
 * @param {React.ElementType} [props.icon] - Lucide icon shown before the title.
 * @param {'neutral'|'danger'} [props.tone] - Icon tile tint.
 * @param {'sm'|'md'|'lg'|'xl'} [props.size] - Max width of the panel.
 * @param {React.ReactNode} [props.actions] - Extra header buttons, before the close button.
 * @param {React.ReactNode} [props.footer] - Sticky footer content.
 * @param {string} [props.bodyClassName] - Classes for the scrollable body.
 * @param {string} [props.panelClassName] - Extra classes for the dialog panel (e.g. a fixed height).
 */
const Modal = ({
  isOpen,
  onClose,
  title,
  description,
  icon: Icon,
  tone = 'neutral',
  size = 'md',
  actions,
  footer,
  bodyClassName = 'p-6',
  panelClassName = '',
  children,
}) => {
  const panelRef = useRef(null);
  const onCloseRef = useRef(onClose);
  const titleId = useId();
  const descriptionId = useId();
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!isOpen) return undefined;

    const previouslyFocused = document.activeElement;
    const panel = panelRef.current;
    const firstField = panel.querySelector('input, textarea, select');
    (firstField || panel).focus();

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;

      const focusables = Array.from(panel.querySelectorAll(FOCUSABLE));
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused.focus();
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-6">
      <div
        className="absolute inset-0 animate-fade-in bg-ink/45 backdrop-blur-[2px]"
        onClick={() => onCloseRef.current()}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          'relative flex max-h-[92dvh] w-full animate-pop-in flex-col overflow-hidden rounded-t-2xl bg-surface shadow-modal outline-none sm:rounded-2xl',
          SIZES[size],
          panelClassName
        )}
      >
        <div className="flex items-start gap-3 border-b border-line-soft px-6 py-4">
          {Icon && (
            <span
              className={cn(
                'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg',
                tone === 'danger' ? 'bg-danger-soft text-danger' : 'bg-accent-soft text-accent'
              )}
            >
              <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
            </span>
          )}
          <div className="min-w-0 flex-1 py-0.5">
            <h2 id={titleId} className="truncate text-[17px] font-semibold leading-snug text-ink">
              {title}
            </h2>
            {description && (
              <p id={descriptionId} className="mt-0.5 truncate text-[13px] text-ink-muted">
                {description}
              </p>
            )}
          </div>
          <div className="-mr-2 flex shrink-0 items-center gap-1">
            {actions}
            <button
              type="button"
              onClick={() => onCloseRef.current()}
              className="btn-ghost btn-icon"
              aria-label="Fermer"
              title="Fermer"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>
        </div>

        <div className={cn('min-h-0 flex-1 overflow-y-auto', bodyClassName)}>
          {children}
        </div>

        {footer && (
          <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line-soft bg-sunken/60 px-6 py-3.5">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
};

export default Modal;
