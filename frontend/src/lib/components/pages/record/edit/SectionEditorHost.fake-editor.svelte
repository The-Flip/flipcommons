<script lang="ts">
  let {
    label,
    saveBehavior = 'success',
    onsaved,
    onerror,
  }: {
    label: string;
    saveBehavior?: 'success' | 'error';
    onsaved: () => void;
    onerror: (msg: string) => void;
  } = $props();

  let dirty = $state(false);

  export { dirty };

  export async function save(): Promise<void> {
    if (saveBehavior === 'error') {
      onerror(`save failed for ${label}`);
      return;
    }
    dirty = false;
    onsaved();
  }

  function setDirty() {
    dirty = true;
  }

  function setClean() {
    dirty = false;
  }
</script>

<div data-testid="fake-editor">
  <p>fake editor: {label}</p>
  <button type="button" onclick={setDirty}>Make dirty</button>
  <button type="button" onclick={setClean}>Make clean</button>
</div>
