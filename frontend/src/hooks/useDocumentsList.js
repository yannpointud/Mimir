import { useState, useEffect, useCallback, useRef } from 'react';
import { documentsAPI } from '../services/api';
import { getErrorMessage, validateDocumentData } from '../utils/helpers';
import { createLogger } from '../utils/logger';

const logger = createLogger('DocumentsList');

export const ITEMS_PER_PAGE = 10;

/**
 * State and actions of the admin documents list: paginated and filtered
 * loading, the count of documents in error, the per-document actions and
 * the delete confirmation.
 *
 * @param {{ onRefresh?: Function, refreshTrigger: unknown }} outlet - Admin outlet context
 */
export const useDocumentsList = ({ onRefresh, refreshTrigger }) => {
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

  // Monotonic request id: guards against out-of-order responses overwriting
  // the latest query result (e.g. page 3 request resolving after page 1).
  const requestIdRef = useRef(0);

  // Count of documents currently in error status (across all pages), used to
  // offer a batch "retry all" action after a bulk upload.
  const [errorCount, setErrorCount] = useState(0);

  // Action states
  const [documentToDelete, setDocumentToDelete] = useState(null);
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
        ITEMS_PER_PAGE,
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
      setTotalPages(Math.ceil(totalCount / ITEMS_PER_PAGE) || 1);
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
    try {
      setActionLoading(true);
      await documentsAPI.deleteDocument(document.id, force);

      // Refresh the list
      await loadDocuments(currentPage, debouncedSearch, statusFilter);
      await refreshErrorCount();
      onRefresh?.();

      setDocumentToDelete(null);

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

  return {
    documents,
    loading,
    error,
    clearError: () => setError(null),
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
    requestDelete: setDocumentToDelete,
    cancelDelete: () => setDocumentToDelete(null),
    handlePageChange,
    handleRetryAllErrors,
    handleDeleteDocument,
    handleTogglePreservation,
    handleReprocess,
  };
};
