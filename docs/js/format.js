/**
 * Meso display units and the shorthand this project reads and writes.
 *
 * Ported from starforce/units.py. Meso figures run to tens of billions, so
 * everything shown to a reader is expressed in 億 (10^8). Every amount stays a
 * plain Number: the largest figure in the datasets is about 2.4e11, four orders
 * of magnitude below the 2^53 safe integer limit, so no BigInt is needed.
 */

export const YI = 100000000;

export function toYi(meso) {
  return meso / YI;
}

export function formatMeso(meso, decimals = 2) {
  const value = toYi(meso).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return `${value}億`;
}

/** Compact form for table cells: "1,234.5e". */
export function formatYi(meso, decimals = 1) {
  const value = toYi(meso).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return `${value}e`;
}

/** Read "100e", "100億" or a bare "100" as 100億 in raw meso. */
export function parseMeso(text) {
  const cleaned = String(text).trim().replace(/,/g, "").replace(/[eE億]$/, "");
  const amount = Number(cleaned);
  if (cleaned === "" || !Number.isFinite(amount)) {
    throw new Error(`「${text}」不是金額，請寫成 100e 這樣的形式`);
  }
  if (amount <= 0) {
    throw new Error(`金額必須大於 0，收到「${text}」`);
  }
  return Math.round(amount * YI);
}

/** Read "22c", "22星" or a bare "22" as the star 22. */
export function parseStar(text) {
  const cleaned = String(text).trim().replace(/[cC星]$/, "");
  const star = Number(cleaned);
  if (cleaned === "" || !Number.isInteger(star)) {
    throw new Error(`「${text}」不是星數，請寫成 22c 這樣的形式`);
  }
  return star;
}
