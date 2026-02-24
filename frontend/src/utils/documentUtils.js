import { documentsAPI } from '../services/api';

/**
 * Opens a document in the browser, handling downloads and blocked popups
 * @param {string} documentId - ID of the document to open
 * @param {string} filename - Filename (optional, for download fallback)
 * @returns {Promise<boolean>} - true if opened successfully, false otherwise
 */
export const openDocumentInBrowser = async (documentId, filename = 'document') => {
  if (!documentId) {
    console.warn('openDocumentInBrowser: documentId manquant');
    return false;
  }

  try {
    console.log(`[DocumentUtils] Ouverture du document ${documentId} dans le navigateur`);

    // Download document via authenticated API
    const response = await documentsAPI.downloadDocument(documentId);

    // Create a temporary blob URL
    const blob = response.data;
    const blobUrl = URL.createObjectURL(blob);

    // Open in a new tab
    const newWindow = window.open(blobUrl, '_blank');

    // Clean up blob URL after opening
    setTimeout(() => {
      URL.revokeObjectURL(blobUrl);
    }, 2000);

    // Check if opening succeeded
    if (!newWindow) {
      console.warn('Popup bloqué par le navigateur, fallback vers téléchargement');

      // Fallback: download the file normally
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = filename || 'document';
      link.click();
      URL.revokeObjectURL(blobUrl);

      return false; // Popup blocked but download completed
    }

    console.log(`[DocumentUtils] Document ${documentId} ouvert avec succès`);
    return true;

  } catch (error) {
    console.error(`[DocumentUtils] Erreur lors de l'ouverture du document ${documentId}:`, error);

    // On error, show a message to the user
    alert('Impossible d\'ouvrir le document. Vérifiez votre connexion.');
    return false;
  }
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

  const relevantIndexes = new Set(relevantChunks.map(rc => rc.chunk_index));
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

  console.log(`[DocumentUtils] Validation chunk_index: ${matchingCount}/${relevantChunks.length} correspondent`, {
    isValid,
    matchingCount,
    totalRelevant: relevantChunks.length,
    missingIndexes: missingIndexes.length > 0 ? missingIndexes : 'aucun'
  });

  return {
    isValid,
    matchingCount,
    totalRelevant: relevantChunks.length,
    missingIndexes
  };
};