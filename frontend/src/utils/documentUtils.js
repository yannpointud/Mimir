import { documentsAPI } from '../services/api';

/**
 * Ouvre un document dans le navigateur en gérant le téléchargement et les popups bloqués
 * @param {string} documentId - ID du document à ouvrir
 * @param {string} filename - Nom du fichier (optionnel, pour le fallback download)
 * @returns {Promise<boolean>} - true si ouvert avec succès, false sinon
 */
export const openDocumentInBrowser = async (documentId, filename = 'document') => {
  if (!documentId) {
    console.warn('openDocumentInBrowser: documentId manquant');
    return false;
  }

  try {
    console.log(`[DocumentUtils] Ouverture du document ${documentId} dans le navigateur`);

    // Télécharger le document via API authentifiée
    const response = await documentsAPI.downloadDocument(documentId);

    // Créer une URL blob temporaire
    const blob = response.data;
    const blobUrl = URL.createObjectURL(blob);

    // Ouvrir dans un nouvel onglet
    const newWindow = window.open(blobUrl, '_blank');

    // Nettoyer l'URL blob après ouverture
    setTimeout(() => {
      URL.revokeObjectURL(blobUrl);
    }, 2000);

    // Vérifier si l'ouverture a réussi
    if (!newWindow) {
      console.warn('Popup bloqué par le navigateur, fallback vers téléchargement');

      // Fallback : télécharger le fichier normalement
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = filename || 'document';
      link.click();
      URL.revokeObjectURL(blobUrl);

      return false; // Popup bloqué mais téléchargement effectué
    }

    console.log(`[DocumentUtils] Document ${documentId} ouvert avec succès`);
    return true;

  } catch (error) {
    console.error(`[DocumentUtils] Erreur lors de l'ouverture du document ${documentId}:`, error);

    // En cas d'erreur, afficher un message à l'utilisateur
    alert('Impossible d\'ouvrir le document. Vérifiez votre connexion.');
    return false;
  }
};

/**
 * Valide que les chunk_index correspondent entre deux sources
 * @param {Array} relevantChunks - Chunks pertinents du backend recherche
 * @param {Array} documentChunks - Chunks du document complet
 * @returns {Object} - Résultat de validation avec statistiques
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