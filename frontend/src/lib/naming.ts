/**
 * Catalog name normalization for collision detection.
 *
 * Used across record types (Title, MachineModel, Person, …) whenever a name
 * needs to be folded to a collision-comparison form. Same rule everywhere:
 * two inputs that normalize to the same string are considered the same name.
 *
 * This implementation MUST stay in lockstep with the Python copy at
 * `backend/apps/catalog/naming.py`. The shared case table lives in
 * `naming.test.ts` and `test_naming.py`; update all four when the rule
 * changes.
 *
 * Rule (applied in order):
 *  1. Unicode NFKC, then lowercase.
 *  2. Replace any run of characters that is not an ASCII letter or digit
 *     with a single space.
 *  3. Strip leading articles: "the", "a", "an".
 *  4. Collapse runs of whitespace and strip edges.
 *
 * The empty string is a legal output, indicating a name with no
 * name-bearing characters.
 */

const NON_ALNUM_RUN = /[^0-9a-z]+/g;
const LEADING_ARTICLE = /^(?:the|a|an)\s+/;
const WHITESPACE_RUN = /\s+/g;

export function normalizeCatalogName(raw: string): string {
  const folded = raw.normalize('NFKC').toLowerCase();
  const spaced = folded.replace(NON_ALNUM_RUN, ' ').trim();
  const dearticled = spaced.replace(LEADING_ARTICLE, '');
  return dearticled.replace(WHITESPACE_RUN, ' ').trim();
}
