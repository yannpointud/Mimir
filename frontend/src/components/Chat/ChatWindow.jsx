import { useEffect, useRef } from 'react';

import MessageList from './MessageList';
import LoadingIndicator from './LoadingIndicator';

const ChatWindow = ({ messages, isLoading, messagesEndRef }) => {
  const scrollAreaRef = useRef(null);

  // Vérifier si un message est en cours de streaming
  const hasStreamingMessage = messages.some(msg => msg.isStreaming);

  // Auto-scroll intelligent : seulement si l'utilisateur est proche du bas
  useEffect(() => {
    const scrollArea = scrollAreaRef.current;
    if (!scrollArea) return;

    const isNearBottom =
      scrollArea.scrollTop + scrollArea.clientHeight >=
      scrollArea.scrollHeight - 100; // 100px de marge

    if (isNearBottom) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, messagesEndRef]);

  return (
    <div className="flex-1 overflow-hidden bg-gray-50">
      <div
        ref={scrollAreaRef}
        className="h-full overflow-y-auto px-4 py-6 space-y-6"
      >
        {/* Messages vides */}
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center max-w-md">
              <div className="mx-auto h-12 w-12 rounded-full bg-primary-100 flex items-center justify-center mb-4">
                <svg className="h-6 w-6 text-primary-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
              </div>
              <h3 className="text-lg font-medium text-gray-900 mb-2">
                Commencez une conversation
              </h3>
              <p className="text-gray-600 text-sm">
                Posez une question sur la documentation de votre entreprise pour commencer.
              </p>
            </div>
          </div>
        )}

        {/* Liste des messages */}
        <MessageList messages={messages} />

        {/* Indicateur de chargement - seulement si pas de streaming */}
        {isLoading && !hasStreamingMessage && <LoadingIndicator />}

        {/* Référence pour l'auto-scroll */}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
};

export default ChatWindow;