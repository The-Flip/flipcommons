// Shared by `+page.server.ts` (registers the dependency on initial load)
// and `+page.svelte` (calls invalidate(...) on the hourly refresh tick).
// Lives outside `*.server.ts` so the client may import it.
export const ADMIN_DASHBOARD_DEPEND_KEY = 'app:admin-dashboard';
