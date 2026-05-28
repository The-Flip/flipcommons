#!/usr/bin/env node
// Rename generated schema-name references in frontend/src after backend Python
// schema classes are renamed and `make codegen` regenerates schema.d.ts.
//
// Scope: word-boundary substitution of `OldName -> NewName` for each entry
// in rename-table.json, excluding client.ts. For .svelte files only the
// <script> block contents are touched (markup never references generated
// types, and short tokens like `Ref` could appear in attributes/strings).
//
// Idempotent: a fully-renamed tree produces zero rewrites.

import { execSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(HERE, '..', '..');
const REPO = resolve(FRONTEND, '..');
const SRC = resolve(FRONTEND, 'src');
const CLIENT_PATH = resolve(SRC, 'lib/api/client.ts');
const SCHEMA_DTS = resolve(SRC, 'lib/api/schema.d.ts');
const RENAME_TABLE = resolve(HERE, 'rename-table.json');

function loadRenameMap(namesFilter) {
  const full = JSON.parse(readFileSync(RENAME_TABLE, 'utf8'));
  if (!namesFilter) return full;
  const missing = namesFilter.filter((n) => !(n in full));
  if (missing.length) {
    console.error(`--names entries not in rename table: ${missing.join(', ')}`);
    process.exit(1);
  }
  return Object.fromEntries(namesFilter.map((k) => [k, full[k]]));
}

function listSourceFiles() {
  const out = execSync('git ls-files frontend/src', { cwd: REPO, encoding: 'utf8' });
  return out
    .split('\n')
    .filter(Boolean)
    .map((p) => resolve(REPO, p))
    .filter((p) => /\.(ts|svelte)$/.test(p))
    .filter((p) => p !== CLIENT_PATH && p !== SCHEMA_DTS);
}

function rewriteText(text, renameMap) {
  // Single combined regex: `\b(OldA|OldB|...)\b`. One pass over the source,
  // alternation handles all entries. Word boundary keeps `Ref` from matching
  // inside `LocationAncestorRef`. Sort by length desc so longer names match
  // first (defensive — alternation is left-greedy regardless, but explicit).
  const keys = Object.keys(renameMap).sort((a, b) => b.length - a.length);
  if (keys.length === 0) return text;
  const escaped = keys.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp(`\\b(${escaped.join('|')})\\b`, 'g');
  return text.replace(pattern, (m) => renameMap[m] ?? m);
}

const SCRIPT_BLOCK_RE = /(<script\b[^>]*>)([\s\S]*?)(<\/script>)/g;

function rewriteSvelte(text, renameMap) {
  return text.replace(SCRIPT_BLOCK_RE, (_m, open, body, close) => {
    return open + rewriteText(body, renameMap) + close;
  });
}

function rewriteFile(path, renameMap) {
  const original = readFileSync(path, 'utf8');
  const next = path.endsWith('.svelte')
    ? rewriteSvelte(original, renameMap)
    : rewriteText(original, renameMap);
  if (next === original) return false;
  writeFileSync(path, next, 'utf8');
  return true;
}

function main() {
  const { values } = parseArgs({
    options: {
      names: { type: 'string' },
      'dry-run': { type: 'boolean', default: false },
    },
  });
  const namesFilter = values.names
    ? values.names
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
    : null;
  const renameMap = loadRenameMap(namesFilter);

  console.log(`Renaming ${Object.keys(renameMap).length} schema(s) in frontend/src`);
  for (const [old, neu] of Object.entries(renameMap)) {
    console.log(`  ${old} -> ${neu}`);
  }

  const files = listSourceFiles();
  let changed = 0;
  for (const f of files) {
    if (values['dry-run']) {
      const original = readFileSync(f, 'utf8');
      const next = f.endsWith('.svelte')
        ? rewriteSvelte(original, renameMap)
        : rewriteText(original, renameMap);
      if (next !== original) {
        changed += 1;
        console.log(`  would rewrite ${f.slice(REPO.length + 1)}`);
      }
    } else if (rewriteFile(f, renameMap)) {
      changed += 1;
    }
  }
  const verb = values['dry-run'] ? 'Would rewrite' : 'Rewrote';
  console.log(`${verb} ${changed} file(s).`);
}

main();
