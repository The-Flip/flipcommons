<script lang="ts">
  import Modal from './Modal.svelte';

  let active = $state<'a' | 'b' | null>(null);

  function openA() {
    active = 'a';
  }
  function openB() {
    active = 'b';
  }
  function close() {
    active = null;
  }
</script>

<button type="button" onclick={openA}>Open A</button>
<button type="button" onclick={openB}>Open B</button>

<Modal title="Modal A" open={active === 'a'} onclose={close}>
  <p>A body</p>
</Modal>
<Modal title="Modal B" open={active === 'b'} onclose={close}>
  <p>B body</p>
</Modal>
