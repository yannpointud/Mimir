import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import ChatPage from '../../../components/Chat/ChatPage';
import { AuthProvider } from '../../../hooks/useAuth';
import * as chatAPI from '../../../services/api';

// Mock the API
vi.mock('../../../services/api', () => ({
  chatAPI: {
    sendMessage: vi.fn(),
    escalateToHuman: vi.fn(),
  },
}));

// Wrapper for tests
const TestWrapper = ({ children }) => (
  <BrowserRouter>
    <AuthProvider>
      {children}
    </AuthProvider>
  </BrowserRouter>
);

describe('ChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('affiche le message de bienvenue au démarrage', () => {
    render(
      <TestWrapper>
        <ChatPage />
      </TestWrapper>
    );

    expect(screen.getByText(/Bonjour ! Je suis Mimir/)).toBeInTheDocument();
  });

  it('permet d\'envoyer un message', async () => {
    const mockResponse = {
      answer: 'Voici ma réponse',
      sources: [],
      confidence_score: 0.9
    };

    chatAPI.chatAPI.sendMessage.mockResolvedValue(mockResponse);

    render(
      <TestWrapper>
        <ChatPage />
      </TestWrapper>
    );

    const input = screen.getByPlaceholderText(/Tapez votre question ici/);
    const sendButton = screen.getByTitle('Envoyer le message');

    fireEvent.change(input, { target: { value: 'Test question' } });
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(chatAPI.chatAPI.sendMessage).toHaveBeenCalledWith('Test question', expect.any(String));
    });

    await waitFor(() => {
      expect(screen.getByText('Voici ma réponse')).toBeInTheDocument();
    });
  });

  it('affiche une erreur en cas de problème API', async () => {
    chatAPI.chatAPI.sendMessage.mockRejectedValue(new Error('Erreur API'));

    render(
      <TestWrapper>
        <ChatPage />
      </TestWrapper>
    );

    const input = screen.getByPlaceholderText(/Tapez votre question ici/);
    const sendButton = screen.getByTitle('Envoyer le message');

    fireEvent.change(input, { target: { value: 'Test question' } });
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(screen.getByText(/une erreur s'est produite/)).toBeInTheDocument();
    });
  });

  it('permet de démarrer une nouvelle conversation', () => {
    render(
      <TestWrapper>
        <ChatPage />
      </TestWrapper>
    );

    const newConversationButton = screen.getByText('Nouvelle conversation');
    fireEvent.click(newConversationButton);

    expect(screen.getByText(/Nouvelle conversation démarrée/)).toBeInTheDocument();
  });
});