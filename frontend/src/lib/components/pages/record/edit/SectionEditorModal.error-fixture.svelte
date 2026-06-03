<script lang="ts">
  import SectionEditorModal from './SectionEditorModal.svelte';

  let { error = '' }: { error?: string } = $props();
</script>

<SectionEditorModal heading="Overview" open={true} {error} onclose={() => {}} onsave={() => {}}>
  <p>Editor content</p>
</SectionEditorModal>
