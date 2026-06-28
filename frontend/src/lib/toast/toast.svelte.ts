/**
 * Lightweight toast queue used for non-error feedback after create / edit /
 * delete actions. One `ToastHost` instance reads this store; any module can
 * push messages.
 *
 * Design notes:
 *   - Queue with a soft cap (MAX_VISIBLE); FIFO dismiss when exceeded so a
 *     runaway caller can't wall the screen.
 *   - `persistUntilNav` marks a toast as surviving exactly one client
 *     navigation, then auto-clearing on the next — lets a delete page show
 *     an undo toast on `/titles` after `goto('/titles')`.
 *   - Each push returns a handle so the caller can `update()` the text
 *     after an async action resolves ("Deleted X" → "Restored X").
 *
 * Errors should surface inline in forms, not here. Toast is a "happy path
 * told you so" channel — anything the user needs to react to belongs in
 * the form.
 */

const MAX_VISIBLE = 3;
const DEFAULT_DWELL_MS = 5_000;

type ToastVariant = 'success' | 'info' | 'error';

type ToastAction = {
  label: string;
  onAction: () => void | Promise<void>;
};

export type ToastOptions = {
  variant?: ToastVariant;
  action?: ToastAction;
  dwellMs?: number;
  href?: string;
  persistUntilNav?: boolean;
};

export type ToastMessage = {
  id: string;
  text: string;
  variant: ToastVariant;
  action?: ToastAction;
  dwellMs: number;
  href?: string;
  persistUntilNav: boolean;
  /** True once a navigation has happened while this toast was alive. */
  _navSeen: boolean;
};

export type ToastHandle = {
  id: string;
  update(text: string, opts?: Omit<ToastOptions, 'persistUntilNav'>): void;
  dismiss(): void;
};

let counter = 0;
const messages = $state<ToastMessage[]>([]);

function nextId(): string {
  counter += 1;
  return `toast-${counter}`;
}

function push(text: string, opts: ToastOptions = {}): ToastHandle {
  const id = nextId();
  const msg: ToastMessage = {
    id,
    text,
    variant: opts.variant ?? 'info',
    action: opts.action,
    dwellMs: opts.dwellMs ?? DEFAULT_DWELL_MS,
    href: opts.href,
    persistUntilNav: opts.persistUntilNav ?? false,
    _navSeen: false,
  };
  messages.push(msg);
  // Drop oldest when over the cap — a toast isn't critical UI.
  while (messages.length > MAX_VISIBLE) {
    messages.shift();
  }
  return {
    id,
    update(text, nextOpts = {}) {
      const m = messages.find((x) => x.id === id);
      if (!m) return;
      m.text = text;
      if (nextOpts.action !== undefined) m.action = nextOpts.action;
      if (nextOpts.href !== undefined) m.href = nextOpts.href;
      if (nextOpts.variant !== undefined) m.variant = nextOpts.variant;
      if (nextOpts.dwellMs !== undefined) m.dwellMs = nextOpts.dwellMs;
      m._navSeen = false;
    },
    dismiss() {
      const ix = messages.findIndex((x) => x.id === id);
      if (ix >= 0) messages.splice(ix, 1);
    },
  };
}

export const toast = {
  get messages(): ReadonlyArray<ToastMessage> {
    return messages;
  },
  success(text: string, opts: Omit<ToastOptions, 'variant'> = {}): ToastHandle {
    return push(text, { ...opts, variant: 'success' });
  },
  info(text: string, opts: Omit<ToastOptions, 'variant'> = {}): ToastHandle {
    return push(text, { ...opts, variant: 'info' });
  },
  error(text: string, opts: Omit<ToastOptions, 'variant'> = {}): ToastHandle {
    // Errors stay until dismissed — don't let them auto-hide before the
    // user has a chance to read them.
    return push(text, { ...opts, variant: 'error', dwellMs: opts.dwellMs ?? Infinity });
  },
  dismiss(id: string): void {
    const ix = messages.findIndex((x) => x.id === id);
    if (ix >= 0) messages.splice(ix, 1);
  },
  /**
   * Called by ToastHost on every SvelteKit navigation. Toasts with
   * `persistUntilNav` survive the first nav and clear on the second; all
   * others pass through untouched.
   */
  onNavigation(): void {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const m = messages[i];
      if (!m.persistUntilNav) continue;
      if (m._navSeen) {
        messages.splice(i, 1);
      } else {
        m._navSeen = true;
      }
    }
  },
  /** Test helper — drain the queue. Not for runtime use. */
  _resetForTest(): void {
    messages.length = 0;
    counter = 0;
  },
};
