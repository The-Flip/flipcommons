<!--
@component
Test fixture for SectionEditHarness: mounts it with a fake editor and a stub
edit-layout context so the dom test can drive Save-gating, the cancel guard,
the immediate (non-form) branch and the post-save remount without a real route.
The `context-dirty` probe reflects what the harness pushes to the nav-lock.
-->
<script lang="ts">
  import SectionEditHarness from './SectionEditHarness.svelte';
  import FakeEditor from './SectionEditorHost.fake-editor.svelte';
  import { setEditLayoutContext } from './editors/edit-layout-context';

  let {
    usesSectionEditorForm = true,
    onsaved,
  }: {
    usesSectionEditorForm?: boolean;
    onsaved?: () => void | Promise<void>;
  } = $props();

  let contextDirty = $state(false);
  setEditLayoutContext({
    setDirty: (dirty: boolean) => (contextDirty = dirty),
  });

  let section = $derived({
    key: 'overview',
    showCitation: false,
    showMixedEditWarning: false,
    usesSectionEditorForm,
  });
</script>

<p data-testid="context-dirty">{String(contextDirty)}</p>

<SectionEditHarness {section} detailHref="/records/1" {onsaved}>
  {#snippet editor({ ref, onsaved: onEditorSaved, onerror })}
    <FakeEditor bind:this={ref.current} label="overview" onsaved={onEditorSaved} {onerror} />
  {/snippet}
  {#snippet immediateEditor()}
    <div data-testid="immediate-body">immediate body</div>
  {/snippet}
</SectionEditHarness>
