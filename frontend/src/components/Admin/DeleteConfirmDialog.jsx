import { Shield, Trash2 } from 'lucide-react';
import LoadingSpinner from '../Common/LoadingSpinner';
import Modal from '../Common/Modal';

// Delete confirmation dialog
const DeleteConfirmDialog = ({ isOpen, document, onConfirm, onCancel, loading }) => {
  if (!document) return null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onCancel}
      size="sm"
      icon={Trash2}
      tone="danger"
      title="Supprimer le document"
      description="Cette action est irréversible."
      footer={
        <>
          <button type="button" onClick={onCancel} className="btn-secondary" disabled={loading}>
            Annuler
          </button>
          <button
            type="button"
            onClick={() => onConfirm(document, document.preserve)}
            className="btn-danger"
            disabled={loading || document.preserve}
          >
            {loading ? (
              <>
                <LoadingSpinner size="sm" className="text-current" />
                Suppression...
              </>
            ) : (
              'Supprimer'
            )}
          </button>
        </>
      }
    >
      <p className="text-sm leading-relaxed text-ink-muted">
        Êtes-vous sûr de vouloir supprimer le document <strong className="font-semibold text-ink">{document.filename}</strong> ?
        Il sera retiré de l&apos;index et ne sera plus utilisé pour répondre aux questions.
      </p>

      {document.preserve && (
        <div className="alert-warning mt-4">
          <Shield className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p>Ce document est protégé. Vous devez d&apos;abord retirer la protection.</p>
        </div>
      )}
    </Modal>
  );
};

export default DeleteConfirmDialog;
