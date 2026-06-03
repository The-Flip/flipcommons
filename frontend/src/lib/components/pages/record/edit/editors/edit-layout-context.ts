import { getContext, setContext } from 'svelte';

type EditLayoutContext = {
  setDirty: (dirty: boolean) => void;
};

const EDIT_LAYOUT_CONTEXT_KEY = Symbol('editLayout');

export function setEditLayoutContext(context: EditLayoutContext): void {
  setContext(EDIT_LAYOUT_CONTEXT_KEY, context);
}

export function getEditLayoutContext(): EditLayoutContext {
  const context = getContext<EditLayoutContext | undefined>(EDIT_LAYOUT_CONTEXT_KEY);
  if (!context) {
    throw new Error('editLayout context missing — must be rendered inside an edit section layout');
  }
  return context;
}
