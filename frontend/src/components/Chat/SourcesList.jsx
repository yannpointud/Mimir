import { useState } from 'react';
import { FileText, ExternalLink, ChevronDown, ChevronUp } from 'lucide-react';
import { cn, truncateText } from '../../utils/helpers';
import DocumentModal from '../Common/DocumentModal';
import { openDocumentInBrowser } from '../../utils/documentUtils';

const SourcesList = ({ sources }) => {
  const [selectedDocumentId, setSelectedDocumentId] = useState(null);
  const [selectedFilename, setSelectedFilename] = useState(null);
  const [selectedChunks, setSelectedChunks] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [isExpanded, setIsExpanded] = useState(false);

  if (!sources || sources.length === 0) {
    return null;
  }

  // Group sources by document_id
  const groupedSources = sources.reduce((acc, source) => {
    if (!acc[source.document_id]) {
      acc[source.document_id] = [];
    }
    acc[source.document_id].push(source);
    return acc;
  }, {});

  // Create document items with metadata
  const documentItems = Object.entries(groupedSources).map(([documentId, chunks]) => {
    const scores = chunks.map(c => c.similarity_score).filter(s => s != null && !isNaN(s));

    const maxScore = scores.length > 0 ? Math.max(...scores) : 0;
    const minScore = scores.length > 0 ? Math.min(...scores) : 0;

    const pertinenceDisplay = scores.length === 0 ? 'N/A' :
      maxScore === minScore ? `${Math.round(maxScore * 100)}%` :
      `${Math.round(maxScore * 100)}%-${Math.round(minScore * 100)}%`;

    return {
      documentId,
      filename: chunks[0].filename || chunks[0].document_name || chunks[0].source || 'Document',
      chunksCount: chunks.length,
      pertinence: pertinenceDisplay,
      chunks,
      maxScore
    };
  });

  // Sort by max relevance descending
  documentItems.sort((a, b) => (b.maxScore || 0) - (a.maxScore || 0));

  const handleSourceClick = (documentItem) => {
    // Open modal with document and relevant chunks
    if (documentItem.documentId) {
      setSelectedDocumentId(documentItem.documentId);
      setSelectedFilename(documentItem.filename);
      setSelectedChunks(documentItem.chunks);
      setSearchQuery(documentItem.chunks[0]?.text ? documentItem.chunks[0].text.substring(0, 50) : '');
    }
  };

  // When the original file cannot be served (e.g. missing on disk), fall back
  // to the sections modal, which still shows the indexed text of the document.
  const handleOpenInBrowser = async (documentItem) => {
    try {
      await openDocumentInBrowser(documentItem.documentId, documentItem.filename);
    } catch {
      handleSourceClick(documentItem);
    }
  };

  const Chevron = isExpanded ? ChevronUp : ChevronDown;

  return (
    <>
      <div>
        {/* Toggle header */}
        <button
          type="button"
          onClick={() => setIsExpanded(!isExpanded)}
          aria-expanded={isExpanded}
          className="group -mx-2 flex w-[calc(100%+1rem)] items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-sunken"
        >
          <FileText className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
          <span className="shrink-0 text-[13px] font-semibold text-ink">Sources ({sources.length})</span>
          {!isExpanded && (
            <span className="min-w-0 truncate text-[13px] text-ink-muted">
              {documentItems.map(item => item.filename).join(' · ')}
            </span>
          )}
          <Chevron className="ml-auto h-4 w-4 shrink-0 text-ink-faint group-hover:text-ink-muted" aria-hidden="true" />
        </button>

        {/* Expandable content */}
        {isExpanded && (
          <ol className="mt-2 animate-fade-in space-y-2">
            {documentItems.map((documentItem, index) => (
              <DocumentSourceItem
                key={documentItem.documentId}
                index={index}
                documentItem={documentItem}
                onOpenModal={handleSourceClick}
                onOpenBrowser={handleOpenInBrowser}
              />
            ))}
          </ol>
        )}
      </div>

      {/* Document modal */}
      <DocumentModal
        isOpen={selectedDocumentId !== null}
        onClose={() => {
          setSelectedDocumentId(null);
          setSelectedChunks([]);
        }}
        documentId={selectedDocumentId}
        filename={selectedFilename}
        relevantChunks={selectedChunks}
        searchQuery={searchQuery}
        highlightText={searchQuery}
      />
    </>
  );
};

const DocumentSourceItem = ({ documentItem, index, onOpenModal, onOpenBrowser }) => {
  const excerpt = documentItem.chunks[0]?.chunk_text || documentItem.chunks[0]?.text;

  return (
    <li
      className={cn(
        'flex items-start gap-3 rounded-lg border p-3 transition-colors duration-200',
        'border-line-soft bg-surface hover:border-line hover:bg-sunken/60'
      )}
    >
      <span
        className="mt-px flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent-soft font-mono text-xs font-medium text-accent-ink"
        aria-hidden="true"
      >
        {index + 1}
      </span>

      <div className="min-w-0 flex-1">
        {/* Document name with section count */}
        <button
          type="button"
          onClick={() => onOpenBrowser(documentItem)}
          className="block max-w-full truncate text-left text-sm font-medium text-ink underline-offset-2 hover:text-accent-ink hover:underline"
          title="Ouvrir le document dans le navigateur"
        >
          {documentItem.filename} <span className="font-normal text-ink-muted">({documentItem.chunksCount} section{documentItem.chunksCount > 1 ? 's' : ''})</span>
        </button>

        {/* Excerpt from most relevant chunk */}
        {excerpt && (
          <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-ink-muted">
            {truncateText(excerpt, 120)}
          </p>
        )}

        {/* Min-max relevance display */}
        <div className="mt-2 flex items-center gap-2">
          <span className="tabular text-xs text-ink-muted">
            Pertinence: {documentItem.pertinence}
          </span>
          <div className="h-1 w-16 overflow-hidden rounded-full bg-line-soft" aria-hidden="true">
            <div
              className="h-1 rounded-full bg-accent"
              style={{ width: `${(documentItem.maxScore || 0) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Relevant sections preview */}
      <button
        type="button"
        onClick={() => onOpenModal(documentItem)}
        className="btn-secondary btn-sm shrink-0"
        title="Voir les sections pertinentes du document"
      >
        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="sr-only sm:not-sr-only">Aperçu</span>
      </button>
    </li>
  );
};

export default SourcesList;
