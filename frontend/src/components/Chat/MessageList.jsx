import MessageBubble from './MessageBubble';

const MessageList = ({ messages }) => {
  return (
    <div className="space-y-6">
      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
        />
      ))}
    </div>
  );
};

export default MessageList;