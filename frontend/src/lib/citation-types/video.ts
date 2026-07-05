/**
 * Frontend behavior for the video citation type: the timestamp grammar mirror.
 *
 * A UX-only mirror of the backend grammar in
 * `backend/apps/citation/citation_types/video.py` — the backend stays
 * authoritative on every write path; this exists so the locator stage can
 * validate inline and show the canonical form before submit. Keep the two in
 * lockstep (accepted forms, canonical formatting, the 100-hour cap).
 */
import type { CitationTypeFrontend } from './frontend-types';

/** The deliberate cap on a start time — mirrors MAX_START_TIME_SECONDS. */
export const MAX_START_TIME_SECONDS = 100 * 3600;

const BARE_SECONDS_RE = /^\d+$/;
const COLON_RE = /^(\d+)(?::(\d{1,2}))?:(\d{1,2})$/;
const UNITS_RE = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/i;

/** Parse a start-time input (`95`, `1:35`, `1:02:03`, `1h2m3s`) into whole seconds, or null. */
export function parseStartTime(raw: string): number | null {
  const text = raw.trim();
  if (!text) return null;
  const seconds = parseBareOrColon(text) ?? parseUnits(text);
  if (seconds === null || seconds > MAX_START_TIME_SECONDS) return null;
  return seconds;
}

function parseBareOrColon(text: string): number | null {
  if (BARE_SECONDS_RE.test(text)) return parseInt(text, 10);
  const m = COLON_RE.exec(text);
  if (!m) return null;
  const [, lead, mid, tail] = m;
  if (mid === undefined) {
    const minutes = parseInt(lead, 10);
    const secs = parseInt(tail, 10);
    if (secs > 59) return null;
    return minutes * 60 + secs;
  }
  const hours = parseInt(lead, 10);
  const minutes = parseInt(mid, 10);
  const secs = parseInt(tail, 10);
  if (minutes > 59 || secs > 59) return null;
  return hours * 3600 + minutes * 60 + secs;
}

function parseUnits(text: string): number | null {
  const m = UNITS_RE.exec(text);
  if (!m || (m[1] === undefined && m[2] === undefined && m[3] === undefined)) return null;
  const hours = m[1] ? parseInt(m[1], 10) : 0;
  const minutes = m[2] ? parseInt(m[2], 10) : 0;
  const secs = m[3] ? parseInt(m[3], 10) : 0;
  return hours * 3600 + minutes * 60 + secs;
}

/** Format whole seconds as the canonical human-readable start time (`0:57`, `1:35`, `1:02:03`). */
export function formatStartTime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  const two = (n: number) => String(n).padStart(2, '0');
  if (hours) return `${hours}:${two(minutes)}:${two(secs)}`;
  return `${minutes}:${two(secs)}`;
}

export const videoType: CitationTypeFrontend = {
  normalizeLocator(raw: string): string | null {
    const seconds = parseStartTime(raw);
    return seconds === null ? null : formatStartTime(seconds);
  },
};
