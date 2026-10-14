import { useEffect, useRef } from 'react';

import MessageList from './MessageList';
import LoadingIndicator from './LoadingIndicator';

const ChatWindow = ({ messages, isLoading, messagesEndRef, onEscalate }) => {
  const scrollAreaRef = useRef(null);

  // Check if a message is currently streaming
  const hasStreamingMessage = messages.some(msg => msg.isStreaming);

  // Smart auto-scroll: only if user is near the bottom
  useEffect(() => {
    const scrollArea = scrollAreaRef.current;
    if (!scrollArea) return;

    const isNearBottom =
      scrollArea.scrollTop + scrollArea.clientHeight >=
      scrollArea.scrollHeight - 100; // 100px margin

    if (isNearBottom) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, messagesEndRef]);

  return (
    <div
      ref={scrollAreaRef}
      className="relative min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable_both-edges]"
    >
      <div className="mx-auto w-full max-w-3xl px-4 pb-6 pt-8 sm:px-6">
        <h1 className="sr-only">Conversation avec Mimir</h1>
        <MessageList messages={messages} onEscalate={onEscalate} />

        {/* Loading indicator - only if not streaming */}
        {isLoading && !hasStreamingMessage && <LoadingIndicator />}

        {/* Reference for auto-scroll */}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
};

export default ChatWindow;
