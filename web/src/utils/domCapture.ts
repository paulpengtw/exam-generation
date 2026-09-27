/**
 * DOM serialization utility for export-only rasterization (#753).
 *
 * Captures what FigureRenderer ACTUALLY renders so the ODT rasterizer uses
 * the same source as the visible preview, rather than re-implementing the
 * rendering logic independently.
 */

/**
 * Serialize a DOM element to HTML markup with inlined computed styles.
 * Clones the element, inlines computed styles on all descendants, and serializes.
 * Images are kept as-is (they should already be inline data: URIs or server URLs).
 * Fonts are NOT inlined (complex; use system fonts in the SVG foreignObject approach).
 */
export function serializeElementToMarkup(element: Element): string {
  const clone = element.cloneNode(true) as Element;
  inlineComputedStyles(element, clone);
  const serializer = new XMLSerializer();
  const result = serializer.serializeToString(clone);
  return result || (clone as HTMLElement).outerHTML;
}

function inlineComputedStyles(original: Element, clone: Element): void {
  const originalStyle = window.getComputedStyle(original);
  const htmlClone = clone as HTMLElement;
  // Copy the computed styles
  const cssText = Array.from(originalStyle)
    .map((prop) => `${prop}:${originalStyle.getPropertyValue(prop)}`)
    .join(";");
  htmlClone.style.cssText = cssText;
  // Recurse into children
  const origChildren = original.children;
  const cloneChildren = clone.children;
  for (let i = 0; i < origChildren.length; i++) {
    inlineComputedStyles(origChildren[i], cloneChildren[i]);
  }
}
