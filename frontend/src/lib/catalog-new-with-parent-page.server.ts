import { error } from '@sveltejs/kit';
import type { ApiClient } from '$lib/api/client';
import { createServerClient } from '$lib/api/server';
import { requireCapability } from '$lib/require-capability.server';

interface LoadCreateWithParentOptions<P extends { slug: string; name: string }> {
  fetch: typeof fetch;
  url: URL;
  request: Request;
  // Fetch the parent list. Kept as a closure so the openapi-typed endpoint
  // literal lives at the call site and keeps full path/response typing.
  fetchParents: (client: ApiClient) => Promise<{ data?: P[]; response: Response }>;
  // Bail when `?parent=` is absent or unmatched. Kept as a closure so the
  // typed `resolve()` route literal lives at the call site. Returns `never`
  // because `redirect()` does — callers write `() => redirect(302, ...)`.
  onMissingParent: () => never;
  // Surfaced verbatim if the parent list fetch fails (e.g. "Failed to load
  // display types.").
  errorLabel: string;
}

interface CreateWithParentData {
  initialName: string;
  parentSlug: string;
  parentName: string;
}

// Shared load for a catalog `new/+page.server.ts` whose entity hangs off a
// parent taxonomy (display-subtypes under display-types, technology-
// subgenerations under technology-generations). Gates on `catalog.create`,
// requires a `?parent=` slug present in the parent list, and returns the form
// seed plus the resolved parent name/slug. Entities created without a parent
// use the simpler [[catalog-new-page]] re-export instead.
export async function loadCreateWithParent<P extends { slug: string; name: string }>({
  fetch,
  url,
  request,
  fetchParents,
  onMissingParent,
  errorLabel,
}: LoadCreateWithParentOptions<P>): Promise<CreateWithParentData> {
  await requireCapability({ fetch, url, request, activity: 'catalog.create' });

  const parentSlug = url.searchParams.get('parent');
  if (!parentSlug) {
    return onMissingParent();
  }

  const client = createServerClient(fetch, url, request);
  const { data, response } = await fetchParents(client);
  if (!data) {
    throw error(response.status || 500, errorLabel);
  }

  const parent = data.find((p) => p.slug === parentSlug);
  if (!parent) {
    return onMissingParent();
  }

  return {
    initialName: url.searchParams.get('name') ?? '',
    parentSlug: parent.slug,
    parentName: parent.name,
  };
}
