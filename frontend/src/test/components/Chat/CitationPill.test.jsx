import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import CitationPill from '../../../components/Chat/CitationPill';

describe('CitationPill', () => {
  const source = {
    document_id: 42,
    filename: 'Guide.pdf',
    chunk_index: 3,
    similarity_score: 0.88,
    chunk_text: 'un extrait pertinent',
  };

  it('rend un bouton natif affichant N sans crochets', () => {
    render(<CitationPill n="1" source={source} onOpenSource={vi.fn()} />);

    const button = screen.getByRole('button');
    expect(button.tagName).toBe('BUTTON');
    expect(button).toHaveAttribute('type', 'button');
    expect(button).toHaveTextContent('1');
    expect(button).not.toHaveTextContent('[1]');
  });

  it('expose un aria-label avec le nom de fichier résolu', () => {
    render(<CitationPill n="2" source={source} onOpenSource={vi.fn()} />);

    expect(
      screen.getByRole('button', { name: 'Voir la source 2 : Guide.pdf' })
    ).toBeInTheDocument();
  });

  it('utilise la chaîne de fallback pour le nom de fichier', () => {
    render(
      <CitationPill
        n="1"
        source={{ document_id: 7, document_name: 'Fallback.md' }}
        onOpenSource={vi.fn()}
      />
    );

    expect(
      screen.getByRole('button', { name: 'Voir la source 1 : Fallback.md' })
    ).toBeInTheDocument();
  });

  it('ne possède aucun état de modale locale : le clic délègue via onOpenSource', () => {
    const onOpenSource = vi.fn();
    render(<CitationPill n="1" source={source} onOpenSource={onOpenSource} />);

    expect(onOpenSource).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button'));

    expect(onOpenSource).toHaveBeenCalledTimes(1);
    expect(onOpenSource).toHaveBeenCalledWith(source);
  });

  it("n'appelle pas onOpenSource si document_id est manquant (defensive guard)", () => {
    const onOpenSource = vi.fn();
    render(
      <CitationPill n="1" source={{ filename: 'NoId.pdf' }} onOpenSource={onOpenSource} />
    );

    fireEvent.click(screen.getByRole('button'));

    expect(onOpenSource).not.toHaveBeenCalled();
  });
});
