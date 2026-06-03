<script lang="ts" module>
  export type CardDistressType = 'none' | 'dog-ear' | 'crease' | 'torn-corner';
  export type CardDistressCorner = 'tr' | 'tl' | 'br' | 'bl';
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import CoffeeStain from '$lib/components/effects/CoffeeStain.svelte';
  import WearEffect from '$lib/components/effects/WearEffect.svelte';

  let {
    href,
    title,
    thumbnailUrl = null,
    distressType = undefined,
    distressCorner = undefined,
    distressEarSize = undefined,
    distressCreaseAngle = undefined,
    distressCreasePos = undefined,
    children = undefined,
  }: {
    href: string;
    title: string;
    thumbnailUrl?: string | null;
    distressType?: CardDistressType;
    distressCorner?: CardDistressCorner;
    distressEarSize?: number;
    distressCreaseAngle?: number;
    distressCreasePos?: number;
    children?: Snippet;
  } = $props();

  const rand = (min: number, max: number) => Math.random() * (max - min) + min;
  const randInt = (max: number) => Math.floor(Math.random() * max);

  // Film grain filter (unique per card)
  const grainId = `grain-${crypto.randomUUID()}`;
  const grainSeed = randInt(1000);

  // Stain seeds and positions
  const stain1 = { seed: randInt(1000), x: `${rand(-5, 55)}%`, y: `${rand(-5, 55)}%` };
  const stain2 = { seed: randInt(1000), x: `${rand(-5, 65)}%`, y: `${rand(-5, 65)}%` };

  // Photo aging — all declarative, no action needed
  const rotation = `${rand(-3, 3)}deg`;
  const sepia = `${rand(0.3, 0.7)}`;
  const brightness = `${rand(0.9, 1.05)}`;
  const contrast = `${rand(0.85, 0.95)}`;
  const saturate = `${rand(0.6, 0.85)}`;
  const paperYellow = `${rand(0.03, 0.08)}`;

  // Wear effect: ~40% of cards get one
  const wearRoll = Math.random();
  const randomWearType: CardDistressType =
    wearRoll < 0.6
      ? 'none'
      : wearRoll < 0.73
        ? 'dog-ear'
        : wearRoll < 0.87
          ? 'crease'
          : 'torn-corner';

  const corners = ['tr', 'tl', 'br', 'bl'] as const;
  const randomWearCorner = corners[randInt(corners.length)];
  const randomCreaseAngle = -25 + Math.random() * 50;
  const randomCreasePos = 30 + Math.random() * 40;
  const randomEarSize = 1 + Math.random() * 0.8;

  const wearType = $derived(distressType ?? randomWearType);
  const wearCorner = $derived(distressCorner ?? randomWearCorner);
  const creaseAngle = $derived(distressCreaseAngle ?? randomCreaseAngle);
  const creasePos = $derived(distressCreasePos ?? randomCreasePos);
  const earSize = $derived(distressEarSize ?? randomEarSize);
</script>

<!-- Film grain filter definition -->
<svg class="svg-filters" aria-hidden="true">
  <defs>
    <filter id={grainId} x="0%" y="0%" width="100%" height="100%">
      <feTurbulence
        type="fractalNoise"
        baseFrequency="0.7"
        numOctaves="3"
        seed={grainSeed}
        result="grain"
      />
      <feColorMatrix type="saturate" values="0" in="grain" result="grainMono" />
      <feBlend in="SourceGraphic" in2="grainMono" mode="multiply" />
    </filter>
  </defs>
</svg>

<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- href is pre-resolved by caller -->
<a
  {href}
  class="card"
  data-wear-type={wearType}
  data-wear-corner={wearCorner}
  style:--rotation={rotation}
  style:--sepia={sepia}
  style:--brightness={brightness}
  style:--contrast={contrast}
  style:--saturate={saturate}
  style:--paper-yellow={paperYellow}
  style:--grain-url="url(#{grainId})"
  style:--ear-size="{earSize}rem"
