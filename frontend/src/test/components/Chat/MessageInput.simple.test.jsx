import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { act } from 'react';
import MessageInput from '../../../components/Chat/MessageInput';

// Mock des icônes
vi.mock('lucide-react', () => ({
  Send: ({ className, ...props }) => <div className={className} data-testid="send-icon" {...props} />,
  Paperclip: ({ className, ...props }) => <div className={className} data-testid="paperclip-icon" {...props} />,
}));

describe('MessageInput Simple Tests', () => {
  const defaultProps = {
    onSendMessage: vi.fn(),
    disabled: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render input field', () => {
    render(<MessageInput {...defaultProps} />);
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });

  it('should render send button', () => {
    render(<MessageInput {...defaultProps} />);
    expect(screen.getByTitle('Envoyer le message')).toBeInTheDocument();
  });

  it('should render paperclip button', () => {
    render(<MessageInput {...defaultProps} />);
    expect(screen.getByTitle('Joindre un fichier (bientôt disponible)')).toBeInTheDocument();
  });

  it('should handle text input', async () => {
    render(<MessageInput {...defaultProps} />);
    const input = screen.getByRole('textbox');

    await act(async () => {
      fireEvent.change(input, { target: { value: 'Hello' } });
    });

    expect(input.value).toBe('Hello');
  });

  it('should call onSendMessage when form submitted', async () => {
    const onSendMessage = vi.fn();
    render(<MessageInput {...defaultProps} onSendMessage={onSendMessage} />);

    const input = screen.getByRole('textbox');
    const form = input.closest('form');

    await act(async () => {
      fireEvent.change(input, { target: { value: 'Test message' } });
    });

    await act(async () => {
      fireEvent.submit(form);
    });

    expect(onSendMessage).toHaveBeenCalledWith('Test message');
  });

  it('should handle Enter key', async () => {
    const onSendMessage = vi.fn();
    render(<MessageInput {...defaultProps} onSendMessage={onSendMessage} />);

    const input = screen.getByRole('textbox');

    await act(async () => {
      fireEvent.change(input, { target: { value: 'Test message' } });
    });

    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' });
    });

    expect(onSendMessage).toHaveBeenCalledWith('Test message');
  });

  it('should handle Shift+Enter without sending', async () => {
    const onSendMessage = vi.fn();
    render(<MessageInput {...defaultProps} onSendMessage={onSendMessage} />);

    const input = screen.getByRole('textbox');

    await act(async () => {
      fireEvent.change(input, { target: { value: 'Test message' } });
    });

    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    });

    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('should be disabled when disabled prop is true', () => {
    render(<MessageInput {...defaultProps} disabled={true} />);

    const input = screen.getByRole('textbox');
    const sendButton = screen.getByTitle('Envoyer le message');

    expect(input).toBeDisabled();
    expect(sendButton).toBeDisabled();
  });

  it('should not send empty message', async () => {
    const onSendMessage = vi.fn();
    render(<MessageInput {...defaultProps} onSendMessage={onSendMessage} />);

    const form = screen.getByRole('textbox').closest('form');

    await act(async () => {
      fireEvent.submit(form);
    });

    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('should trim whitespace', async () => {
    const onSendMessage = vi.fn();
    render(<MessageInput {...defaultProps} onSendMessage={onSendMessage} />);

    const input = screen.getByRole('textbox');
    const form = input.closest('form');

    await act(async () => {
      fireEvent.change(input, { target: { value: '  Hello World  ' } });
    });

    await act(async () => {
      fireEvent.submit(form);
    });

    expect(onSendMessage).toHaveBeenCalledWith('Hello World');
  });

  it('should clear input after sending', async () => {
    const onSendMessage = vi.fn();
    render(<MessageInput {...defaultProps} onSendMessage={onSendMessage} />);

    const input = screen.getByRole('textbox');
    const form = input.closest('form');

    await act(async () => {
      fireEvent.change(input, { target: { value: 'Test message' } });
    });

    await act(async () => {
      fireEvent.submit(form);
    });

    expect(input.value).toBe('');
  });
});