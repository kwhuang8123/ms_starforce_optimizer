/**
 * The editable price table, held in localStorage.
 *
 * data/prices.json is what build_site_data.py exported from
 * data/volatile.json; anything saved here overrides it for this browser only.
 * A static site cannot write back to the repo, so the price page exports JSON
 * for the operator to paste in themselves.
 */

const KEY = "ms-starforce/prices";

// Same folding starforce/volatile_data.py applies before matching a name, so
// the editor rejects exactly the collisions the Python loader would reject.
const DIGIT_FOLD = {
  "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
  "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
  "〇": "0", "零": "0", "一": "1", "二": "2", "三": "3", "四": "4",
  "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
};

export function normalizeName(name) {
  return Array.from(name.replace(/\s+/g, ""))
    .map((char) => DIGIT_FOLD[char] || char)
    .join("")
    .toLowerCase();
}

let shipped = null;
let current = null;
const listeners = [];

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function readSaved() {
  const raw = window.localStorage.getItem(KEY);
  if (raw === null) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw);
    if (parsed && parsed.star_scroll_cost && Array.isArray(parsed.equipment)) {
      return parsed;
    }
    // Stored data that no longer fits the shape is a bug worth seeing, not
    // something to silently paper over with the shipped defaults.
    console.warn("localStorage 的價格格式不符，已忽略", parsed);
  } catch (error) {
    console.warn("localStorage 的價格不是合法 JSON，已忽略", error);
  }
  return null;
}

/**
 * Fill in sections a saved copy predates.
 *
 * Breakthrough scrolls arrived after people had already saved prices, so an
 * older browser has no section for them at all. Falling back to the shipped
 * figures per scroll keeps that browser working; throwing the first time one is
 * used would be a broken page rather than a stale price.
 */
function withShippedDefaults(prices) {
  return {
    ...prices,
    breakthrough_scroll_cost: {
      ...shipped.breakthrough_scroll_cost,
      ...(prices.breakthrough_scroll_cost || {}),
    },
  };
}

export function init(shippedPrices) {
  shipped = shippedPrices;
  const saved = readSaved();
  current = saved === null ? clone(shipped) : withShippedDefaults(saved);
  return current;
}

export function shippedPrices() {
  return shipped;
}

export function currentPrices() {
  return current;
}

export function isModified() {
  return JSON.stringify(current) !== JSON.stringify(shipped);
}

export function save(prices) {
  current = clone(prices);
  window.localStorage.setItem(KEY, JSON.stringify(current));
  listeners.forEach((fn) => fn(current));
}

export function reset() {
  window.localStorage.removeItem(KEY);
  current = clone(shipped);
  listeners.forEach((fn) => fn(current));
}

export function onChange(fn) {
  listeners.push(fn);
}

export function lookup(name) {
  return current.equipment.find((item) => item.name === name) || null;
}
