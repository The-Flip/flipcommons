<script lang="ts">
  import SectionEditorHost from './SectionEditorHost.svelte';
  import FakeEditor from './SectionEditorHost.fake-editor.svelte';
  import type { EditSectionMenuItem } from '$lib/components/layout/page/edit-section-menu';

  type SectionKey = 'overview' | 'features' | 'media';

  const sections = [
    {
      key: 'overview' as const,
      label: 'Overview',
      showCitation: false,
      showMixedEditWarning: false,
      usesSectionEditorForm: true,
    },
    {
      key: 'features' as const,
      label: 'Features',
      showCitation: true,
      showMixedEditWarning: true,
      usesSectionEditorForm: true,
      saveBehavior: 'error' as const,
    },
    {
      key: 'media' as const,
      label: 'Media',
      showCitation: false,
      showMixedEditWarning: false,
      usesSectionEditorForm: false,
    },
  ];

  let editing = $state<SectionKey | null>(null);

  const switcherItems: EditSectionMenuItem[] = sections.map((s) => ({
    key: s.key,
    label: s.label,
    onclick: () => (editing = s.key),
  }));
</script>

<button type="button" onclick={() => (editing = 'overview')}>Open overview</button>
<button type="button" onclick={() => (editing = 'features')}>Open features</button>
<button type="button" onclick={() => (editing = 'media')}>Open media</button>
<button type="button" onclick={() => (editing = null)}>Reset editing</button>

<p data-testid="editing-key">{editing ?? 'none'}</p>

<SectionEditorHost bind:editingKey={editing} {sections} {switcherItems}>
  {#snippet editor(key, callbacks)}
    {#if key === 'overview'}
      <FakeEditor
        bind:this={callbacks.ref.current}
        label="overview"
        onsaved={callbacks.onsaved}
        onerror={callbacks.onerror}
        ondirtychange={callbacks.ondirtychange}
      />
    {:else if key === 'features'}
      <FakeEditor
        bind:this={callbacks.ref.current}
        label="features"
        saveBehavior="error"
        onsaved={callbacks.onsaved}
        onerror={callbacks.onerror}
        ondirtychange={callbacks.ondirtychange}
      />
    {/if}
  {/snippet}

  {#snippet immediateEditor()}
    <div data-testid="immediate-editor">media editor body</div>
  {/snippet}
</SectionEditorHost>
