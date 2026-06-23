import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import CitationWebCreateStage from './CitationWebCreateStage.svelte';
import type { CreateSeed, ExtractionDraft } from './citation-types';

const { mockPOST } = vi.hoisted(() => ({ mockPOST: vi.fn() }));
vi.mock('$lib/api/client', () => ({ default: { POST: mockPOST } }));

const WEB_CHILD = { id: 42, name: 'newsite.com/article', skip_locator: true };

const WEB_DRAFT: ExtractionDraft = {
  name: 'A great article',
  source_type: 'web',
  author: '',
  publisher: 'New Site',
  year: null,
  isbn: null,
  url: 'https://newsite.com/article',
};

/** A new-site web seed whose scrape succeeded. */
function newSite(draft: ExtractionDraft): CreateSeed {
  return { kind: 'web', url: draft.url ?? '', siteName: null, draft };
}
/** A new-site web seed whose scrape failed/was skipped. */
function newSiteNoScrape(url: string): CreateSeed {
  return { kind: 'web', url, siteName: null, draft: null };
}
/** An existing-site web seed (Create Site skipped); optional scrape draft and
 *  explicit page-name prefill (the identify "add a page under this root" path). */
function existingSite(
  url: string,
  siteName: string,
  draft: ExtractionDraft | null = null,
  pageName?: string,
): CreateSeed {
  return { kind: 'web', url, siteName, draft, pageName };
}

function noop() {}

beforeEach(() => mockPOST.mockReset());

