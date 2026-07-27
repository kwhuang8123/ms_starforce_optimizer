/**
 * Star force rules, ported from starforce/rules.py.
 *
 * Not one number lives in this file. The official tables arrive as
 * data/static.json, generated from starforce/static_data.py by
 * build_site_data.py, and the prices arrive from data/prices.json or from
 * whatever the price page has saved. Only the logic is ported; the figures stay
 * on the Python side of the fence.
 *
 * Like the Python module, every lookup validates and throws rather than
 * returning a default, so an unsupported level or an out-of-range star fails
 * loudly instead of quietly producing a wrong cost.
 */

let STATIC = null;
let PRICES = null;

/** Point the module at the generated tables and a set of prices. */
export function configure(staticData, prices) {
  STATIC = staticData;
  PRICES = prices;
}

/** Swap in edited prices without reloading the tables. */
export function setPrices(prices) {
  PRICES = prices;
}

export function prices() {
  return PRICES;
}

function requireConfigured() {
  if (STATIC === null || PRICES === null) {
    throw new Error("rules.configure() 尚未呼叫，靜態資料或價格還沒載入");
  }
}

export function rateBasis() {
  requireConfigured();
  return STATIC.rate_basis;
}

export function supportedLevels() {
  requireConfigured();
  return STATIC.supported_levels;
}

export function starScrollStars() {
  requireConfigured();
  return STATIC.star_scroll_stars;
}

export function cheapRepairStar() {
  requireConfigured();
  return STATIC.cheap_repair_star;
}

export function destroyStartStar() {
  requireConfigured();
  return STATIC.destroy_start_star;
}

export function checkLevel(level) {
  requireConfigured();
  if (!STATIC.supported_levels.includes(level)) {
    throw new Error(
      `等級 ${level} 不在官方公布的表格內，支援的等級為 ${STATIC.supported_levels.join("、")}`
    );
  }
}

export function maxStar(level) {
  checkLevel(level);
  return STATIC.max_star[String(level)];
}

/**
 * Highest target this engine will simulate for a level. Level 130 stops below
 * the destruction range because the official repair table has no 130 column.
 */
export function maxTargetStar(level) {
  checkLevel(level);
  return STATIC.max_target_star[String(level)];
}

export function enhanceCost(level, star) {
  checkLevel(level);
  const cost = STATIC.enhance_cost[String(level)][String(star)];
  if (cost === undefined) {
    throw new Error(`等級 ${level} 沒有 ${star} → ${star + 1} 的公布費用`);
  }
  return cost;
}

/** [success, destroy, maintain] in basis points for one attempt. */
export function enhanceRates(star) {
  requireConfigured();
  const rates = STATIC.enhance_rates[String(star)];
  if (rates === undefined) {
    throw new Error(`沒有 ${star} → ${star + 1} 的公布機率`);
  }
  return rates;
}

/** Star force recorded on the trace left by destruction at a given star. */
export function traceStar(destroyedStar) {
  requireConfigured();
  if (destroyedStar < STATIC.destroy_start_star) {
    throw new Error(
      `${destroyedStar} 星的裝備不會被破壞，破壞從 ${STATIC.destroy_start_star} 星開始`
    );
  }
  return Math.min(destroyedStar, STATIC.trace_star_cap);
}

/** [meso, equipmentPieces] to restore a trace to its original stars. */
export function fullRepair(level, trace) {
  checkLevel(level);
  const table = STATIC.repair_meso[String(level)];
  if (table === undefined) {
    throw new Error(`官方修復表沒有等級 ${level} 這一欄`);
  }
  const meso = table[String(trace)];
  if (meso === undefined) {
    throw new Error(`沒有 ${trace} 星痕跡的公布修復費用`);
  }
  return [meso, STATIC.repair_equipment[String(trace)]];
}

/** [meso, equipmentPieces] to restore a trace to 12 stars. */
export function cheapRepair() {
  requireConfigured();
  return [0, STATIC.cheap_repair_equipment];
}

export function checkStartStar(star) {
  requireConfigured();
  if (star < STATIC.min_start_star || star > STATIC.max_start_star) {
    throw new Error(
      `星捲只存在於 ${STATIC.min_start_star} ~ ${STATIC.max_start_star} 星，收到 ${star}`
    );
  }
}

/** Meso cost of a star scroll, as currently priced. */
export function starScrollCost(star) {
  checkStartStar(star);
  const cost = PRICES.star_scroll_cost[String(star)];
  if (cost === undefined) {
    throw new Error(`價格表沒有 ${star} 星星捲的價格`);
  }
  return cost;
}
