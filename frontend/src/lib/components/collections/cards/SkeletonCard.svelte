<div class="skeleton-card">
  <div class="skeleton-img shimmer"></div>
  <div class="skeleton-body">
    <div class="skeleton-title shimmer"></div>
    <div class="skeleton-meta shimmer"></div>
  </div>
</div>

<style>
  @keyframes shimmer {
    0% {
      background-position: -200% 0;
    }
    100% {
      background-position: 200% 0;
    }
  }

  .shimmer {
    background: linear-gradient(
      90deg,
      var(--color-border-soft) 25%,
      var(--color-surface) 50%,
      var(--color-border-soft) 75%
    );
    background-size: 200% 100%;
    animation: shimmer 1.5s ease-in-out infinite;
    border-radius: var(--radius-1);
  }

  .skeleton-card {
    display: flex;
    flex-direction: column;
    background-color: var(--color-surface);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    overflow: hidden;
  }

  .skeleton-img {
    width: 100%;
    height: 8rem;
  }

  .skeleton-body {
    padding: var(--size-3);
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .skeleton-title {
    height: 1rem;
    width: 70%;
  }

  .skeleton-meta {
    height: 0.75rem;
    width: 45%;
  }
</style>
