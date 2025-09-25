import { useState, useRef, useEffect } from 'react';
import { AlertCircle, Mail } from 'lucide-react';

import ChatWindow from './ChatWindow';
import MessageInput from './MessageInput';
import EscalationDialog from './EscalationDialog';

import { chatAPI } from '../../services/api';
import { getErrorMessage, generateSessionId, safeDisplayValue } from '../../utils/helpers';
import { chatHistoryStorage, chatSessionStorage } from '../../utils/storage';

const ChatPage = () => {
  const [sessionId] = useState(() => {
    // Réutiliser le sessionId existant ou en créer un nouveau
    const existingSessionId = chatSessionStorage.getCurrentSessionId();
    if (existingSessionId) {
      return existingSessionId;
    }
    const newSessionId = generateSessionId();
    chatSessionStorage.setCurrentSessionId(newSessionId);
    return newSessionId;
  });

  const [messages, setMessages] = useState(() => {
    // Charger l'historique depuis sessionStorage de manière sécurisée
    return chatHistoryStorage.getHistory(sessionId);
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showEscalation, setShowEscalation] = useState(false);
  const [streamingMessageId, setStreamingMessageId] = useState(null);
  const messagesEndRef = useRef(null);

  // Sauvegarder l'historique à chaque changement de messages
  useEffect(() => {
    if (messages.length > 0) {
      chatHistoryStorage.saveHistory(sessionId, messages);
    }
  }, [messages, sessionId]);

  // Nettoyage automatique des anciennes sessions au montage
  useEffect(() => {
    chatHistoryStorage.cleanupOldSessions(24); // Nettoyer les sessions de plus de 24h
  }, []);

  // Message de bienvenue initial si aucun historique
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

  // Auto-scroll vers le bas
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages.length]);

  // Envoi d'un message avec streaming
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

    // Créer message assistant vide pour le streaming
    const assistantMessageId = (Date.now() + 1).toString();
    const assistantMessage = {
      id: assistantMessageId,
      type: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      sources: [],
      confidence: 0,
      isStreaming: true
    };

    setMessages(prev => [...prev, assistantMessage]);
    setStreamingMessageId(assistantMessageId);

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

          setStreamingMessageId(null);
          setIsLoading(false);
        },

        onError: (errorMessage) => {
          console.error('Stream error:', errorMessage);

          setError(errorMessage);

          setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  content: `Désolé, une erreur s'est produite: ${errorMessage}`,
                  isStreaming: false,
                  type: 'error'
                }
              : msg
          ));

          setStreamingMessageId(null);
          setIsLoading(false);
        }
      });

    } catch (error) {
      console.error('=== ERREUR STREAMING ===', error);
      setError(getErrorMessage(error));
      setStreamingMessageId(null);
      setIsLoading(false);
    }
  };

  // Escalade vers un humain
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
      console.error('Erreur lors de l\'escalade:', error);
      setError('Erreur lors de la transmission vers un opérateur humain');
    }
  };

  // Nouvelle conversation
  const handleNewConversation = () => {
    // Effacer l'historique de sessionStorage de manière sécurisée
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

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {/* En-tête */}
      <div className="bg-white border-b border-gray-200 px-4 py-4 sm:px-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">
              Assistant Documentaire Mimir
            </h1>
            <p className="text-sm text-gray-600 mt-1">
              Posez vos questions sur la documentation de l&apos;entreprise
            </p>
          </div>
          <div className="flex items-center space-x-2">
            <button
              onClick={() => setShowEscalation(true)}
              className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
              title="Contacter un humain"
            >
              <Mail className="h-4 w-4 mr-2" />
              <span className="hidden sm:inline">Contacter un humain</span>
            </button>
            <button
              onClick={handleNewConversation}
              className="btn-secondary text-sm"
            >
              Nouvelle conversation
            </button>
          </div>
        </div>
      </div>

      {/* Message d'erreur global */}
      {error && (
        <div className="bg-red-50 border-l-4 border-red-400 p-4 mx-4 mt-4">
          <div className="flex">
            <AlertCircle className="h-5 w-5 text-red-400" />
            <div className="ml-3">
              <p className="text-sm text-red-700">{error}</p>
            </div>
            <button
              onClick={() => setError(null)}
              className="ml-auto text-red-400 hover:text-red-600"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* Zone de chat */}
      <div className="flex-1 flex flex-col min-h-0">
        <ChatWindow
          messages={messages}
          isLoading={isLoading}
          messagesEndRef={messagesEndRef}
        />

        <MessageInput
          onSendMessage={handleSendMessage}
          disabled={isLoading}
        />
      </div>

      {/* Dialog d'escalade */}
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