import { useState, useRef, useEffect } from 'react';
import { AlertCircle, Mail, Plus, X } from 'lucide-react';

import ChatWindow from './ChatWindow';
import ChatHome from './ChatHome';
import ChatAside from './ChatAside';
import MessageInput from './MessageInput';
import EscalationDialog from './EscalationDialog';
import { TopbarActions } from '../Common/Layout';

import { chatAPI } from '../../services/api';
import { getErrorMessage, generateSessionId } from '../../utils/helpers';
import { chatHistoryStorage, chatSessionStorage } from '../../utils/storage';
import { createLogger } from '../../utils/logger';

const logger = createLogger('ChatPage');

// Welcome messages seed every session; they render as the home screen, not as bubbles.
const isWelcomeMessage = (message) => String(message.id).startsWith('welcome');

// Turns raw transport errors from the stream client into an actionable sentence.
// A 429 covers both the per-minute rate limit and the daily AI budget cap.
const describeChatError = (message) => {
  if (message.startsWith('HTTP 429')) {
    return 'Mimir ne peut pas répondre pour le moment (limite de requêtes ou plafond de dépense quotidien atteint). Réessayez plus tard.';
  }
  if (message.startsWith('HTTP 5')) {
    return `Le serveur a rencontré un problème (${message}). Réessayez dans quelques instants.`;
  }
  if (message === 'Failed to fetch') {
    return 'Impossible de joindre le serveur. Vérifiez votre connexion.';
  }
  if (message === 'Stream closed before completion') {
    return 'La réponse a été interrompue avant la fin. Réessayez.';
  }
  return message;
};

