<script lang="ts">
  import Modal from './Modal.svelte';

  let open = $state(false);
  let closeCount = $state(0);

  function openModal() {
    open = true;
  }

  function closeModal() {
    closeCount++;
    open = false;
  }
</script>

<button type="button" onclick={openModal}>Open modal</button>

<Modal title="Edit Media" {open} onclose={closeModal}>
  <label>
    Caption
    <input type="text" value="Current media caption" />
  </label>
</Modal>

<p data-testid="close-count">{closeCount}</p>
