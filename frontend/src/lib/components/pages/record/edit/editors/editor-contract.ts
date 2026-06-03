import type { SaveMeta } from './save-claims-shared';

export type EditorDirtyChange = (dirty: boolean) => void;

export type SectionEditorHandle = {
  save(meta?: SaveMeta): Promise<void>;
  isDirty(): boolean;
};

export interface SectionEditorProps<TData> {
  initialData: TData;
  slug: string;
  onsaved: () => void;
  onerror: (message: string) => void;
  ondirtychange?: EditorDirtyChange;
}