const ChatPage = () => {
  const [sessionId] = useState(() => {
    // Reuse existing sessionId or create a new one
    const existingSessionId = chatSessionStorage.getCurrentSessionId();
    if (existingSessionId) {
      return existingSessionId;
    }
    const newSessionId = generateSessionId();
    chatSessionStorage.setCurrentSessionId(newSessionId);
    return newSessionId;
  });

  const [messages, setMessages] = useState(() => {
    // Safely load history from sessionStorage
    return chatHistoryStorage.getHistory(sessionId);
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showEscalation, setShowEscalation] = useState(false);
  const messagesEndRef = useRef(null);

  // Save history on every message change
  useEffect(() => {
    if (messages.length > 0) {
      chatHistoryStorage.saveHistory(sessionId, messages);
    }
  }, [messages, sessionId]);

  // Automatic cleanup of old sessions on mount
  useEffect(() => {
    chatHistoryStorage.cleanupOldSessions(24); // Clean sessions older than 24h
  }, []);

  // Initial welcome message if no history
  useEffect(() => {
    if (messages.length === 0) {
      const welcomeMessage = {
        id: 'welcome',
        type: 'assistant',
        content: 'Bonjour ! Je suis Mimir, votre assistant documentaire intelligent. Je peux répondre à vos questions en me basant sur la documentation de votre entreprise. Comment puis-je vous aider aujourd\'hui ?',
        timestamp: new Date().toISOString(),
        sources: []
      };
      setMessages([welcomeMessage]);
    }
  }, [messages.length]);

  // Auto-scroll to bottom
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages.length]);

  // Send a message with streaming
  const handleSendMessage = async (content) => {
    if (!content.trim() || isLoading) {
      return;
    }

    const userMessage = {
      id: Date.now().toString(),
      type: 'user',
      content: content.trim(),
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);
    setError(null);

    // Create empty assistant message for streaming
    const assistantMessageId = (Date.now() + 1).toString();
    const assistantMessage = {
      id: assistantMessageId,
      type: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      sources: [],
      citations: {},
      confidence: 0,
      isStreaming: true
    };

    setMessages(prev => [...prev, assistantMessage]);

    // Set once the failure is shown inside the thread, so the global banner
    // does not repeat it (the stream client calls onError, then rejects).
    let reportedInThread = false;

    try {
      await chatAPI.sendMessageStream(content.trim(), sessionId, {
        onStart: () => {},

        onChunk: (chunk) => {
          setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
              ? { ...msg, content: msg.content + chunk }
              : msg
          ));
        },

        // The SSE `citation` event lands before `done`. Store the [N] -> source
        // map via the same spread-preserve pattern as onChunk/onDone so sibling
        // fields (content/sources/confidence) are never dropped.
        onCitation: (citations) => {
          setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
              ? { ...msg, citations: citations || {} }
              : msg
          ));
        },

        onDone: (event) => {
          setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  sources: event.sources || [],
                  confidence: event.confidence_score || 0,
                  isStreaming: false
                }
              : msg
          ));

          setIsLoading(false);
        },

        onError: (errorMessage) => {
          logger.error('Chat stream error', null, { errorMessage });
          const readableError = describeChatError(errorMessage);
          reportedInThread = true;

          setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  content: `Désolé, une erreur s'est produite : ${readableError}`,
                  isStreaming: false,
                  type: 'error'
                }
              : msg
          ));

          setIsLoading(false);
        }
      });

    } catch (error) {
      logger.error('Chat streaming failed', error);
      if (!reportedInThread) {
        setError(describeChatError(getErrorMessage(error)));
      }
      setIsLoading(false);
    }
  };

  // Escalate to a human
  const handleEscalation = async (userEmail, escalationMessage) => {
    try {
      await chatAPI.escalateToHuman(sessionId, userEmail, escalationMessage, messages);

      const confirmationMessage = {
        id: Date.now().toString(),
        type: 'system',
        content: 'Votre demande a été transmise à un opérateur humain. Vous recevrez une réponse par email dans les plus brefs délais.',
        timestamp: new Date().toISOString()
      };

      setMessages(prev => [...prev, confirmationMessage]);
      setShowEscalation(false);

    } catch (error) {
      logger.error('Escalation failed', error);
      setError('Erreur lors de la transmission vers un opérateur humain');
    }
  };

  // New conversation
  const handleNewConversation = () => {
    // Safely clear sessionStorage history
    chatHistoryStorage.clearHistory(sessionId);

    const welcomeMessage = {
      id: 'welcome-' + Date.now(),
      type: 'assistant',
      content: 'Nouvelle conversation démarrée. Comment puis-je vous aider ?',
      timestamp: new Date().toISOString(),
      sources: []
    };
    setMessages([welcomeMessage]);
    setError(null);
  };

  const openEscalation = () => setShowEscalation(true);
  const welcomeMessage = messages.find(isWelcomeMessage);
  const conversation = messages.filter(message => !isWelcomeMessage(message));
  const isHome = conversation.length === 0;

  return (
    <div className="flex min-h-0 flex-1">
      <TopbarActions>
        <button
          type="button"
          onClick={openEscalation}
          className="btn-nav"
          title="Contacter un humain"
        >
          <Mail className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only sm:not-sr-only">Contacter un humain</span>
        </button>
        <button
          type="button"
          onClick={handleNewConversation}
          className="btn-nav-primary"
          title="Nouvelle conversation"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only sm:not-sr-only">Nouvelle conversation</span>
        </button>
      </TopbarActions>

      <section aria-label="Conversation" className="flex min-w-0 flex-1 flex-col">
        {/* Global error message */}
        {error && (
          <div className="px-4 pt-4 sm:px-6">
            <div role="alert" className="alert-danger mx-auto max-w-3xl animate-slide-up">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <p className="flex-1">{error}</p>
              <button
                type="button"
                onClick={() => setError(null)}
                className="-my-1 -mr-2 flex h-7 w-7 items-center justify-center rounded-md hover:bg-danger/10"
                aria-label="Fermer le message d'erreur"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          </div>
        )}

        {isHome ? (
          <ChatHome
            welcomeText={welcomeMessage?.content}
            onSendMessage={handleSendMessage}
            onContactHuman={openEscalation}
            disabled={isLoading}
          />
        ) : (
          <>
            <ChatWindow
              messages={conversation}
              isLoading={isLoading}
              messagesEndRef={messagesEndRef}
              onEscalate={openEscalation}
            />

            <MessageInput
              onSendMessage={handleSendMessage}
              disabled={isLoading}
            />
          </>
        )}
      </section>

      {!isHome && (
        <ChatAside
          messages={conversation}
          onContactHuman={openEscalation}
        />
      )}

      {/* Escalation dialog */}
      <EscalationDialog
        isOpen={showEscalation}
        onClose={() => setShowEscalation(false)}
        onEscalate={handleEscalation}
        chatHistory={messages}
      />
    </div>
  );
};

export default ChatPage;
