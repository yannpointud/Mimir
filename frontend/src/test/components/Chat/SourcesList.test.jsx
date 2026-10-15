import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SourcesList from '../../../components/Chat/SourcesList';

// Mock Lucide icons — must include EVERY icon the component imports
// (FileText, ExternalLink, ChevronDown, ChevronUp). A missing export makes
// the whole render throw.
vi.mock('lucide-react', () => ({
  FileText: ({ className }) => <div className={className} data-testid="file-icon" />,
  ExternalLink: ({ className }) => <div className={className} data-testid="external-icon" />,
  ChevronDown: ({ className }) => <div className={className} data-testid="chevron-down" />,
  ChevronUp: ({ className }) => <div className={className} data-testid="chevron-up" />,
}));

// Mock utilities
vi.mock('../../../utils/helpers', () => ({
  cn: (...classes) => classes.filter(Boolean).join(' '),
  truncateText: (text, limit) => text.length > limit ? text.substring(0, limit) + '...' : text,
}));

// DocumentModal is exercised elsewhere; stub it so a click just records props.
vi.mock('../../../components/Common/DocumentModal', () => ({
  default: ({ isOpen, documentId }) =>
    isOpen ? <div data-testid="document-modal" data-document-id={documentId} /> : null,
}));

// documentUtils is imported by SourcesList (openDocumentInBrowser)
vi.mock('../../../utils/documentUtils', () => ({
  openDocumentInBrowser: vi.fn(),
}));

