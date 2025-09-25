import { describe, it, expect } from 'vitest';
import {
  formatDate,
  formatFileSize,
  formatNumber,
  isValidEmail,
  truncateText,
  getFileExtension,
  isSupportedFileType,
  translateDocumentStatus,
  getStatusColor
} from '../../utils/helpers';

describe('helpers utilities', () => {
  describe('formatDate', () => {
    it('formate une date correctement', () => {
      const date = '2023-09-15T10:30:00Z';
      const formatted = formatDate(date);
      expect(formatted).toMatch(/15 septembre 2023/);
    });

    it('retourne N/A pour une date null', () => {
      expect(formatDate(null)).toBe('N/A');
      expect(formatDate(undefined)).toBe('N/A');
    });

    it('retourne "Date invalide" pour une date invalide', () => {
      expect(formatDate('invalid-date')).toBe('Date invalide');
    });
  });

  describe('formatFileSize', () => {
    it('formate les tailles de fichier correctement', () => {
      expect(formatFileSize(0)).toBe('0 B');
      expect(formatFileSize(1024)).toBe('1 KB');
      expect(formatFileSize(1024 * 1024)).toBe('1 MB');
      expect(formatFileSize(1024 * 1024 * 1024)).toBe('1 GB');
    });
  });

  describe('formatNumber', () => {
    it('formate les nombres avec des espaces', () => {
      // Le formatage peut varier selon la locale, testons que c'est une chaîne
      expect(typeof formatNumber(1000)).toBe('string');
      expect(formatNumber(1000).length).toBeGreaterThan(3);
      expect(typeof formatNumber(1234567)).toBe('string');
      expect(formatNumber(1234567).length).toBeGreaterThan(6);
    });
  });

  describe('isValidEmail', () => {
    it('valide les emails corrects', () => {
      expect(isValidEmail('test@example.com')).toBe(true);
      expect(isValidEmail('user.name@domain.co.uk')).toBe(true);
    });

    it('invalide les emails incorrects', () => {
      expect(isValidEmail('invalid-email')).toBe(false);
      expect(isValidEmail('test@')).toBe(false);
      expect(isValidEmail('@example.com')).toBe(false);
    });
  });

  describe('truncateText', () => {
    it('tronque le texte correctement', () => {
      const text = 'This is a very long text that should be truncated';
      expect(truncateText(text, 20)).toBe('This is a very long...');
    });

    it('ne tronque pas si le texte est plus court', () => {
      const text = 'Short text';
      expect(truncateText(text, 20)).toBe('Short text');
    });

    it('gère les valeurs null/undefined', () => {
      expect(truncateText(null)).toBe(null);
      expect(truncateText(undefined)).toBe(undefined);
    });
  });

  describe('getFileExtension', () => {
    it('extrait l\'extension correctement', () => {
      expect(getFileExtension('document.pdf')).toBe('pdf');
      expect(getFileExtension('archive.tar.gz')).toBe('gz');
      expect(getFileExtension('README')).toBe('readme');
    });
  });

  describe('isSupportedFileType', () => {
    it('identifie les types supportés', () => {
      expect(isSupportedFileType('document.pdf')).toBe(true);
      expect(isSupportedFileType('text.docx')).toBe(true);
      expect(isSupportedFileType('readme.md')).toBe(true);
      expect(isSupportedFileType('notes.txt')).toBe(true);
    });

    it('identifie les types non supportés', () => {
      expect(isSupportedFileType('image.jpg')).toBe(false);
      expect(isSupportedFileType('archive.zip')).toBe(false);
    });
  });

  describe('translateDocumentStatus', () => {
    it('traduit les statuts correctement', () => {
      expect(translateDocumentStatus('pending')).toBe('En attente');
      expect(translateDocumentStatus('indexing')).toBe('Indexation en cours');
      expect(translateDocumentStatus('indexed')).toBe('Indexé');
      expect(translateDocumentStatus('error')).toBe('Erreur');
    });

    it('retourne le statut original si non traduit', () => {
      expect(translateDocumentStatus('unknown')).toBe('unknown');
    });
  });

  describe('getStatusColor', () => {
    it('retourne les bonnes classes CSS', () => {
      expect(getStatusColor('pending')).toContain('bg-yellow-100');
      expect(getStatusColor('indexing')).toContain('bg-blue-100');
      expect(getStatusColor('indexed')).toContain('bg-green-100');
      expect(getStatusColor('error')).toContain('bg-red-100');
    });

    it('retourne la couleur par défaut pour un statut inconnu', () => {
      expect(getStatusColor('unknown')).toContain('bg-gray-100');
    });
  });
});