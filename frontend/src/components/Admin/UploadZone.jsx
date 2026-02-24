import { useState, useCallback } from 'react';
import { useOutletContext } from 'react-router-dom';
import { useDropzone } from 'react-dropzone';
import { documentsAPI } from '../../services/api';
import { getErrorMessage, formatFileSize, isSupportedFileType } from '../../utils/helpers';
import {
  Upload,
  File,
  X,
  CheckCircle,
  AlertCircle,
  Shield,
  Loader
} from 'lucide-react';

const UploadZone = () => {
  const { onUploadSuccess } = useOutletContext();
  const [uploads, setUploads] = useState([]);
  const [isUploading, setIsUploading] = useState(false);

  // react-dropzone configuration
  const onDrop = useCallback((acceptedFiles, rejectedFiles) => {
    // Handle rejected files
    rejectedFiles.forEach(({ file, errors }) => {
      console.error('Fichier rejeté:', file.name, errors);
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
      console.error('Erreur lors de l\'upload:', error);
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
  const successCount = uploads.filter(u => u.status === 'success').length;
  const errorCount = uploads.filter(u => u.status === 'error').length;

  return (
    <div className="p-4 max-w-7xl h-full">
      {/* Drop zone */}
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors duration-200 ${
          isDragActive
            ? 'border-primary-400 bg-primary-50'
            : 'border-gray-300 hover:border-gray-400'
        }`}
      >
        <input {...getInputProps()} />
        <Upload className="mx-auto h-12 w-12 text-gray-400 mb-4" />
        {isDragActive ? (
          <p className="text-lg text-primary-600">
            Relâchez pour ajouter les fichiers...
          </p>
        ) : (
          <div>
            <p className="text-lg text-gray-600 mb-2">
              Glissez-déposez vos documents ici, ou cliquez pour sélectionner
            </p>
            <p className="text-sm text-gray-500">
              Formats supportés : PDF, DOCX, TXT, MD (max 100 MB par fichier)
            </p>
          </div>
        )}
      </div>

      {/* Statistics */}
      {uploads.length > 0 && (
        <div className="mt-6 grid grid-cols-1 sm:grid-cols-4 gap-4">
          <div className="bg-blue-50 rounded-lg p-4">
            <div className="flex items-center">
              <File className="h-5 w-5 text-blue-600 mr-2" />
              <span className="text-sm font-medium text-blue-900">En attente</span>
            </div>
            <p className="text-2xl font-bold text-blue-900">{pendingCount}</p>
          </div>

          <div className="bg-yellow-50 rounded-lg p-4">
            <div className="flex items-center">
              <Loader className="h-5 w-5 text-yellow-600 mr-2" />
              <span className="text-sm font-medium text-yellow-900">En cours</span>
            </div>
            <p className="text-2xl font-bold text-yellow-900">
              {uploads.filter(u => u.status === 'uploading').length}
            </p>
          </div>

          <div className="bg-green-50 rounded-lg p-4">
            <div className="flex items-center">
              <CheckCircle className="h-5 w-5 text-green-600 mr-2" />
              <span className="text-sm font-medium text-green-900">Réussis</span>
            </div>
            <p className="text-2xl font-bold text-green-900">{successCount}</p>
          </div>

          <div className="bg-red-50 rounded-lg p-4">
            <div className="flex items-center">
              <AlertCircle className="h-5 w-5 text-red-600 mr-2" />
              <span className="text-sm font-medium text-red-900">Erreurs</span>
            </div>
            <p className="text-2xl font-bold text-red-900">{errorCount}</p>
          </div>
        </div>
      )}

      {/* Global actions */}
      {uploads.length > 0 && (
        <div className="mt-6 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            {pendingCount > 0 && (
              <button
                onClick={uploadAllFiles}
                disabled={isUploading}
                className="btn-primary"
              >
                {isUploading ? (
                  <div className="flex items-center">
                    <Loader className="h-4 w-4 mr-2 animate-spin" />
                    Upload en cours...
                  </div>
                ) : (
                  <>
                    <Upload className="h-4 w-4 mr-2" />
                    Uploader tout ({pendingCount})
                  </>
                )}
              </button>
            )}
          </div>

          <div className="flex items-center space-x-3">
            {(successCount > 0 || errorCount > 0) && (
              <button
                onClick={clearCompleted}
                className="btn-secondary"
              >
                Nettoyer la liste
              </button>
            )}
          </div>
        </div>
      )}

      {/* File list */}
      {uploads.length > 0 && (
        <div className="mt-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">
            Fichiers sélectionnés ({uploads.length})
          </h3>

          <div className="space-y-3">
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
          </div>
        </div>
      )}

      {/* Instructions */}
      <div className="mt-8 bg-gray-50 rounded-lg p-6">
        <h4 className="text-lg font-medium text-gray-900 mb-3">
          Instructions d&apos;upload
        </h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <h5 className="font-medium text-gray-700 mb-2">Formats supportés :</h5>
            <ul className="text-sm text-gray-600 space-y-1">
              <li>• PDF - Documents et manuels</li>
              <li>• DOCX - Documents Word</li>
              <li>• TXT - Fichiers texte simple</li>
              <li>• MD - Documents Markdown</li>
            </ul>
          </div>
          <div>
            <h5 className="font-medium text-gray-700 mb-2">Protection des documents :</h5>
            <div className="flex items-start text-sm text-gray-600">
              <Shield className="h-4 w-4 text-blue-600 mr-2 mt-0.5 flex-shrink-0" />
              <span>
                Activez la protection pour empêcher la suppression accidentelle
                des documents critiques.
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

// Component for an individual file
const UploadItem = ({ upload, onRemove, onTogglePreserve, onRetry, disabled }) => {
  const getStatusIcon = () => {
    switch (upload.status) {
      case 'pending':
        return <File className="h-5 w-5 text-gray-400" />;
      case 'uploading':
        return <Loader className="h-5 w-5 text-blue-600 animate-spin" />;
      case 'success':
        return <CheckCircle className="h-5 w-5 text-green-600" />;
      case 'error':
        return <AlertCircle className="h-5 w-5 text-red-600" />;
      default:
        return <File className="h-5 w-5 text-gray-400" />;
    }
  };

  const getStatusColor = () => {
    switch (upload.status) {
      case 'pending':
        return 'border-gray-200 bg-white';
      case 'uploading':
        return 'border-blue-200 bg-blue-50';
      case 'success':
        return 'border-green-200 bg-green-50';
      case 'error':
        return 'border-red-200 bg-red-50';
      default:
        return 'border-gray-200 bg-white';
    }
  };

  const isSupported = isSupportedFileType(upload.file.name);

  return (
    <div className={`border rounded-lg p-4 ${getStatusColor()}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center flex-1 min-w-0">
          {getStatusIcon()}
          <div className="ml-3 flex-1 min-w-0">
            <div className="flex items-center">
              <p className="text-sm font-medium text-gray-900 truncate">
                {upload.file.name}
              </p>
              {!isSupported && (
                <span className="ml-2 inline-flex px-2 py-1 text-xs font-semibold bg-red-100 text-red-800 rounded-full">
                  Format non supporté
                </span>
              )}
            </div>
            <div className="flex items-center mt-1 space-x-4">
              <p className="text-sm text-gray-500">
                {formatFileSize(upload.file.size)}
              </p>
              {upload.status === 'error' && upload.error && (
                <p className="text-sm text-red-600">{upload.error}</p>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-3 ml-4">
          {/* Preservation option */}
          {upload.status === 'pending' && (
            <button
              onClick={onTogglePreserve}
              disabled={disabled}
              className={`p-2 rounded transition-colors duration-200 ${
                upload.preserve
                  ? 'text-blue-600 bg-blue-100 hover:bg-blue-200'
                  : 'text-gray-400 hover:text-blue-600 hover:bg-blue-50'
              }`}
              title={upload.preserve ? 'Retirer la protection' : 'Protéger le document'}
            >
              <Shield className="h-4 w-4" />
            </button>
          )}

          {/* Retry button for errors */}
          {upload.status === 'error' && (
            <button
              onClick={onRetry}
              disabled={disabled}
              className="btn-secondary text-sm"
            >
              Réessayer
            </button>
          )}

          {/* Delete button */}
          {upload.status !== 'uploading' && (
            <button
              onClick={onRemove}
              disabled={disabled}
              className="text-gray-400 hover:text-red-600 transition-colors duration-200"
              title="Retirer de la liste"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {upload.status === 'uploading' && (
        <div className="mt-3">
          <div className="bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-2 rounded-full transition-all duration-300"
              style={{ width: `${upload.progress}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default UploadZone;