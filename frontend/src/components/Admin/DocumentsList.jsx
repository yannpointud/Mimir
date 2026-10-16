import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Link, useOutletContext } from 'react-router-dom';
import { documentsAPI } from '../../services/api';
import { getErrorMessage, formatDate, translateDocumentStatus, getStatusColor, validateDocumentData, safeDisplayValue, getFileExtension, cn } from '../../utils/helpers';
import {
  Search,
  Filter,
  Trash2,
  RefreshCw,
  Shield,
  ShieldOff,
  MoreVertical,
  FileText,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Upload,
  X
} from 'lucide-react';
import LoadingSpinner from '../Common/LoadingSpinner';
import Modal from '../Common/Modal';
import { createLogger } from '../../utils/logger';

const logger = createLogger('DocumentsList');

const DocumentsList = () => {
  const { onRefresh, refreshTrigger } = useOutletContext();
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filters and pagination
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalDocuments, setTotalDocuments] = useState(0);
  const itemsPerPage = 10;

  // Monotonic request id: guards against out-of-order responses overwriting
  // the latest query result (e.g. page 3 request resolving after page 1).
  const requestIdRef = useRef(0);

  // Count of documents currently in error status (across all pages), used to
  // offer a batch "retry all" action after a bulk upload.
  const [errorCount, setErrorCount] = useState(0);

  // Action states
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [retryingAll, setRetryingAll] = useState(false);

  // Load documents. Stable identity (no reactive deps) so effects that call it
  // don't re-run when page/search/filter change; those are passed explicitly.
  const loadDocuments = useCallback(async (page, search, status) => {
    const requestId = ++requestIdRef.current;
    try {
      setLoading(true);
      setError(null);

      const response = await documentsAPI.getDocuments(
        page,
        itemsPerPage,
        status || null,
        search || null
      );

      // Ignore stale responses from a superseded request
      if (requestId !== requestIdRef.current) return;

      // Validate and clean data
      const validatedDocuments = (response.documents || []).map(validateDocumentData);
      setDocuments(validatedDocuments);

      // Page state is driven by the UI, not derived from the response, so we
      // only sync totals here.
      const totalCount = response.total_count || 0;
      setTotalPages(Math.ceil(totalCount / itemsPerPage) || 1);
      setTotalDocuments(totalCount);

    } catch (error) {
      if (requestId !== requestIdRef.current) return;
      logger.error('Failed to load the documents', error);
      setError(getErrorMessage(error));
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, []);

  // Refresh the total count of documents in error status (limit=1: we only
  // need total_count, not the rows). Stable identity for use in effects.
  const refreshErrorCount = useCallback(async () => {
    try {
      const response = await documentsAPI.getDocuments(1, 1, 'error', null);
      setErrorCount(response.total_count || 0);
    } catch (error) {
      // Non-critical: leave the previous count on failure
      logger.error('Failed to count the failed documents', error);
    }
  }, []);

  // Debounce the search input into its own state
  useEffect(() => {
    const timeout = setTimeout(() => setDebouncedSearch(searchTerm), 300);
    return () => clearTimeout(timeout);
  }, [searchTerm]);

  // Reset to the first page whenever the effective query changes (new search
  // or status filter) — but NOT when only the page changes.
  useEffect(() => {
    setCurrentPage(1);
  }, [debouncedSearch, statusFilter]);

  // Single source of loading: reacts to page, effective query, and global refresh
  useEffect(() => {
    loadDocuments(currentPage, debouncedSearch, statusFilter);
    refreshErrorCount();
  }, [currentPage, debouncedSearch, statusFilter, refreshTrigger, loadDocuments, refreshErrorCount]);

  // Clamp the page if it falls out of range (e.g. deleting the last item of
  // the last page); the load effect then refetches the corrected page.
  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages);
  }, [totalPages, currentPage]);

  // Pagination handling
  const handlePageChange = (newPage) => {
    if (newPage >= 1 && newPage <= totalPages) {
      setCurrentPage(newPage);
    }
  };

  // Retry every document currently in error status. Collects them across all
  // pages (limit is capped at 1000 backend-side) and re-queues each via the
  // reprocess endpoint; the backend queue paces the actual work with backoff.
  const handleRetryAllErrors = async () => {
    try {
      setRetryingAll(true);
      setError(null);

      const pageSize = 1000;
      const erroredDocs = [];
      for (let page = 1; page <= 100; page++) {
        const response = await documentsAPI.getDocuments(page, pageSize, 'error', null);
        const docs = response.documents || [];
        erroredDocs.push(...docs);
        if (docs.length < pageSize) break;
      }

      // Re-queue sequentially to keep the requests gentle
      for (const doc of erroredDocs) {
        await documentsAPI.reprocessDocument(doc.id);
      }

      await loadDocuments(currentPage, debouncedSearch, statusFilter);
      await refreshErrorCount();
      onRefresh?.();

    } catch (error) {
      logger.error('Failed to retry the failed documents', error);
      setError(getErrorMessage(error));
    } finally {
      setRetryingAll(false);
    }
  };

  // Document actions
  const handleDeleteDocument = async (document, force = false) => {
    if (!document) return;

    try {
      setActionLoading(true);
      await documentsAPI.deleteDocument(document.id, force);

      // Refresh the list
      await loadDocuments(currentPage, debouncedSearch, statusFilter);
      await refreshErrorCount();
      onRefresh?.();

      setShowDeleteConfirm(false);
      setSelectedDocument(null);

    } catch (error) {
      logger.error('Failed to delete the document', error);
      setError(getErrorMessage(error));
    } finally {
      setActionLoading(false);
    }
  };

  const handleTogglePreservation = async (document) => {
    try {
      setActionLoading(true);
      await documentsAPI.togglePreservation(document.id, !document.preserve);

      // Refresh the list
      await loadDocuments(currentPage, debouncedSearch, statusFilter);
      onRefresh?.();

    } catch (error) {
      logger.error('Failed to update the document', error);
      setError(getErrorMessage(error));
    } finally {
      setActionLoading(false);
    }
  };

  const handleReprocess = async (document) => {
    try {
      setActionLoading(true);
      await documentsAPI.reprocessDocument(document.id);

      // Refresh the list
      await loadDocuments(currentPage, debouncedSearch, statusFilter);
      await refreshErrorCount();
      onRefresh?.();

    } catch (error) {
      logger.error('Failed to reprocess the document', error);
      setError(getErrorMessage(error));
    } finally {
      setActionLoading(false);
    }
  };

  const firstShown = Math.min((currentPage - 1) * itemsPerPage + 1, totalDocuments);
  const lastShown = Math.min(currentPage * itemsPerPage, totalDocuments);

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1 sm:max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" aria-hidden="true" />
          <label htmlFor="documents-search" className="sr-only">Rechercher un document</label>
          <input
            id="documents-search"
            type="search"
            placeholder="Rechercher un document..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="input-field pl-9"
          />
        </div>

        <div className="relative sm:w-56">
          <Filter className="pointer-events-none absolute left-3 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-ink-faint" aria-hidden="true" />
          <label htmlFor="documents-status" className="sr-only">Filtrer par statut</label>
          <select
            id="documents-status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="select pl-9"
          >
            <option value="">Tous les statuts</option>
            <option value="pending">En attente</option>
            <option value="indexing">Indexation en cours</option>
            <option value="indexed">Indexé</option>
            <option value="error">Erreur</option>
          </select>
        </div>

        <p className="text-sm text-ink-muted sm:ml-auto tabular" aria-live="polite">
          {totalDocuments > 0
            ? <>Affichage de {firstShown} à {lastShown} sur <span className="font-medium text-ink">{totalDocuments}</span> documents</>
            : 'Aucun document trouvé'}
        </p>
      </div>

      {/* Error message */}
      {error && (
        <div role="alert" className="alert-danger">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p className="flex-1">{error}</p>
          <button
            type="button"
            onClick={() => setError(null)}
            className="-my-1 -mr-2 flex h-7 w-7 items-center justify-center rounded-md hover:bg-danger/10"
            aria-label="Fermer le message d'erreur"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      )}

      {/* Failed-ingestion banner: offer to retry all documents in error */}
      {errorCount > 0 && (
        <div className="alert-warning items-center">
          <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
          <p className="flex-1">
            <span className="font-semibold">{errorCount} document{errorCount > 1 ? 's' : ''} en erreur d&apos;indexation.</span>
          </p>
          <button
            type="button"
            onClick={handleRetryAllErrors}
            disabled={retryingAll || actionLoading}
            className="btn-secondary btn-sm"
          >
            {retryingAll ? (
              <>
                <LoadingSpinner size="sm" className="h-3.5 w-3.5" />
                Relance en cours...
              </>
            ) : (
              <>
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                Réessayer tout ({errorCount})
              </>
            )}
          </button>
        </div>
      )}

      {/* Documents table */}
      <div className="card overflow-hidden">
        {loading && documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-4 py-24">
            <LoadingSpinner size="lg" />
            <p className="text-sm text-ink-muted">Chargement des documents...</p>
          </div>
        ) : documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center px-6 py-20 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-sunken text-ink-faint">
              <FileText className="h-6 w-6" aria-hidden="true" />
            </span>
            <h2 className="mt-4 font-medium text-ink">Aucun document</h2>
            <p className="mt-1 max-w-sm text-sm text-ink-muted">
              {searchTerm || statusFilter
                ? 'Aucun document ne correspond à vos critères de recherche'
                : 'Commencez par importer vos premiers documents'}
            </p>
            {!searchTerm && !statusFilter && (
              <Link to="/admin/upload" className="btn-primary mt-5">
                <Upload className="h-4 w-4" aria-hidden="true" />
                Importer des documents
              </Link>
            )}
          </div>
        ) : (
          <div className={cn('overflow-x-auto transition-opacity', loading && 'opacity-60')}>
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-line bg-sunken/70">
                <tr>
                  <th scope="col" className="eyebrow py-2.5 pl-3 pr-2 sm:pl-5">Document</th>
                  <th scope="col" className="eyebrow px-2 py-2.5 sm:px-5">Statut</th>
                  <th scope="col" className="eyebrow hidden px-5 py-2.5 md:table-cell">Date d&apos;ajout</th>
                  <th scope="col" className="eyebrow hidden px-5 py-2.5 text-right md:table-cell">Sections</th>
                  <th scope="col" className="py-2.5 pl-1 pr-2 sm:px-3"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-soft">
                {documents.map((document) => (
                  <DocumentRow
                    key={document.id}
                    document={document}
                    onDelete={() => {
                      setSelectedDocument(document);
                      setShowDeleteConfirm(true);
                    }}
                    onTogglePreservation={() => handleTogglePreservation(document)}
                    onReprocess={() => handleReprocess(document)}
                    actionLoading={actionLoading}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between gap-3 border-t border-line-soft px-5 py-3">
            <p className="text-sm text-ink-muted tabular">
              Page <span className="font-medium text-ink">{currentPage}</span> sur{' '}
              <span className="font-medium text-ink">{totalPages}</span>
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => handlePageChange(currentPage - 1)}
                disabled={currentPage <= 1}
                className="btn-secondary btn-sm"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                <span className="sr-only sm:not-sr-only">Précédent</span>
              </button>
              <button
                type="button"
                onClick={() => handlePageChange(currentPage + 1)}
                disabled={currentPage >= totalPages}
                className="btn-secondary btn-sm"
              >
                <span className="sr-only sm:not-sr-only">Suivant</span>
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Delete confirmation dialog */}
      <DeleteConfirmDialog
        isOpen={showDeleteConfirm}
        document={selectedDocument}
        onConfirm={handleDeleteDocument}
        onCancel={() => {
          setShowDeleteConfirm(false);
          setSelectedDocument(null);
        }}
        loading={actionLoading}
      />
    </div>
  );
};

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

