import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import SourcesList from './SourcesList';
import CitationPill from './CitationPill';
import { ThinkingDots } from './LoadingIndicator';
import DocumentModal from '../Common/DocumentModal';
import BrandMark from '../Common/BrandMark';
import remarkCitations from '../../utils/remarkCitations';
import { formatRelativeDate, copyToClipboard } from '../../utils/helpers';
import { Copy, Check, User, AlertTriangle, Info, Mail } from 'lucide-react';

const MarkdownContent = ({ message, onOpenSource }) => (
  <ReactMarkdown
    remarkPlugins={message.isStreaming ? [] : [[remarkCitations, message.citations || {}]]}
    components={{
      'citation-pill': ({ n }) => (
        <CitationPill
          n={n}
          source={message.citations?.[n]}
          onOpenSource={onOpenSource}
        />
      ),
      code({ inline, className, children, ...props }) {
        const match = /language-(\w+)/.exec(className || '');
        return !inline && match ? (
          <SyntaxHighlighter
            style={oneLight}
            language={match[1]}
            PreTag="div"
            customStyle={{ margin: 0, background: 'transparent', padding: 0, fontSize: '13px' }}
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
);

const UserQuestion = ({ message }) => (
  <div className="relative flex animate-slide-up items-start gap-3 pt-2">
    <span
      className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface text-ink-muted ring-1 ring-line"
      aria-hidden="true"
    >
      <User className="h-4 w-4" />
    </span>
    <div className="min-w-0 flex-1">
      <p className="sr-only">Vous :</p>
      <p className="whitespace-pre-wrap break-words pt-0.5 font-serif text-[19px] font-semibold leading-snug text-ink">
        {message.content}
      </p>
    </div>
  </div>
);

const SystemNotice = ({ message }) => (
  <div className="flex animate-slide-up justify-center" role="status">
    <p className="inline-flex max-w-xl items-start gap-2 rounded-xl border border-accent/15 bg-accent-soft px-4 py-2.5 text-sm text-accent-ink">
      <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{message.content}</span>
    </p>
  </div>
);

const MessageBubble = ({ message, onEscalate }) => {
  const [copied, setCopied] = useState(false);
  // Single shared modal source for ALL citation pills in this message. Lifting
  // this state up (rather than letting each CitationPill own its own modal)
  // guarantees at most one source modal is ever open: clicking pill [2] while
  // pill [1]'s modal is open just swaps the source, it never stacks a second
  // overlay on top of the first.
  const [openCitationSource, setOpenCitationSource] = useState(null);

  const handleCopy = async () => {
    const success = await copyToClipboard(message.content);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (message.type === 'user') {
    return <UserQuestion message={message} />;
  }

  if (message.type === 'system') {
    return <SystemNotice message={message} />;
  }

  if (message.type === 'error') {
    return (
      <div role="alert" className="alert-danger animate-slide-up px-5 py-4">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        <p className="min-w-0 flex-1 break-words">{message.content}</p>
      </div>
    );
  }

  const isWaiting = message.isStreaming && !message.content;
  const hasSources = !message.isStreaming && message.sources && message.sources.length > 0;

  return (
    <>
      <article className="card animate-slide-up overflow-hidden" aria-label="Réponse de Mimir">
        <header className="flex items-center gap-2 border-b border-line-soft py-2 pl-5 pr-2.5">
          <BrandMark className="h-4 w-4 text-accent" />
          <span className="text-[13px] font-semibold text-ink">Mimir</span>
          <span className="text-[13px] text-ink-faint" aria-hidden="true">·</span>
          <time dateTime={message.timestamp} className="text-[13px] text-ink-muted">
            {formatRelativeDate(message.timestamp)}
          </time>
          {!message.isStreaming && message.confidence > 0 && (
            <span className="badge-neutral ml-1 hidden sm:inline-flex">
              Confiance {Math.round(message.confidence * 100)} %
            </span>
          )}
          {!message.isStreaming && (
            <button
              type="button"
              onClick={handleCopy}
              className="btn-ghost btn-sm ml-auto"
              title="Copier le message"
            >
              {copied ? (
                <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />
              ) : (
                <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              {copied ? 'Copié' : 'Copier'}
            </button>
          )}
        </header>

        <div className="px-5 py-4">
          {isWaiting ? (
            <p className="flex items-center gap-3 py-1 text-sm text-ink-muted" role="status">
              Recherche dans la documentation
              <ThinkingDots />
            </p>
          ) : (
            <div className="prose max-w-none">
              <MarkdownContent message={message} onOpenSource={setOpenCitationSource} />
              {message.isStreaming && (
                <span
                  className="ml-0.5 inline-block h-[1.1em] w-[2px] translate-y-[3px] animate-caret bg-accent"
                  aria-hidden="true"
                />
              )}
            </div>
          )}
        </div>

        {hasSources && (
          <div className="border-t border-line-soft px-5 py-3">
            <SourcesList sources={message.sources} />
          </div>
        )}

        {onEscalate && (
          <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-line-soft bg-sunken/70 px-5 py-2.5">
            <p className="text-[13px] text-ink-muted">Cette réponse ne vous suffit pas ?</p>
            <button type="button" onClick={onEscalate} className="btn-ghost btn-sm -mr-2 text-accent-ink hover:text-accent-ink">
              <Mail className="h-3.5 w-3.5" aria-hidden="true" />
              Transmettre à un humain
            </button>
          </footer>
        )}
      </article>

      {/* Single shared modal for every citation pill in this message (see
          openCitationSource above) — reuses the existing DocumentModal, never
          stacked. */}
      <DocumentModal
        isOpen={openCitationSource != null}
        onClose={() => setOpenCitationSource(null)}
        documentId={openCitationSource?.document_id}
        filename={openCitationSource?.filename || openCitationSource?.document_name}
        relevantChunks={openCitationSource ? [openCitationSource] : []}
      />
    </>
  );
};

export default MessageBubble;
