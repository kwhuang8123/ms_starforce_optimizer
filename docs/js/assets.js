/**
 * Optional artwork, and what to show when it is not there.
 *
 * The icons are fan-sourced game art rather than anything this project owns, so
 * nothing may depend on them: assets/manifest.json can be missing entirely, list
 * only some of the catalogue, or point at a file that has since been renamed,
 * and every one of those cases has to degrade to the text the page showed before
 * there were any images at all.
 *
 * The mapping lives here rather than in data/volatile.json because equipment can
 * be renamed and added on the price page, and because keeping the artwork
 * references inside docs/ leaves the Python data model clean.
 */

let manifest = { equipment: {}, scroll: null, breakthrough: null };

export async function loadManifest(path = "assets/manifest.json") {
  try {
    const response = await fetch(path);
    if (!response.ok) {
      return manifest;
    }
    const payload = await response.json();
    manifest = {
      equipment: payload.equipment || {},
      scroll: payload.scroll || null,
      breakthrough: payload.breakthrough || null,
    };
  } catch (error) {
    // A missing or malformed manifest is not worth breaking the page over -
    // the fallbacks cover it - but it should not pass unnoticed either.
    console.warn("圖檔對應表載入失敗，全部退回文字顯示", error);
  }
  return manifest;
}

/** Path to this equipment's icon, or null when there is no artwork for it. */
export function equipmentIcon(name) {
  if (name === null || name === undefined) {
    return null;
  }
  return manifest.equipment[name] || null;
}

export function scrollIcon() {
  return manifest.scroll;
}

export function breakthroughIcon() {
  return manifest.breakthrough;
}

/**
 * An <img> that removes itself if the file will not load. Inline handlers
 * rather than listeners because these are built as HTML strings.
 *
 * Returns "" when there is no artwork, so callers can use `|| fallback`.
 */
export function iconTag(src, alt, className) {
  if (!src) {
    return "";
  }
  return (
    `<img class="${className}" src="${src}" alt="${alt}" ` +
    `onerror="this.remove()">`
  );
}

/**
 * Artwork with text behind it, for the case a manifest entry exists but the
 * file does not. A path that no longer resolves has to fall back to the same
 * text as having no entry at all - otherwise a typo leaves an empty box, which
 * looks deliberate and hides the mistake.
 */
export function iconOrText(src, alt, className, fallbackHtml) {
  if (!src) {
    return fallbackHtml;
  }
  return (
    fallbackHtml +
    `<img class="${className}" src="${src}" alt="${alt}" ` +
    `onerror="this.remove()" ` +
    `onload="this.previousElementSibling && this.previousElementSibling.remove()">`
  );
}
