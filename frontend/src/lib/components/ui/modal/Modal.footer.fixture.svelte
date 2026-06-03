<script lang="ts">
  import Modal from './Modal.svelte';

  let open = $state(false);

  function openModal() {
    open = true;
  }

  function closeModal() {
    open = false;
  }
</script>

<button type="button" onclick={openModal}>Open modal</button>

<Modal title="Edit Media" {open} onclose={closeModal}>
  <label>
    Caption
    <input type="text" value="Current media caption" />
  </label>

  {#snippet footer()}
    <button type="button">Upload</button>
  {/snippet}
</Modal>
