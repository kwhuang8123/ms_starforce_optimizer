/**
 * The published tables, laid out to be read.
 *
 * Everything on this tab comes from data/static.json - the official V272
 * figures, generated from starforce/static_data.py. Nothing here is volatile:
 * no market price appears, and editing the price page changes none of it. The
 * scroll prices that do move live on the price tab instead.
 *
 * One level at a time, because the alternative is a five-level table eight
 * columns wide that has to scroll sideways on a phone, and this is a page
 * people come to look one figure up in.
 */

import * as rules from "./rules.js";
import { formatFee } from "./format.js";

/** Opens on the level of the manual tab's default item. */
const DEFAULT_LEVEL = 150;


const el = {};

function bind() {
  for (const id of ["rates-level"]) {
    el[id] = document.getElementById(id);
  }
  el.enhance = document.querySelector("#rates-enhance tbody");
  el.repair = document.querySelector("#rates-repair tbody");
  el.repairHead = document.querySelector("#rates-repair thead tr");
}

function percent(basisPoints) {
  return `${((basisPoints / rules.rateBasis()) * 100).toFixed(2)}%`;
}

function fillLevels() {
  const levels = rules.supportedLevels();
  el["rates-level"].innerHTML = levels
    .map((level) => `<option value="${level}">${level} 等</option>`)
    .join("");
  el["rates-level"].value = levels.includes(DEFAULT_LEVEL)
    ? DEFAULT_LEVEL
    : levels[0];
}

/**
 * One row per attempt, from the first star that can be destroyed to the cap.
 *
 * Below 15 stars the fees are rounding error against everything above and
 * nothing can be destroyed, so there is no decision to look up. Those rows are
 * still in static.json - this is what gets shown, not what gets carried.
 *
 * The star column names the attempt rather than the state - "19 → 20" is what
 * the rates and the fee on that row describe, and writing it as a bare 19
 * invites reading it as the cost of being at 19.
 */
function renderEnhance() {
  const level = Number(el["rates-level"].value);
  const cap = rules.maxStar(level);

  const rows = [];
  for (let star = rules.destroyStartStar(); star < cap; star += 1) {
    const [success, destroy, maintain] = rules.enhanceRates(star);
    rows.push(`<tr>
      <td class="num">${star} → ${star + 1}</td>
      <td class="num gold">${formatFee(rules.enhanceCost(level, star))}</td>
      <td class="num ok-text">${percent(success)}</td>
      <td class="num">${percent(maintain)}</td>
      <td class="num ${destroy ? "bad-text" : "muted"}">${percent(destroy)}</td>
    </tr>`);
  }
  el.enhance.innerHTML = rows.join("");
}

/**
 * The repair table, all levels at once.
 *
 * Only eight rows - traces run 15 to 22, because destruction above 22 stars
 * still leaves a 22 star trace - so five levels side by side stays readable
 * where the thirty-row enhancement table would not.
 */
function renderRepair() {
  const levels = rules.supportedLevels();
  el.repairHead.innerHTML =
    `<th>痕跡星數</th><th class="num">消耗裝備</th>` +
    levels.map((level) => `<th class="num">${level} 等</th>`).join("");

  const rows = [];
  const highest = rules.traceStarCap();
  for (let trace = rules.destroyStartStar(); trace <= highest; trace += 1) {
    const [, pieces] = rules.fullRepair(levels[0], trace);
    const cells = levels
      .map((level) => {
        const [meso] = rules.fullRepair(level, trace);
        return `<td class="num gold">${formatFee(meso)}</td>`;
      })
      .join("");
    rows.push(
      `<tr><td class="num">${trace} 星</td>` +
        `<td class="num">${pieces} 件</td>${cells}</tr>`
    );
  }
  el.repair.innerHTML = rows.join("");
}

export function initRates() {
  bind();
  fillLevels();
  el["rates-level"].addEventListener("change", renderEnhance);
  renderEnhance();
  renderRepair();
}
