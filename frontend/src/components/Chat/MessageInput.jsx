import { useState, useRef, useEffect } from 'react';
import { Send, Paperclip } from 'lucide-react';

const MessageInput = ({ onSendMessage, disabled = false }) => {
  const [message, setMessage] = useState('');
  const [isComposing, setIsComposing] = useState(false);
  const textareaRef = useRef(null);

  // Auto-resize du textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
    }
  }, [message]);

  // Focus automatique
  useEffect(() => {
    if (!disabled && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [disabled]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (message.trim() && !disabled && !isComposing) {
      onSendMessage(message.trim());
      setMessage('');
    }
  };

  const handleKeyDown = (e) => {
    // Envoyer avec Ctrl+Enter ou Cmd+Enter
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSubmit(e);
    }
    // Empêcher l'envoi avec Enter seul pendant la composition (IME)
    else if (e.key === 'Enter' && !e.shiftKey && !isComposing) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleCompositionStart = () => {
    setIsComposing(true);
  };

  const handleCompositionEnd = () => {
    setIsComposing(false);
  };

  const canSend = message.trim() && !disabled && !isComposing;

  return (
    <div className="bg-white border-t border-gray-200 px-4 py-4">
      <form onSubmit={handleSubmit} className="max-w-4xl mx-auto">
        <div className="relative">
          {/* Zone de saisie */}
          <div className="flex items-end space-x-3">
            {/* Bouton d'attachement (placeholder pour futures fonctionnalités) */}
            <button
              type="button"
              className="flex-shrink-0 p-2 text-gray-400 hover:text-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={disabled}
              title="Joindre un fichier (bientôt disponible)"
            >
              <Paperclip className="h-5 w-5" />
            </button>

            {/* Textarea */}
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={handleKeyDown}
                onCompositionStart={handleCompositionStart}
                onCompositionEnd={handleCompositionEnd}
                placeholder={disabled ? "Veuillez patienter..." : "Tapez votre question ici... (Entrée pour envoyer, Shift+Entrée pour une nouvelle ligne)"}
                className="w-full px-4 py-3 pr-12 border border-gray-300 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
                rows={1}
                disabled={disabled}
                maxLength={2000}
              />

              {/* Compteur de caractères */}
              <div className="absolute bottom-1 right-1 text-xs text-gray-400">
                {message.length}/2000
              </div>
            </div>

            {/* Bouton d'envoi */}
            <button
              type="submit"
              disabled={!canSend}
              className={`flex-shrink-0 p-3 rounded-lg transition-colors duration-200 ${
                canSend
                  ? 'bg-primary-600 hover:bg-primary-700 text-white'
                  : 'bg-gray-300 text-gray-500 cursor-not-allowed'
              }`}
              title="Envoyer le message"
            >
              <Send className="h-5 w-5" />
            </button>
          </div>

          {/* Indicateurs d'état */}
          <div className="flex items-center justify-between mt-2 text-xs text-gray-500">
            <div className="flex items-center space-x-4">
              <span>
                💡 Astuce: Utilisez Shift+Entrée pour une nouvelle ligne
              </span>
            </div>
            {disabled && (
              <span className="text-orange-600">
                Traitement en cours...
              </span>
            )}
          </div>
        </div>
      </form>
    </div>
  );
};

export default MessageInput;