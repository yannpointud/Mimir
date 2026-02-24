import { useState, useEffect, useCallback } from 'react';
import { X, Mail, Send } from 'lucide-react';
import { isValidEmail, createMailtoLink } from '../../utils/helpers';

const EscalationDialog = ({ isOpen, onClose, onEscalate, chatHistory }) => {
  const [userEmail, setUserEmail] = useState('');
  const [message, setMessage] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [emailError, setEmailError] = useState('');

  // Reset the form when dialog opens
  const handleOpen = useCallback(() => {
    if (isOpen) {
      setUserEmail('');
      setMessage('');
      setEmailError('');
      setIsSubmitting(false);
    }
  }, [isOpen]);

  useEffect(() => {
    handleOpen();
  }, [handleOpen]);

  const handleEmailChange = (e) => {
    const email = e.target.value;
    setUserEmail(email);

    if (email && !isValidEmail(email)) {
      setEmailError('Veuillez entrer une adresse email valide');
    } else {
      setEmailError('');
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!userEmail || !isValidEmail(userEmail)) {
      setEmailError('Veuillez entrer une adresse email valide');
      return;
    }

    if (!message.trim()) {
      return;
    }

    setIsSubmitting(true);

    try {
      await onEscalate(userEmail, message.trim());
    } catch (error) {
      console.error('Erreur lors de l\'escalade:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Create a fallback mailto link
  const createFallbackMailto = () => {
    const subject = 'Demande d\'assistance - Mimir';
    const body = `Bonjour,

J'ai besoin d'aide concernant le système documentaire.

Message:
${message}

Historique de conversation (derniers messages):
${chatHistory.slice(-5).map(msg =>
  `${msg.type === 'user' ? 'Moi' : 'Mimir'}: ${msg.content}`
).join('\n\n')}

Cordialement,
${userEmail}`;

    return createMailtoLink('support@entreprise.com', subject, body);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        {/* Overlay */}
        <div className="fixed inset-0 bg-gray-600 bg-opacity-75 transition-opacity" onClick={onClose} />

        {/* Dialog */}
        <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center">
              <Mail className="h-6 w-6 text-primary-600 mr-2" />
              <h3 className="text-lg font-medium text-gray-900">
                Contacter un humain
              </h3>
            </div>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600"
            >
              <X className="h-6 w-6" />
            </button>
          </div>

          {/* Description */}
          <p className="text-sm text-gray-600 mb-6">
            Si vous n&apos;avez pas trouvé de réponse satisfaisante, vous pouvez contacter notre équipe de support.
            Votre conversation sera automatiquement incluse dans la demande.
          </p>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email */}
            <div>
              <label htmlFor="userEmail" className="block text-sm font-medium text-gray-700 mb-1">
                Votre adresse email
              </label>
              <input
                type="email"
                id="userEmail"
                value={userEmail}
                onChange={handleEmailChange}
                className={`input-field ${emailError ? 'border-red-300 focus:ring-red-500' : ''}`}
                placeholder="votre.email@entreprise.com"
                required
              />
              {emailError && (
                <p className="mt-1 text-sm text-red-600">{emailError}</p>
              )}
            </div>

            {/* Message */}
            <div>
              <label htmlFor="escalationMessage" className="block text-sm font-medium text-gray-700 mb-1">
                Votre message
              </label>
              <textarea
                id="escalationMessage"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={4}
                className="input-field"
                placeholder="Décrivez votre problème ou votre question..."
                required
                maxLength={1000}
              />
              <p className="mt-1 text-xs text-gray-500">
                {message.length}/1000 caractères
              </p>
            </div>

            {/* History info */}
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
              <p className="text-sm text-blue-800">
                💡 L&apos;historique de votre conversation avec Mimir sera automatiquement inclus dans votre demande.
              </p>
            </div>

            {/* Buttons */}
            <div className="flex space-x-3 pt-4">
              <button
                type="button"
                onClick={onClose}
                className="flex-1 btn-secondary"
                disabled={isSubmitting}
              >
                Annuler
              </button>
              <button
                type="submit"
                className="flex-1 btn-primary"
                disabled={isSubmitting || !userEmail || !message.trim() || !!emailError}
              >
                {isSubmitting ? (
                  <div className="flex items-center justify-center">
                    <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent mr-2" />
                    Envoi...
                  </div>
                ) : (
                  <div className="flex items-center justify-center">
                    <Send className="h-4 w-4 mr-2" />
                    Envoyer
                  </div>
                )}
              </button>
            </div>

            {/* Fallback link */}
            <div className="text-center pt-4 border-t border-gray-200">
              <p className="text-xs text-gray-500 mb-2">
                Problème avec le formulaire ?
              </p>
              <a
                href={createFallbackMailto()}
                className="text-xs text-primary-600 hover:text-primary-500 underline"
              >
                Ouvrir votre client email
              </a>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};

export default EscalationDialog;