import { useState, useEffect } from 'react';
import { X, FileText, Search, Download, ExternalLink } from 'lucide-react';
import { documentsAPI } from '../../services/api';
import { getErrorMessage } from '../../utils/helpers';
import { openDocumentInBrowser, validateChunkIndexes } from '../../utils/documentUtils';
import LoadingSpinner from './LoadingSpinner';

const DocumentModal = ({ isOpen, onClose, documentId, searchQuery = '', highlightText = '', relevantChunks = [] }) => {
  const [documentData, setDocumentData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedChunk, setSelectedChunk] = useState(null);
  const [showAllChunks, setShowAllChunks] = useState(false);

  // Load document when modal opens
  useEffect(() => {
    if (isOpen && documentId) {
      loadDocument();
    }
  }, [isOpen, documentId]);

  // Auto-select the first relevant chunk when data is loaded
  useEffect(() => {
    if (documentData?.chunks && relevantChunks.length > 0) {
      console.log(`[DocumentModal] Validation des chunks pour document ${documentId}`);

      // Validate chunk_index correspondence
      const validation = validateChunkIndexes(relevantChunks, documentData.chunks);

      if (!validation.isValid) {
        console.warn(`[DocumentModal] Chunks manquants détectés:`, {
          matching: validation.matchingCount,
          total: validation.totalRelevant,
          missing: validation.missingIndexes
        });
      }

      // Find the first relevant chunk in the document data
      const firstRelevantChunk = documentData.chunks.find(chunk =>
        relevantChunks.some(rc => rc.chunk_index === chunk.chunk_index)
      );

      if (firstRelevantChunk) {
        console.log(`[DocumentModal] Chunk pertinent sélectionné: index ${firstRelevantChunk.chunk_index}`);
        setSelectedChunk(firstRelevantChunk);
      } else if (validation.matchingCount === 0) {
        console.error(`[DocumentModal] Aucun chunk pertinent trouvé - problème de correspondance d'index`);
        // Fallback: select the first chunk of the document
        if (documentData.chunks.length > 0) {
          setSelectedChunk(documentData.chunks[0]);
        }
      }
    }
  }, [documentData, relevantChunks, documentId]);

  const loadDocument = async () => {
    try {
      setLoading(true);
      setError(null);

      // Fetch document details with chunks
      const docResponse = await documentsAPI.getDocumentWithChunks(documentId);
      setDocumentData(docResponse);

    } catch (error) {
      console.error('Erreur lors du chargement du document:', error);
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  // Highlight searched text in content
  const highlightTextInContent = (text, query) => {
    if (!query || !text) return text;

    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return text.replace(regex, '<mark class="bg-yellow-200 px-1 rounded">$1</mark>');
  };

  // Close the modal
  const handleClose = () => {
    setDocumentData(null);
    setSelectedChunk(null);
    setError(null);
    onClose();
  };

  // Open the original document in the browser
  const handleOpenDocument = async () => {
    if (!documentId) return;

    await openDocumentInBrowser(documentId, documentData?.filename);
  };

  // Keyboard event handling
  useEffect(() => {
    const handleEscKey = (event) => {
      if (event.key === 'Escape') {
        handleClose();
      }
    };

    if (isOpen && typeof window !== 'undefined' && window.document) {
      window.document.addEventListener('keydown', handleEscKey);
      return () => window.document.removeEventListener('keydown', handleEscKey);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        {/* Overlay */}
        <div
          className="fixed inset-0 bg-gray-600 bg-opacity-75 transition-opacity"
          onClick={handleClose}
        />

        {/* Modal */}
        <div className="relative bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-gray-200">
            <div className="flex items-center">
              <FileText className="h-6 w-6 text-gray-400 mr-3" />
              <div>
                <h3 className="text-lg font-medium text-gray-900">
                  {documentData?.filename || 'Document'}
                </h3>
                {documentData?.path && (
                  <p className="text-sm text-gray-500">{documentData.path}</p>
                )}
              </div>
            </div>

            <div className="flex items-center space-x-2">
              {/* Document actions */}
              {documentData?.path && (
                <button
                  onClick={handleOpenDocument}
                  className="p-2 text-gray-400 hover:text-gray-600 rounded-md hover:bg-gray-100"
                  title="Ouvrir le fichier original dans le navigateur"
                >
                  <ExternalLink className="h-5 w-5" />
                </button>
              )}

              <button
                onClick={handleClose}
                className="p-2 text-gray-400 hover:text-gray-600 rounded-md hover:bg-gray-100"
              >
                <X className="h-6 w-6" />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-hidden flex">
            {loading ? (
              <div className="flex-1 flex items-center justify-center">
                <div className="text-center">
                  <LoadingSpinner size="lg" />
                  <p className="mt-4 text-gray-600">Chargement du document...</p>
                </div>
              </div>
            ) : error ? (
              <div className="flex-1 flex items-center justify-center">
                <div className="text-center">
                  <div className="bg-red-50 border border-red-200 rounded-md p-4">
                    <p className="text-red-700">{error}</p>
                    <button
                      onClick={loadDocument}
                      className="mt-2 btn-primary text-sm"
                    >
                      Réessayer
                    </button>
                  </div>
                </div>
              </div>
            ) : documentData ? (
              <>
                {/* Chunk navigation on the left */}
                {documentData.chunks && documentData.chunks.length > 0 && (() => {
                  // If we have relevant chunks, only show those
                  const relevantChunkIndices = new Set(
                    relevantChunks.map(rc => rc.chunk_index)
                  );

                  // Filtering with match validation
                  let chunksToDisplay = documentData.chunks;

                  if (relevantChunks.length > 0 && !showAllChunks) {
                    chunksToDisplay = documentData.chunks.filter(chunk =>
                      relevantChunkIndices.has(chunk.chunk_index)
                    );

                    console.log(`[DocumentModal] Filtrage chunks: ${chunksToDisplay.length}/${documentData.chunks.length} affichés`, {
                      relevantIndexes: Array.from(relevantChunkIndices).slice(0, 5),
                      filteredCount: chunksToDisplay.length
                    });

                    // If no chunks match, display all chunks with a warning
                    if (chunksToDisplay.length === 0) {
                      console.warn(`[DocumentModal] Aucun chunk ne correspond aux index pertinents - affichage de tous les chunks`);
                      chunksToDisplay = documentData.chunks;
                    }
                  }

                  // Sort by chunk_index
                  const sortedChunks = [...chunksToDisplay].sort((a, b) =>
                    (a.chunk_index || 0) - (b.chunk_index || 0)
                  );

                  return (
                    <div className="w-80 border-r border-gray-200 overflow-y-auto">
                      <div className="p-4 border-b border-gray-200">
                        <div className="flex items-center justify-between">
                          <h4 className="text-sm font-medium text-gray-900 flex items-center">
                            <Search className="h-4 w-4 mr-2" />
                            {relevantChunks.length > 0 && !showAllChunks ? (
                              <>
                                Sections pertinentes ({chunksToDisplay.length})
                                <span className="ml-2 text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded-full">
                                  sur {documentData.chunks.length} total
                                </span>
                              </>
                            ) : (
                              `Sections (${documentData.chunks.length})`
                            )}
                          </h4>

                          {relevantChunks.length > 0 && (
                            <button
                              onClick={() => setShowAllChunks(!showAllChunks)}
                              className="text-xs text-blue-600 hover:text-blue-800 underline"
                              title={showAllChunks ? "Voir seulement les sections pertinentes" : "Voir toutes les sections du document"}
                            >
                              {showAllChunks ? "Pertinentes seulement" : "Voir tout"}
                            </button>
                          )}
                        </div>
                      </div>
                      <div className="p-2">
                        {sortedChunks.map((chunk) => {
                          const relevantChunk = relevantChunks.find(rc => rc.chunk_index === chunk.chunk_index);
                          const isFromSearch = !!relevantChunk;

                          return (
                            <button
                              key={chunk.id || chunk.chunk_index}
                              onClick={() => setSelectedChunk(chunk)}
                              className={`w-full text-left p-3 rounded-md mb-2 transition-colors duration-200 ${
                                selectedChunk?.id === chunk.id
                                  ? 'bg-primary-50 border border-primary-200'
                                  : isFromSearch
                                    ? 'bg-blue-50 hover:bg-blue-100 border border-blue-200'
                                    : 'hover:bg-gray-50 border border-transparent'
                              }`}
                            >
                              <div className="text-sm text-gray-900 font-medium mb-1 flex items-center">
                                <span>Section {(chunk.chunk_index || 0) + 1}</span>
                                {isFromSearch && (
                                  <span className="ml-2 text-xs bg-blue-600 text-white px-2 py-0.5 rounded-full">
                                    {Math.round((relevantChunk.similarity_score || 0) * 100)}%
                                  </span>
                                )}
                              </div>
                              <div className="text-xs text-gray-600 line-clamp-3">
                                {chunk.text?.substring(0, 120)}...
                              </div>
                              {highlightText && chunk.text?.toLowerCase().includes(highlightText.toLowerCase()) && (
                                <div className="mt-1">
                                  <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
                                    Contient le terme recherché
                                  </span>
                                </div>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}

                {/* Main content on the right */}
                <div className="flex-1 overflow-y-auto">
                  <div className="p-6">
                    {selectedChunk ? (
                      <div>
                        <div className="mb-4">
                          <div className="flex items-center justify-between">
                            <h4 className="text-lg font-medium text-gray-900">
                              Section sélectionnée
                            </h4>
                            <button
                              onClick={() => setSelectedChunk(null)}
                              className="text-sm text-gray-500 hover:text-gray-700"
                            >
                              Voir tout le document
                            </button>
                          </div>
                        </div>
                        <div
                          className="prose max-w-none text-gray-700 whitespace-pre-wrap"
                          dangerouslySetInnerHTML={{
                            __html: highlightTextInContent(selectedChunk.text, highlightText || searchQuery)
                          }}
                        />
                      </div>
                    ) : (
                      <div>
                        <div className="mb-6">
                          <h4 className="text-lg font-medium text-gray-900 mb-2">
                            Aperçu du document
                          </h4>
                          <div className="grid grid-cols-2 gap-4 text-sm">
                            <div>
                              <span className="font-medium text-gray-500">Taille:</span>
                              <span className="ml-2 text-gray-900">
                                {documentData.file_size ? `${Math.round(documentData.file_size / 1024)} KB` : 'N/A'}
                              </span>
                            </div>
                            <div>
                              <span className="font-medium text-gray-500">Sections:</span>
                              <span className="ml-2 text-gray-900">
                                {documentData.chunk_count || documentData.chunks?.length || 0}
                              </span>
                            </div>
                            <div>
                              <span className="font-medium text-gray-500">Type:</span>
                              <span className="ml-2 text-gray-900">
                                {documentData.mime_type || 'N/A'}
                              </span>
                            </div>
                            <div>
                              <span className="font-medium text-gray-500">Ajouté:</span>
                              <span className="ml-2 text-gray-900">
                                {documentData.created_at ? new Date(documentData.created_at).toLocaleDateString('fr-FR') : 'N/A'}
                              </span>
                            </div>
                          </div>
                        </div>

                        {/* Full or excerpt content */}
                        {documentData.content ? (
                          <div
                            className="prose max-w-none text-gray-700 whitespace-pre-wrap"
                            dangerouslySetInnerHTML={{
                              __html: highlightTextInContent(documentData.content, highlightText || searchQuery)
                            }}
                          />
                        ) : documentData.chunks && documentData.chunks.length > 0 ? (
                          <div className="space-y-6">
                            <p className="text-gray-600 text-sm">
                              Sélectionnez une section à gauche pour voir le contenu détaillé, ou parcourez l'aperçu ci-dessous.
                            </p>
                            {documentData.chunks.slice(0, 3).map((chunk, index) => (
                              <div key={chunk.id || index} className="border-l-4 border-gray-200 pl-4">
                                <div className="text-sm font-medium text-gray-900 mb-2">
                                  Section {index + 1}
                                </div>
                                <div
                                  className="text-gray-700 text-sm line-clamp-4"
                                  dangerouslySetInnerHTML={{
                                    __html: highlightTextInContent(
                                      chunk.text?.substring(0, 300) + (chunk.text?.length > 300 ? '...' : ''),
                                      highlightText || searchQuery
                                    )
                                  }}
                                />
                              </div>
                            ))}
                            {documentData.chunks.length > 3 && (
                              <p className="text-gray-500 text-sm">
                                ... et {documentData.chunks.length - 3} autres sections
                              </p>
                            )}
                          </div>
                        ) : (
                          <div className="text-center py-8">
                            <FileText className="mx-auto h-12 w-12 text-gray-400" />
                            <h3 className="mt-2 text-sm font-medium text-gray-900">
                              Contenu non disponible
                            </h3>
                            <p className="mt-1 text-sm text-gray-500">
                              Le contenu de ce document n'a pas pu être chargé.
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </>
            ) : null}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between p-4 border-t border-gray-200 bg-gray-50">
            <div className="text-sm text-gray-500">
              {searchQuery && (
                <span>Recherche : <strong>{searchQuery}</strong></span>
              )}
            </div>
            <button
              onClick={handleClose}
              className="btn-secondary"
            >
              Fermer
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DocumentModal;