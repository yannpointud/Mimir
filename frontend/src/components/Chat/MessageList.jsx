import MessageBubble from './MessageBubble';

const MessageList = ({ messages, onEscalate }) => {
  // Only the latest completed answer offers the hand-off to a human.
  const lastAnswer = [...messages].reverse().find(
    (message) => message.type === 'assistant' && !message.isStreaming
  );

  return (
    <div className="space-y-6">
      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          onEscalate={message === lastAnswer ? onEscalate : undefined}
        />
      ))}
    </div>
  );
};

export default MessageList;
