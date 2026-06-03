/**
 * Pure markdown editing shortcuts for textareas.
 *
 * Each function takes textarea state (value, selectionStart, selectionEnd)
 * and returns a result descriptor, or null if no action should be taken.
 * The caller applies the result via execCommand for undo support.
 */

export type EditResult = {
  replaceStart: number;
  replaceEnd: number;
  replacement: string;
  selectionStart: number;
  selectionEnd: number;
};

// ---------------------------------------------------------------------------
// Bold / Italic toggle (Cmd+B, Cmd+I)
// ---------------------------------------------------------------------------

export function toggleMarker(
  value: string,
  start: number,
  end: number,
  marker: string,
): EditResult {
  const len = marker.length;

  if (start !== end) {
    // Selection exists — check if already wrapped
    const before = value.substring(start - len, start);
    const after = value.substring(end, end + len);

    if (before === marker && after === marker) {
      // Unwrap: remove markers around selection
      return {
        replaceStart: start - len,
        replaceEnd: end + len,
        replacement: value.substring(start, end),
        selectionStart: start - len,
        selectionEnd: end - len,
      };
    }

    // Wrap selection
    const selected = value.substring(start, end);
    return {
      replaceStart: start,
      replaceEnd: end,
      replacement: marker + selected + marker,
      selectionStart: start + len,
      selectionEnd: end + len,
    };
  }

  // No selection — insert empty marker pair with cursor between
  return {
    replaceStart: start,
    replaceEnd: start,
    replacement: marker + marker,
    selectionStart: start + len,
    selectionEnd: start + len,
  };
}

// ---------------------------------------------------------------------------
// Smart character wrapping (`, *, _)
// ---------------------------------------------------------------------------

const WRAP_CHARS: Record<string, [string, string]> = {
  '`': ['`', '`'],
  '*': ['*', '*'],
  _: ['_', '_'],
};

export function wrapSelection(
  value: string,
  start: number,
  end: number,
  char: string,
): EditResult | null {
  if (start === end) return null; // No selection — normal typing

  const pair = WRAP_CHARS[char];
  if (!pair) return null;

  const [open, close] = pair;
  const selected = value.substring(start, end);
  return {
    replaceStart: start,
    replaceEnd: end,
    replacement: open + selected + close,
    selectionStart: start + open.length,
    selectionEnd: end + open.length,
  };
}

// ---------------------------------------------------------------------------
// Link insertion (Cmd+K)
// ---------------------------------------------------------------------------

export function insertLink(value: string, start: number, end: number): EditResult {
  if (start !== end) {
    // Has selection — wrap as link text, select "url" placeholder
    const selected = value.substring(start, end);
    const replacement = `[${selected}](url)`;
    return {
      replaceStart: start,
      replaceEnd: end,
      replacement,
      selectionStart: start + selected.length + 3, // after ](
      selectionEnd: start + selected.length + 6, // after url
    };
  }

  // No selection — insert empty link, select "url"
  const replacement = '[](url)';
  return {
    replaceStart: start,
    replaceEnd: start,
    replacement,
    selectionStart: start + 3,
    selectionEnd: start + 6,
  };
}

// ---------------------------------------------------------------------------
// Paste URL over selection
// ---------------------------------------------------------------------------

export function pasteLink(
  value: string,
  start: number,
  end: number,
  pastedText: string,
): EditResult | null {
  if (start === end) return null;
  if (!/^https?:\/\//.test(pastedText)) return null;

  const selected = value.substring(start, end);
  const replacement = `[${selected}](${pastedText})`;
  return {
    replaceStart: start,
    replaceEnd: end,
    replacement,
    selectionStart: start,
    selectionEnd: start + replacement.length,
  };
}

// ---------------------------------------------------------------------------
// Tab indentation
// ---------------------------------------------------------------------------

const INDENT = '  ';

export function indentLines(
  value: string,
  start: number,
  end: number,
  dedent: boolean,
): EditResult {
  // Find the start of the first selected line
  const lineStart = value.lastIndexOf('\n', start - 1) + 1;
  // Find the end of the last selected line
  let lineEnd = value.indexOf('\n', end);
  if (lineEnd === -1) lineEnd = value.length;

  const block = value.substring(lineStart, lineEnd);
  const lines = block.split('\n');

  let selectionDelta = 0; // change to start position (first line only)
  let totalDelta = 0;

  const newLines = lines.map((line, i) => {
    if (dedent) {
      let removed = 0;
      if (line.startsWith(INDENT)) {
        removed = INDENT.length;
      } else if (line.startsWith(' ')) {
        removed = 1;
      }
      if (i === 0) selectionDelta = -removed;
      totalDelta -= removed;
      return line.substring(removed);
    } else {
      if (i === 0) selectionDelta = INDENT.length;
      totalDelta += INDENT.length;
      return INDENT + line;
    }
  });

  return {
    replaceStart: lineStart,
    replaceEnd: lineEnd,
    replacement: newLines.join('\n'),
    selectionStart: Math.max(lineStart, start + selectionDelta),
    selectionEnd: end + totalDelta,
  };
}

// ---------------------------------------------------------------------------
// List enter continuation
// ---------------------------------------------------------------------------

const TASK_LIST_RE = /^((?:>\s*)*\s*)([-*+]|\d+\.)\s+\[([^\]]*)\]\s?(.*)$/;
const PLAIN_LIST_RE = /^((?:>\s*)*\s*)([-*+]|\d+\.)\s(.*)$/;

