import type { SaveMeta } from './save-claims-shared';

export type SectionEditorHandle = {
  save(meta?: SaveMeta): Promise<void>;
  /** Reactive: whether the editor holds unsaved changes. The single dirty
   *  channel — read it inside a reactive context (e.g. `$derived`) so the
   *  host chrome (Save button, section nav-lock, cancel guard) tracks it. */
  readonly dirty: boolean;
};

export interface SectionEditorProps<TData> {
  initialData: TData;
  slug: string;
  onsaved: () => void;
  onerror: (message: string) => void;
}
