import { useState, useEffect, useCallback } from 'react';
import { Mail, Send, Info } from 'lucide-react';
import { isValidEmail, createMailtoLink, cn } from '../../utils/helpers';
import Modal from '../Common/Modal';

const MESSAGE_MAX_LENGTH = 1000;

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

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      icon={Mail}
      title="Contacter un humain"
      description="L'équipe support vous répondra par e-mail."
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary"
            disabled={isSubmitting}
          >
            Annuler
          </button>
          <button
            type="submit"
            form="escalation-form"
            className="btn-primary"
            disabled={isSubmitting || !userEmail || !message.trim() || !!emailError}
          >
            {isSubmitting ? (
              <>
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
                Envoi...
              </>
            ) : (
              <>
                <Send className="h-4 w-4" aria-hidden="true" />
                Envoyer
              </>
            )}
          </button>
        </>
      }
    >
      <p className="text-sm leading-relaxed text-ink-muted">
        Si vous n&apos;avez pas trouvé de réponse satisfaisante, décrivez votre besoin :
        un membre de l&apos;équipe prendra le relais.
      </p>

      <form id="escalation-form" onSubmit={handleSubmit} className="mt-5 space-y-4" noValidate>
        {/* Email */}
        <div>
          <label htmlFor="userEmail" className="field-label">
            Votre adresse email
          </label>
          <input
            type="email"
            id="userEmail"
            value={userEmail}
            onChange={handleEmailChange}
            className={cn('input-field', emailError && 'border-danger focus:border-danger')}
            placeholder="prenom.nom@entreprise.com"
            autoComplete="email"
            aria-invalid={!!emailError}
            aria-describedby={emailError ? 'userEmail-error' : undefined}
            required
          />
          {emailError && (
            <p id="userEmail-error" className="mt-1.5 text-xs font-medium text-danger">{emailError}</p>
          )}
        </div>

        {/* Message */}
        <div>
          <div className="flex items-baseline justify-between">
            <label htmlFor="escalationMessage" className="field-label">
              Votre message
            </label>
            <span className="tabular text-xs text-ink-faint">
              {message.length}/{MESSAGE_MAX_LENGTH}
            </span>
          </div>
          <textarea
            id="escalationMessage"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            rows={4}
            className="input-field resize-y"
            placeholder="Décrivez votre problème ou votre question..."
            required
            maxLength={MESSAGE_MAX_LENGTH}
          />
        </div>

        {/* History info */}
        <div className="alert-info py-2.5">
          <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p>L&apos;historique de votre conversation avec Mimir sera automatiquement joint à votre demande.</p>
        </div>

        {/* Fallback link */}
        <p className="text-center text-xs text-ink-muted">
          Problème avec le formulaire ?{' '}
          <a
            href={createFallbackMailto()}
            className="font-medium text-accent-ink underline decoration-accent/40 underline-offset-2 hover:decoration-accent"
          >
            Ouvrir votre client email
          </a>
        </p>
      </form>
    </Modal>
  );
};

export default EscalationDialog;
