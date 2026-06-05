/**
 * Kiosk cookie helpers. The write/read *helpers* are browser-only (they
 * touch `document.cookie`); do not call them from server load functions
 * (which read cookies via SvelteKit's `cookies` event helper). The
 * `MODE_COOKIE_*` name/value string constants carry no DOM access and are
 * safe to import server-side (e.g. the SSR `cacheControlHandle` hook).
 *
 * Three cookies coordinate kiosk mode:
 * - `mode=kiosk` — gates kiosk-mode behavior site-wide.
 * - `kioskConfigId=<id>` — which DB-backed config the device displays;
 *   read by `/kiosk/+page.server.ts` to fetch the page model.
 * - `kioskIdleSeconds=<n>` — denormalized copy of the config's
 *   `idle_seconds`. KioskMode runs on every route so it can return a
 *   wandered-off device to /kiosk on idle; reading this from a cookie
 *   avoids a server load on every navigation just to learn one integer.
 *   Kept in sync at two write sites: list-page "Enter Kiosk Mode" (uses
 *   the config's known idle_seconds) and editor "Save" (refreshes the
 *   cookie when the value changed). Stale-cookie risk is "operator
 *   edited idle_seconds from another device" — for a single-device
 *   museum kiosk this is fine, and re-picking the config from the
 *   device fixes it.
 */

export const MODE_COOKIE_NAME = 'mode';
export const MODE_COOKIE_VALUE = 'kiosk';
const CONFIG_ID_COOKIE_NAME = 'kioskConfigId';
const IDLE_SECONDS_COOKIE_NAME = 'kioskIdleSeconds';
const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365; // 1 year

export const DEFAULT_IDLE_SECONDS = 180;
export const HOOK_MAX_LENGTH = 80;

function cookieFlags(): string {
  const secure =
    typeof location !== 'undefined' && location.protocol === 'https:' ? '; Secure' : '';
  return `Path=/; SameSite=Lax${secure}`;
}

/**
 * Set the three kiosk-mode cookies. Call from the `/kiosk/edit` list page
 * when an operator picks a config ("Enter Kiosk Mode") and from the editor
 * when "Save" changes `idle_seconds`. `idleSeconds` is denormalized into a
 * cookie so `KioskMode.svelte` can read it without a server load on every
 * navigation; see the file-header comment.
 */
export function setKioskCookies(configId: number, idleSeconds: number): void {
  const flags = cookieFlags();
  document.cookie = `${MODE_COOKIE_NAME}=${MODE_COOKIE_VALUE}; ${flags}; Max-Age=${COOKIE_MAX_AGE_SECONDS}`;
  document.cookie = `${CONFIG_ID_COOKIE_NAME}=${configId}; ${flags}; Max-Age=${COOKIE_MAX_AGE_SECONDS}`;
  document.cookie = `${IDLE_SECONDS_COOKIE_NAME}=${idleSeconds}; ${flags}; Max-Age=${COOKIE_MAX_AGE_SECONDS}`;
}

export function clearKioskCookies(): void {
  const flags = cookieFlags();
  document.cookie = `${MODE_COOKIE_NAME}=; ${flags}; Max-Age=0`;
  document.cookie = `${CONFIG_ID_COOKIE_NAME}=; ${flags}; Max-Age=0`;
  document.cookie = `${IDLE_SECONDS_COOKIE_NAME}=; ${flags}; Max-Age=0`;
}

export function isKioskCookieSet(): boolean {
  if (typeof document === 'undefined') return false;
  return new RegExp(`(?:^|;\\s*)${MODE_COOKIE_NAME}=${MODE_COOKIE_VALUE}(?:;|$)`).test(
    document.cookie,
  );
}

/**
 * Browser-only. Reads `kioskConfigId` from `document.cookie`. The server
 * (e.g. `/kiosk/+page.server.ts`) reads it via SvelteKit's
 * `cookies.get('kioskConfigId')` directly — no helper needed there.
 *
 * Returns the parsed positive integer id, or null when the cookie is
 * absent or malformed.
 */
export function getKioskConfigIdFromCookie(): number | null {
  return parsePositiveIntCookie(CONFIG_ID_COOKIE_NAME);
}

/**
 * Browser-only. Reads `kioskIdleSeconds` from `document.cookie`. Used by
 * `KioskMode.svelte`. Returns null if absent/malformed; callers fall back
 * to `DEFAULT_IDLE_SECONDS`.
 */
export function getKioskIdleSecondsFromCookie(): number | null {
  return parsePositiveIntCookie(IDLE_SECONDS_COOKIE_NAME);
}

function parsePositiveIntCookie(name: string): number | null {
  if (typeof document === 'undefined') return null;
  const match = new RegExp(`(?:^|;\\s*)${name}=([^;]+)`).exec(document.cookie);
  if (!match) return null;
  const n = Number(match[1]);
  return Number.isInteger(n) && n > 0 ? n : null;
}
