import { useState, useEffect, useCallback } from 'react';
import { FileText, ExternalLink, AlertCircle, RefreshCw } from 'lucide-react';
import { documentsAPI } from '../../services/api';
import { getErrorMessage, escapeHtml, cn } from '../../utils/helpers';
import { openDocumentInBrowser, validateChunkIndexes } from '../../utils/documentUtils';
import LoadingSpinner from './LoadingSpinner';
import Modal from './Modal';

const formatScore = (score) => `${Math.round((score || 0) * 100)} %`;

const DocumentModal = ({ isOpen, onClose, documentId, filename, searchQuery = '', highlightText = '', relevantChunks = [] }) => {
  const [documentData, setDocumentData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [openOriginalError, setOpenOriginalError] = useState(null);
  const [selectedChunk, setSelectedChunk] = useState(null);
  const [showAllChunks, setShowAllChunks] = useState(false);


  // Auto-select the first relevant chunk when data is loaded
  useEffect(() => {
    if (documentData?.chunks && relevantChunks.length > 0) {
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

  const loadDocument = useCallback(async () => {
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
  }, [documentId]);

  // Load document when modal opens
  useEffect(() => {
    if (isOpen && documentId) {
      loadDocument();
    }
  }, [isOpen, documentId, loadDocument]);

  // Highlight searched text in content (escape-then-highlight, SEC-04).
  // The document text is ALWAYS HTML-escaped before insertion so malicious
  // content renders as inert literal text; the query is escaped the same way
  // so matches still line up with the escaped text. Only <mark> tags may
  // exist in the final injected HTML.
  const highlightTextInContent = (text, query) => {
    if (!text) return text;

    const escapedText = escapeHtml(text);
    if (!query) return escapedText;

    // Escape the query as HTML first (to match escaped entities), then escape
    // regex metacharacters so a crafted query cannot break the highlighting
    const escapedQuery = escapeHtml(query);
    const regex = new RegExp(`(${escapedQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return escapedText.replace(regex, '<mark class="rounded-sm bg-hl px-0.5 text-ink">$1</mark>');
  };

  // Close the modal
  const handleClose = () => {
    setDocumentData(null);
    setSelectedChunk(null);
    setError(null);
    setOpenOriginalError(null);
    onClose();
  };

  // Open the original document in the browser
  const handleOpenDocument = async () => {
    setOpenOriginalError(null);
    try {
      await openDocumentInBrowser(documentId, documentData?.filename);
    } catch (openError) {
      setOpenOriginalError(getErrorMessage(openError));
    }
  };

  const query = highlightText || searchQuery;

  const metaParts = documentData ? [
    documentData.mime_type,
    `${documentData.chunk_count || documentData.chunks?.length || 0} sections`,
    documentData.created_at && `ajouté le ${new Date(documentData.created_at).toLocaleDateString('fr-FR')}`,
  ].filter(Boolean) : [];

  // Sections listed in the left pane: only the relevant ones unless the user asks for all
  const relevantChunkIndices = new Set(relevantChunks.map(rc => rc.chunk_index));
  let chunksToDisplay = documentData?.chunks || [];
  if (relevantChunks.length > 0 && !showAllChunks) {
    const filtered = chunksToDisplay.filter(chunk => relevantChunkIndices.has(chunk.chunk_index));
    // If no chunks match, display all chunks
    if (filtered.length > 0) {
      chunksToDisplay = filtered;
    }
  }
  const sortedChunks = [...chunksToDisplay].sort((a, b) => (a.chunk_index || 0) - (b.chunk_index || 0));
  const showingRelevantOnly = relevantChunks.length > 0 && !showAllChunks;
  const selectedRelevance = selectedChunk && relevantChunks.find(rc => rc.chunk_index === selectedChunk.chunk_index);

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      size="xl"
      icon={FileText}
      title={documentData?.filename || filename || 'Document'}
      description={loading ? 'Chargement…' : metaParts.join(' · ')}
      panelClassName="sm:h-[86dvh]"
      bodyClassName="flex flex-col overflow-hidden md:flex-row"
      actions={documentData?.path && (
        <button
          type="button"
          onClick={handleOpenDocument}
          className="btn-secondary btn-sm mr-1"
          title="Ouvrir le fichier original dans le navigateur"
        >
          <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="sr-only sm:not-sr-only">Ouvrir l&apos;original</span>
        </button>
      )}
      footer={
        <>
          {openOriginalError && (
            <p role="alert" className="mr-auto min-w-0 truncate text-sm text-danger">
              Impossible d&apos;ouvrir le fichier original : {openOriginalError}
            </p>
          )}
          {searchQuery && !openOriginalError && (
            <p className="mr-auto min-w-0 truncate text-sm text-ink-muted">
              Recherche : <strong className="font-medium text-ink">{searchQuery}</strong>
            </p>
          )}
          <button type="button" onClick={handleClose} className="btn-secondary">
            Fermer
          </button>
        </>
      }
    >
      {loading ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-12">
          <LoadingSpinner size="lg" />
          <p className="text-sm text-ink-muted">Chargement du document...</p>
        </div>
      ) : error ? (
        <div className="flex flex-1 items-center justify-center p-8">
          <div className="alert-danger max-w-md">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <div>
              <p>{error}</p>
              <button type="button" onClick={loadDocument} className="btn-secondary btn-sm mt-3">
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                Réessayer
              </button>
            </div>
          </div>
        </div>
      ) : documentData ? (
        <>
          {/* Section navigation */}
          {sortedChunks.length > 0 && (
            <nav
              aria-label="Sections du document"
              className="max-h-[34%] shrink-0 overflow-y-auto border-b border-line-soft bg-surface md:max-h-none md:w-72 md:border-b-0 md:border-r"
            >
              <div className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-line-soft bg-surface/95 px-4 py-3 backdrop-blur">
                <p className="eyebrow">
                  {showingRelevantOnly ? `Sections pertinentes · ${sortedChunks.length}/${documentData.chunks.length}` : `Sections · ${documentData.chunks.length}`}
                </p>
                {relevantChunks.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setShowAllChunks(!showAllChunks)}
                    className="text-xs font-medium text-accent-ink underline-offset-2 hover:underline"
                    title={showAllChunks ? 'Voir seulement les sections pertinentes' : 'Voir toutes les sections du document'}
                  >
                    {showAllChunks ? 'Pertinentes seulement' : 'Voir tout'}
                  </button>
                )}
              </div>
              <ul className="space-y-1.5 p-2.5">
                {sortedChunks.map((chunk) => {
                  const relevantChunk = relevantChunks.find(rc => rc.chunk_index === chunk.chunk_index);
                  const isSelected = selectedChunk?.id === chunk.id;
                  const matchesQuery = highlightText && chunk.text?.toLowerCase().includes(highlightText.toLowerCase());

                  return (
                    <li key={chunk.id || chunk.chunk_index}>
                      <button
                        type="button"
                        onClick={() => setSelectedChunk(chunk)}
                        aria-current={isSelected ? 'true' : undefined}
                        className={cn(
                          'w-full rounded-lg border p-3 text-left transition-colors duration-150',
                          isSelected
                            ? 'border-accent/50 bg-accent-soft/60'
                            : 'border-transparent hover:border-line-soft hover:bg-sunken'
                        )}
                      >
                        <span className="flex items-center gap-2">
                          <span className={cn('text-sm font-semibold', isSelected ? 'text-accent-ink' : 'text-ink')}>
                            Section {(chunk.chunk_index || 0) + 1}
                          </span>
                          {relevantChunk && (
                            <span className="badge-accent ml-auto px-2 py-0 font-mono text-2xs tabular">
                              {formatScore(relevantChunk.similarity_score)}
                            </span>
                          )}
                        </span>
                        <span className="mt-1 line-clamp-2 block text-xs leading-relaxed text-ink-muted">
                          {chunk.text?.substring(0, 120)}…
                        </span>
                        {matchesQuery && (
                          <span className="mt-2 inline-flex items-center rounded-full bg-hl-soft px-2 py-0.5 text-2xs font-medium text-ink">
                            Contient le terme recherché
                          </span>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </nav>
          )}

          {/* Reading pane */}
          <div className="min-h-0 flex-1 overflow-y-auto bg-canvas/70 p-4 sm:p-6 lg:p-8">
            <article className="mx-auto max-w-prose rounded-lg border border-line bg-surface px-6 py-7 shadow-card sm:px-10 sm:py-10">
              {selectedChunk ? (
                <>
                  <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-line-soft pb-4">
                    <div>
                      <p className="eyebrow">Section sélectionnée</p>
                      <h3 className="mt-1 font-serif text-xl font-semibold text-ink">
                        Section {(selectedChunk.chunk_index || 0) + 1}
                        {selectedRelevance && (
                          <span className="ml-2 align-middle font-sans text-xs font-medium text-accent-ink">
                            Pertinence {formatScore(selectedRelevance.similarity_score)}
                          </span>
                        )}
                      </h3>
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedChunk(null)}
                      className="btn-ghost btn-sm"
                    >
                      Voir tout le document
                    </button>
                  </div>
                  <div
                    className="prose doc-text max-w-none whitespace-pre-wrap"
                    dangerouslySetInnerHTML={{
                      __html: highlightTextInContent(selectedChunk.text, query)
                    }}
                  />
                </>
              ) : (
                <>
                  <p className="eyebrow">Aperçu du document</p>
                  <h3 className="mt-1 font-serif text-2xl font-semibold leading-snug text-ink">
                    {documentData.filename || 'Document'}
                  </h3>
                  <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 border-y border-line-soft py-4 text-sm sm:grid-cols-4">
                    <div>
                      <dt className="text-xs text-ink-muted">Taille</dt>
                      <dd className="mt-0.5 font-medium text-ink tabular">
                        {documentData.file_size ? `${Math.round(documentData.file_size / 1024)} Ko` : 'N/A'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-ink-muted">Sections</dt>
                      <dd className="mt-0.5 font-medium text-ink tabular">
                        {documentData.chunk_count || documentData.chunks?.length || 0}
                      </dd>
                    </div>
                    <div className="min-w-0">
                      <dt className="text-xs text-ink-muted">Type</dt>
                      <dd className="mt-0.5 truncate font-medium text-ink">{documentData.mime_type || 'N/A'}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-ink-muted">Ajouté</dt>
                      <dd className="mt-0.5 font-medium text-ink tabular">
                        {documentData.created_at ? new Date(documentData.created_at).toLocaleDateString('fr-FR') : 'N/A'}
                      </dd>
                    </div>
                  </dl>

                  {/* Full or excerpt content */}
                  {documentData.content ? (
                    <div
                      className="prose doc-text mt-6 max-w-none whitespace-pre-wrap"
                      dangerouslySetInnerHTML={{
                        __html: highlightTextInContent(documentData.content, query)
                      }}
                    />
                  ) : documentData.chunks && documentData.chunks.length > 0 ? (
                    <div className="mt-6 space-y-6">
                      <p className="text-sm text-ink-muted">
                        Sélectionnez une section pour lire son contenu détaillé, ou parcourez l&apos;aperçu ci-dessous.
                      </p>
                      {documentData.chunks.slice(0, 3).map((chunk, index) => (
                        <button
                          type="button"
                          key={chunk.id || index}
                          onClick={() => setSelectedChunk(chunk)}
                          className="block w-full border-l-2 border-line pl-4 text-left transition-colors hover:border-accent"
                        >
                          <span className="block text-sm font-semibold text-ink">Section {index + 1}</span>
                          <span
                            className="doc-text mt-1 line-clamp-4 block text-[15px]"
                            dangerouslySetInnerHTML={{
                              __html: highlightTextInContent(
                                chunk.text?.substring(0, 300) + (chunk.text?.length > 300 ? '...' : ''),
                                query
                              )
                            }}
                          />
                        </button>
                      ))}
                      {documentData.chunks.length > 3 && (
                        <p className="text-sm text-ink-muted">
                          … et {documentData.chunks.length - 3} autres sections
                        </p>
                      )}
                    </div>
                  ) : (
                    <div className="py-10 text-center">
                      <FileText className="mx-auto h-10 w-10 text-ink-faint" aria-hidden="true" />
                      <p className="mt-3 text-sm font-medium text-ink">Contenu non disponible</p>
                      <p className="mt-1 text-sm text-ink-muted">
                        Le contenu de ce document n&apos;a pas pu être chargé.
                      </p>
                    </div>
                  )}
                </>
              )}
            </article>
          </div>
        </>
      ) : null}
    </Modal>
  );
};

export default DocumentModal;