>
  <div class="card-photo">
    {#if thumbnailUrl}
      <img src={thumbnailUrl} alt="" class="card-img" loading="lazy" />
    {:else}
      <div class="card-img-placeholder"></div>
    {/if}
  </div>
  <div class="card-body">
    <h3 class="card-title">{title}</h3>
    {#if children}
      {@render children()}
    {/if}
  </div>

  <CoffeeStain
    seed={stain1.seed}
    x={stain1.x}
    y={stain1.y}
    width="40%"
    height="40%"
    opacity={0.15}
    blur={3}
    threshold="0 0 0 0 0 0 0.6 0.8"
  />
  <CoffeeStain
    seed={stain2.seed}
    frequency={0.045}
    octaves={4}
    x={stain2.x}
    y={stain2.y}
    width="30%"
    height="30%"
    opacity={0.1}
    blur={4}
    threshold="0 0 0 0 0 0 0 0.5"
    color="rgb(100, 65, 20)"
  />

  {#if wearType !== 'none'}
    <WearEffect type={wearType} corner={wearCorner} {earSize} {creaseAngle} {creasePos} />
  {/if}
</a>

<style>
  .svg-filters {
    position: absolute;
    width: 0;
    height: 0;
    overflow: hidden;
    pointer-events: none;
  }

  .card {
    position: relative;
    display: flex;
    flex-direction: column;
    background-color: var(--color-card-bg);
    border: none;
    border-radius: 2px;
    overflow: hidden;
    text-decoration: none;
    color: inherit;
    padding: 0.6rem 0.6rem 1.6rem;
    transform: rotate(var(--rotation, 0deg));
    box-shadow: var(--shadow-card);
    transition:
      transform 0.2s ease,
      box-shadow 0.2s ease;
  }

  /* Yellowed paper tint overlay. Hue is the themed --color-card-tint
     (dimmer in dark mode); alpha is randomized per-card via --paper-yellow
     so individual cards age unevenly. */
  .card::before {
    content: '';
    position: absolute;
    inset: 0;
    background: color-mix(
      in srgb,
      var(--color-card-tint) calc(var(--paper-yellow, 0.05) * 100%),
      transparent
    );
    pointer-events: none;
    border-radius: 2px;
    z-index: 2;
  }

  .card:hover {
    transform: rotate(0deg) scale(1.03);
    box-shadow: var(--shadow-popover);
    z-index: 1;
  }

  .card-photo {
    position: relative;
    overflow: hidden;
    border-radius: 1px;
  }

  /* When a dog-ear sits over a top corner of the photo, clip the photo's
     corner along the fold's diagonal so the photo edge follows the fold
     instead of running straight past it. The dog-ear box (var(--ear-size))
     is anchored to .card's outer edge, which is 0.6rem outside .card-photo
     (.card has 0.6rem horizontal/top padding). The fold line crosses
     .card-photo only when ear-size > 1.1rem; below that, the calc()s go
     negative and the clip is a no-op. The 1.1rem (instead of 1.2rem, the
     exact geometric inset) overshoots the fold diagonal by ~0.1rem so
     sub-pixel anti-aliasing on both the clip and the gradient's 50% stop
     can't leak a sliver of photo at the fold. The overshoot lands inside
     the fold's opaque half and is invisibly covered. */
  .card[data-wear-type='dog-ear'][data-wear-corner='tl'] .card-photo {
    clip-path: polygon(
      calc(var(--ear-size) - 1.1rem) 0,
      100% 0,
      100% 100%,
      0 100%,
      0 calc(var(--ear-size) - 1.1rem)
    );
  }

  .card[data-wear-type='dog-ear'][data-wear-corner='tr'] .card-photo {
    clip-path: polygon(
      0 0,
      calc(100% + 1.1rem - var(--ear-size)) 0,
      100% calc(var(--ear-size) - 1.1rem),
      100% 100%,
      0 100%
    );
  }

  .card-img {
    width: 100%;
    height: 8rem;
    object-fit: cover;
    filter: var(--grain-url) sepia(var(--sepia, 0.5)) brightness(var(--brightness, 0.95))
      contrast(var(--contrast, 0.9)) saturate(var(--saturate, 0.7));
  }

  .card-img-placeholder {
    width: 100%;
    height: 8rem;
    background-color: var(--color-card-bg-dim);
  }

  .card-body {
    padding: var(--size-3) 0 0;
  }

  .card-title {
    font-size: var(--font-size-2);
    font-weight: 600;
    color: var(--color-card-text);
    margin-bottom: var(--size-1);
  }

  /* ---- Dark mode ---- */
  @media (prefers-color-scheme: dark) {
    .card-img {
      filter: var(--grain-url) sepia(var(--sepia, 0.5))
        brightness(calc(var(--brightness, 0.95) * 0.85)) contrast(var(--contrast, 0.9))
        saturate(var(--saturate, 0.7));
    }
  }
</style>
