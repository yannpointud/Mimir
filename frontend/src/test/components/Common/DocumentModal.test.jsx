import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import DocumentModal from '../../../components/Common/DocumentModal';

// Mock the API module (SEC-04 tests render the modal with controlled chunk content)
vi.mock('../../../services/api', () => ({
  documentsAPI: {
    getDocumentWithChunks: vi.fn(),
  },
}));
import { documentsAPI } from '../../../services/api';

const XSS_PAYLOAD = '<script>alert(1)</script> and <img src=x onerror=alert(2)>';

// Helper: render the modal with a single chunk auto-selected as relevant
const renderModalWithChunk = (text, extraProps = {}) => {
  documentsAPI.getDocumentWithChunks.mockResolvedValue({
    filename: 'evil.md',
    chunks: [{ id: 1, chunk_index: 0, text }],
  });
  return render(
    <DocumentModal
      isOpen={true}
      onClose={() => {}}
      documentId="1"
      relevantChunks={[{ chunk_index: 0, similarity_score: 0.9 }]}
      {...extraProps}
    />
  );
};

describe('DocumentModal — SEC-04 escape-then-highlight', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders a malicious chunk as inert literal text (no script/img element in DOM)', async () => {
    const { baseElement: container } = renderModalWithChunk(XSS_PAYLOAD);

    // Wait for the selected chunk content panel to appear
    await waitFor(() => {
      expect(container.querySelector('.prose')).not.toBeNull();
    });

    // Structural assertions (Pitfall 9: jsdom never executes injected scripts,
    // so we assert DOM structure, not execution)
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();

    // The literal payload source must be VISIBLE text in the content panel (UI-SPEC invariant 2)
    const prose = container.querySelector('.prose');
    expect(prose.textContent).toContain('<script>alert(1)</script>');
    expect(prose.textContent).toContain('<img src=x onerror=alert(2)>');
  });

  it('preserves search highlighting on escaped text (mark survives escaping)', async () => {
    const { baseElement: container } = renderModalWithChunk(XSS_PAYLOAD, { searchQuery: 'alert' });

    await waitFor(() => {
      const marks = container.querySelectorAll('mark.bg-hl');
      expect(marks.length).toBeGreaterThan(0);
      expect(marks[0].textContent).toBe('alert');
    });

    // Only <mark> may exist in the injected HTML (UI-SPEC invariant 5)
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();

    // Highlight appearance unchanged (exact classes, UI-SPEC invariant 4)
    const mark = container.querySelector('mark.bg-hl');
    expect(mark.className).toBe('rounded-sm bg-hl px-0.5 text-ink');
  });

  it('renders a plain-text chunk identically (zero regression, no mark without query)', async () => {
    const plainText = 'Ceci est un document ordinaire sans balise HTML.';
    const { baseElement: container } = renderModalWithChunk(plainText);

    await waitFor(() => {
      expect(container.querySelector('.prose')).not.toBeNull();
    });

    const prose = container.querySelector('.prose');
    expect(prose.textContent).toContain(plainText);
    // No highlight marks when no query is provided
    expect(container.querySelectorAll('mark').length).toBe(0);
    // Layout invariant: whitespace-pre-wrap preserved on the content panel
    expect(prose.className).toContain('whitespace-pre-wrap');
  });

  it('displays &, <, > literally even WITHOUT a query (guard bug fixed)', async () => {
    const htmlChars = 'Tom & Jerry disent <notes> que 1 > 0';
    const { baseElement: container } = renderModalWithChunk(htmlChars);

    await waitFor(() => {
      expect(container.querySelector('.prose')).not.toBeNull();
    });

    // The vulnerable guard returned raw text when query was empty:
    // '<notes>' would then become a real DOM element instead of visible text
    expect(container.querySelector('notes')).toBeNull();

    const prose = container.querySelector('.prose');
    expect(prose.textContent).toContain('Tom & Jerry disent <notes> que 1 > 0');
  });
});
