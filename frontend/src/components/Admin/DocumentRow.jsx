import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { MoreVertical, RefreshCw, Shield, ShieldOff, Trash2 } from 'lucide-react';
import { formatDate, translateDocumentStatus, getStatusColor, safeDisplayValue, getFileExtension, cn } from '../../utils/helpers';

const FILE_TYPE_TONES = {
  pdf: 'bg-danger-soft text-danger-ink',
  docx: 'bg-accent-soft text-accent-ink',
  md: 'bg-success-soft text-success-ink',
  txt: 'bg-sunken text-ink-muted',
};

const FileTypeTile = ({ filename }) => {
  const extension = getFileExtension(filename);
  return (
    <span
      className={cn(
        'flex h-8 w-8 shrink-0 items-center justify-center rounded-md font-mono text-[9px] font-semibold uppercase',
        FILE_TYPE_TONES[extension] || 'bg-sunken text-ink-muted'
      )}
      aria-hidden="true"
    >
      {extension.slice(0, 4) || 'doc'}
    </span>
  );
};

// Component for a document row
const MENU_HEIGHT = 150;

const DocumentRow = ({ document, onDelete, onTogglePreservation, onReprocess, actionLoading }) => {
  const [menuPosition, setMenuPosition] = useState(null);
  const triggerRef = useRef(null);
  const menuRef = useRef(null);
  const showMenu = menuPosition !== null;

  // The menu is portaled with fixed coordinates so the table card cannot clip it
  const toggleMenu = () => {
    if (showMenu) {
      setMenuPosition(null);
      return;
    }
    const rect = triggerRef.current.getBoundingClientRect();
    const opensUpward = rect.bottom + MENU_HEIGHT > window.innerHeight;
    setMenuPosition({
      right: window.innerWidth - rect.right,
      ...(opensUpward ? { bottom: window.innerHeight - rect.top + 4 } : { top: rect.bottom + 4 }),
    });
  };

  const closeMenu = () => setMenuPosition(null);

  // Close the actions menu on outside click, Escape, scroll or resize
  useEffect(() => {
    if (!showMenu) return undefined;
    const handlePointerDown = (event) => {
      if (!menuRef.current.contains(event.target) && !triggerRef.current.contains(event.target)) closeMenu();
    };
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') closeMenu();
    };
    window.document.addEventListener('mousedown', handlePointerDown);
    window.document.addEventListener('keydown', handleKeyDown);
    window.addEventListener('scroll', closeMenu, true);
    window.addEventListener('resize', closeMenu);
    return () => {
      window.document.removeEventListener('mousedown', handlePointerDown);
      window.document.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('scroll', closeMenu, true);
      window.removeEventListener('resize', closeMenu);
    };
  }, [showMenu]);

  return (
    <tr className="group transition-colors hover:bg-sunken/60">
      <td className="w-full max-w-0 py-2.5 pl-3 pr-2 sm:pl-5 md:w-1/2">
        <div className="flex min-w-0 items-center gap-3">
          <FileTypeTile filename={document.filename} />
          <div className="min-w-0">
            <p className="truncate font-medium text-ink" title={document.filename}>
              {document.filename}
            </p>
            {document.status === 'error' && document.error_message ? (
              <p className="truncate text-xs text-danger" title={document.error_message}>{document.error_message}</p>
            ) : (
              <p className="truncate text-xs text-ink-muted md:hidden">{formatDate(document.created_at)}</p>
            )}
          </div>
        </div>
      </td>
      <td className="whitespace-nowrap px-2 py-2.5 sm:px-5">
        <span className="flex items-center gap-2">
          <span className={cn('badge-dot', getStatusColor(document.status))}>
            {translateDocumentStatus(document.status)}
          </span>
          {document.preserve && (
            <span className="text-accent" title="Document protégé">
              <Shield className="h-4 w-4" aria-hidden="true" />
              <span className="sr-only">Document protégé</span>
            </span>
          )}
        </span>
      </td>
      <td className="hidden whitespace-nowrap px-5 py-2.5 text-ink-muted md:table-cell">
        {formatDate(document.created_at)}
      </td>
      <td className="hidden whitespace-nowrap px-5 py-2.5 text-right text-ink-muted tabular md:table-cell">
        {safeDisplayValue(document.chunk_count, 0)}
      </td>
      <td className="whitespace-nowrap py-2.5 pl-1 pr-2 text-right sm:px-3">
        <button
          ref={triggerRef}
          type="button"
          onClick={toggleMenu}
          className="btn-ghost btn-icon h-8 w-8"
          disabled={actionLoading}
          aria-haspopup="menu"
          aria-expanded={showMenu}
          aria-label={`Actions pour ${document.filename}`}
        >
          <MoreVertical className="h-4 w-4" aria-hidden="true" />
        </button>

        {showMenu && createPortal(
          <div
            ref={menuRef}
            role="menu"
            style={menuPosition}
            className="fixed z-50 w-56 animate-pop-in overflow-hidden rounded-xl border border-line bg-surface py-1 text-left shadow-raised"
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                onTogglePreservation();
                closeMenu();
              }}
              className="flex w-full items-center gap-2.5 px-3.5 py-2 text-sm text-ink hover:bg-sunken"
            >
              {document.preserve ? (
                <>
                  <ShieldOff className="h-4 w-4 text-ink-muted" aria-hidden="true" />
                  Retirer la protection
                </>
              ) : (
                <>
                  <Shield className="h-4 w-4 text-ink-muted" aria-hidden="true" />
                  Protéger le document
                </>
              )}
            </button>

            <button
              type="button"
              role="menuitem"
              onClick={() => {
                onReprocess();
                closeMenu();
              }}
              className="flex w-full items-center gap-2.5 px-3.5 py-2 text-sm text-ink hover:bg-sunken"
            >
              <RefreshCw className="h-4 w-4 text-ink-muted" aria-hidden="true" />
              {document.status === 'pending' ? 'Relancer le traitement' :
               document.status === 'error' ? 'Retraiter le document' :
               'Réindexer le document'}
            </button>

            <div className="my-1 border-t border-line-soft" />

            <button
              type="button"
              role="menuitem"
              onClick={() => {
                onDelete();
                closeMenu();
              }}
              className="flex w-full items-center gap-2.5 px-3.5 py-2 text-sm text-danger hover:bg-danger-soft disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
              disabled={document.preserve}
              title={document.preserve ? 'Retirez la protection pour supprimer ce document' : undefined}
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
              Supprimer
            </button>
          </div>,
          window.document.body
        )}
      </td>
    </tr>
  );
};

export default DocumentRow;
