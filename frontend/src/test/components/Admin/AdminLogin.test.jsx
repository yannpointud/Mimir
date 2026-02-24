import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { act } from 'react';
import { BrowserRouter } from 'react-router-dom';
import AdminLogin from '../../../components/Admin/AdminLogin';

// Mock the useAuth hook
const mockLogin = vi.fn();
const mockUseAuth = {
  login: mockLogin,
  isAuthenticated: false,
  loading: false,
};

vi.mock('../../../hooks/useAuth', () => ({
  useAuth: () => mockUseAuth,
  AuthProvider: ({ children }) => children,
}));

// Wrapper for tests
const TestWrapper = ({ children }) => (
  <BrowserRouter>
    {children}
  </BrowserRouter>
);

describe('AdminLogin', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAuth.isAuthenticated = false;
    mockUseAuth.loading = false;
  });

  it('affiche le formulaire de connexion', () => {
    render(
      <TestWrapper>
        <AdminLogin />
      </TestWrapper>
    );

    expect(screen.getByText('Administration Mimir')).toBeInTheDocument();
    expect(screen.getByLabelText('Nom d\'utilisateur')).toBeInTheDocument();
    expect(screen.getByLabelText('Mot de passe')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Se connecter' })).toBeInTheDocument();
  });

  it('permet de saisir les identifiants', () => {
    render(
      <TestWrapper>
        <AdminLogin />
      </TestWrapper>
    );

    const usernameInput = screen.getByLabelText('Nom d\'utilisateur');
    const passwordInput = screen.getByLabelText('Mot de passe');

    fireEvent.change(usernameInput, { target: { value: 'admin' } });
    fireEvent.change(passwordInput, { target: { value: 'password' } });

    expect(usernameInput.value).toBe('admin');
    expect(passwordInput.value).toBe('password');
  });

  it('appelle la fonction de connexion lors de la soumission', async () => {
    mockLogin.mockResolvedValue({ success: true });

    render(
      <TestWrapper>
        <AdminLogin />
      </TestWrapper>
    );

    const usernameInput = screen.getByLabelText('Nom d\'utilisateur');
    const passwordInput = screen.getByLabelText('Mot de passe');
    const submitButton = screen.getByRole('button', { name: 'Se connecter' });

    await act(async () => {
      fireEvent.change(usernameInput, { target: { value: 'admin' } });
      fireEvent.change(passwordInput, { target: { value: 'password' } });
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('admin', 'password');
    });
  });

  it('affiche une erreur en cas d\'échec de connexion', async () => {
    mockLogin.mockResolvedValue({
      success: false,
      error: 'Identifiants incorrects'
    });

    render(
      <TestWrapper>
        <AdminLogin />
      </TestWrapper>
    );

    const usernameInput = screen.getByLabelText('Nom d\'utilisateur');
    const passwordInput = screen.getByLabelText('Mot de passe');
    const submitButton = screen.getByRole('button', { name: 'Se connecter' });

    fireEvent.change(usernameInput, { target: { value: 'admin' } });
    fireEvent.change(passwordInput, { target: { value: 'wrong' } });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText('Identifiants incorrects')).toBeInTheDocument();
    });
  });

  it('permet de basculer la visibilité du mot de passe', () => {
    render(
      <TestWrapper>
        <AdminLogin />
      </TestWrapper>
    );

    const passwordInput = screen.getByLabelText('Mot de passe');
    // The toggle button is the only button of type button that is not the submit
    const toggleButton = screen.getAllByRole('button').find(btn => btn.type === 'button');

    expect(passwordInput.type).toBe('password');

    fireEvent.click(toggleButton);
    expect(passwordInput.type).toBe('text');

    fireEvent.click(toggleButton);
    expect(passwordInput.type).toBe('password');
  });
});