describe('SourcesList', () => {
  // Sources now carry document_id (used for grouping) + chunk_index + filename,
  // matching the SSE `done.sources` shape.
  const mockSources = [
    {
      document_id: 'doc-1',
      filename: 'Guide utilisateur.pdf',
      chunk_index: 0,
      chunk_text: 'Ceci est un extrait du guide utilisateur contenant des informations importantes pour les utilisateurs.',
      similarity_score: 0.85,
    },
    {
      document_id: 'doc-2',
      filename: 'FAQ.md',
      chunk_index: 0,
      chunk_text: 'Questions fréquemment posées par les utilisateurs du système.',
      similarity_score: 0.72,
    },
    {
      document_id: 'doc-3',
      filename: 'manual.txt',
      chunk_index: 0,
      chunk_text: 'Manuel technique complet du système avec toutes les spécifications.',
      similarity_score: 0.91,
    },
  ];

  // Helper: the list is collapsed by default — expand it to reveal the items.
  const expand = () => fireEvent.click(screen.getByText(/^Sources \(/));

  it('affiche null quand aucune source n\'est fournie', () => {
    const { container } = render(<SourcesList sources={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('affiche null quand le tableau de sources est vide', () => {
    const { container } = render(<SourcesList sources={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('affiche le titre avec le nombre de sources', () => {
    render(<SourcesList sources={mockSources} />);

    expect(screen.getByText('Sources (3)')).toBeInTheDocument();
    expect(screen.getByTestId('file-icon')).toBeInTheDocument();
  });

  it('affiche toutes les sources fournies une fois déplié', () => {
    render(<SourcesList sources={mockSources} />);
    expand();

    expect(screen.getByText(/Guide utilisateur\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/FAQ\.md/)).toBeInTheDocument();
    expect(screen.getByText(/manual\.txt/)).toBeInTheDocument();
  });

  it('affiche les extraits de texte tronqués une fois déplié', () => {
    render(<SourcesList sources={mockSources} />);
    expand();

    expect(screen.getByText(/Ceci est un extrait du guide utilisateur/)).toBeInTheDocument();
    expect(screen.getByText(/Questions fréquemment posées/)).toBeInTheDocument();
    expect(screen.getByText(/Manuel technique complet/)).toBeInTheDocument();
  });

  it('affiche les scores de pertinence correctement formatés', () => {
    render(<SourcesList sources={mockSources} />);
    expand();

    expect(screen.getByText('Pertinence: 85%')).toBeInTheDocument();
    expect(screen.getByText('Pertinence: 72%')).toBeInTheDocument();
    expect(screen.getByText('Pertinence: 91%')).toBeInTheDocument();
  });

  it('affiche les barres de progression avec les bonnes largeurs', () => {
    const { container } = render(<SourcesList sources={mockSources} />);
    expand();

    const progressBars = container.querySelectorAll('.bg-accent');
    expect(progressBars).toHaveLength(3);

    // documentItems are sorted by descending maxScore: 91%, 85%, 72%
    expect(progressBars[0]).toHaveStyle('width: 91%');
    expect(progressBars[1]).toHaveStyle('width: 85%');
    expect(progressBars[2]).toHaveStyle('width: 72%');
  });

  it('affiche les icônes externes pour chaque source', () => {
    render(<SourcesList sources={mockSources} />);
    expand();

    const externalIcons = screen.getAllByTestId('external-icon');
    expect(externalIcons).toHaveLength(3);
  });

  it('ouvre la modale au clic sur l\'icône de sections pertinentes', () => {
    render(<SourcesList sources={mockSources} />);
    expand();

    // Click the modal action icon of the first (most relevant) document row.
    const firstExternalIcon = screen.getAllByTestId('external-icon')[0];
    fireEvent.click(firstExternalIcon.closest('button'));

    const modal = screen.getByTestId('document-modal');
    // Most relevant document is manual.txt (91%) → doc-3
    expect(modal).toHaveAttribute('data-document-id', 'doc-3');
  });

  it('utilise le nom de document ou source comme fallback', () => {
    const sourcesWithMissingNames = [
      { document_id: 'a', filename: 'test.pdf', chunk_text: 'Test content' },
      { document_id: 'b', document_name: 'empty.pdf', chunk_text: 'Empty name' },
      { document_id: 'c', chunk_text: 'No source info' },
    ];

    render(<SourcesList sources={sourcesWithMissingNames} />);
    expand();

    expect(screen.getByText(/test\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/empty\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/Document/)).toBeInTheDocument(); // fallback
  });

  it('gère les sources sans score de similarité', () => {
    const sourcesWithoutScore = [
      {
        document_id: 'no-score',
        filename: 'Sans score.pdf',
        chunk_text: 'Contenu sans score',
      },
    ];

    render(<SourcesList sources={sourcesWithoutScore} />);
    expand();

    expect(screen.getByText(/Sans score\.pdf/)).toBeInTheDocument();
    expect(screen.getByText('Contenu sans score')).toBeInTheDocument();
    // With no numeric score the pertinence reads N/A
    expect(screen.getByText('Pertinence: N/A')).toBeInTheDocument();
  });

  it('gère les sources sans texte', () => {
    const sourcesWithoutText = [
      {
        document_id: 'no-text',
        filename: 'Sans texte.pdf',
        similarity_score: 0.5,
      },
    ];

    render(<SourcesList sources={sourcesWithoutText} />);
    expand();

    expect(screen.getByText(/Sans texte\.pdf/)).toBeInTheDocument();
    expect(screen.getByText('Pertinence: 50%')).toBeInTheDocument();
  });

  it('applique les bonnes classes CSS pour les états hover sur les items', () => {
    const { container } = render(<SourcesList sources={[mockSources[0]]} />);
    expand();

    // The document row carries the item-level hover classes.
    const itemRow = container.querySelector('li');
    expect(itemRow).not.toBeNull();
    expect(itemRow).toHaveClass('transition-colors', 'duration-200');
    expect(itemRow).toHaveClass('hover:border-line', 'hover:bg-sunken/60');
  });

  it('respecte la limite de caractères pour la troncature', () => {
    const longTextSource = [{
      document_id: 'long',
      filename: 'Long text.pdf',
      chunk_text: 'A'.repeat(200), // 200 characters text
      similarity_score: 0.8,
    }];

    render(<SourcesList sources={longTextSource} />);
    expand();

    // The text should be truncated to 120 characters + "..."
    const textElement = screen.getByText(new RegExp('A{120}\\.\\.\\.$'));
    expect(textElement).toBeInTheDocument();
  });
});
