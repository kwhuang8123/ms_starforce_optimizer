/**
 * Which action to take at each star, ported from starforce/policy.py.
 *
 * The sweep measures a handful of named policies, chosen against the prices the
 * sweep ran on. Prices move, and the page lets people move them - so the row
 * labelled "optimal" in the dataset is only optimal at the snapshot. This module
 * re-derives the cheapest policy from whatever prices are in effect right now,
 * which is what lets the cheat sheet say so when the dataset has gone stale.
 *
 * Not one number lives here either: the scroll list arrives in data/static.json
 * and the prices come from the price page, exactly as in rules.js.
 *
 * Why this is a closed form rather than a simulation: a breakthrough scroll
 * cannot destroy, so its star is a geometric wait costing price/rate. An
 * enhancement can, and under FULL repair the trace carries the item's own star,
 * so a repair puts it back where it was - another independent wait. Under TO_12
 * the item drops to 12 and re-scrolls to start_star, so every star depends on
 * one shared unknown: the value of restarting. See the Python module for the
 * derivation; this is a direct port of it, and selftest.html checks the two
 * against each other on golden cases.
 */

import * as rules from "./rules.js";

/** Policy iteration should settle in two or three rounds; this is the guard. */
const MAX_ROUNDS = 50;

export const NONE = { name: "none", entries: [] };

function scrollAt(policy, star) {
  for (const [entryStar, capStar, success] of policy.entries) {
    if (entryStar === star) {
      return [capStar, success];
    }
  }
  return null;
}

/** The cheapest scroll for one star as [expected cost, [cap, rate]], or null. */
function bestScroll(star, deterministicOnly) {
  const basis = rules.rateBasis();
  let best = null;
  for (const [capStar, success] of rules.breakthroughScrolls()) {
    if (star + 1 > capStar) continue;
    if (deterministicOnly && success !== basis) continue;
    const cost = rules.breakthroughCost(capStar, success) / (success / basis);
    if (best === null || cost < best[0]) {
      best = [cost, [capStar, success]];
    }
  }
  return best;
}

/** [fee, pSuccess, pDestroy, immediate destruction cost] for one attempt. */
function enhanceTerms(problem, star) {
  const basis = rules.rateBasis();
  const fee = rules.enhanceCost(problem.level, star);
  const [success, destroy] = rules.enhanceRates(star);

  let cost = 0;
  if (destroy > 0) {
    const [meso, pieces] =
      problem.repairPolicy === "full"
        ? rules.fullRepair(problem.level, rules.traceStar(star))
        : rules.cheapRepair();
    cost = meso + pieces * problem.equipmentPrice;
    if (problem.repairPolicy !== "full") {
      // The engine climbs back out of a 12 star repair with another start_star
      // scroll, charged at repair time.
      cost += rules.starScrollCost(problem.startStar);
    }
  }
  return [fee, success / basis, destroy / basis, cost];
}

/**
 * One backward pass from the target, holding the restart value fixed.
 *
 * With `policy` given every star follows it; with null every star takes
 * whichever action is cheaper, which is the greedy improvement. V(s) comes back
 * split into a constant and a coefficient on the restart value, so the caller
 * can close the fixed point. Under FULL repair the coefficient stays zero.
 */
