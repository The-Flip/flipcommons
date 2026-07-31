# TypeScript Development

Conventions for TypeScript in the frontend.

For Svelte-specific patterns see [Svelte.md](Svelte.md).

## Use JSDoc for declaration comments

When a named declaration warrants a comment — function, class, type, interface, exported constant, even an object property — use `/** */` so editors surface it in hover tooltips and signature help. Single-line `//` comments don't appear in IDE popups.

```ts
/** Resolve an href that may be internal or external; falls back to the raw string. */
export function resolveHref(href: string): string {
  // ...
}

/** Maximum length of a username, mirrored from the backend validator. */
export const USERNAME_MAX_LENGTH = 32;
```

The bar for writing a comment is unchanged — most declarations don't need one. But when you do write one, use the format that shows up where readers look. Inline `//` comments inside a function body are still fine; they're for the next person editing the code, not for callers.

Also ensure the comment says the right things as mandated in [CodeComments.md](CodeComments.md).