function nextMarker(marker: string): string {
  const num = parseInt(marker, 10);
  if (!isNaN(num)) return `${num + 1}.`;
  return marker;
}

export function listEnter(value: string, start: number, end: number): EditResult | null {
  if (start !== end) return null; // Has selection — normal Enter

  // Find the current line
  const lineStart = value.lastIndexOf('\n', start - 1) + 1;
  const lineEnd = value.indexOf('\n', start);
  const fullLine = value.substring(lineStart, lineEnd === -1 ? value.length : lineEnd);
  const beforeCursor = fullLine.substring(0, start - lineStart);
  const afterCursor = fullLine.substring(start - lineStart);

  // Try task list first
  let match = TASK_LIST_RE.exec(fullLine);
  if (match) {
    const [, prefix, marker] = match;
    const contentBeforeCursor = beforeCursor.replace(TASK_LIST_RE, '$4');
    const isEmpty = !contentBeforeCursor.trim() && !afterCursor.trim();

    if (isEmpty) {
      // Empty item — remove it, leave just the prefix
      return {
        replaceStart: lineStart,
        replaceEnd: lineEnd === -1 ? value.length : lineEnd,
        replacement: prefix,
        selectionStart: lineStart + prefix.length,
        selectionEnd: lineStart + prefix.length,
      };
    }

    const newItem = `\n${prefix}${nextMarker(marker)} [ ] ${afterCursor}`;
    return {
      replaceStart: start,
      replaceEnd: start + afterCursor.length,
      replacement: newItem,
      selectionStart: start + newItem.length,
      selectionEnd: start + newItem.length,
    };
  }

  // Try plain list
  match = PLAIN_LIST_RE.exec(fullLine);
  if (match) {
    const [, prefix, marker] = match;
    const contentBeforeCursor = beforeCursor.replace(PLAIN_LIST_RE, '$3');
    const isEmpty = !contentBeforeCursor.trim() && !afterCursor.trim();

    if (isEmpty) {
      return {
        replaceStart: lineStart,
        replaceEnd: lineEnd === -1 ? value.length : lineEnd,
        replacement: prefix,
        selectionStart: lineStart + prefix.length,
        selectionEnd: lineStart + prefix.length,
      };
    }

    const newItem = `\n${prefix}${nextMarker(marker)} ${afterCursor}`;
    return {
      replaceStart: start,
      replaceEnd: start + afterCursor.length,
      replacement: newItem,
      selectionStart: start + newItem.length,
      selectionEnd: start + newItem.length,
    };
  }

  return null; // Not a list line — normal Enter
}

// ---------------------------------------------------------------------------
// List toggle (toolbar buttons)
// ---------------------------------------------------------------------------

export function toggleList(
  value: string,
  start: number,
  end: number,
  ordered: boolean,
): EditResult {
  // Find the full block of selected lines
  const lineStart = value.lastIndexOf('\n', start - 1) + 1;
  let lineEnd = value.indexOf('\n', end);
  if (lineEnd === -1) lineEnd = value.length;

  const block = value.substring(lineStart, lineEnd);
  const lines = block.split('\n');

  // Check if ALL lines already have the target prefix
  const bulletRe = /^[-*+] /;
  const orderedRe = /^\d+\. /;
  const targetRe = ordered ? orderedRe : bulletRe;

  const singleLine = lines.length === 1;
  const allHaveTarget = lines.every((l) => targetRe.test(l) || (!singleLine && !l.trim()));

  let totalDelta = 0;
  let firstLineDelta = 0;
  let contentLineIndex = 0;

  const newLines = lines.map((line, i) => {
    if (!singleLine && !line.trim()) return line; // leave interior blank lines alone

    if (allHaveTarget) {
      // Remove the prefix
      const match = line.match(targetRe);
      if (match) {
        const removed = match[0].length;
        if (i === 0) firstLineDelta = -removed;
        totalDelta -= removed;
        return line.substring(removed);
      }
      return line;
    }

    // Strip any existing list prefix first, then add the target
    let stripped = line;
    const existingBullet = line.match(bulletRe);
    const existingOrdered = line.match(orderedRe);
    if (existingBullet) {
      stripped = line.substring(existingBullet[0].length);
    } else if (existingOrdered) {
      stripped = line.substring(existingOrdered[0].length);
    }

    contentLineIndex++;
    const prefix = ordered ? `${contentLineIndex}. ` : '- ';
    const result = prefix + stripped;
    const delta = result.length - line.length;
    if (i === 0) firstLineDelta = delta;
    totalDelta += delta;
    return result;
  });

  return {
    replaceStart: lineStart,
    replaceEnd: lineEnd,
    replacement: newLines.join('\n'),
    selectionStart: Math.max(lineStart, start + firstLineDelta),
    selectionEnd: end + totalDelta,
  };
}

// ---------------------------------------------------------------------------
// Apply result to textarea (undo-safe)
// ---------------------------------------------------------------------------

export function applyResult(textarea: HTMLTextAreaElement, result: EditResult): void {
  textarea.focus();
  textarea.setSelectionRange(result.replaceStart, result.replaceEnd);

  if (!document.execCommand('insertText', false, result.replacement)) {
    const before = textarea.value.substring(0, result.replaceStart);
    const after = textarea.value.substring(result.replaceEnd);
    textarea.value = before + result.replacement + after;
  }

  textarea.setSelectionRange(result.selectionStart, result.selectionEnd);
}
