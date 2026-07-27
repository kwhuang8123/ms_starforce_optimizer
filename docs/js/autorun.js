/**
 * Automatic drivers over a Session, ported from starforce/autorun.py.
 *
 * Two modes, one loop, different reasons for the budget:
 *   runWithinBudget - "I have 100億 and I want 22 stars." The budget is the point.
 *   runToStar       - "Take it to 22 stars." The budget is only a fuse, because
 *                     a climb has no guaranteed length and this runs in a
 *                     browser. The p95 total cost from the sweep is the figure
 *                     the page fills in.
 *
 * Neither mode overspends: every action's price is known before it is taken, so
 * the loop stops rather than starting something the budget cannot cover. A run
 * that is destroyed and cannot afford either repair stops in that state and
 * reports it.
 */

import * as rules from "./rules.js";
import { RepairPolicy } from "./session.js";

const REPAIR = "repair";
const SCROLL = "scroll";
const ENHANCE = "enhance";

export const StopReason = {
  REACHED_TARGET: "reached_target",
  BUDGET_EXHAUSTED: "budget_exhausted",
};

/**
 * The decisions an automatic run is not allowed to make for itself.
 * scrollStar is the star scroll the strategy uses: it goes on at the start when
 * the item sits below it, and again after every 12 star repair.
 */
export function autoPolicy({ repairPolicy = RepairPolicy.FULL, scrollStar = null } = {}) {
  if (scrollStar !== null) {
    rules.checkStartStar(scrollStar);
  }
  return { repair_policy: repairPolicy, scroll_star: scrollStar };
}

/** What the policy does next, and what it costs before it is taken. */
function nextAction(session, targetStar, policy) {
  if (session.destroyed) {
    const [meso, equipment] =
      policy.repair_policy === RepairPolicy.FULL
        ? rules.fullRepair(session.level, session.star)
        : rules.cheapRepair();
    return [REPAIR, meso + equipment * session.equipmentPrice];
  }

  if (
    policy.scroll_star !== null &&
    session.star < policy.scroll_star &&
    policy.scroll_star < targetStar
  ) {
    return [SCROLL, rules.starScrollCost(policy.scroll_star)];
  }

  return [ENHANCE, rules.enhanceCost(session.level, session.star)];
}

function takeAction(session, kind, policy) {
  if (kind === REPAIR) {
    session.repair(policy.repair_policy);
  } else if (kind === SCROLL) {
    session.useScroll(policy.scroll_star);
  } else {
    session.enhance();
  }
}

/**
 * Enhance towards targetStar until the budget runs out. The budget caps the
 * session's lifetime total cost - meso plus the market value of the equipment
 * repairs consume - not this run's spending alone, so resuming a session cannot
 * spend the same budget twice.
 */
export function runWithinBudget(session, targetStar, budget, policy = autoPolicy()) {
  if (!(budget > 0)) {
    throw new Error(`預算必須大於 0，收到 ${budget}`);
  }
  if (targetStar > session.maxStar) {
    throw new Error(
      `等級 ${session.level} 上限為 ${session.maxStar} 星，目標 ${targetStar} 星無法達成`
    );
  }

  const firstEntry = session.log.length;
  const spentBefore = session.totalCost;
  let stopReason;

  for (;;) {
    if (!session.destroyed && session.star >= targetStar) {
      stopReason = StopReason.REACHED_TARGET;
      break;
    }

    const [kind, cost] = nextAction(session, targetStar, policy);
    if (session.totalCost + cost > budget) {
      stopReason = StopReason.BUDGET_EXHAUSTED;
      break;
    }

    takeAction(session, kind, policy);
  }

  return {
    stop_reason: stopReason,
    entries: session.log.slice(firstEntry),
    star: session.star,
    destroyed: session.destroyed,
    spent: session.totalCost - spentBefore,
  };
}

/** Identical to runWithinBudget; the name records that the budget is the fuse. */
export function runToStar(session, targetStar, budget, policy = autoPolicy()) {
  return runWithinBudget(session, targetStar, budget, policy);
}
