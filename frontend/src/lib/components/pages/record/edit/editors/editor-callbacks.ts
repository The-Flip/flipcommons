import type { SectionEditorHandle } from './editor-contract';
import type { EditSectionDef } from './edit-section-def';

/**
 * The section fields a full-page/modal edit host renders on. Derived from
 * {@link EditSectionDef} so the field types track the source. `usesSectionEditorForm`
 * is optional because entities with no immediate (non-form) sections don't
 * declare it; a host treats absent as form-based and only an explicit `false`
 * as an immediate (non-form) section.
 */
export type HarnessSection = Pick<
  EditSectionDef<string>,
  'key' | 'showCitation' | 'showMixedEditWarning'
> & { usesSectionEditorForm?: boolean };

/**
 * Mutable box a host passes down so an editor snippet can publish its handle
 * back up via `bind:editorRef={callbacks.ref.current}`. A plain get/set box
 * (rather than a bindable prop) keeps the snippet boundary callback-only.
 */
export type EditorRefBox = { current: SectionEditorHandle | undefined };

/**
 * The wiring a section-edit host (page harness or modal) hands to the editor
 * snippet it renders: where to publish the handle, and the save/error callbacks.
 * Dirtiness flows the other way — the host reads `ref.current.dirty` reactively.
 */
export type EditorCallbacks = {
  ref: EditorRefBox;
  onsaved: () => void;
  onerror: (msg: string) => void;
};
