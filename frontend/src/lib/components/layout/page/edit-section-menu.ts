export type EditSectionMenuItem = {
  key: string;
  label: string;
  href?: string;
  onclick?: () => void;
  /** Render a horizontal divider above this item — useful to set off
   * destructive actions (e.g. "Delete …") from the section editors. */
  separatorBefore?: boolean;
};

/** A labeled dropdown in the page action bar (e.g. "Edit Title", "Edit Model"). */
export type EditSectionDropdown = {
  label: string;
  items: EditSectionMenuItem[];
};

/**
 * Get a callback for a menu item — navigates to `href` or calls `onclick`.
 * Returns `undefined` when the item is not found (useful for auth gating:
 * pass an empty array when unauthenticated).
 */
export function getMenuItemAction(
  items: EditSectionMenuItem[],
  key: string,
  navigate: (href: string) => void,
): (() => void) | undefined {
  const item = items.find((i) => i.key === key);
  if (!item) return undefined;
  if (item.href) {
    const href = item.href;
    return () => navigate(href);
  }
  return item.onclick;
}
