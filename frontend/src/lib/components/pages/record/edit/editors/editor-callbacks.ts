import type { SectionEditorHandle } from './editor-contract';
import type { EditSectionDef } from './edit-section-def';

/**
 * The section fields a full-page/modal edit host renders on. Derived from
 * {@link EditSectionDef} so the field types track the source. A `false`
 * `usesSectionEditorForm` marks an immediate (non-form) section.
 */
export type HarnessSection = Pick<
  EditSectionDef<string>,
  'key' | 'showCitation' | 'showMixedEditWarning' | 'usesSectionEditorForm'
>;

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
