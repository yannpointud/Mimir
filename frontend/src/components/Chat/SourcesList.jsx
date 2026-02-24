import { useState } from 'react';
import { FileText, ExternalLink, ChevronDown, ChevronUp } from 'lucide-react';
import { cn, truncateText } from '../../utils/helpers';
import DocumentModal from '../Common/DocumentModal';
import { openDocumentInBrowser } from '../../utils/documentUtils';

const SourcesList = ({ sources }) => {
  const [selectedDocumentId, setSelectedDocumentId] = useState(null);
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
      console.log(`[SourcesList] Ouverture modal pour document ${documentItem.documentId}`, {
        chunksCount: documentItem.chunks?.length || 0,
        chunkIndexes: documentItem.chunks?.map(c => c.chunk_index).slice(0, 5) || []
      });

      setSelectedDocumentId(documentItem.documentId);
      setSelectedChunks(documentItem.chunks);
      setSearchQuery(documentItem.chunks[0]?.text ? documentItem.chunks[0].text.substring(0, 50) : '');
    }
  };

  const handleOpenInBrowser = async (documentItem) => {
    if (!documentItem.documentId) return;

    await openDocumentInBrowser(documentItem.documentId, documentItem.filename);
  };


  return (
    <>
      <div className="bg-gray-50 rounded-lg border border-gray-200">
        {/* Clickable header */}
        <div
          className="flex items-center justify-between p-3 cursor-pointer hover:bg-gray-100 transition-colors duration-200"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <div className="flex items-center text-sm font-medium text-gray-700">
            <FileText className="h-4 w-4 mr-1" />
            Sources ({sources.length})
          </div>

          {/* Chevron icon */}
          {isExpanded ? (
            <ChevronUp className="h-4 w-4 text-gray-500" />
          ) : (
            <ChevronDown className="h-4 w-4 text-gray-500" />
          )}
        </div>

        {/* Expandable content */}
        {isExpanded && (
          <div className="px-3 pb-3 space-y-2 border-t border-gray-200">
            {documentItems.map((documentItem, index) => (
              <DocumentSourceItem
                key={documentItem.documentId}
                documentItem={documentItem}
                onOpenModal={handleSourceClick}
                onOpenBrowser={handleOpenInBrowser}
              />
            ))}
          </div>
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
        relevantChunks={selectedChunks}
        searchQuery={searchQuery}
        highlightText={searchQuery}
      />
    </>
  );
};

const DocumentSourceItem = ({ documentItem, onOpenModal, onOpenBrowser }) => {
  const handleOpenBrowser = () => {
    onOpenBrowser(documentItem);
  };

  const handleOpenModal = (e) => {
    e.stopPropagation();
    onOpenModal(documentItem);
  };

  return (
    <div
      className={cn(
        'p-2 rounded border transition-colors duration-200',
        'bg-white hover:bg-gray-50 border-gray-200 hover:border-gray-300'
      )}
    >
      <div className="flex items-start justify-between">
        <div
          className="flex-1 min-w-0 cursor-pointer"
          onClick={handleOpenBrowser}
          title="Ouvrir le document dans le navigateur"
        >
          {/* Document name with section count */}
          <p className="text-sm font-medium text-gray-900 truncate">
            📄 {documentItem.filename} ({documentItem.chunksCount} section{documentItem.chunksCount > 1 ? 's' : ''})
          </p>

          {/* Excerpt from most relevant chunk */}
          {(documentItem.chunks[0]?.chunk_text || documentItem.chunks[0]?.text) && (
            <p className="text-xs text-gray-600 mt-1 line-clamp-2">
              {truncateText(documentItem.chunks[0]?.chunk_text || documentItem.chunks[0]?.text || '', 120)}
            </p>
          )}

          {/* Min-max relevance display */}
          <div className="flex items-center mt-1">
            <span className="text-xs text-gray-500">
              Pertinence: {documentItem.pertinence}
            </span>
            <div className="ml-2 flex-1 max-w-16">
              <div className="bg-gray-200 rounded-full h-1">
                <div
                  className="bg-primary-600 h-1 rounded-full"
                  style={{ width: `${(documentItem.maxScore || 0) * 100}%` }}
                />
              </div>
            </div>
          </div>
        </div>

        {/* Action icon for modal */}
        <div
          className="flex-shrink-0 ml-2 cursor-pointer p-1 rounded hover:bg-gray-100"
          onClick={handleOpenModal}
          title="Voir les sections pertinentes du document"
        >
          <ExternalLink className="h-4 w-4 text-gray-400 hover:text-gray-600" />
        </div>
      </div>
    </div>
  );
};

export default SourcesList;