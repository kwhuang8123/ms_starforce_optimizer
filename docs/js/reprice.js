/**
 * Re-price a stored sweep row for edited prices, without simulating anything.
 *
 * No price can change a run's trajectory - the engine only ever adds prices up,
 * it never branches on one - so the mean total cost is exactly linear in them:
 *
 *   total = static_meso_mean
 *         + scrolls_mean       x star scroll price
 *         + equipment_mean     x equipment price
 *         + rebuild_count_mean x rebuild cost
 *
 * build_site_data.py splits every row into those four parts. Multiplying them
 * out is all the re-pricing there is.
 *
 * This works for the MEAN ONLY. Percentiles cannot be re-priced: changing a
 * price reorders the trials, and a stored p95 says nothing about where the new
 * one lands. Callers must keep presenting stored percentiles as belonging to
 * the prices the sweep was run against.
 */

import * as rules from "./rules.js";

/** What one star scroll costs this row, or 0 when the run buys none. */
export function scrollPrice(row, prices) {
  if (row.scroll_star === null) {
    return 0;
  }
  const price = prices.star_scroll_cost[String(row.scroll_star)];
  if (price === undefined) {
    throw new Error(`價格表缺少 ${row.scroll_star} 星星捲的價格`);
  }
  return price;
}

/** This row's equipment price, or null when it is no longer in the table. */
export function equipmentPrice(row, prices) {
  const item = prices.equipment.find((entry) => entry.name === row.equipment);
  return item === undefined ? null : item.price;
}

/**
 * The row's mean total cost at the given prices, or null when it cannot be
 * worked out - the equipment has been deleted, or a run that rebuilds has no
 * rebuild cost to work from. Null means "unknown", and callers must show it as
 * unknown rather than falling back to the stored figure, which would silently
 * present a stale number as a current one.
 */
export function repricedMean(row, prices, rebuildCost = null) {
  const equipment = equipmentPrice(row, prices);
  if (equipment === null) {
    return null;
  }
  if (row.rebuild_count_mean > 0 && rebuildCost === null) {
    return null;
  }
  return Math.round(
    row.static_meso_mean +
      row.scrolls_mean * scrollPrice(row, prices) +
      row.equipment_mean * equipment +
      row.rebuild_count_mean * (rebuildCost === null ? 0 : rebuildCost)
  );
}

/**
 * Cheapest re-priced mean of reaching the rebuild star, per equipment.
 *
 * Mirrors starforce/sim_data_loader.py: a marginal run that repairs to 12 stars
 * has to climb back, and what that costs is not a guess - it is the cheapest
 * measured route to 22 stars for the same item. Re-pricing the marginal dataset
 * therefore has to re-price the from-scratch one first.
 */
export function rebuildBasis(fromScratchRows, prices) {
  const star = rules.rebuildStar();
  const best = new Map();
  for (const row of fromScratchRows) {
    if (row.target_star !== star || !row.equipment) {
      continue;
    }
    const mean = repricedMean(row, prices);
    if (mean === null) {
      continue;
    }
    const current = best.get(row.equipment);
    if (current === undefined || mean < current) {
      best.set(row.equipment, mean);
    }
  }
  return best;
}
