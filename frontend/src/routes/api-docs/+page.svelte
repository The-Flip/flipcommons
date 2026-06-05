<script lang="ts">
  import { page } from '$app/state';
  import { pageTitle } from '$lib/constants';

  let scalarLoaded = $state(false);
  let scalarError = $state('');

  // page.url.origin resolves to SITE_ORIGIN at prerender time (see
  // svelte.config.js prerender.origin), the same source the canonical
  // href and OG tags use, so this stays correct without hardcoding.
  let typesCommand = $derived(
    `npx openapi-typescript ${page.url.origin}/api/openapi.json -o schema.d.ts`,
  );

  const scalarCustomCss = `
		.scalar-api-reference {
			--scalar-background-1: var(--color-bg);
			--scalar-background-2: var(--color-surface);
			--scalar-background-3: var(--color-bg);
			--scalar-color-1: var(--color-text);
			--scalar-color-2: var(--color-text-muted);
			--scalar-color-3: var(--color-text-muted);
			--scalar-color-accent: var(--color-accent);
			--scalar-font: 'Lora', serif;
			--scalar-border-color: var(--color-border-soft);
		}
	`;

  /** Remove endpoints tagged "private" from the OpenAPI spec before display. */
  function filterSchema(schema: Record<string, unknown>): Record<string, unknown> {
    const paths = schema.paths as Record<string, Record<string, Record<string, unknown>>>;
    const filtered: typeof paths = {};
    for (const [path, methods] of Object.entries(paths)) {
      const kept: Record<string, Record<string, unknown>> = {};
      for (const [method, details] of Object.entries(methods)) {
        const tags = (details.tags as string[]) ?? [];
        if (!tags.includes('private')) {
          kept[method] = details;
        }
      }
      if (Object.keys(kept).length > 0) {
        filtered[path] = kept;
      }
    }
    return { ...schema, paths: filtered };
  }

  $effect(() => {
    const controller = new AbortController();

    (async () => {
      let spec: Record<string, unknown>;
      try {
        const res = await fetch('/api/openapi.json', { signal: controller.signal });
        spec = filterSchema(await res.json());
      } catch {
        if (!controller.signal.aborted) {
          scalarError = 'Failed to load API reference. Please try refreshing the page.';
        }
        return;
      }

      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/@scalar/api-reference';
      script.onload = () => {
        // @ts-expect-error — Scalar loaded via CDN
        Scalar.createApiReference('#scalar-api-reference', {
          content: JSON.stringify(spec),
          theme: 'none',
          layout: 'modern',
          showSidebar: true,
          hideClientButton: true,
          customCss: scalarCustomCss,
        });
        scalarLoaded = true;
      };
      script.onerror = () => {
        scalarError = 'Failed to load API reference. Please try refreshing the page.';
      };
      document.head.appendChild(script);
    })();

    return () => {
      controller.abort();
    };
  });
</script>

<svelte:head>
  <title>{pageTitle('API')}</title>
</svelte:head>

<section class="hero">
  <h1>Open Data API</h1>
  <p>
    Catalog data is available through public APIs, subject to
    <a href="/licensing">licensing terms</a> that vary by source.
  </p>
</section>

<section class="developer-resources">
  <div class="resource-card">
    <h3>OpenAPI Spec</h3>
    <p>
      <a href="/api/openapi.json" target="_blank" rel="noopener external">Download</a> the raw OpenAPI
      3.1 specification to use with any compatible tooling.
    </p>
  </div>

  <div class="resource-card">
    <h3>TypeScript Types</h3>
    <p>Generate fully-typed API bindings in one command:</p>
    <pre><code>{typesCommand}</code></pre>
  </div>
</section>

<section class="api-reference-section">
  <h2>API Reference</h2>
  {#if scalarError}
    <p class="error-message">{scalarError}</p>
  {:else if !scalarLoaded}
    <p class="loading-message">Loading API reference…</p>
  {/if}
  <div id="scalar-api-reference"></div>
</section>

<style>
  .hero {
    margin-bottom: var(--size-8);
  }

  .hero h1 {
    font-size: var(--font-size-7);
    font-weight: 700;
    color: var(--color-text);
    margin-bottom: var(--size-3);
  }

  .hero p {
    font-size: var(--font-size-2);
    color: var(--color-text-muted);
    line-height: var(--font-lineheight-3);
    max-width: 48rem;
  }

  h2 {
    font-size: var(--font-size-3);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-4);
  }

  .api-reference-section {
    margin-bottom: var(--size-8);
  }

  .loading-message,
  .error-message {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    padding: var(--size-6) 0;
  }

  .error-message {
    color: var(--color-error-text);
  }

  .developer-resources {
    margin-bottom: var(--size-8);
  }

  .resource-card {
    background-color: var(--color-surface);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    padding: var(--size-4) var(--size-5);
    margin-bottom: var(--size-4);
  }

  .resource-card h3 {
    font-size: var(--font-size-2);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-2);
  }

  .resource-card p {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    margin-bottom: var(--size-2);
    line-height: var(--font-lineheight-3);
  }

  pre {
    background-color: var(--color-bg);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    padding: var(--size-3) var(--size-4);
    overflow-x: auto;
    font-size: var(--font-size-0);
    font-family: var(--font-mono);
  }

  code {
    font-family: var(--font-mono);
  }
</style>
