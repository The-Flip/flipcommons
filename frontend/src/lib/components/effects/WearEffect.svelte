<script lang="ts">
  let {
    type,
    corner,
    earSize,
    creaseAngle,
    creasePos,
  }: {
    type: 'dog-ear' | 'crease' | 'torn-corner';
    corner: 'tr' | 'tl' | 'br' | 'bl';
    earSize: number;
    creaseAngle: number;
    creasePos: number;
  } = $props();
</script>

{#if type === 'dog-ear'}
  <div class="dog-ear dog-ear--{corner}" style:--ear-size="{earSize}rem"></div>
{:else if type === 'crease'}
  <div
    class="crease"
    style:--crease-angle="{creaseAngle}deg"
    style:--crease-pos="{creasePos}%"
  ></div>
{:else if type === 'torn-corner'}
  <div class="torn-corner torn-corner--{corner}"></div>
{/if}

<style>
  /* =============================================
	   DOG-EAR: folded corner triangle
	   ============================================= */
  .dog-ear {
    position: absolute;
    width: var(--ear-size, 1.4rem);
    height: var(--ear-size, 1.4rem);
    pointer-events: none;
    z-index: 4;
    overflow: hidden;
  }

  .dog-ear::before {
    content: '';
    position: absolute;
    width: 100%;
    height: 100%;
    background: linear-gradient(
      135deg,
      rgba(0, 0, 0, 0.06) 0%,
      rgba(0, 0, 0, 0.02) 50%,
      var(--color-card-fold-light) 50%,
      var(--color-card-fold-dark) 100%
    );
  }

  .dog-ear::after {
    content: '';
    position: absolute;
    width: 140%;
    height: 140%;
    background: radial-gradient(ellipse at center, rgba(0, 0, 0, 0.1) 0%, transparent 70%);
  }

  /* Position each corner variant */
  .dog-ear--tr {
    top: 0;
    right: 0;
  }
  .dog-ear--tr::before {
    background: linear-gradient(
      225deg,
      rgba(0, 0, 0, 0.06) 0%,
      rgba(0, 0, 0, 0.02) 50%,
      var(--color-card-fold-light) 50%,
      var(--color-card-fold-dark) 100%
    );
  }
  .dog-ear--tr::after {
    bottom: -20%;
    left: -20%;
  }

  .dog-ear--tl {
    top: 0;
    left: 0;
  }
  .dog-ear--tl::before {
    background: linear-gradient(
      135deg,
      rgba(0, 0, 0, 0.06) 0%,
      rgba(0, 0, 0, 0.02) 50%,
      var(--color-card-fold-light) 50%,
      var(--color-card-fold-dark) 100%
    );
  }
  .dog-ear--tl::after {
    bottom: -20%;
    right: -20%;
  }

  .dog-ear--br {
    bottom: 0;
    right: 0;
  }
  .dog-ear--br::before {
    background: linear-gradient(
      135deg,
      var(--color-card-fold-light) 0%,
      var(--color-card-fold-dark) 50%,
      rgba(0, 0, 0, 0.02) 50%,
      rgba(0, 0, 0, 0.06) 100%
    );
  }
  .dog-ear--br::after {
    top: -20%;
    left: -20%;
  }

  .dog-ear--bl {
    bottom: 0;
    left: 0;
  }
  .dog-ear--bl::before {
    background: linear-gradient(
      45deg,
      rgba(0, 0, 0, 0.06) 0%,
      rgba(0, 0, 0, 0.02) 50%,
      var(--color-card-fold-light) 50%,
      var(--color-card-fold-dark) 100%
    );
  }
  .dog-ear--bl::after {
    top: -20%;
    right: -20%;
  }

  /* =============================================
	   CREASE: diagonal fold line across the card
	   ============================================= */
  .crease {
    position: absolute;
    left: 0;
    right: 0;
    top: var(--crease-pos, 50%);
    height: 2px;
    pointer-events: none;
    z-index: 4;
    transform: rotate(var(--crease-angle, 0deg));
    transform-origin: center;
  }

  .crease::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(
      to right,
      transparent 0%,
      rgba(0, 0, 0, 0.08) 15%,
      rgba(0, 0, 0, 0.12) 50%,
      rgba(0, 0, 0, 0.08) 85%,
      transparent 100%
    );
  }

  .crease::after {
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    top: -1px;
    height: 1px;
    background: linear-gradient(
      to right,
      transparent 0%,
      rgba(255, 255, 255, 0.15) 20%,
      rgba(255, 255, 255, 0.25) 50%,
      rgba(255, 255, 255, 0.15) 80%,
      transparent 100%
    );
  }

  /* =============================================
	   TORN CORNER: ragged missing piece
	   ============================================= */
  .torn-corner {
    position: absolute;
    width: 1.6rem;
    height: 1.6rem;
    pointer-events: none;
    z-index: 4;
    overflow: hidden;
  }

  .torn-corner::before {
    content: '';
    position: absolute;
    width: 100%;
    height: 100%;
    background: var(--color-bg);
    clip-path: polygon(
      0% 0%,
      100% 0%,
      85% 15%,
      95% 30%,
      75% 45%,
      90% 55%,
      70% 70%,
      80% 85%,
      60% 100%,
      0% 100%
    );
  }

  .torn-corner::after {
    content: '';
    position: absolute;
    width: 100%;
    height: 100%;
    background: linear-gradient(135deg, transparent 40%, rgba(0, 0, 0, 0.1) 60%, transparent 80%);
  }

  .torn-corner--tr {
    top: 0;
    right: 0;
    transform: rotate(90deg);
  }

  .torn-corner--tl {
    top: 0;
    left: 0;
  }

  .torn-corner--br {
    bottom: 0;
    right: 0;
    transform: rotate(180deg);
  }

  .torn-corner--bl {
    bottom: 0;
    left: 0;
    transform: rotate(270deg);
  }

  /* ---- Dark mode ---- */
  @media (prefers-color-scheme: dark) {
    .dog-ear--tr::before,
    .dog-ear--tl::before,
    .dog-ear--br::before,
    .dog-ear--bl::before {
      filter: brightness(0.5);
    }

    .torn-corner::before {
      background: var(--color-bg);
    }

    .crease::before {
      background: linear-gradient(
        to right,
        transparent 0%,
        rgba(0, 0, 0, 0.15) 15%,
        rgba(0, 0, 0, 0.2) 50%,
        rgba(0, 0, 0, 0.15) 85%,
        transparent 100%
      );
    }
    .crease::after {
      background: linear-gradient(
        to right,
        transparent 0%,
        rgba(255, 255, 255, 0.06) 20%,
        rgba(255, 255, 255, 0.1) 50%,
        rgba(255, 255, 255, 0.06) 80%,
        transparent 100%
      );
    }
  }
</style>
