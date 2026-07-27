/**
 * Hand-driven star force enhancement, ported from starforce/session.py.
 *
 * One call does exactly one thing - one attempt, one star scroll, one repair -
 * and appends a log entry describing it. Log entries and totals use the same
 * snake_case keys the Python side emits, because docs/selftest.html compares
 * them field for field against data/parity.json.
 *
 * The item the session starts from is not charged: it is a constant across
 * every strategy being compared.
 */

import * as rules from "./rules.js";

export const Action = {
  ENHANCE: "enhance",
  SCROLL: "scroll",
  REPAIR_FULL: "repair_full",
  REPAIR_TO_12: "repair_to_12",
};

export const Outcome = {
  SUCCESS: "success",
  MAINTAIN: "maintain",
  DESTROY: "destroy",
};

export const RepairPolicy = { FULL: "full", TO_12: "to_12" };

/** The live roll: an integer in [0, rateBasis). */
export function defaultRng() {
  return Math.floor(Math.random() * rules.rateBasis());
}

/** Replays a fixed sequence, for parity checks. Throws when it runs dry. */
export function scriptedRng(rolls) {
  let used = 0;
  return () => {
    if (used >= rolls.length) {
      throw new Error("這次重播消耗的骰子比記錄的還多");
    }
    return rolls[used++];
  };
}

function emptyTotals() {
  return {
    total_meso: 0,
    equipment_used: 0,
    equipment_cost: 0,
    // A hand-driven climb charges every step as it happens, so nothing is
    // ever booked as a flat rebuild. Kept so the shape matches RunResult.
    rebuild_cost: 0,
    scrolls_used: 0,
    attempts: 0,
    destroys: 0,
    attempts_by_star: {},
  };
}

export class Session {
  constructor({
    level,
    startStar = 0,
    equipmentName = null,
    equipmentPrice = 0,
    rng = defaultRng,
  }) {
    rules.checkLevel(level);
    const cap = rules.maxTargetStar(level);
    if (!Number.isInteger(startStar) || startStar < 0 || startStar > cap) {
      throw new Error(`起始星數必須介於 0 ~ ${cap}（等級 ${level}），收到 ${startStar}`);
    }
    if (equipmentPrice < 0) {
      throw new Error(`裝備價格不得為負，收到 ${equipmentPrice}`);
    }

    this.level = level;
    this.startStar = startStar;
    this.equipmentName = equipmentName;
    this.equipmentPrice = equipmentPrice;
    this.rng = rng;

    this.star = startStar;
    this.destroyed = false;
    this.log = [];
    this.totals = emptyTotals();
  }

  get maxStar() {
    return rules.maxTargetStar(this.level);
  }

  get totalCost() {
    return (
      this.totals.total_meso + this.totals.equipment_cost + this.totals.rebuild_cost
    );
  }

  /** True when an attempt is legal right now. */
  get canEnhance() {
    return !this.destroyed && this.star < this.maxStar;
  }

  /** The scrolls that would actually raise this item, cheapest star first. */
  availableScrolls() {
    if (this.destroyed) {
      return [];
    }
    return rules
      .starScrollStars()
      .filter((star) => star > this.star && star <= this.maxStar);
  }

  enhance() {
    if (this.destroyed) {
      throw new Error(`裝備已破壞：先修復 ${this.star} 星痕跡才能繼續強化`);
    }
    if (this.star >= this.maxStar) {
      throw new Error(
        `等級 ${this.level} 無法強化超過 ${this.maxStar} 星，目前已在 ${this.star} 星`
      );
    }

    const starBefore = this.star;
    const meso = rules.enhanceCost(this.level, starBefore);
    this.totals.total_meso += meso;
    this.totals.attempts += 1;
    this.totals.attempts_by_star[starBefore] =
      (this.totals.attempts_by_star[starBefore] || 0) + 1;

    const [success, destroy] = rules.enhanceRates(starBefore);
    const roll = this.rng();

    let outcome;
    if (roll < success) {
      outcome = Outcome.SUCCESS;
      this.star = starBefore + 1;
    } else if (roll < success + destroy) {
      outcome = Outcome.DESTROY;
      this.totals.destroys += 1;
      this.destroyed = true;
      // Destruction above 22 stars still leaves a 22 star trace.
      this.star = rules.traceStar(starBefore);
    } else {
      outcome = Outcome.MAINTAIN;
    }

    return this._record(Action.ENHANCE, starBefore, meso, 0, outcome, 0);
  }

  /**
   * Buy a star scroll and set the item to that star force. A scroll may only
   * raise the item: applying one at or below the current star throws it away.
   */
  useScroll(star) {
    if (this.destroyed) {
      throw new Error(`裝備已破壞：先修復 ${this.star} 星痕跡才能使用星捲`);
    }
    rules.checkStartStar(star);
    if (star <= this.star) {
      throw new Error(
        `星捲只能往上，目前已在 ${this.star} 星，${star} 星星捲沒有意義`
      );
    }
    if (star > this.maxStar) {
      throw new Error(`等級 ${this.level} 上限為 ${this.maxStar} 星，${star} 星星捲不適用`);
    }

    const starBefore = this.star;
    const meso = rules.starScrollCost(star);
    this.totals.total_meso += meso;
    this.totals.scrolls_used += 1;
    this.star = star;

    return this._record(Action.SCROLL, starBefore, meso, 0, null, 0);
  }

  /** Restore a destroyed item, either to its trace star or to 12 stars. */
  repair(policy) {
    if (!this.destroyed) {
      throw new Error(`裝備沒有破壞（目前 ${this.star} 星），沒有東西可以修復`);
    }

    const starBefore = this.star;
    let action;
    let meso;
    let equipment;
    let starAfter;

    if (policy === RepairPolicy.FULL) {
      action = Action.REPAIR_FULL;
      [meso, equipment] = rules.fullRepair(this.level, starBefore);
      starAfter = starBefore;
    } else if (policy === RepairPolicy.TO_12) {
      action = Action.REPAIR_TO_12;
      [meso, equipment] = rules.cheapRepair();
      starAfter = rules.cheapRepairStar();
    } else {
      throw new Error(`未知的修復方式：${policy}`);
    }

    const equipmentCost = equipment * this.equipmentPrice;
    this.totals.total_meso += meso;
    this.totals.equipment_used += equipment;
    this.totals.equipment_cost += equipmentCost;
    this.star = starAfter;
    this.destroyed = false;

    return this._record(action, starBefore, meso, equipmentCost, null, equipment);
  }

  _record(action, starBefore, meso, equipmentCost, outcome, equipment) {
    const entry = {
      index: this.log.length + 1,
      action,
      star_before: starBefore,
      star_after: this.star,
      outcome: outcome === undefined ? null : outcome,
      meso,
      equipment_used: equipment,
      equipment_cost: equipmentCost,
      total_cost_after: this.totalCost,
    };
    this.log.push(entry);
    return entry;
  }
}
