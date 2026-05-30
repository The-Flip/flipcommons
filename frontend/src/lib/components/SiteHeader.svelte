<script lang="ts">
  import type { Snippet } from 'svelte';
  import { resolve } from '$app/paths';
  import CoffeeStain from './effects/CoffeeStain.svelte';
  import Wordmark from './Wordmark.svelte';

  let { children }: { children?: Snippet } = $props();

  const randInt = (max: number) => Math.floor(Math.random() * max);

  const stainSeed1 = randInt(1000);
  const stainSeed2 = randInt(1000);
  const stainSeed3 = randInt(1000);

  const tornId = `tear-${crypto.randomUUID()}`;
  const tornSeed = randInt(1000);
</script>

<svg class="svg-filters" aria-hidden="true">
  <defs>
    <filter id={tornId} x="-2%" y="-2%" width="104%" height="120%">
      <feTurbulence
        type="turbulence"
        baseFrequency="0.06 0.02"
        numOctaves="4"
        seed={tornSeed}
        result="warp"
      />
      <feDisplacementMap in="SourceGraphic" in2="warp" scale="6" yChannelSelector="R" />
    </filter>
  </defs>
</svg>

<header class="site-header">
  <div class="header-inner">
    <a href={resolve('/')} class="site-title"><Wordmark /></a>
    {@render children?.()}
  </div>

  <div class="header-stains">
    <CoffeeStain
      seed={stainSeed1}
      frequency={0.03}
      opacity={0.12}
      blur={4}
      threshold="0 0 0 0 0 0 0.5 0.7"
      x="0%"
      width="40%"
    />
    <CoffeeStain
      seed={stainSeed2}
      frequency={0.04}
      octaves={4}
      opacity={0.08}
      blur={5}
      threshold="0 0 0 0 0 0 0 0.4"
      color="rgb(100, 65, 20)"
      x="30%"
      width="40%"
    />
    <CoffeeStain
      seed={stainSeed3}
      frequency={0.025}
      opacity={0.1}
      blur={3}
      threshold="0 0 0 0 0 0.4 0.6 0.8"
      color="rgb(130, 90, 35)"
      x="60%"
      width="40%"
    />
  </div>

  <div class="torn-edge" style:filter="url(#{tornId})"></div>
</header>

<style>
  .svg-filters {
    position: absolute;
    width: 0;
    height: 0;
    overflow: hidden;
    pointer-events: none;
  }

  .site-header {
    position: sticky;
    top: 0;
    z-index: var(--z-header);
    background-color: var(--color-header-bg);
    border-bottom: none;
  }

  /* Subtle paper grain via repeating gradient */
  .site-header::before {
    content: '';
    position: absolute;
    inset: 0;
    /* Paper-grain texture: stops are intentionally near-transparent black,
       not themed colors. Promoting these to tokens would add indirection
       without enabling any real retheming. */
    /* stylelint-disable function-disallowed-list */
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0, 0, 0, 0.01) 2px,
      rgba(0, 0, 0, 0.01) 4px
    );
    /* stylelint-enable function-disallowed-list */
    pointer-events: none;
    z-index: 1;
  }

  /* Torn paper bottom edge — shares background color via token */
  .torn-edge {
    position: absolute;
    bottom: -4px;
    left: 0;
    right: 0;
    height: 8px;
    background: var(--color-header-bg);
    pointer-events: none;
    z-index: 3;
  }

  .header-inner {
    position: relative;
    max-width: 72rem;
    margin: 0 auto;
    padding: var(--size-3) var(--size-5);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--size-4);
    z-index: 4;
  }

  /* Wordmark fills from `currentColor`, so `color` here recolors the mark.
     --color-logo flips red→cyan between light and dark in app.css. */
  .site-title {
    display: inline-flex;
    align-items: center;
    height: clamp(2.25rem, 1.8rem + 1.6vw, 3rem);
    color: var(--color-logo);
    text-decoration: none;
  }

  .site-title:hover {
    opacity: 0.85;
  }

  .header-stains {
    display: var(--header-stains-display, none);
    position: absolute;
    inset: 0;
    pointer-events: none;
  }

  @media (prefers-color-scheme: light) {
    .header-stains {
      display: var(--header-stains-display, block);
    }
  }

  /* ---- Dark mode ---- */
  @media (prefers-color-scheme: dark) {
    /* Paper grain is a light-mode-only flourish; in dark mode the
       low-contrast stops vanish into the bg anyway, so skip the layer. */
    .site-header::before {
      background: none;
    }
  }
</style>
