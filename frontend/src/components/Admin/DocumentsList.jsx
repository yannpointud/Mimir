import { useState, useEffect, useCallback } from 'react';
import { useOutletContext } from 'react-router-dom';
import { documentsAPI } from '../../services/api';
import { getErrorMessage, formatDate, translateDocumentStatus, getStatusColor, validateDocumentData, safeDisplayValue } from '../../utils/helpers';
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
  ChevronRight
} from 'lucide-react';
import LoadingSpinner from '../Common/LoadingSpinner';

const DocumentsList = () => {
  const { onRefresh, refreshTrigger } = useOutletContext();
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filters and pagination
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalDocuments, setTotalDocuments] = useState(0);
  const itemsPerPage = 10;

  // Action states
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  // Load documents
  const loadDocuments = useCallback(async (page = currentPage, search = searchTerm, status = statusFilter) => {
    try {
      setLoading(true);
      setError(null);

      const response = await documentsAPI.getDocuments(
        page,
        itemsPerPage,
        status || null,
        search || null
      );

      // Validate and clean data
      const validatedDocuments = (response.documents || []).map(validateDocumentData);
      setDocuments(validatedDocuments);

      // Adapt backend response structure
      const totalCount = response.total_count || 0;
      const pagination = response.pagination || {};
      const totalPages = Math.ceil(totalCount / itemsPerPage) || 1;
      const currentPage = Math.floor((pagination.offset || 0) / itemsPerPage) + 1;

      setTotalPages(totalPages);
      setTotalDocuments(totalCount);
      setCurrentPage(currentPage);

    } catch (error) {
      console.error('Erreur lors du chargement des documents:', error);
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [currentPage, searchTerm, statusFilter]);

  // Effects
  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  // Debounced search
  useEffect(() => {
    const timeout = setTimeout(() => {
      setCurrentPage(1);
      loadDocuments(1, searchTerm, statusFilter);
    }, 300);

    return () => clearTimeout(timeout);
  }, [searchTerm, statusFilter, loadDocuments]);

  // Listen to parent refreshTrigger for global refresh
  useEffect(() => {
    if (refreshTrigger > 0) {
      loadDocuments();
    }
  }, [refreshTrigger, loadDocuments]);

  // Pagination handling
  const handlePageChange = (newPage) => {
    if (newPage >= 1 && newPage <= totalPages) {
      setCurrentPage(newPage);
      loadDocuments(newPage, searchTerm, statusFilter);
    }
  };

  // Document actions
  const handleDeleteDocument = async (document, force = false) => {
    if (!document) return;

    try {
      setActionLoading(true);
      await documentsAPI.deleteDocument(document.id, force);

      // Refresh the list
      await loadDocuments();
      onRefresh?.();

      setShowDeleteConfirm(false);
      setSelectedDocument(null);

    } catch (error) {
      console.error('Erreur lors de la suppression:', error);
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
      await loadDocuments();
      onRefresh?.();

    } catch (error) {
      console.error('Erreur lors de la modification:', error);
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
      await loadDocuments();
      onRefresh?.();

    } catch (error) {
      console.error('Erreur lors du retraitement:', error);
      setError(getErrorMessage(error));
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full max-w-7xl p-4">
      <div className="card p-0 flex flex-col h-full">
        {/* Header with filters */}
        <div className="bg-white border-b border-gray-200 p-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between space-y-3 sm:space-y-0">
          {/* Search */}
          <div className="flex-1 max-w-lg">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                type="text"
                placeholder="Rechercher un document..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10 input-field"
              />
            </div>
          </div>

          {/* Filters */}
          <div className="flex items-center space-x-3">
            <div className="relative">
              <Filter className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="pl-10 pr-8 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              >
                <option value="">Tous les statuts</option>
                <option value="pending">En attente</option>
                <option value="indexing">Indexation en cours</option>
                <option value="indexed">Indexé</option>
                <option value="error">Erreur</option>
              </select>
            </div>

            {/* Refresh button removed - used from main dashboard */}
          </div>
        </div>

        {/* Summary */}
        <div className="mt-3 text-sm text-gray-600">
          {totalDocuments > 0 ? (
            <>
              Affichage de {Math.min((currentPage - 1) * itemsPerPage + 1, totalDocuments)} à{' '}
              {Math.min(currentPage * itemsPerPage, totalDocuments)} sur {totalDocuments} documents
            </>
          ) : (
            'Aucun document trouvé'
          )}
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className="bg-red-50 border-l-4 border-red-400 p-4 m-4">
          <div className="flex">
            <AlertTriangle className="h-5 w-5 text-red-400" />
            <div className="ml-3">
              <p className="text-sm text-red-700">{error}</p>
            </div>
            <button
              onClick={() => setError(null)}
              className="ml-auto text-red-400 hover:text-red-600"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 overflow-y-auto admin-scroll">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <LoadingSpinner size="lg" />
              <p className="mt-4 text-gray-600">Chargement des documents...</p>
            </div>
          </div>
        ) : documents.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <FileText className="mx-auto h-12 w-12 text-gray-400" />
              <h3 className="mt-2 text-sm font-medium text-gray-900">Aucun document</h3>
              <p className="mt-1 text-sm text-gray-500">
                {searchTerm || statusFilter
                  ? 'Aucun document ne correspond à vos critères de recherche'
                  : 'Commencez par uploader vos premiers documents'}
              </p>
            </div>
          </div>
        ) : (
          <div className="overflow-auto h-full">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Document
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Statut
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Date d&apos;ajout
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Chunks
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
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
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="bg-white border-t border-gray-200 px-4 py-3 flex items-center justify-between">
          <div className="flex-1 flex justify-between sm:hidden">
            <button
              onClick={() => handlePageChange(currentPage - 1)}
              disabled={currentPage <= 1}
              className="btn-secondary"
            >
              Précédent
            </button>
            <button
              onClick={() => handlePageChange(currentPage + 1)}
              disabled={currentPage >= totalPages}
              className="btn-secondary"
            >
              Suivant
            </button>
          </div>
          <div className="hidden sm:flex sm:flex-1 sm:items-center sm:justify-between">
            <div>
              <p className="text-sm text-gray-700">
                Page <span className="font-medium">{currentPage}</span> sur{' '}
                <span className="font-medium">{totalPages}</span>
              </p>
            </div>
            <div className="flex items-center space-x-2">
              <button
                onClick={() => handlePageChange(currentPage - 1)}
                disabled={currentPage <= 1}
                className="btn-secondary"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                onClick={() => handlePageChange(currentPage + 1)}
                disabled={currentPage >= totalPages}
                className="btn-secondary"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}

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
    </div>
  );
};

