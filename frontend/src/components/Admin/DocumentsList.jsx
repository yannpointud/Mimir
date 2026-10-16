import { Link, useOutletContext } from 'react-router-dom';
import { cn } from '../../utils/helpers';
import {
  Search,
  Filter,
  RefreshCw,
  FileText,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Upload,
  X
} from 'lucide-react';
import LoadingSpinner from '../Common/LoadingSpinner';
import DocumentRow from './DocumentRow';
import DeleteConfirmDialog from './DeleteConfirmDialog';
import { useDocumentsList, ITEMS_PER_PAGE } from '../../hooks/useDocumentsList';

const DocumentsList = () => {
  const {
    documents,
    loading,
    error,
    clearError,
    searchTerm,
    setSearchTerm,
    statusFilter,
    setStatusFilter,
    currentPage,
    totalPages,
    totalDocuments,
    errorCount,
    retryingAll,
    actionLoading,
    documentToDelete,
    requestDelete,
    cancelDelete,
    handlePageChange,
    handleRetryAllErrors,
    handleDeleteDocument,
    handleTogglePreservation,
    handleReprocess,
  } = useDocumentsList(useOutletContext());

  const firstShown = Math.min((currentPage - 1) * ITEMS_PER_PAGE + 1, totalDocuments);
  const lastShown = Math.min(currentPage * ITEMS_PER_PAGE, totalDocuments);

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
            onClick={clearError}
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
                    onDelete={() => requestDelete(document)}
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
        isOpen={documentToDelete !== null}
        document={documentToDelete}
        onConfirm={handleDeleteDocument}
        onCancel={cancelDelete}
        loading={actionLoading}
      />
    </div>
  );
};

export default DocumentsList;
