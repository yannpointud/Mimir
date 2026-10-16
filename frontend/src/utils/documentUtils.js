import { documentsAPI } from '../services/api';
import { createLogger } from './logger';

const logger = createLogger('DocumentUtils');

/**
 * Opens a document in a new browser tab, falling back to a download when the
 * popup is blocked. API errors (e.g. 404 when the file is missing on disk)
 * propagate to the caller, which decides how to surface them.
 * @param {string} documentId - ID of the document to open
 * @param {string} filename - Filename used by the download fallback
 * @returns {Promise<boolean>} - true if opened in a tab, false if downloaded instead
 */
export const openDocumentInBrowser = async (documentId, filename = 'document') => {
  // Download document via authenticated API
  const response = await documentsAPI.downloadDocument(documentId);
  const blobUrl = URL.createObjectURL(response.data);

  const newWindow = window.open(blobUrl, '_blank');

  if (!newWindow) {
    // Popup blocked: download the file instead
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = filename || 'document';
    link.click();
    URL.revokeObjectURL(blobUrl);
    return false;
  }

  // Clean up blob URL once the new tab has loaded it
  setTimeout(() => {
    URL.revokeObjectURL(blobUrl);
  }, 2000);
  return true;
};

/**
 * Validates that chunk_index values match between two sources
 * @param {Array} relevantChunks - Relevant chunks from the search backend
 * @param {Array} documentChunks - Chunks from the full document
 * @returns {Object} - Validation result with statistics
 */
export const validateChunkIndexes = (relevantChunks, documentChunks) => {
  if (!relevantChunks || !documentChunks) {
    return {
      isValid: false,
      matchingCount: 0,
      totalRelevant: 0,
      missingIndexes: []
    };
  }

  const documentIndexes = new Set(documentChunks.map(dc => dc.chunk_index));

  const missingIndexes = [];
  const matchingCount = relevantChunks.filter(rc => {
    const hasMatch = documentIndexes.has(rc.chunk_index);
    if (!hasMatch) {
      missingIndexes.push(rc.chunk_index);
    }
    return hasMatch;
  }).length;

  const isValid = matchingCount === relevantChunks.length;

  logger.debug(`chunk_index validation: ${matchingCount}/${relevantChunks.length} match`, {
    isValid,
    matchingCount,
    totalRelevant: relevantChunks.length,
    missingIndexes
  });

  return {
    isValid,
    matchingCount,
    totalRelevant: relevantChunks.length,
    missingIndexes
  };
};