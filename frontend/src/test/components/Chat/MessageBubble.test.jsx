import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import MessageBubble from '../../../components/Chat/MessageBubble';

// Mock every lucide icon referenced by MessageBubble (and its children) so a
// missing export can never blow up the render (Pitfall 6).
vi.mock('lucide-react', () => {
  const Icon = ({ className }) => <span className={className} />;
  return {
    Copy: Icon,
    Check: Icon,
    User: Icon,
    Bot: Icon,
    AlertTriangle: Icon,
    Info: Icon,
    FileText: Icon,
    ExternalLink: Icon,
    ChevronDown: Icon,
    ChevronUp: Icon,
    Mail: Icon,
  };
});

// Stub DocumentModal — its internals are covered by their own suite; here we
// only care that MessageBubble renders exactly ONE instance and feeds it the
// currently selected citation source (documentId exposed for assertions).
vi.mock('../../../components/Common/DocumentModal', () => ({
  default: ({ isOpen, documentId }) =>
    isOpen ? <div data-testid="document-modal" data-document-id={String(documentId)} /> : null,
}));

vi.mock('../../../utils/helpers', () => ({
  formatRelativeDate: () => 'il y a un instant',
  copyToClipboard: vi.fn(() => Promise.resolve(true)),
  cn: (...classes) => classes.filter(Boolean).join(' '),
  truncateText: (text) => text,
}));

const baseMessage = {
  type: 'assistant',
  timestamp: new Date().toISOString(),
  sources: [],
  confidence: 0,
};

const citation = (name) => (screen.queryByRole('button', { name: new RegExp(`Voir la source ${name}`) }));

describe('MessageBubble citation rendering', () => {
  it('rend une pastille pour un [N] valide hors streaming', () => {
    render(
      <MessageBubble
        message={{
          ...baseMessage,
          content: 'Réponse sourcée [1] ici',
          citations: { 1: { document_id: 5, filename: 'Doc.pdf' } },
          isStreaming: false,
        }}
      />
    );

    const pill = screen.getByRole('button', { name: 'Voir la source 1 : Doc.pdf' });
    expect(pill).toBeInTheDocument();
    expect(pill).toHaveTextContent('1');
  });

  it('laisse un [N] hors périmètre en texte brut (pas de pastille)', () => {
    render(
      <MessageBubble
        message={{
          ...baseMessage,
          content: 'Réponse avec marqueur [9] invalide',
          citations: { 1: { document_id: 5, filename: 'Doc.pdf' } },
          isStreaming: false,
        }}
      />
    );

    // No pill for the out-of-range marker...
    expect(citation('9')).toBeNull();
    expect(citation('1')).toBeNull();
    // ...and the literal "[9]" survives in the text.
    expect(screen.getByText(/\[9\]/)).toBeInTheDocument();
  });

  it('rend [N] en texte brut pendant le streaming, même si valide', () => {
    render(
      <MessageBubble
        message={{
          ...baseMessage,
          content: 'Réponse en cours [1]',
          citations: { 1: { document_id: 5, filename: 'Doc.pdf' } },
          isStreaming: true,
        }}
      />
    );

    expect(citation('1')).toBeNull();
    expect(screen.getByText(/\[1\]/)).toBeInTheDocument();
  });

  it('rend un texte identique (sans pastille) quand la map de citations est vide', () => {
    const content = 'Une réponse sans aucune citation valide [1]';

    // Control: no citations key at all.
    const control = render(
      <MessageBubble
        message={{ ...baseMessage, content, isStreaming: false }}
      />
    );
    const controlText = control.container.textContent;
    control.unmount();

    // Subject: explicit empty citations map — must be byte-identical text.
    const subject = render(
      <MessageBubble
        message={{ ...baseMessage, content, citations: {}, isStreaming: false }}
      />
    );

    expect(citation('1')).toBeNull();
    expect(screen.getByText(/\[1\]/)).toBeInTheDocument();
    expect(subject.container.textContent).toBe(controlText);
  });

  it('partage une seule DocumentModal entre plusieurs pastilles : ouvrir la 2e remplace la 1re, jamais d\'empilement', () => {
    render(
      <MessageBubble
        message={{
          ...baseMessage,
          content: 'Réponse citant [1] puis [2]',
          citations: {
            1: { document_id: 5, filename: 'Premier.pdf' },
            2: { document_id: 9, filename: 'Second.pdf' },
          },
          isStreaming: false,
        }}
      />
    );

    // No modal before any pill is clicked.
    expect(screen.queryByTestId('document-modal')).not.toBeInTheDocument();

    // Open the first source.
    fireEvent.click(screen.getByRole('button', { name: 'Voir la source 1 : Premier.pdf' }));
    expect(screen.getAllByTestId('document-modal')).toHaveLength(1);
    expect(screen.getByTestId('document-modal')).toHaveAttribute('data-document-id', '5');

    // Clicking the second pill must swap the shared modal's source, never
    // stack a second overlay alongside the first.
    fireEvent.click(screen.getByRole('button', { name: 'Voir la source 2 : Second.pdf' }));
    expect(screen.getAllByTestId('document-modal')).toHaveLength(1);
    expect(screen.getByTestId('document-modal')).toHaveAttribute('data-document-id', '9');
  });
});
