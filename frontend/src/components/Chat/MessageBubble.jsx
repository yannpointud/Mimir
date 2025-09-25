import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import SourcesList from './SourcesList';
import { formatRelativeDate, copyToClipboard } from '../../utils/helpers';
import { Copy, Check, User, Bot, AlertTriangle, Info } from 'lucide-react';

const MessageBubble = ({ message }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const success = await copyToClipboard(message.content);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const getMessageIcon = () => {
    switch (message.type) {
      case 'user':
        return <User className="h-5 w-5" />;
      case 'assistant':
        return <Bot className="h-5 w-5" />;
      case 'error':
        return <AlertTriangle className="h-5 w-5" />;
      case 'system':
        return <Info className="h-5 w-5" />;
      default:
        return <Bot className="h-5 w-5" />;
    }
  };

  const getMessageStyle = () => {
    switch (message.type) {
      case 'user':
        return 'ml-auto max-w-3xl';
      case 'assistant':
        return 'mr-auto max-w-4xl';
      case 'error':
        return 'mr-auto max-w-4xl';
      case 'system':
        return 'mx-auto max-w-2xl';
      default:
        return 'mr-auto max-w-4xl';
    }
  };

  const getBubbleStyle = () => {
    switch (message.type) {
      case 'user':
        return 'message-user';
      case 'assistant':
        return 'message-assistant';
      case 'error':
        return 'bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-800';
      case 'system':
        return 'bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 text-blue-800';
      default:
        return 'message-assistant';
    }
  };

  const getIconContainerStyle = () => {
    switch (message.type) {
      case 'user':
        return 'bg-primary-600 text-white';
      case 'assistant':
        return 'bg-gray-600 text-white';
      case 'error':
        return 'bg-red-600 text-white';
      case 'system':
        return 'bg-blue-600 text-white';
      default:
        return 'bg-gray-600 text-white';
    }
  };

  return (
    <div className={`flex ${message.type === 'user' ? 'justify-end' : 'justify-start'} ${getMessageStyle()}`}>
      <div className="flex space-x-3 max-w-full">
        {/* Avatar (sauf pour les messages utilisateur) */}
        {message.type !== 'user' && (
          <div className={`flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center ${getIconContainerStyle()}`}>
            {getMessageIcon()}
          </div>
        )}

        <div className="flex-1 min-w-0">
          {/* Bulle de message */}
          <div className={getBubbleStyle()}>
            <div className="flex items-start justify-between">
              {/* Contenu markdown */}
              <div className="prose prose-sm max-w-none flex-1">
                <ReactMarkdown
                  components={{
                    code({ inline, className, children, ...props }) {
                      const match = /language-(\w+)/.exec(className || '');
                      return !inline && match ? (
                        <SyntaxHighlighter
                          style={oneLight}
                          language={match[1]}
                          PreTag="div"
                          {...props}
                        >
                          {String(children).replace(/\n$/, '')}
                        </SyntaxHighlighter>
                      ) : (
                        <code className={className} {...props}>
                          {children}
                        </code>
                      );
                    },
                  }}
                >
                  {message.content}
                </ReactMarkdown>
                {message.isStreaming && (
                  <span className="inline-block ml-1 w-2 h-4 bg-gray-600 animate-pulse" style={{ animation: 'blink 1s infinite' }}></span>
                )}
              </div>

              {/* Bouton de copie à droite du texte */}
              {message.type !== 'user' && (
                <button
                  onClick={handleCopy}
                  className="ml-3 mt-1 text-gray-400 hover:text-gray-600 transition-colors duration-200 flex-shrink-0"
                  title="Copier le message"
                >
                  {copied ? (
                    <Check className="h-4 w-4 text-green-500" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </button>
              )}
            </div>

            {/* Score de confiance pour l'assistant - seulement si pas en streaming et confiance > 0 */}
            {message.type === 'assistant' && !message.isStreaming && message.confidence > 0 && (
              <div className="mt-2 text-xs text-gray-500">
                Confiance: {Math.round(message.confidence * 100)}%
              </div>
            )}
          </div>

          {/* Sources (pour les messages de l'assistant) */}
          {message.type === 'assistant' && message.sources && message.sources.length > 0 && (
            <div className="mt-2">
              <SourcesList sources={message.sources} />
            </div>
          )}

          {/* Métadonnées */}
          <div className={`mt-2 ${message.type === 'user' ? 'text-right' : ''}`}>
            <span className="text-xs text-gray-500">
              {formatRelativeDate(message.timestamp)}
            </span>
          </div>
        </div>

        {/* Avatar pour les messages utilisateur */}
        {message.type === 'user' && (
          <div className={`flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center ${getIconContainerStyle()}`}>
            {getMessageIcon()}
          </div>
        )}
      </div>
    </div>
  );
};

export default MessageBubble;