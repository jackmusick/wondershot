export interface SelectionModifiers {
  toggle: boolean;
  range: boolean;
}

export interface SelectionResult {
  selected: string[];
  anchor: string;
}

/** Apply desktop-style single, toggle, and range selection semantics. */
export function selectGalleryItem(
  selected: string[],
  ordered: string[],
  clicked: string,
  anchor: string | null,
  modifiers: SelectionModifiers
): SelectionResult {
  if (modifiers.range && anchor) {
    const from = ordered.indexOf(anchor);
    const to = ordered.indexOf(clicked);
    if (from >= 0 && to >= 0) {
      const range = ordered.slice(Math.min(from, to), Math.max(from, to) + 1);
      return {
        selected: modifiers.toggle ? ordered.filter((path) => selected.includes(path) || range.includes(path)) : range,
        anchor
      };
    }
  }

  if (modifiers.toggle) {
    return {
      selected: selected.includes(clicked)
        ? selected.filter((path) => path !== clicked)
        : ordered.filter((path) => selected.includes(path) || path === clicked),
      anchor: clicked
    };
  }

  return { selected: [clicked], anchor: clicked };
}

/** Keep a fixed-position menu fully inside the current webview viewport. */
export function placeContextMenu(
  pointerX: number,
  pointerY: number,
  menuWidth: number,
  menuHeight: number,
  viewportWidth: number,
  viewportHeight: number,
  margin = 8
): { x: number; y: number } {
  const maxX = Math.max(margin, viewportWidth - menuWidth - margin);
  const maxY = Math.max(margin, viewportHeight - menuHeight - margin);
  const preferredY = pointerY + menuHeight > viewportHeight - margin
    ? pointerY - menuHeight
    : pointerY;

  return {
    x: Math.min(Math.max(margin, pointerX), maxX),
    y: Math.min(Math.max(margin, preferredY), maxY)
  };
}