function sweepBack(problem, restart, policy, deterministicOnly) {
  const constant = { [problem.targetStar]: 0 };
  const coefficient = { [problem.targetStar]: 0 };
  const chosen = [];

  for (let star = problem.targetStar - 1; star >= problem.startStar; star -= 1) {
    const [fee, pSuccess, pDestroy, destruction] = enhanceTerms(problem, star);
    const nextConstant = constant[star + 1];
    const nextCoefficient = coefficient[star + 1];

    let enhanceConstant;
    let enhanceCoefficient;
    if (problem.repairPolicy === "full") {
      enhanceConstant = (fee + pDestroy * destruction) / pSuccess + nextConstant;
      enhanceCoefficient = nextCoefficient;
    } else {
      const denominator = pSuccess + pDestroy;
      enhanceConstant =
        (fee + pDestroy * destruction + pSuccess * nextConstant) / denominator;
      enhanceCoefficient = (pDestroy + pSuccess * nextCoefficient) / denominator;
    }
    const enhanceValue = enhanceConstant + enhanceCoefficient * restart;

    let scroll = policy === null ? null : scrollAt(policy, star);
    if (policy === null) {
      const best = bestScroll(star, deterministicOnly);
      if (
        best !== null &&
        best[0] + nextConstant + nextCoefficient * restart < enhanceValue
      ) {
        scroll = best[1];
      }
    }

    if (scroll === null) {
      constant[star] = enhanceConstant;
      coefficient[star] = enhanceCoefficient;
      continue;
    }

    const [capStar, success] = scroll;
    const perSuccess =
      rules.breakthroughCost(capStar, success) / (success / rules.rateBasis());
    constant[star] = perSuccess + nextConstant;
    coefficient[star] = nextCoefficient;
    chosen.push([star, capStar, success]);
  }

  chosen.reverse();
  return { chosen, constant, coefficient };
}

/** V(start_star) for a fixed policy: a / (1 - b), solved exactly. */
function restartValue(problem, policy) {
  const { constant, coefficient } = sweepBack(problem, 0, policy, false);
  const a = constant[problem.startStar];
  const b = coefficient[problem.startStar];
  if (b >= 1) {
    throw new Error(`重啟不動點無法收斂（係數 ${b}）`);
  }
  return a / (1 - b);
}

function problemOf({ level, startStar, targetStar, equipmentPrice, repairPolicy }) {
  rules.checkLevel(level);
  if (targetStar <= startStar) {
    throw new Error(`目標星力必須大於起手星，收到 ${startStar} → ${targetStar}`);
  }
  if (targetStar > rules.maxTargetStar(level)) {
    throw new Error(
      `等級 ${level} 無法模擬超過 ${rules.maxTargetStar(level)} 星，收到 ${targetStar}`
    );
  }
  return { level, startStar, targetStar, equipmentPrice, repairPolicy };
}

/** Exact expected total cost of following a policy, in meso. */
export function expectedTotal(policy, options) {
  const problem = problemOf(options);
  return (
    rules.starScrollCost(problem.startStar) + restartValue(problem, policy)
  );
}

/**
 * The cheapest policy by expected total cost, at the prices in effect now.
 *
 * `deterministicOnly` restricts the choice to 100% scrolls - they cost more per
 * star but cannot miss, which is the trade the cheat sheet's stable answer is
 * about.
 */
export function optimalPolicy(options, deterministicOnly = false) {
  const problem = problemOf(options);
  const name = deterministicOnly ? "safe" : "optimal";

  let policy = { name, entries: [] };
  for (let round = 0; round < MAX_ROUNDS; round += 1) {
    const restart = restartValue(problem, policy);
    const { chosen } = sweepBack(problem, restart, null, deterministicOnly);
    const improved = { name, entries: chosen };
    if (sameEntries(improved.entries, policy.entries)) {
      return improved;
    }
    policy = improved;
  }
  throw new Error(
    `策略疊代在 ${MAX_ROUNDS} 輪內沒有收斂（等級 ${options.level} ` +
      `${options.startStar}→${options.targetStar}）`
  );
}

export function sameEntries(left, right) {
  if (left.length !== right.length) {
    return false;
  }
  return left.every((entry, index) =>
    entry.every((value, position) => value === right[index][position])
  );
}

/** One line naming every scroll a policy buys, for a table cell or a tooltip. */
export function describe(policy) {
  if (policy.entries.length === 0) {
    return "全部強化";
  }
  return policy.entries
    .map(
      ([star, capStar, success]) =>
        `${star}星→${rules.breakthroughLabel(capStar, success)}`
    )
    .join("、");
}
