import { describe, expect, it } from 'vitest';

import { isFocusModeRoute, isMinimalShellRoute } from './focus-mode';

describe('isFocusModeRoute', () => {
  describe('focus-mode routes', () => {
    it('matches top-level create', () => {
      expect(isFocusModeRoute('/titles/new')).toBe(true);
    });

    it('matches nested create', () => {
      expect(isFocusModeRoute('/titles/[slug]/models/new')).toBe(true);
    });

    it('matches edit without section', () => {
      expect(isFocusModeRoute('/manufacturers/[slug]/edit')).toBe(true);
    });

    it('matches edit with section', () => {
      expect(isFocusModeRoute('/models/[slug]/edit/[section]')).toBe(true);
    });

    it('matches delete confirmation', () => {
      expect(isFocusModeRoute('/titles/[slug]/delete')).toBe(true);
    });

    it('matches edit-history', () => {
      expect(isFocusModeRoute('/titles/[slug]/edit-history')).toBe(true);
    });

    it('matches sources', () => {
      expect(isFocusModeRoute('/titles/[slug]/sources')).toBe(true);
    });

    it('matches the kiosk', () => {
      expect(isFocusModeRoute('/kiosk')).toBe(true);
    });

    it('does not match /signup (minimal shell, not focus)', () => {
      expect(isFocusModeRoute('/signup')).toBe(false);
    });
  });

  describe('records whose public id spans several URL segments', () => {
    // A Location nested two or more levels deep (/locations/canada/on) still
    // routes through a single [...path] segment, so its sub-routes classify
    // exactly like a [slug] entity's.
    it('matches every location sub-route', () => {
      expect(isFocusModeRoute('/locations/[...path]/edit-history')).toBe(true);
      expect(isFocusModeRoute('/locations/[...path]/sources')).toBe(true);
      expect(isFocusModeRoute('/locations/[...path]/delete')).toBe(true);
      expect(isFocusModeRoute('/locations/[...path]/edit')).toBe(true);
      expect(isFocusModeRoute('/locations/[...path]/edit/[section]')).toBe(true);
      expect(isFocusModeRoute('/locations/[...path]/new')).toBe(true);
    });

    it('does not match the location detail page', () => {
      expect(isFocusModeRoute('/locations/[...path]')).toBe(false);
    });
  });

  describe('full-chrome routes', () => {
    it('does not match the home page', () => {
      expect(isFocusModeRoute('/')).toBe(false);
    });

    it('does not match an entity index', () => {
      expect(isFocusModeRoute('/titles')).toBe(false);
    });

    it('does not match a detail page', () => {
      expect(isFocusModeRoute('/manufacturers/[slug]')).toBe(false);
    });

    it('does not match a record whose slug names a sub-route', () => {
      // /titles/sources, /titles/edit and friends are detail pages for records
      // slugged 'sources' / 'edit'. All are served by /titles/[slug], which
      // carries no sub-route segment.
      expect(isFocusModeRoute('/titles/[slug]')).toBe(false);
    });

    it('does not match a nested listing under a detail page', () => {
      expect(isFocusModeRoute('/manufacturers/[slug]/systems')).toBe(false);
    });

    it('does not match "edit" outside a record route', () => {
      expect(isFocusModeRoute('/kiosk/edit/[id]')).toBe(false);
    });

    it('does not match an unmatched URL', () => {
      expect(isFocusModeRoute(null)).toBe(false);
    });
  });
});

describe('isMinimalShellRoute', () => {
  it('matches /signup', () => {
    expect(isMinimalShellRoute('/signup')).toBe(true);
  });

  it('matches the auth error page', () => {
    expect(isMinimalShellRoute('/auth/error')).toBe(true);
  });

  it('does not match the home page', () => {
    expect(isMinimalShellRoute('/')).toBe(false);
  });

  it('does not match a focus-mode route', () => {
    expect(isMinimalShellRoute('/titles/new')).toBe(false);
  });

  it('does not match a record whose slug is "signup"', () => {
    expect(isMinimalShellRoute('/titles/[slug]')).toBe(false);
  });

  it('does not match an unmatched URL', () => {
    expect(isMinimalShellRoute(null)).toBe(false);
  });
});