describe('CitationWebCreateStage new site', () => {
  it('describe-site → page → finalize calls cite-url with all fields and emits the child', async () => {
    const user = userEvent.setup();
    mockPOST.mockResolvedValueOnce({ data: WEB_CHILD });
    const created = vi.fn();
    render(CitationWebCreateStage, {
      seed: newSite(WEB_DRAFT),
      onsourcecreated: created,
      oncancel: noop,
      onback: noop,
    });

    // Site panel: name prefilled from og:site_name (the draft's publisher).
    const siteName = screen.getByLabelText(/Site name/i) as HTMLInputElement;
    expect(siteName.value).toBe('New Site');
    await user.type(screen.getByLabelText(/Site description/i), 'A pinball news site.');
    await user.click(screen.getByRole('button', { name: 'Next' }));

    // Page panel: name prefilled from og:title, URL prefilled + read-only.
    expect((screen.getByLabelText(/Page name/i) as HTMLInputElement).value).toBe('A great article');
    const urlInput = screen.getByLabelText('URL') as HTMLInputElement;
    expect(urlInput.value).toBe('https://newsite.com/article');
    expect(urlInput.readOnly).toBe(true);

    await user.click(screen.getByRole('button', { name: /Create Citation/ }));

    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/cite-url/', {
      body: {
        url: 'https://newsite.com/article',
        site_name: 'New Site',
        site_description: 'A pinball news site.',
        page_name: 'A great article',
      },
    });
    expect(created).toHaveBeenCalledWith({
      sourceId: 42,
      sourceName: 'newsite.com/article',
      skipLocator: true,
    });
  });

  it('page panel shows the retrieval note when the page name was scraped', async () => {
    const user = userEvent.setup();
    render(CitationWebCreateStage, {
      seed: newSite(WEB_DRAFT),
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    // The note belongs on the page panel (where the scraped value lives), not
    // the site panel.
    expect(screen.queryByText(/Retrieved from page/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText(/Retrieved from page/i)).toBeInTheDocument();
  });

  it('page panel hides the retrieval note when nothing was scraped (blank page name)', async () => {
    const user = userEvent.setup();
    render(CitationWebCreateStage, {
      // A scrape that returned no og:title — Page name is blank, nothing to review.
      seed: newSite({ ...WEB_DRAFT, name: '' }),
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect((screen.getByLabelText(/Page name/i) as HTMLInputElement).value).toBe('');
    expect(screen.queryByText(/Retrieved from page/i)).not.toBeInTheDocument();
  });

  it('failed scrape: Site name prefilled from the domain, editable URL, no note', async () => {
    const user = userEvent.setup();
    render(CitationWebCreateStage, {
      seed: newSiteNoScrape('https://www.newsite.com/article'),
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    // No og:site_name was scraped, so Site name prefills from the (www-stripped)
    // domain — the name the new root will get.
    expect((screen.getByLabelText(/Site name/i) as HTMLInputElement).value).toBe('newsite.com');
    await user.click(screen.getByRole('button', { name: 'Next' }));

    expect((screen.getByLabelText(/Page name/i) as HTMLInputElement).value).toBe('');
    const urlInput = screen.getByLabelText('URL') as HTMLInputElement;
    expect(urlInput.value).toBe('https://www.newsite.com/article');
    // A failed scrape is exactly when the URL may be mistyped, so it's editable.
    expect(urlInput.readOnly).toBe(false);
    expect(screen.queryByText(/Retrieved from page/i)).not.toBeInTheDocument();
  });

  it('failed scrape: editing the URL resyncs the host-derived site name (until the user overrides it)', async () => {
    const user = userEvent.setup();
    render(CitationWebCreateStage, {
      seed: newSiteNoScrape('https://typo.example/page'),
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    expect((screen.getByLabelText(/Site name/i) as HTMLInputElement).value).toBe('typo.example');
    await user.click(screen.getByRole('button', { name: 'Next' }));

    // Correct the mistyped host on the (editable) URL field.
    const urlInput = screen.getByLabelText('URL') as HTMLInputElement;
    await user.clear(urlInput);
    await user.type(urlInput, 'https://real.com/page');

    // Back on the site panel the host-derived name has followed the URL, so the
    // root won't be named after the typo.
    await user.click(screen.getByRole('button', { name: /back/i }));
    expect((screen.getByLabelText(/Site name/i) as HTMLInputElement).value).toBe('real.com');
  });

  it('a user-typed site name is not overwritten when the URL later changes', async () => {
    const user = userEvent.setup();
    render(CitationWebCreateStage, {
      seed: newSiteNoScrape('https://typo.example/page'),
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    const siteField = screen.getByLabelText(/Site name/i) as HTMLInputElement;
    await user.clear(siteField);
    await user.type(siteField, 'My Site');
    await user.click(screen.getByRole('button', { name: 'Next' }));

    const urlInput = screen.getByLabelText('URL') as HTMLInputElement;
    await user.clear(urlInput);
    await user.type(urlInput, 'https://real.com/page');

    await user.click(screen.getByRole('button', { name: /back/i }));
    expect((screen.getByLabelText(/Site name/i) as HTMLInputElement).value).toBe('My Site');
  });

  it('back on the page panel returns to the site panel (no write); back on site leaves the flow', async () => {
    const user = userEvent.setup();
    const onback = vi.fn();
    render(CitationWebCreateStage, {
      seed: newSiteNoScrape('https://newsite.com/article'),
      onsourcecreated: noop,
      oncancel: noop,
      onback,
    });

    const siteNameField = screen.getByLabelText(/Site name/i) as HTMLInputElement;
    await user.clear(siteNameField);
    await user.type(siteNameField, 'Typed Name');
    await user.click(screen.getByRole('button', { name: 'Next' }));
    // Page panel is shown.
    expect(screen.getByLabelText(/Page name/i)).toBeInTheDocument();

    // Back → site panel, preserving the typed name (local state survives).
    await user.click(screen.getByRole('button', { name: /back/i }));
    expect((screen.getByLabelText(/Site name/i) as HTMLInputElement).value).toBe('Typed Name');
    expect(onback).not.toHaveBeenCalled();

    // Back again from the site panel leaves the flow entirely.
    await user.click(screen.getByRole('button', { name: /back/i }));
    expect(onback).toHaveBeenCalled();
    expect(mockPOST).not.toHaveBeenCalled();
  });
});

describe('CitationWebCreateStage existing site', () => {
  it('opens straight on the page panel (no Create Site), page name prefilled from the scrape', async () => {
    const user = userEvent.setup();
    mockPOST.mockResolvedValueOnce({ data: WEB_CHILD });
    const created = vi.fn();
    render(CitationWebCreateStage, {
      seed: existingSite('https://newsite.com/article', 'New Site', WEB_DRAFT),
      onsourcecreated: created,
      oncancel: noop,
      onback: noop,
    });

    // No Create Site panel — the site already exists; the page panel names it.
    expect(screen.queryByLabelText(/Site name/i)).not.toBeInTheDocument();
    expect(screen.getByText('New Site')).toBeInTheDocument();
    // The page name is prefilled from the scrape, just like the new-site path.
    expect((screen.getByLabelText(/Page name/i) as HTMLInputElement).value).toBe('A great article');
    const urlInput = screen.getByLabelText('URL') as HTMLInputElement;
    expect(urlInput.value).toBe('https://newsite.com/article');
    expect(urlInput.readOnly).toBe(true);

    await user.click(screen.getByRole('button', { name: /Create Citation/ }));

    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    // Site fields are sent blank — cite-url re-recognizes and nests under the
    // existing root, ignoring them.
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/cite-url/', {
      body: {
        url: 'https://newsite.com/article',
        site_name: '',
        site_description: '',
        page_name: 'A great article',
      },
    });
    expect(created).toHaveBeenCalledWith({
      sourceId: 42,
      sourceName: 'newsite.com/article',
      skipLocator: true,
    });
  });

  it('failed scrape: blank page name, but the URL stays read-only (no host re-pointing on a domain match)', async () => {
    // The host already recognized to this root; editing it would let cite-url
    // silently re-route the cite away from the named site, so it's locked even
    // though the scrape failed.
    render(CitationWebCreateStage, {
      seed: existingSite('https://newsite.com/article', 'New Site', null),
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    expect((screen.getByLabelText(/Page name/i) as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('URL') as HTMLInputElement).readOnly).toBe(true);
  });

  it('back from the page panel leaves the flow (no site panel to step back to)', async () => {
    const user = userEvent.setup();
    const onback = vi.fn();
    render(CitationWebCreateStage, {
      seed: existingSite('https://newsite.com/article', 'New Site'),
      onsourcecreated: noop,
      oncancel: noop,
      onback,
    });

    await user.click(screen.getByRole('button', { name: /back/i }));
    expect(onback).toHaveBeenCalled();
    expect(mockPOST).not.toHaveBeenCalled();
  });
});

describe('CitationWebCreateStage explicit parent (identify path)', () => {
  it('files the page under the chosen parent via create, not cite-url; page name prefilled from the seed', async () => {
    const user = userEvent.setup();
    mockPOST.mockResolvedValueOnce({ data: WEB_CHILD });
    const created = vi.fn();
    render(CitationWebCreateStage, {
      // Identify path: URL blank (entered here), site name + page name carried in,
      // and the explicit parent id passed by the orchestrator.
      seed: existingSite('', 'Jersey Jack Pinball', null, 'Elton John'),
      parentId: 30,
      onsourcecreated: created,
      oncancel: noop,
      onback: noop,
    });

    expect(screen.queryByLabelText(/Site name/i)).not.toBeInTheDocument();
    expect(screen.getByText('Jersey Jack Pinball')).toBeInTheDocument();
    expect((screen.getByLabelText(/Page name/i) as HTMLInputElement).value).toBe('Elton John');

    await user.type(
      screen.getByLabelText('URL'),
      'https://jerseyjackpinball.com/products/elton-john',
    );
    await user.click(screen.getByRole('button', { name: /Create Citation/ }));

    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    // Filed directly under the chosen root via pages/ — not routed through
    // cite-url, which would re-recognize the URL and could land it elsewhere.
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/{source_id}/pages/', {
      params: { path: { source_id: 30 } },
      body: {
        url: 'https://jerseyjackpinball.com/products/elton-john',
        page_name: 'Elton John',
      },
    });
    expect(mockPOST).not.toHaveBeenCalledWith('/api/citation-sources/cite-url/', expect.anything());
    expect(created).toHaveBeenCalledWith({
      sourceId: 42,
      sourceName: 'newsite.com/article',
      skipLocator: true,
    });
  });

  it('requires a page name on the explicit-parent path', async () => {
    const user = userEvent.setup();
    render(CitationWebCreateStage, {
      seed: existingSite('', 'Jersey Jack Pinball', null, ''),
      parentId: 30,
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    await user.type(screen.getByLabelText('URL'), 'https://jerseyjackpinball.com/x');
    await user.click(screen.getByRole('button', { name: /Create Citation/ }));

    expect(screen.getByText('Page name is required.')).toBeInTheDocument();
    expect(mockPOST).not.toHaveBeenCalled();
  });
});