// Component for a document row
const DocumentRow = ({ document, onDelete, onTogglePreservation, onReprocess, actionLoading }) => {
  const [showMenu, setShowMenu] = useState(false);

  return (
    <tr className="hover:bg-gray-50">
      <td className="px-6 py-4 whitespace-nowrap">
        <div className="flex items-center">
          <FileText className="h-5 w-5 text-gray-400 mr-3" />
          <div>
            <div className="text-sm font-medium text-gray-900 truncate max-w-xs">
              {document.filename}
            </div>
            {document.path && (
              <div className="text-sm text-gray-500 truncate max-w-xs">
                {document.path}
              </div>
            )}
          </div>
        </div>
      </td>
      <td className="px-6 py-4 whitespace-nowrap">
        <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${getStatusColor(document.status)}`}>
          {translateDocumentStatus(document.status)}
        </span>
        {document.preserve && (
          <Shield className="inline h-4 w-4 text-blue-600 ml-2" title="Document protégé" />
        )}
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
        {formatDate(document.created_at)}
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
        {safeDisplayValue(document.chunk_count, 0)}
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
        <div className="relative">
          <button
            onClick={() => setShowMenu(!showMenu)}
            className="text-gray-400 hover:text-gray-600"
            disabled={actionLoading}
          >
            <MoreVertical className="h-5 w-5" />
          </button>

          {showMenu && (
            <div className="absolute right-0 mt-2 w-48 bg-white rounded-md shadow-lg z-10 border border-gray-200">
              <div className="py-1">
                <button
                  onClick={() => {
                    onTogglePreservation();
                    setShowMenu(false);
                  }}
                  className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                >
                  <div className="flex items-center">
                    {document.preserve ? (
                      <>
                        <ShieldOff className="h-4 w-4 mr-2" />
                        Retirer la protection
                      </>
                    ) : (
                      <>
                        <Shield className="h-4 w-4 mr-2" />
                        Protéger le document
                      </>
                    )}
                  </div>
                </button>

                <button
                  onClick={() => {
                    onReprocess();
                    setShowMenu(false);
                  }}
                  className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                >
                  <div className="flex items-center">
                    <RefreshCw className="h-4 w-4 mr-2" />
                    {document.status === 'pending' ? 'Relancer le traitement' :
                     document.status === 'error' ? 'Retraiter le document' :
                     'Réindexer le document'}
                  </div>
                </button>

                <button
                  onClick={() => {
                    onDelete();
                    setShowMenu(false);
                  }}
                  className="block w-full text-left px-4 py-2 text-sm text-red-700 hover:bg-red-50"
                  disabled={document.preserve}
                >
                  <div className="flex items-center">
                    <Trash2 className="h-4 w-4 mr-2" />
                    Supprimer
                  </div>
                </button>
              </div>
            </div>
          )}
        </div>
      </td>
    </tr>
  );
};

// Delete confirmation dialog
const DeleteConfirmDialog = ({ isOpen, document, onConfirm, onCancel, loading }) => {
  if (!isOpen || !document) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        <div className="fixed inset-0 bg-gray-600 bg-opacity-75 transition-opacity" onClick={onCancel} />
        <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
          <div className="flex items-center mb-4">
            <Trash2 className="h-6 w-6 text-red-600 mr-2" />
            <h3 className="text-lg font-medium text-gray-900">
              Supprimer le document
            </h3>
          </div>

          <p className="text-sm text-gray-600 mb-6">
            Êtes-vous sûr de vouloir supprimer le document <strong>{document.filename}</strong> ?
            Cette action est irréversible.
          </p>

          {document.preserve && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-md p-3 mb-4">
              <div className="flex">
                <Shield className="h-5 w-5 text-yellow-400" />
                <div className="ml-3">
                  <p className="text-sm text-yellow-800">
                    Ce document est protégé. Vous devez d&apos;abord retirer la protection.
                  </p>
                </div>
              </div>
            </div>
          )}

          <div className="flex space-x-3">
            <button
              onClick={onCancel}
              className="flex-1 btn-secondary"
              disabled={loading}
            >
              Annuler
            </button>
            <button
              onClick={() => onConfirm(document, document.preserve)}
              className="flex-1 btn-danger"
              disabled={loading || document.preserve}
            >
              {loading ? (
                <div className="flex items-center justify-center">
                  <LoadingSpinner size="sm" className="mr-2" />
                  Suppression...
                </div>
              ) : (
                'Supprimer'
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DocumentsList;