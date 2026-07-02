/**
 * Client-side mirror of backend `validate_username_format` (apps/accounts/usernames.py).
 *
 * Used as a pre-check to gate the debounced /check call — don't burn a network
 * round-trip on input that fails locally. The server remains source of truth;
 * this mirror is an optimization, not a guard.
 */

export const USERNAME_MIN_LEN = 3;
export const USERNAME_MAX_LEN = 20;

export type UsernameFormatRejectReason =
  'too_short' | 'too_long' | 'bad_charset' | 'leading_or_trailing_hyphen' | 'consecutive_hyphens';
// `reserved` is server-side only (the reserved list lives in Python). Local
// pre-check never returns "reserved" or "taken".

const ALLOWED_CHARS_RE = /^[a-z0-9-]+$/;

/**
 * Client-side format pre-check. Returns a reason for the *committed* errors
 * (wrong character, hyphen shape, oversize).
 */
export function checkUsernameFormat(value: string): UsernameFormatRejectReason | null {
  if (value.length > USERNAME_MAX_LEN) return 'too_long';
  if (!ALLOWED_CHARS_RE.test(value)) return 'bad_charset';
  if (value.startsWith('-') || value.endsWith('-')) return 'leading_or_trailing_hyphen';
  if (value.includes('--')) return 'consecutive_hyphens';
  return null;
}
