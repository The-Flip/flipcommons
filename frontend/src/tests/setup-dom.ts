// DOM test setup — loaded only by the "dom" vitest project.

import '@testing-library/jest-dom/vitest';

// jsdom does not implement scrollIntoView
Element.prototype.scrollIntoView ??= function () {};

// jsdom stubs execCommand but it doesn't work. Override unconditionally
// to return false, which triggers MarkdownTextArea's manual fallback path.
document.execCommand = () => false;

// jsdom doesn't implement ResizeObserver.
window.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof window.ResizeObserver;

// jsdom doesn't implement matchMedia. `createBelowBreakpointFlag` reads it at
// module-eval time for a correct first-paint value, so any test that
// touches a detail layout needs it defined.
window.matchMedia ??= (() => ({
  matches: false,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
  media: '',
  onchange: null,
})) as unknown as typeof window.matchMedia;

// In browser-transformed modules SvelteKit compiles `$env/dynamic/public` to
// `export const env = globalThis.__sveltekit_dev.env;` — a global only the
// real client runtime defines, so importing it here would otherwise throw.
// Provide an empty env; tests that need values mock the module instead.
(globalThis as { __sveltekit_dev?: { env: Record<string, string> } }).__sveltekit_dev ??= {
  env: {},
};
