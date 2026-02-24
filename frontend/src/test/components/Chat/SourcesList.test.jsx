import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SourcesList from '../../../components/Chat/SourcesList';

// Mock Lucide icons
vi.mock('lucide-react', () => ({
  FileText: ({ className }) => <div className={className} data-testid="file-icon" />,
  ExternalLink: ({ className }) => <div className={className} data-testid="external-icon" />,
}));

// Mock utilities
vi.mock('../../../utils/helpers', () => ({
  cn: (...classes) => classes.filter(Boolean).join(' '),
  truncateText: (text, limit) => text.length > limit ? text.substring(0, limit) + '...' : text,
}));

describe('SourcesList', () => {
  const mockSources = [
    {
      document_name: 'Guide utilisateur.pdf',
      text: 'Ceci est un extrait du guide utilisateur contenant des informations importantes pour les utilisateurs.',
      similarity_score: 0.85,
      source: 'guides/guide-utilisateur.pdf'
    },
    {
      document_name: 'FAQ.md',
      text: 'Questions fréquemment posées par les utilisateurs du système.',
      similarity_score: 0.72,
      source: 'docs/faq.md'
    },
    {
      source: 'manual.txt',
      text: 'Manuel technique complet du système avec toutes les spécifications.',
      similarity_score: 0.91
    }
  ];

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

  it('affiche toutes les sources fournies', () => {
    render(<SourcesList sources={mockSources} />);

    expect(screen.getByText('Guide utilisateur.pdf')).toBeInTheDocument();
    expect(screen.getByText('FAQ.md')).toBeInTheDocument();
    expect(screen.getByText('manual.txt')).toBeInTheDocument();
  });

  it('affiche les extraits de texte tronqués', () => {
    render(<SourcesList sources={mockSources} />);

    expect(screen.getByText(/Ceci est un extrait du guide utilisateur/)).toBeInTheDocument();
    expect(screen.getByText(/Questions fréquemment posées/)).toBeInTheDocument();
    expect(screen.getByText(/Manuel technique complet/)).toBeInTheDocument();
  });

  it('affiche les scores de pertinence correctement formatés', () => {
    render(<SourcesList sources={mockSources} />);

    expect(screen.getByText('Pertinence: 85%')).toBeInTheDocument();
    expect(screen.getByText('Pertinence: 72%')).toBeInTheDocument();
    expect(screen.getByText('Pertinence: 91%')).toBeInTheDocument();
  });

  it('affiche les barres de progression avec les bonnes largeurs', () => {
    const { container } = render(<SourcesList sources={mockSources} />);

    const progressBars = container.querySelectorAll('.bg-primary-600');
    expect(progressBars).toHaveLength(3);

    // Verify the width styles
    expect(progressBars[0]).toHaveStyle('width: 85%');
    expect(progressBars[1]).toHaveStyle('width: 72%');
    expect(progressBars[2]).toHaveStyle('width: 91%');
  });

  it('affiche les icônes externes pour chaque source', () => {
    render(<SourcesList sources={mockSources} />);

    const externalIcons = screen.getAllByTestId('external-icon');
    expect(externalIcons).toHaveLength(3);
  });

  it('gère le clic sur une source et log les informations', () => {
    const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

    render(<SourcesList sources={mockSources} />);

    // Click on the first source
    const firstSourceItem = screen.getByText('Guide utilisateur.pdf').closest('div[role="button"], div');
    fireEvent.click(firstSourceItem.parentElement.parentElement);

    expect(consoleSpy).toHaveBeenCalledWith('Source clicked:', mockSources[0]);

    consoleSpy.mockRestore();
  });

  it('utilise le nom de document ou source comme fallback', () => {
    const sourcesWithMissingNames = [
      { source: 'test.pdf', text: 'Test content' },
      { document_name: '', source: 'empty.pdf', text: 'Empty name' },
      { text: 'No source info' }
    ];

    render(<SourcesList sources={sourcesWithMissingNames} />);

    expect(screen.getByText('test.pdf')).toBeInTheDocument();
    expect(screen.getByText('empty.pdf')).toBeInTheDocument();
    expect(screen.getByText('Document')).toBeInTheDocument(); // fallback
  });

  it('gère les sources sans score de similarité', () => {
    const sourcesWithoutScore = [
      {
        document_name: 'Sans score.pdf',
        text: 'Contenu sans score'
      }
    ];

    render(<SourcesList sources={sourcesWithoutScore} />);

    expect(screen.getByText('Sans score.pdf')).toBeInTheDocument();
    expect(screen.getByText('Contenu sans score')).toBeInTheDocument();
    // Should not display a relevance section
    expect(screen.queryByText(/Pertinence:/)).not.toBeInTheDocument();
  });

  it('gère les sources sans texte', () => {
    const sourcesWithoutText = [
      {
        document_name: 'Sans texte.pdf',
        similarity_score: 0.5
      }
    ];

    render(<SourcesList sources={sourcesWithoutText} />);

    expect(screen.getByText('Sans texte.pdf')).toBeInTheDocument();
    expect(screen.getByText('Pertinence: 50%')).toBeInTheDocument();
    // The text should not be displayed
    expect(screen.queryByText(/class="text-xs text-gray-600"/)).not.toBeInTheDocument();
  });

  it('applique les bonnes classes CSS pour les états hover', () => {
    const { container } = render(<SourcesList sources={[mockSources[0]]} />);

    const sourceItem = container.querySelector('.cursor-pointer');
    expect(sourceItem).toHaveClass('transition-colors', 'duration-200');
    expect(sourceItem).toHaveClass('hover:bg-gray-50', 'hover:border-gray-300');
  });

  it('respecte la limite de caractères pour la troncature', () => {
    const longTextSource = [{
      document_name: 'Long text.pdf',
      text: 'A'.repeat(200), // 200 characters text
      similarity_score: 0.8
    }];

    render(<SourcesList sources={longTextSource} />);

    // The text should be truncated to 120 characters + "..."
    const textElement = screen.getByText(new RegExp('A{120}\\.\\.\\.$'));
    expect(textElement).toBeInTheDocument();
  });
});