<script lang="ts">
  import { page } from '$app/state';
  import { resolve } from '$app/paths';
  import { faBars, faMagnifyingGlass } from '@fortawesome/free-solid-svg-icons';
  import FaIcon from '$lib/components/ui/FaIcon.svelte';
  import SiteHeader from './SiteHeader.svelte';
  import ActionMenu from '$lib/components/ui/menu/ActionMenu.svelte';
  import MenuItem from '$lib/components/ui/menu/MenuItem.svelte';
  import MenuSectionHeader from '$lib/components/ui/menu/MenuSectionHeader.svelte';
  import MenuDivider from '$lib/components/ui/menu/MenuDivider.svelte';
  import Avatar from '$lib/components/ui/Avatar.svelte';
  import { NARROW_BREAKPOINT } from '$lib/constants';
  import { auth } from '$lib/auth.svelte';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import { toast } from '$lib/toast/toast.svelte';

  const navItems = [
    { href: '/titles' as const, label: 'Titles' },
    { href: '/manufacturers' as const, label: 'Manufacturers' },
    { href: '/people' as const, label: 'People' },
  ];
  const changelogHref = '/changesets' as const;

  function isActive(href: string) {
    return page.url.pathname.startsWith(href);
  }

  // Mirrors the `(--breakpoint-narrow)` CSS tier below. Used to decide
  // whether the hamburger menu duplicates the primary nav items — tablet
  // keeps them in the bar, mobile collapses them in.
  const isMobileFlag = createBelowBreakpointFlag(NARROW_BREAKPOINT);
  const isMobile = $derived(isMobileFlag.current === true);

  $effect(() => {
    auth.load();
  });

  async function handleLogout() {
    await auth.logout();
    toast.success('Signed out');
  }

  function loginHref() {
    return `/api/auth/login/?next=${encodeURIComponent(page.url.pathname)}`;
  }

  const myContributionsHref = $derived(resolve(`/users/${auth.username}`));
  const myContributionsActive = $derived(isActive(`/users/${auth.username}`));

  // Single source of truth for "should the ADMIN menu section render at all?"
  // Both the desktop avatar menu and the mobile hamburger gate on this; a new
  // admin activity is added here once, not in two `||` chains.
  const hasAnyAdminSurface = $derived(
    auth.can('admin_area.view') || auth.can('kiosk.edit') || auth.can('django_admin.access'),
  );
</script>

