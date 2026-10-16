import { useState, useCallback } from 'react';
import { useOutletContext } from 'react-router-dom';
import { useDropzone } from 'react-dropzone';
import { documentsAPI } from '../../services/api';
import { getErrorMessage, formatFileSize, isSupportedFileType, cn } from '../../utils/helpers';
import {
  Upload,
  UploadCloud,
  File,
  X,
  CheckCircle,
  AlertCircle,
  Shield,
  Loader
} from 'lucide-react';
import { createLogger } from '../../utils/logger';

const logger = createLogger('UploadZone');

const UploadZone = () => {
  const { onUploadSuccess } = useOutletContext();
  const [uploads, setUploads] = useState([]);
  const [isUploading, setIsUploading] = useState(false);

  // react-dropzone configuration
  const onDrop = useCallback((acceptedFiles, rejectedFiles) => {
    // Handle rejected files
    rejectedFiles.forEach(({ file, errors }) => {
      logger.warn('File rejected', { filename: file.name, errors });
    });

    // Add accepted files to the upload list
    const newUploads = acceptedFiles.map(file => ({
      id: Date.now() + Math.random(),
      file,
      status: 'pending', // pending, uploading, success, error
      progress: 0,
      preserve: false,
      error: null
    }));

    setUploads(prev => [...prev, ...newUploads]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'text/plain': ['.txt'],
      'text/markdown': ['.md']
    },
    maxSize: 100 * 1024 * 1024, // 100MB
    multiple: true
  });

  // Remove a file from the list
  const removeUpload = (id) => {
    setUploads(prev => prev.filter(upload => upload.id !== id));
  };

  // Toggle preservation status
  const togglePreserve = (id) => {
    setUploads(prev => prev.map(upload =>
      upload.id === id
        ? { ...upload, preserve: !upload.preserve }
        : upload
    ));
  };

  // Upload a file
  const uploadFile = async (upload) => {
    setUploads(prev => prev.map(u =>
      u.id === upload.id
        ? { ...u, status: 'uploading', progress: 0 }
        : u
    ));

    try {
      await documentsAPI.uploadDocument(upload.file, upload.preserve);

      setUploads(prev => prev.map(u =>
        u.id === upload.id
          ? { ...u, status: 'success', progress: 100 }
          : u
      ));

      // Notify parent of success
      onUploadSuccess?.();

    } catch (error) {
      logger.error('Upload failed', error);
      setUploads(prev => prev.map(u =>
        u.id === upload.id
          ? {
              ...u,
              status: 'error',
              progress: 0,
              error: getErrorMessage(error)
            }
          : u
      ));
    }
  };

  // Upload all pending files
  const uploadAllFiles = async () => {
    const pendingUploads = uploads.filter(upload => upload.status === 'pending');
    if (pendingUploads.length === 0) return;

    setIsUploading(true);

    try {
      // Upload files sequentially to avoid overload
      for (const upload of pendingUploads) {
        await uploadFile(upload);
      }
    } finally {
      setIsUploading(false);
    }
  };

  // Clean the list (remove successes and errors)
  const clearCompleted = () => {
    setUploads(prev => prev.filter(upload =>
      upload.status === 'pending' || upload.status === 'uploading'
    ));
  };

  const pendingCount = uploads.filter(u => u.status === 'pending').length;
  const uploadingCount = uploads.filter(u => u.status === 'uploading').length;
  const successCount = uploads.filter(u => u.status === 'success').length;
  const errorCount = uploads.filter(u => u.status === 'error').length;

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        {/* Drop zone */}
        <div
          {...getRootProps({ role: 'button' })}
          className={cn(
            'group flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-14 text-center transition-colors duration-150',
            isDragActive
              ? 'border-accent bg-accent-soft/60'
              : 'border-line-strong bg-surface hover:border-accent/60 hover:bg-accent-soft/25'
          )}
        >
          <input {...getInputProps({ 'aria-label': 'Sélectionner des documents à importer' })} />
          <span
            className={cn(
              'flex h-14 w-14 items-center justify-center rounded-2xl transition-colors',
              isDragActive ? 'bg-accent text-accent-on' : 'bg-accent-soft text-accent group-hover:bg-accent group-hover:text-accent-on'
            )}
          >
            <UploadCloud className="h-7 w-7" aria-hidden="true" />
          </span>
          {isDragActive ? (
            <p className="mt-5 text-lg font-semibold text-accent-ink">
              Relâchez pour ajouter les fichiers...
            </p>
          ) : (
            <>
              <p className="mt-5 text-lg font-semibold text-ink">
                Glissez-déposez vos documents ici
              </p>
              <p className="mt-1 text-sm text-ink-muted">
                ou <span className="font-medium text-accent-ink underline decoration-accent/40 underline-offset-2">cliquez pour parcourir</span> vos fichiers
              </p>
            </>
          )}
          <div className="mt-5 flex flex-wrap items-center justify-center gap-1.5">
            {['PDF', 'DOCX', 'TXT', 'MD'].map(format => (
              <span key={format} className="rounded-md border border-line bg-surface px-2 py-0.5 font-mono text-2xs font-medium text-ink-muted">
                {format}
              </span>
            ))}
            <span className="ml-1 text-xs text-ink-muted">100 Mo max par fichier</span>
          </div>
        </div>

        {/* Upload queue */}
        {uploads.length > 0 && (
          <div className="card overflow-hidden">
            <div className="card-header flex-wrap">
              <div>
                <h2 className="card-title">Fichiers sélectionnés ({uploads.length})</h2>
                <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-muted tabular">
                  <span>{pendingCount} en attente</span>
                  <span>{uploadingCount} en cours</span>
                  <span className="text-success-ink">{successCount} réussi{successCount > 1 ? 's' : ''}</span>
                  <span className={cn(errorCount > 0 && 'text-danger')}>{errorCount} erreur{errorCount > 1 ? 's' : ''}</span>
                </p>
              </div>

              <div className="flex items-center gap-2">
                {(successCount > 0 || errorCount > 0) && (
                  <button
                    type="button"
                    onClick={clearCompleted}
                    className="btn-ghost btn-sm"
                  >
                    Nettoyer la liste
                  </button>
                )}
                {pendingCount > 0 && (
                  <button
                    type="button"
                    onClick={uploadAllFiles}
                    disabled={isUploading}
                    className="btn-primary btn-sm"
                  >
                    {isUploading ? (
                      <>
                        <Loader className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                        Import en cours...
                      </>
                    ) : (
                      <>
                        <Upload className="h-3.5 w-3.5" aria-hidden="true" />
                        Importer tout ({pendingCount})
                      </>
                    )}
                  </button>
                )}
              </div>
            </div>

            <ul className="divide-y divide-line-soft">
              {uploads.map((upload) => (
                <UploadItem
                  key={upload.id}
                  upload={upload}
                  onRemove={() => removeUpload(upload.id)}
                  onTogglePreserve={() => togglePreserve(upload.id)}
                  onRetry={() => uploadFile(upload)}
                  disabled={isUploading}
                />
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Instructions */}
      <aside className="space-y-4">
        <div className="card p-5">
          <h2 className="card-title">Formats supportés</h2>
          <ul className="mt-3 space-y-2.5 text-sm">
            {[
              ['PDF', 'Documents et manuels'],
              ['DOCX', 'Documents Word'],
              ['TXT', 'Fichiers texte simple'],
              ['MD', 'Documents Markdown'],
            ].map(([format, label]) => (
              <li key={format} className="flex items-center gap-3">
                <span className="w-11 shrink-0 rounded-md bg-sunken py-0.5 text-center font-mono text-2xs font-semibold text-ink-muted">
                  {format}
                </span>
                <span className="text-ink-muted">{label}</span>
              </li>
            ))}
          </ul>
          <p className="mt-4 border-t border-line-soft pt-3 text-xs leading-relaxed text-ink-muted">
            Les PDF doivent contenir du texte sélectionnable : un document scanné sans couche texte ne peut pas être indexé.
          </p>
        </div>

        <div className="card p-5">
          <h2 className="card-title">
            <Shield className="h-4 w-4 text-accent" aria-hidden="true" />
            Protection des documents
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-ink-muted">
            Activez la protection pour empêcher la suppression accidentelle
            des documents critiques.
          </p>
        </div>
      </aside>
    </div>
  );
};

const UPLOAD_STATUS = {
  pending: { label: 'En attente', className: 'badge-neutral' },
  uploading: { label: 'Envoi…', className: 'badge-accent' },
  success: { label: 'Importé', className: 'badge-success' },
  error: { label: 'Erreur', className: 'badge-danger' },
};

// Component for an individual file
const UploadItem = ({ upload, onRemove, onTogglePreserve, onRetry, disabled }) => {
  const isSupported = isSupportedFileType(upload.file.name);
  const status = UPLOAD_STATUS[upload.status];

  return (
    <li className="relative px-5 py-3.5">
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sunken text-ink-muted">
          {upload.status === 'uploading' ? (
            <Loader className="h-4 w-4 animate-spin text-accent" aria-hidden="true" />
          ) : upload.status === 'success' ? (
            <CheckCircle className="h-4 w-4 text-success" aria-hidden="true" />
          ) : upload.status === 'error' ? (
            <AlertCircle className="h-4 w-4 text-danger" aria-hidden="true" />
          ) : (
            <File className="h-4 w-4" aria-hidden="true" />
          )}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <p className="truncate text-sm font-medium text-ink" title={upload.file.name}>
              {upload.file.name}
            </p>
            {!isSupported && (
              <span className="badge-danger shrink-0">Format non supporté</span>
            )}
          </div>
          <p className="mt-0.5 flex min-w-0 gap-3 text-xs text-ink-muted">
            <span className="shrink-0 tabular">{formatFileSize(upload.file.size)}</span>
            {upload.status === 'error' && upload.error && (
              <span className="truncate text-danger" title={upload.error}>{upload.error}</span>
            )}
            {upload.preserve && (
              <span className="flex shrink-0 items-center gap-1 text-accent-ink">
                <Shield className="h-3 w-3" aria-hidden="true" /> Protégé
              </span>
            )}
          </p>
        </div>

        <span className={cn('hidden sm:inline-flex', status.className)}>{status.label}</span>

        <div className="flex items-center gap-1">
          {/* Preservation option */}
          {upload.status === 'pending' && (
            <button
              type="button"
              onClick={onTogglePreserve}
              disabled={disabled}
              aria-pressed={upload.preserve}
              className={cn(
                'btn-icon btn h-8 w-8',
                upload.preserve
                  ? 'bg-accent-soft text-accent-ink hover:bg-accent-soft'
                  : 'text-ink-faint hover:bg-sunken hover:text-accent'
              )}
              title={upload.preserve ? 'Retirer la protection' : 'Protéger le document'}
            >
              <Shield className="h-4 w-4" aria-hidden="true" />
            </button>
          )}

          {/* Retry button for errors */}
          {upload.status === 'error' && (
            <button
              type="button"
              onClick={onRetry}
              disabled={disabled}
              className="btn-secondary btn-sm"
            >
              Réessayer
            </button>
          )}

          {/* Delete button */}
          {upload.status !== 'uploading' && (
            <button
              type="button"
              onClick={onRemove}
              disabled={disabled}
              className="btn-ghost btn-icon h-8 w-8 hover:text-danger"
              title="Retirer de la liste"
              aria-label={`Retirer ${upload.file.name} de la liste`}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      {/* Indeterminate progress bar while the file is sent */}
      {upload.status === 'uploading' && (
        <div className="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden bg-accent-soft" aria-hidden="true">
          <div className="h-full w-1/3 animate-indeterminate rounded-full bg-accent" />
        </div>
      )}
    </li>
  );
};

export default UploadZone;