import { useState } from 'react';
import { FileText, Mail, MousePointerClick, Search, CornerDownLeft } from 'lucide-react';
import DocumentModal from '../Common/DocumentModal';

const TIPS = [
  {
    icon: Search,
    title: 'Soyez précis',
    text: 'Citez le sujet, le service ou le document concerné.',
  },
  {
    icon: MousePointerClick,
    title: 'Vérifiez les sources',
    text: 'Un clic sur un numéro ouvre le passage cité.',
  },
  {
    icon: CornerDownLeft,
    title: 'Raccourcis',
    text: 'Entrée envoie, Maj + Entrée ajoute une ligne.',
  },
];

// Documents retrieved for the answers of this conversation, most used first.
const collectConsultedDocuments = (messages) => {
  const byDocument = new Map();
  messages
    .filter(message => message.type === 'assistant' && message.sources)
    .flatMap(message => message.sources)
    .forEach((source) => {
      const entry = byDocument.get(source.document_id) || {
        documentId: source.document_id,
        filename: source.filename || source.document_name || source.source || 'Document',
        chunks: [],
      };
      entry.chunks.push(source);
      byDocument.set(source.document_id, entry);
    });
  return [...byDocument.values()].sort((a, b) => b.chunks.length - a.chunks.length);
};

/**
 * Right-hand panel of the conversation view: what this session consulted,
 * usage tips and the hand-off to a human.
 */
const ChatAside = ({ messages, onContactHuman }) => {
  const [openDocument, setOpenDocument] = useState(null);

  const questionCount = messages.filter(message => message.type === 'user').length;
  const documents = collectConsultedDocuments(messages);

  return (
    <aside
      aria-label="À propos de cette conversation"
      className="relative hidden w-[300px] shrink-0 overflow-y-auto border-l border-line bg-surface/60 xl:block"
    >
      <div className="space-y-7 p-5">
        <section>
          <h2 className="eyebrow">Cette conversation</h2>
          <dl className="mt-3 grid grid-cols-2 gap-2.5">
            <div className="rounded-lg border border-line-soft bg-surface p-3">
              <dt className="text-xs text-ink-muted">Questions</dt>
              <dd className="mt-1 font-serif text-2xl font-semibold leading-none text-ink tabular">{questionCount}</dd>
            </div>
            <div className="rounded-lg border border-line-soft bg-surface p-3">
              <dt className="text-xs text-ink-muted">Documents</dt>
              <dd className="mt-1 font-serif text-2xl font-semibold leading-none text-ink tabular">{documents.length}</dd>
            </div>
          </dl>

          {documents.length > 0 && (
            <ul className="mt-3 space-y-0.5">
              {documents.map((document) => (
                <li key={document.documentId}>
                  <button
                    type="button"
                    onClick={() => setOpenDocument(document)}
                    className="group flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-[13px] text-ink transition-colors hover:bg-sunken"
                    title={`Voir les passages de ${document.filename}`}
                  >
                    <FileText className="h-4 w-4 shrink-0 text-ink-faint group-hover:text-accent" aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate">{document.filename}</span>
                    <span className="shrink-0 text-xs text-ink-faint tabular">{document.chunks.length}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h2 className="eyebrow">Bien utiliser Mimir</h2>
          <ul className="mt-3 space-y-3.5">
            {TIPS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
                <div>
                  <p className="text-[13px] font-semibold text-ink">{title}</p>
                  <p className="text-[13px] leading-snug text-ink-muted">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-xl border border-line bg-surface p-4 shadow-xs">
          <h2 className="text-sm font-semibold text-ink">Besoin d&apos;un interlocuteur ?</h2>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-muted">
            Votre question et la conversation sont transmises par e-mail à l&apos;équipe support.
          </p>
          <button type="button" onClick={onContactHuman} className="btn-secondary btn-sm mt-3 w-full">
            <Mail className="h-3.5 w-3.5" aria-hidden="true" />
            Contacter un humain
          </button>
        </section>
      </div>

      <DocumentModal
        isOpen={openDocument !== null}
        onClose={() => setOpenDocument(null)}
        documentId={openDocument?.documentId}
        filename={openDocument?.filename}
        relevantChunks={openDocument?.chunks || []}
      />
    </aside>
  );
};

export default ChatAside;
