import { useState, useRef, useEffect } from 'react';
import { Send, Paperclip } from 'lucide-react';
import { cn } from '../../utils/helpers';

const MAX_LENGTH = 2000;

/**
 * Question composer.
 *
 * @param {Object} props
 * @param {Function} props.onSendMessage - Called with the trimmed question.
 * @param {boolean} [props.disabled] - Locks the field while an answer streams.
 * @param {'docked'|'hero'} [props.variant] - Docked under the thread, or large on the home screen.
 */
const MessageInput = ({ onSendMessage, disabled = false, variant = 'docked' }) => {
  const [message, setMessage] = useState('');
  const [isComposing, setIsComposing] = useState(false);
  const textareaRef = useRef(null);
  const isHero = variant === 'hero';
  const maxHeight = isHero ? 220 : 160;

  // Auto-resize the textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
    }
  }, [message, maxHeight]);

  // Auto-focus
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
    // Send with Ctrl+Enter or Cmd+Enter
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSubmit(e);
    }
    // Prevent sending with Enter alone during composition (IME)
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
    <div className={cn(!isHero && 'shrink-0 bg-gradient-to-t from-canvas from-60% to-canvas/0 pb-4 pt-2 sm:pb-5')}>
      <form onSubmit={handleSubmit} className={cn(!isHero && 'mx-auto max-w-3xl px-4 sm:px-6')}>
        <div
          className={cn(
            'relative rounded-2xl border border-line bg-surface transition-[border-color,box-shadow] duration-150 focus-within:border-accent/60 focus-within:shadow-focus',
            isHero ? 'shadow-raised' : 'shadow-card',
            disabled && 'bg-sunken'
          )}
        >
          <label htmlFor={`question-${variant}`} className="sr-only">Votre question</label>
          <textarea
            id={`question-${variant}`}
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            onCompositionStart={handleCompositionStart}
            onCompositionEnd={handleCompositionEnd}
            placeholder={disabled ? 'Veuillez patienter...' : (isHero ? 'Tapez votre question ici… par exemple sur une procédure, un accord ou une règle interne' : 'Tapez votre question ici…')}
            className={cn(
              'block w-full resize-none bg-transparent px-4 text-ink focus:outline-none disabled:cursor-not-allowed',
              isHero ? 'min-h-[88px] pt-4 text-base' : 'pt-3.5 text-[15px]'
            )}
            rows={isHero ? 3 : 1}
            disabled={disabled}
            maxLength={MAX_LENGTH}
          />

          <div className="flex items-center gap-2 px-2.5 pb-2.5 pt-1">
            {/* Attachment button (placeholder for future features) */}
            <button
              type="button"
              className="btn-ghost btn-icon h-8 w-8 text-ink-faint"
              disabled={disabled}
              title="Joindre un fichier (bientôt disponible)"
            >
              <Paperclip className="h-4 w-4" aria-hidden="true" />
            </button>

            <p className="hidden min-w-0 flex-1 truncate text-xs text-ink-muted sm:block">
              {disabled ? (
                'Mimir rédige sa réponse…'
              ) : (
                <>
                  <kbd className="kbd">Entrée</kbd> pour envoyer · <kbd className="kbd">Maj</kbd> + <kbd className="kbd">Entrée</kbd> pour un retour à la ligne
                </>
              )}
            </p>

            <span
              className={cn(
                'ml-auto tabular text-xs sm:ml-0',
                message.length > MAX_LENGTH * 0.9 ? 'text-warning' : 'text-ink-faint'
              )}
            >
              {message.length > 0 && `${message.length}/${MAX_LENGTH}`}
            </span>

            {/* Send button */}
            <button
              type="submit"
              disabled={!canSend}
              className={cn(
                'flex h-9 shrink-0 items-center justify-center gap-2 rounded-xl px-3 text-sm font-medium transition-colors duration-150',
                canSend
                  ? 'bg-accent text-accent-on shadow-xs hover:bg-accent-hover'
                  : 'cursor-not-allowed bg-line-soft text-ink-faint'
              )}
              title="Envoyer le message"
              aria-label="Envoyer le message"
            >
              <span className={cn(!isHero && 'sr-only')}>Envoyer</span>
              <Send className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};

export default MessageInput;
