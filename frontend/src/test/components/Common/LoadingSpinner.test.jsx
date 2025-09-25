import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import LoadingSpinner from '../../../components/Common/LoadingSpinner';

describe('LoadingSpinner', () => {
  it('affiche le spinner avec la taille par défaut', () => {
    render(<LoadingSpinner />);

    const spinner = screen.getByText('Chargement...');
    expect(spinner).toBeInTheDocument();
  });

  it('applique la taille spécifiée', () => {
    const { container } = render(<LoadingSpinner size="lg" />);

    const spinnerDiv = container.querySelector('div');
    expect(spinnerDiv).toHaveClass('h-8', 'w-8');
  });

  it('applique les classes personnalisées', () => {
    const { container } = render(<LoadingSpinner className="custom-class" />);

    const spinnerDiv = container.querySelector('div');
    expect(spinnerDiv).toHaveClass('custom-class');
  });

  it('affiche le texte sr-only pour l\'accessibilité', () => {
    render(<LoadingSpinner />);

    const srText = screen.getByText('Chargement...');
    expect(srText).toHaveClass('sr-only');
  });
});