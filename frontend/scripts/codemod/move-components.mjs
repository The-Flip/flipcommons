#!/usr/bin/env node
// Move top-level component files in frontend/src/lib/components/ into a
// subfolder and rewrite the affected import specifiers.
//
//   node scripts/codemod/move-components.mjs --to <folder> Name1 Name2 ...
//
// Each NAME is a file stem under lib/components/ (no extension). All
// co-located files sharing that stem move together — e.g. `ClaimValue`
// pulls ClaimValue.svelte, ClaimValue.dom.test.ts, ClaimValue.fixture.svelte.
//
// Touched files only. A file is rewritten iff it is itself moving OR it
// imports a moved file. Files that reference nothing in the move set are
// never opened. Within a touched file, EVERY import is normalized to the
// project convention (same-folder -> relative `./x`; cross-folder under
// src/lib -> `$lib/...`), so editing a file's imports leaves all of them
// consistent — not just the moved specifier.
//
// Specifiers are resolved against each file's NEW directory, so the rule is
// uniform: compare the target's post-move dir to the file's post-move dir.
// Equal -> relative; different (and under src/lib) -> $lib. Extension
// presence is preserved (the filename never changes, only its directory).
//
// Targets that resolve outside src/lib, and bare/$app/$env specifiers, are
// left untouched. Verify with `pnpm svelte-check` afterwards — an unresolved
// import is a check error, so the gate proves the rewrite.

import { execSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(HERE, '..', '..');
const REPO = resolve(FRONTEND, '..');
const SRC = resolve(FRONTEND, 'src');
const LIB = resolve(SRC, 'lib');
const COMPONENTS = resolve(LIB, 'components');

const { values, positionals } = parseArgs({
  options: { to: { type: 'string' } },
  allowPositionals: true,
});

const folder = values.to;
const stems = positionals;
if (!folder || stems.length === 0) {
  console.error('usage: move-components.mjs --to <folder> Stem1 Stem2 ...');
  process.exit(1);
}

const targetDir = resolve(COMPONENTS, folder);

// Resolve each stem to the set of co-located files that share it.
function filesForStem(stem) {
  const matches = readdirSync(COMPONENTS, { withFileTypes: true })
    .filter((e) => e.isFile())
    .map((e) => e.name)
    .filter((name) => name === stem || name.startsWith(`${stem}.`));
  if (matches.length === 0) {
    console.error(`no files under lib/components/ for stem "${stem}"`);
    process.exit(1);
  }
  return matches;
}

// oldAbs -> newAbs
const moveMap = new Map();
for (const stem of stems) {
  for (const name of filesForStem(stem)) {
    moveMap.set(resolve(COMPONENTS, name), resolve(targetDir, name));
  }
}
const movedOldAbs = new Set(moveMap.keys());

// Resolve a relative/$lib specifier to an absolute path sans extension, or
// null for bare / $app / $env specifiers we never rewrite.
function resolveBase(spec, fromDir) {
  if (spec.startsWith('$lib/')) return resolve(LIB, spec.slice('$lib/'.length));
  if (spec.startsWith('.')) return resolve(fromDir, spec);
  return null;
}

// Does a specifier point at a moved file? Try the extensions Vite would.
function resolveToMoved(base) {
  if (!base) return false;
  for (const cand of [base, `${base}.svelte`, `${base}.ts`, `${base}.js`]) {
    if (movedOldAbs.has(cand)) return true;
  }
  return false;
}

const isUnderLib = (dir) => dir === LIB || dir.startsWith(`${LIB}/`);
const posix = (p) => p.split('\\').join('/');

const SPEC_RE = /(\bfrom\b|\bimport\b|\bvi\.mock\b|\brequire\b)(\s*\(?\s*)(['"])([^'"]+)\3/g;

// Post-move directory of a file/target: moved entries land in targetDir,
// everything else keeps its current directory.
const newDirOf = (oldAbs) => (movedOldAbs.has(oldAbs) ? targetDir : dirname(oldAbs));

function fileImportsMoved(text, fromDir) {
  SPEC_RE.lastIndex = 0;
  let m;
  while ((m = SPEC_RE.exec(text))) {
    if (resolveToMoved(resolveBase(m[4], fromDir))) return true;
  }
  return false;
}

function rewrite(fileAbs, text) {
  const fromDir = dirname(fileAbs);
  const fileNewDir = newDirOf(fileAbs);
  return text.replace(SPEC_RE, (whole, kw, sep, quote, spec) => {
    const base = resolveBase(spec, fromDir);
    if (!base) return whole; // bare / $app / $env

    const lastSeg = spec.split('/').pop();
    // A moved target's post-move file path is targetDir/<lastSeg>; for a
    // non-moved target the base path (hence its dir) is unchanged.
    const targetNewDir = resolveToMoved(base) ? targetDir : dirname(base);

    if (targetNewDir === fileNewDir) return `${kw}${sep}${quote}./${lastSeg}${quote}`;
    if (isUnderLib(targetNewDir)) {
      const relDir = posix(relative(LIB, targetNewDir));
      const path = [relDir, lastSeg].filter(Boolean).join('/');
      return `${kw}${sep}${quote}$lib/${path}${quote}`;
    }
    // Cross-folder, target outside src/lib (e.g. a route-private `_components/`
    // home): not $lib-addressable, so emit a relative path from the importer's
    // post-move dir. Restricted to moved targets so non-moved outside-lib
    // imports are left exactly as they were.
    if (resolveToMoved(base)) {
      const relDir = posix(relative(fileNewDir, targetNewDir));
      const rel = relDir.startsWith('.') ? relDir : `./${relDir}`;
      return `${kw}${sep}${quote}${rel}/${lastSeg}${quote}`;
    }
    return whole; // cross-folder but outside src/lib — not $lib-addressable
  });
}

// Rewrite every touched source file in place (still at old locations).
const tracked = execSync('git ls-files frontend/src', { cwd: REPO, encoding: 'utf8' })
  .split('\n')
  .filter((p) => /\.(ts|svelte)$/.test(p))
  .map((p) => resolve(REPO, p));

let changed = 0;
for (const fileAbs of tracked) {
  const text = readFileSync(fileAbs, 'utf8');
  const touched = movedOldAbs.has(fileAbs) || fileImportsMoved(text, dirname(fileAbs));
  if (!touched) continue;
  const next = rewrite(fileAbs, text);
  if (next !== text) {
    writeFileSync(fileAbs, next);
    changed += 1;
  }
}

// Physically move the files.
if (!existsSync(targetDir)) mkdirSync(targetDir, { recursive: true });
for (const [oldAbs, newAbs] of moveMap) {
  execSync(`git mv ${JSON.stringify(oldAbs)} ${JSON.stringify(newAbs)}`, { cwd: REPO });
}

console.log(`moved ${moveMap.size} file(s) into ${folder}/, rewrote imports in ${changed} file(s)`);