{#snippet adminSection()}
  <MenuSectionHeader>admin</MenuSectionHeader>
  {#if auth.can('admin_area.view')}
    <MenuItem href={resolve('/admin/dashboard')} current={isActive('/admin')}>Stats</MenuItem>
  {/if}
  {#if auth.can('kiosk.edit')}
    <MenuItem href={resolve('/kiosk/edit')} current={isActive('/kiosk/edit')}>Kiosks</MenuItem>
    <MenuItem href={resolve('/style-lab')} current={isActive('/style-lab')}>Style Lab</MenuItem>
  {/if}
  {#if auth.can('django_admin.access')}
    <MenuItem href="/djadmin/" reload>Django Admin</MenuItem>
  {/if}
{/snippet}

{#snippet userSection()}
  <MenuSectionHeader>{auth.username}</MenuSectionHeader>
  <MenuItem href={myContributionsHref} current={myContributionsActive}>My Contributions</MenuItem>
  <MenuItem onclick={handleLogout}>Sign Out</MenuItem>
{/snippet}

<SiteHeader>
  <nav class="primary-nav" aria-label="Primary">
    {#each navItems as { href, label } (href)}
      <a href={resolve(href)} class="nav-link" class:active={isActive(href)}>
        {label}
      </a>
    {/each}
    <a
      href={resolve(changelogHref)}
      class="nav-link changelog-link"
      class:active={isActive(changelogHref)}
    >
      Changelog
    </a>
  </nav>

  <div class="header-actions">
    <a
      href={resolve('/search')}
      class="search-link"
      class:active={isActive('/search')}
      aria-label="Search"
    >
      <FaIcon icon={faMagnifyingGlass} size="1.1rem" />
    </a>
    {#if auth.loaded}
      <div class="desktop-account">
        {#if auth.isAuthenticated}
          <ActionMenu label="Account" variant="bare" ariaLabel="Account menu">
            {#snippet trigger()}
              <Avatar
                firstName={auth.firstName}
                lastName={auth.lastName}
                username={auth.username ?? ''}
              />
            {/snippet}
            {#if hasAnyAdminSurface}
              {@render adminSection()}
              <MenuDivider />
            {/if}
            {@render userSection()}
          </ActionMenu>
        {:else}
          <a href={loginHref()} class="auth-link" data-sveltekit-reload>Sign In</a>
        {/if}
      </div>
    {/if}

    <!-- Hamburger renders unconditionally so mobile users always have a way
         to reach Titles / Manufacturers / People, even before auth resolves.
         Auth-dependent sections inside skip rendering until auth.loaded. -->
    <div class="hamburger">
      <ActionMenu label="Menu" variant="bare" ariaLabel="Menu">
        {#snippet trigger()}
          <FaIcon icon={faBars} size="1.25rem" />
        {/snippet}
        {#if isMobile}
          {#each navItems as { href, label } (href)}
            <MenuItem href={resolve(href)} current={isActive(href)}>{label}</MenuItem>
          {/each}
          <MenuDivider />
        {/if}
        <MenuSectionHeader>activity</MenuSectionHeader>
        <MenuItem href={resolve(changelogHref)} current={isActive(changelogHref)}>
          Changelog
        </MenuItem>
        {#if auth.loaded}
          {#if hasAnyAdminSurface}
            <MenuDivider />
            {@render adminSection()}
          {/if}
          <MenuDivider />
          {#if auth.isAuthenticated}
            {@render userSection()}
          {:else}
            <MenuItem href={loginHref()} reload>Sign In</MenuItem>
          {/if}
        {/if}
      </ActionMenu>
    </div>
  </div>
</SiteHeader>

<style>
  .primary-nav {
    display: flex;
    gap: var(--size-5);
  }

  .nav-link {
    color: var(--color-header-text-muted);
    text-decoration: none;
    font-size: var(--font-size-2);
    font-weight: 500;
    padding: var(--size-1) 0;
    border-bottom: 2px solid transparent;
    transition:
      color 0.15s var(--ease-2),
      border-color 0.15s var(--ease-2);
  }

  .nav-link:hover {
    color: var(--color-header-text);
  }

  .nav-link.active {
    color: var(--color-link);
    border-bottom-color: var(--color-link);
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: var(--size-3);
  }

  .search-link {
    color: var(--color-header-text-muted);
    padding: var(--size-1);
    display: flex;
    align-items: center;
    transition: color 0.15s var(--ease-2);
  }

  .search-link:hover {
    color: var(--color-header-text);
  }

  .search-link.active {
    color: var(--color-link);
  }

  .auth-link {
    font-size: var(--font-size-2);
    color: var(--color-header-text-muted);
    text-decoration: none;
    font-weight: 500;
    transition: color 0.15s var(--ease-2);
  }

  .auth-link:hover {
    color: var(--color-header-text);
  }

  /* Hamburger / desktop-account wrappers: ActionMenu's `bare` trigger inherits
     color from us, so we own idle and hover styling via inheritance. The
     custom properties scale MenuItem / MenuSectionHeader densities up from
     their compact defaults, since this menu has fewer items than e.g. the
     image-category picker and doubles as the primary nav on mobile. */
  .hamburger,
  .desktop-account {
    --menu-item-font-size: var(--font-size-2);
    --menu-item-padding: var(--size-2) var(--size-4);
    --menu-section-header-font-size: 0.875rem;
    display: flex;
    align-items: center;
    color: var(--color-header-text-muted);
    transition: color 0.15s var(--ease-2);
  }

  .hamburger:hover,
  .desktop-account:hover {
    color: var(--color-header-text);
  }

  /* ── Three responsive tiers ──
     Narrow: only logo, search, hamburger.
     Middle band: bar shows primary nav minus Changelog, plus hamburger;
       account menu collapses into hamburger.
     Wide: full bar including Changelog and account menu; hamburger hidden. */
  .hamburger {
    display: none;
  }

  @media (--breakpoint-narrow) {
    .primary-nav {
      display: none;
    }
    .desktop-account {
      display: none;
    }
    .hamburger {
      display: flex;
    }
  }

  @media (not (--breakpoint-narrow)) and (not (--breakpoint-wide)) {
    .changelog-link {
      display: none;
    }
    .desktop-account {
      display: none;
    }
    .hamburger {
      display: flex;
    }
  }
</style>
