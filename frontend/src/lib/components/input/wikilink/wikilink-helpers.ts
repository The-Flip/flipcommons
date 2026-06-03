/**
 * Pure helper functions for wikilink autocomplete.
 *
 * Extracted from MarkdownTextArea so they can be tested without DOM/Svelte.
 */

/**
 * Detect whether a `[[` trigger was just typed at the cursor position.
 * Returns the start index of `[[` if found, or -1.
 */
export function detectTrigger(text: string, cursorPos: number): number {
  if (cursorPos >= 2 && text.substring(cursorPos - 2, cursorPos) === '[[') {
    return cursorPos - 2;
  }
  return -1;
}

/**
 * Build the link text to insert: `[[type:ref]]`.
 */
export function formatLinkText(typeName: string, ref: string): string {
  return `[[${typeName}:${ref}]]`;
}

/**
 * Compute the result of splicing a link into textarea content.
 *
 * Replaces everything from `triggerStart` to `cursorPos` (the `[[` plus
 * any additional characters typed while the dropdown was open) with the
 * link text.
 *
 * Returns the new text and where the cursor should be placed.
 */
export function spliceLink(
  text: string,
  triggerStart: number,
  cursorPos: number,
  linkText: string,
): { newText: string; newCursorPos: number } {
  const before = text.substring(0, triggerStart);
  const after = text.substring(cursorPos);
  return {
    newText: before + linkText + after,
    newCursorPos: triggerStart + linkText.length,
  };
}