// Delete confirmation dialog
const DeleteConfirmDialog = ({ isOpen, document, onConfirm, onCancel, loading }) => {
  if (!document) return null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onCancel}
      size="sm"
      icon={Trash2}
      tone="danger"
      title="Supprimer le document"
      description="Cette action est irréversible."
      footer={
        <>
          <button type="button" onClick={onCancel} className="btn-secondary" disabled={loading}>
            Annuler
          </button>
          <button
            type="button"
            onClick={() => onConfirm(document, document.preserve)}
            className="btn-danger"
            disabled={loading || document.preserve}
          >
            {loading ? (
              <>
                <LoadingSpinner size="sm" className="text-current" />
                Suppression...
              </>
            ) : (
              'Supprimer'
            )}
          </button>
        </>
      }
    >
      <p className="text-sm leading-relaxed text-ink-muted">
        Êtes-vous sûr de vouloir supprimer le document <strong className="font-semibold text-ink">{document.filename}</strong> ?
        Il sera retiré de l&apos;index et ne sera plus utilisé pour répondre aux questions.
      </p>

      {document.preserve && (
        <div className="alert-warning mt-4">
          <Shield className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p>Ce document est protégé. Vous devez d&apos;abord retirer la protection.</p>
        </div>
      )}
    </Modal>
  );
};

export default DocumentsList;