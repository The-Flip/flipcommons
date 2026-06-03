<script lang="ts">
  import FaIcon from '$lib/components/ui/FaIcon.svelte';
  import {
    faBold,
    faItalic,
    faLink,
    faListUl,
    faListOl,
    faBookmark,
  } from '@fortawesome/free-solid-svg-icons';

  let {
    onbold,
    onitalic,
    onlink,
    onbulletlist,
    onnumberedlist,
    oncitation,
  }: {
    onbold: () => void;
    onitalic: () => void;
    onlink: () => void;
    onbulletlist: () => void;
    onnumberedlist: () => void;
    oncitation: () => void;
  } = $props();

  const buttons = [
    { action: () => onbold(), icon: faBold, label: 'Bold' },
    { action: () => onitalic(), icon: faItalic, label: 'Italic' },
    { action: () => onbulletlist(), icon: faListUl, label: 'Bulleted list' },
    { action: () => onnumberedlist(), icon: faListOl, label: 'Numbered list' },
    { action: () => onlink(), icon: faLink, label: 'Link' },
    { action: () => oncitation(), icon: faBookmark, label: 'Citation' },
  ];
</script>

<div class="markdown-toolbar" role="toolbar" aria-label="Markdown formatting">
  {#each buttons as btn (btn.label)}
    <button
      type="button"
      aria-label={btn.label}
      onmousedown={(e) => e.preventDefault()}
      onclick={btn.action}
    >
      <FaIcon icon={btn.icon} size="0.8rem" />
      <span class="tooltip">{btn.label}</span>
    </button>
  {/each}
</div>

<style>
  .markdown-toolbar {
    display: flex;
    gap: 1px;
    padding: 3px;
    border: 1px solid var(--color-input-border);
    border-bottom: none;
    border-radius: var(--radius-2) var(--radius-2) 0 0;
    background: var(--color-surface);
  }

  button {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    padding: 0;
    border: 1px solid transparent;
    border-radius: var(--radius-1);
    background: var(--color-input-bg);
    color: var(--color-text-muted);
    cursor: pointer;
  }

  button:hover {
    border-color: var(--color-input-border);
    background: var(--color-input-focus-ring);
    color: var(--color-text);
  }

  .tooltip {
    position: absolute;
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%);
    margin-bottom: 4px;
    padding: 2px 6px;
    font-size: var(--font-size-0);
    white-space: nowrap;
    color: var(--color-text);
    background: var(--color-surface);
    border: 1px solid var(--color-input-border);
    border-radius: var(--radius-1);
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.1s;
  }

  button:hover .tooltip {
    opacity: 1;
  }
</style>
