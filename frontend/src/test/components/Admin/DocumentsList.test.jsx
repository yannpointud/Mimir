import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DocumentsList from '../../../components/Admin/DocumentsList';

const outletContext = vi.hoisted(() => ({ onRefresh: vi.fn(), refreshTrigger: 0 }));

vi.mock('react-router-dom', async (importOriginal) => ({
  ...(await importOriginal()),
  useOutletContext: () => outletContext,
}));

vi.mock('../../../services/api', () => ({
  documentsAPI: {
    getDocuments: vi.fn(),
    deleteDocument: vi.fn(),
    togglePreservation: vi.fn(),
    reprocessDocument: vi.fn(),
  },
}));
import { documentsAPI } from '../../../services/api';

const INDEXED = { id: 'doc-1', filename: 'guide.pdf', status: 'indexed', chunk_count: 12, preserve: false, created_at: '2026-01-05T10:00:00' };
const PRESERVED = { id: 'doc-2', filename: 'charte.md', status: 'indexed', chunk_count: 3, preserve: true, created_at: '2026-01-06T10:00:00' };
const FAILED = { id: 'doc-3', filename: 'scan.pdf', status: 'error', chunk_count: 0, preserve: false, error_message: 'No text extracted', created_at: '2026-01-07T10:00:00' };

// Serve the list query and the error-count query (limit=1, status 'error')
const serveDocuments = (documents, errored = []) => {
  documentsAPI.getDocuments.mockImplementation(async (page, limit, status) => {
    if (status === 'error') {
      return { documents: limit === 1 ? errored.slice(0, 1) : errored, total_count: errored.length };
    }
    return { documents, total_count: documents.length };
  });
};

const renderList = () => render(
  <MemoryRouter>
    <DocumentsList />
  </MemoryRouter>
);

const openActionsOf = (filename) => {
  fireEvent.click(screen.getByRole('button', { name: `Actions pour ${filename}` }));
  return screen.getByRole('menu');
};

describe('DocumentsList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists the documents returned by the API with their total', async () => {
    serveDocuments([INDEXED, PRESERVED]);
    renderList();

    expect(await screen.findByText('guide.pdf')).toBeInTheDocument();
    expect(screen.getByText('charte.md')).toBeInTheDocument();
    expect(screen.getByText(/Affichage de 1 à 2 sur/)).toHaveTextContent('2 documents');
    expect(documentsAPI.getDocuments).toHaveBeenCalledWith(1, 10, null, null, 'created_at', 'desc');
  });

  it('shows the load error returned by the API', async () => {
    documentsAPI.getDocuments.mockRejectedValue(new Error('Backend unreachable'));
    renderList();

    expect(await screen.findByText('Backend unreachable')).toBeInTheDocument();
  });

  it('sends the debounced search term to the API', async () => {
    serveDocuments([INDEXED]);
    renderList();
    await screen.findByText('guide.pdf');

    fireEvent.change(screen.getByLabelText('Rechercher un document'), { target: { value: 'guide' } });

    await waitFor(() => {
      expect(documentsAPI.getDocuments).toHaveBeenCalledWith(1, 10, null, 'guide', 'created_at', 'desc');
    });
  });

  it('retries every document in error from the banner', async () => {
    serveDocuments([INDEXED, FAILED], [FAILED]);
    documentsAPI.reprocessDocument.mockResolvedValue({});
    renderList();

    fireEvent.click(await screen.findByRole('button', { name: /Réessayer tout \(1\)/ }));

    await waitFor(() => {
      expect(outletContext.onRefresh).toHaveBeenCalled();
    });
    expect(documentsAPI.reprocessDocument).toHaveBeenCalledTimes(1);
    expect(documentsAPI.reprocessDocument).toHaveBeenCalledWith('doc-3');
  });

  it('deletes a document after confirmation', async () => {
    serveDocuments([INDEXED]);
    documentsAPI.deleteDocument.mockResolvedValue({});
    renderList();
    await screen.findByText('guide.pdf');

    fireEvent.click(within(openActionsOf('guide.pdf')).getByRole('menuitem', { name: 'Supprimer' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Supprimer' }));

    await waitFor(() => {
      expect(outletContext.onRefresh).toHaveBeenCalled();
    });
    expect(documentsAPI.deleteDocument).toHaveBeenCalledWith('doc-1', false);
  });

  it('forbids deleting a preserved document', async () => {
    serveDocuments([PRESERVED]);
    renderList();
    await screen.findByText('charte.md');

    const menu = openActionsOf('charte.md');

    expect(within(menu).getByRole('menuitem', { name: 'Supprimer' })).toBeDisabled();
  });

  it('toggles the preservation and reprocesses from the actions menu', async () => {
    serveDocuments([INDEXED]);
    documentsAPI.togglePreservation.mockResolvedValue({});
    documentsAPI.reprocessDocument.mockResolvedValue({});
    renderList();
    await screen.findByText('guide.pdf');

    fireEvent.click(within(openActionsOf('guide.pdf')).getByRole('menuitem', { name: /Protéger le document/ }));
    await waitFor(() => {
      expect(outletContext.onRefresh).toHaveBeenCalled();
    });
    expect(documentsAPI.togglePreservation).toHaveBeenCalledWith('doc-1', true);

    fireEvent.click(within(openActionsOf('guide.pdf')).getByRole('menuitem', { name: /Réindexer le document/ }));
    await waitFor(() => {
      expect(documentsAPI.reprocessDocument).toHaveBeenCalledWith('doc-1');
    });
  });

  it('sorts on a column header, then flips the direction on a second click', async () => {
    serveDocuments([INDEXED, PRESERVED]);
    renderList();
    await screen.findByText('guide.pdf');

    expect(screen.getByRole('columnheader', { name: /Date d'ajout/ })).toHaveAttribute('aria-sort', 'descending');

    fireEvent.click(screen.getByRole('button', { name: 'Document' }));
    await waitFor(() => {
      expect(documentsAPI.getDocuments).toHaveBeenCalledWith(1, 10, null, null, 'filename', 'asc');
    });
    expect(screen.getByRole('columnheader', { name: /Document/ })).toHaveAttribute('aria-sort', 'ascending');
    expect(screen.getByRole('columnheader', { name: /Date d'ajout/ })).toHaveAttribute('aria-sort', 'none');

    fireEvent.click(screen.getByRole('button', { name: 'Document' }));
    await waitFor(() => {
      expect(documentsAPI.getDocuments).toHaveBeenCalledWith(1, 10, null, null, 'filename', 'desc');
    });
  });

  it('starts the sections and status columns in their natural direction', async () => {
    serveDocuments([INDEXED]);
    renderList();
    await screen.findByText('guide.pdf');

    fireEvent.click(screen.getByRole('button', { name: 'Sections' }));
    await waitFor(() => {
      expect(documentsAPI.getDocuments).toHaveBeenCalledWith(1, 10, null, null, 'chunk_count', 'desc');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Statut' }));
    await waitFor(() => {
      expect(documentsAPI.getDocuments).toHaveBeenCalledWith(1, 10, null, null, 'status', 'asc');
    });
  });
});
