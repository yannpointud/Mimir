import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import ChatPage from '../../../components/Chat/ChatPage';
import { AuthProvider } from '../../../hooks/useAuth';
import * as chatAPI from '../../../services/api';

// Mock the API — the chat UI streams via sendMessageStream(question, sessionId, callbacks)
vi.mock('../../../services/api', () => ({
  chatAPI: {
    sendMessageStream: vi.fn(),
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

  const sendMessage = async (text) => {
    const input = screen.getByPlaceholderText(/Tapez votre question ici/);
    const sendButton = screen.getByTitle('Envoyer le message');
    fireEvent.change(input, { target: { value: text } });
    fireEvent.click(sendButton);
  };

  it('affiche le message de bienvenue au démarrage', () => {
    render(
      <TestWrapper>
        <ChatPage />
      </TestWrapper>
    );

    expect(screen.getByText(/Bonjour ! Je suis Mimir/)).toBeInTheDocument();
  });

  it('permet d\'envoyer un message', async () => {
    // Drive the streaming callbacks to simulate a full answer.
    chatAPI.chatAPI.sendMessageStream.mockImplementation((question, sessionId, callbacks) => {
      callbacks.onStart?.(sessionId);
      callbacks.onChunk?.('Voici ma réponse');
      callbacks.onDone?.({ sources: [], confidence_score: 0.9 });
      return Promise.resolve({});
    });

    render(
      <TestWrapper>
        <ChatPage />
      </TestWrapper>
    );

    await sendMessage('Test question');

    await waitFor(() => {
      expect(chatAPI.chatAPI.sendMessageStream).toHaveBeenCalledWith(
        'Test question',
        expect.any(String),
        expect.any(Object)
      );
    });

    await waitFor(() => {
      expect(screen.getByText('Voici ma réponse')).toBeInTheDocument();
    });
  });

  it('affiche une erreur en cas de problème API', async () => {
    chatAPI.chatAPI.sendMessageStream.mockImplementation((question, sessionId, callbacks) => {
      callbacks.onError?.('Erreur API');
      return Promise.reject(new Error('Erreur API'));
    });

    render(
      <TestWrapper>
        <ChatPage />
      </TestWrapper>
    );

    await sendMessage('Test question');

    await waitFor(() => {
      expect(screen.getByText(/une erreur s'est produite/)).toBeInTheDocument();
    });
  });

  it('stocke les citations reçues sur le message et rend une pastille', async () => {
    // The citation event lands before done and must populate message.citations,
    // producing a clickable pill for the valid [N] marker once streaming ends.
    chatAPI.chatAPI.sendMessageStream.mockImplementation((question, sessionId, callbacks) => {
      callbacks.onChunk?.('Réponse sourcée [1]');
      callbacks.onCitation?.({
        1: {
          document_id: 42,
          filename: 'Guide.pdf',
          chunk_index: 0,
          similarity_score: 0.9,
          chunk_text: 'extrait',
        },
      });
      callbacks.onDone?.({ sources: [], confidence_score: 0.9 });
      return Promise.resolve({});
    });

    render(
      <TestWrapper>
        <ChatPage />
      </TestWrapper>
    );

    await sendMessage('Question avec source');

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Voir la source 1 : Guide\.pdf/ })
      ).toBeInTheDocument();
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
