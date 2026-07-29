/**
 * The hand-driven simulation tab.
 *
 * The buttons mirror the Session rules rather than duplicating them: a scroll
 * that cannot raise the item never appears in the dropdown, repair only lights
 * up on a destroyed item, and enhancing stops at the level cap. Anything that
 * still slips through surfaces as the engine's own error message.
 */

import * as rules from "./rules.js";
import * as store from "./prices-store.js";
import { Session, RepairPolicy } from "./session.js";
import { runWithinBudget, runToStar, autoPolicy, StopReason } from "./autorun.js";
import { formatMeso, parseMeso, parseStar, toYi } from "./format.js";

const ACTION_LABEL = {
  enhance: "強化",
  scroll: "星捲",
  repair_full: "完整修復",
  repair_to_12: "修復至 12 星",
};

const OUTCOME_LABEL = {
  success: "成功",
  maintain: "維持",
  destroy: "破壞",
};

/**
 * What the page starts on, so a visitor can enhance something immediately
 * instead of picking an item first. Falls back to "不指定" when the price table
 * no longer has it - renaming or deleting it costs the default, not the page.
 */
const DEFAULT_EQUIPMENT = "頂培";

let datasets = null;
let session = null;

const el = {};

function bind() {
  for (const id of [
    "play-equipment", "play-level", "play-level-field", "play-start-star",
    "play-new", "play-name", "play-star", "play-star-grid", "play-next-star",
    "play-arrow", "play-rates", "play-cost", "play-total", "play-subtotal",
    "play-flag",
    "play-enhance", "play-scroll-star", "play-scroll", "play-repair-full",
    "play-repair-12", "play-error", "play-copy", "play-summary",
    "auto-repair", "auto-scroll", "auto-budget", "auto-budget-target",
    "auto-budget-run", "auto-budget-reset-run", "auto-star-target",
    "auto-star-budget", "auto-star-run", "auto-star-reset-run",
    "auto-star-hint", "auto-result",
  ]) {
    el[id] = document.getElementById(id);
  }
  el.logBody = document.querySelector("#play-log tbody");
}

function fillSetup() {
  const prices = store.currentPrices();
  // Only the very first fill picks the default. Later fills come from a price
  // edit, and resetting the operator's choice every time they touched a price
  // would be its own bug.
  const first = el["play-equipment"].options.length === 0;
  const chosen = el["play-equipment"].value;

  el["play-equipment"].innerHTML =
    prices.equipment
      .map(
        (item) =>
          `<option value="${item.name}">${item.name}（Lv${item.level}・${formatMeso(item.price)}）</option>`
      )
      .join("") + `<option value="">不指定（修復裝備計 0）</option>`;

  if (first) {
    const known = prices.equipment.some((item) => item.name === DEFAULT_EQUIPMENT);
    el["play-equipment"].value = known ? DEFAULT_EQUIPMENT : "";
  } else {
    // Assigning a value no option carries leaves the select empty, which is
    // exactly the right answer when the chosen equipment has just been deleted.
    el["play-equipment"].value = chosen;
  }

  el["play-level"].innerHTML = rules
    .supportedLevels()
    .map((level) => `<option value="${level}">${level}</option>`)
    .join("");
  el["play-level"].value = String(rules.supportedLevels()[2]);

  el["auto-scroll"].innerHTML =
    `<option value="">不使用</option>` +
    rules
      .starScrollStars()
      .map((star) => `<option value="${star}">${star} 星星捲</option>`)
      .join("");

  syncLevelField();
}

function syncLevelField() {
  const usingCatalogue = el["play-equipment"].value !== "";
  el["play-level-field"].hidden = usingCatalogue;
}

function chosenLevel() {
  const name = el["play-equipment"].value;
  if (name === "") {
    return Number(el["play-level"].value);
  }
  return store.lookup(name).level;
}

function showError(message) {
  el["play-error"].hidden = message === null;
  el["play-error"].textContent = message || "";
}

function newSession() {
  showError(null);
  el["auto-result"].hidden = true;
  try {
    const name = el["play-equipment"].value;
    const item = name === "" ? null : store.lookup(name);
    session = new Session({
      level: item === null ? Number(el["play-level"].value) : item.level,
      startStar: Number(el["play-start-star"].value),
      equipmentName: item === null ? null : item.name,
      equipmentPrice: item === null ? 0 : item.price,
    });
  } catch (error) {
    session = null;
    showError(error.message);
  }
  render();
}

function act(fn) {
  showError(null);
  try {
    fn();
  } catch (error) {
    showError(error.message);
  }
  render();
}

function currentPolicy() {
  const scroll = el["auto-scroll"].value;
  return autoPolicy({
    repairPolicy: el["auto-repair"].value,
    scrollStar: scroll === "" ? null : Number(scroll),
  });
}

function reportAuto(result) {
  const box = el["auto-result"];
  box.hidden = false;
  box.className = "banner";

  // A run that took no action at all reads as if it had run and got nowhere,
  // so it says plainly that nothing happened and why. The budget caps the
  // session's lifetime cost, not this run's, so a second run on the same item
  // with the same budget has nothing left to spend.
  if (result.entries.length === 0) {
    box.className = "banner warn";
    box.textContent =
      result.stop_reason === StopReason.REACHED_TARGET
        ? `已經在 ${result.star} 星，沒有需要執行的動作。`
        : "累計花費已達預算上限，這次沒有執行任何動作。要重跑一次請按「重設後模擬」。";
    return;
  }

  if (result.stop_reason === StopReason.REACHED_TARGET) {
    box.textContent = `達標：${result.star} 星，本次花費 ${formatMeso(result.spent)}`;
  } else if (result.destroyed) {
    box.className = "banner bad";
    box.textContent =
      `預算用盡，而且 ${result.star} 星痕跡還沒修復 - 剩下的錢付不起任何一種修復。` +
      `本次花費 ${formatMeso(result.spent)}`;
  } else {
    box.className = "banner warn";
    box.textContent = `預算用盡，停在 ${result.star} 星，本次花費 ${formatMeso(result.spent)}`;
  }
}

function runBudget() {
  act(() => {
    if (session === null) throw new Error("請先建立裝備");
    const budget = parseMeso(el["auto-budget"].value);
    const target = parseStar(el["auto-budget-target"].value);
    reportAuto(runWithinBudget(session, target, budget, currentPolicy()));
  });
}

function runTarget() {
  act(() => {
    if (session === null) throw new Error("請先建立裝備");
    const target = parseStar(el["auto-star-target"].value);
    const raw = el["auto-star-budget"].value.trim();
    if (raw === "") {
      throw new Error("請填保險絲預算：沒有上限的話，跑不完的組合會讓瀏覽器停不下來");
    }
    reportAuto(runToStar(session, target, parseMeso(raw), currentPolicy()));
  });
}

/**
 * Throw the current item away and run again from the 建立裝備 settings.
 *
 * The two run buttons continue the item they are given, which is what makes
 * "click a few times by hand, then let it finish" work. This is the other
 * thing people want - another independent attempt - and it has to reset first,
 * because a budget caps the session's lifetime cost and a spent session has
 * nothing left to run with.
 */
function resetAndRun(runner) {
  newSession();
  if (session === null) {
    // newSession already reported why it could not build the item; running
    // anyway would only replace that with a vaguer message.
    return;
  }
  runner();
}

/**
 * The p95 total cost of the cheapest measured route to this target, used as the
 * fuse. It is a measured figure, not a guess - and it is only a rough fit,
 * because the dataset's rows start from their own stars, not from wherever this
 * session happens to be.
 *
 * Returns {p95, hint}, with p95 null when there is nothing to suggest.
 */
function budgetSuggestion() {
  const name = el["play-equipment"].value;
  let target;
  try {
    target = parseStar(el["auto-star-target"].value);
  } catch (error) {
    return { p95: null, hint: error.message };
  }

  if (name === "" || datasets === null) {
    return {
      p95: null,
      hint: "選擇資料集內的裝備後，這裡會帶出建議的保險絲預算。",
    };
  }

  let best = null;
  for (const dataset of [datasets.simulations, datasets.marginal]) {
    if (!dataset) continue;
    for (const row of dataset.results) {
      if (row.equipment !== name || row.target_star !== target) continue;
      if (best === null || row.total_cost_mean < best.total_cost_mean) best = row;
    }
  }

  if (best === null) {
    return {
      p95: null,
      hint: `資料集裡沒有「${name}」到 ${target} 星的結果，請自行填一個上限。`,
    };
  }

  const p95 = best.total_cost_percentiles["95"];
  return {
    p95,
    hint:
      `建議上限 ${formatMeso(p95)}：資料集中「${name}」到 ${target} 星最便宜路線` +
      `（${best.start_star} 星起手、${best.repair_policy === "full" ? "完整修復" : "修復至 12 星"}）的 p95。`,
  };
}

/** Refresh the wording only. Safe to call after every action. */
function renderBudgetHint() {
  el["auto-star-hint"].textContent = budgetSuggestion().hint;
}

/**
 * Overwrite the fuse with the suggestion for what is selected now.
 *
 * Only ever called when the equipment or the target changes, and once at
 * startup. Calling it from render() would wipe a hand-typed budget on the next
 * enhancement, because render() runs after every single action.
 */
function applyBudgetSuggestion() {
  const { p95, hint } = budgetSuggestion();
  el["auto-star-hint"].textContent = hint;
  if (p95 !== null) {
    el["auto-star-budget"].value = `${toYi(p95).toFixed(1)}e`;
  }
}

function renderLog() {
  const rows = session === null ? [] : session.log;
  el.logBody.innerHTML = rows
    .map((entry) => {
      const outcome = entry.outcome === null ? "" : OUTCOME_LABEL[entry.outcome];
      const cost = entry.meso + entry.equipment_cost;
      return `<tr class="${entry.outcome === "destroy" ? "destroy" : ""}">
        <td class="num">${entry.index}</td>
        <td>${ACTION_LABEL[entry.action]}</td>
        <td>${entry.star_before} → ${entry.star_after}</td>
        <td>${outcome}</td>
        <td class="num">${formatMeso(cost)}</td>
        <td class="num">${formatMeso(entry.total_cost_after)}</td>
      </tr>`;
    })
    .join("");

  if (session === null || rows.length === 0) {
    el["play-summary"].textContent = "尚未有任何操作。";
    return;
  }
  const t = session.totals;
  el["play-summary"].textContent =
    `楓幣 ${formatMeso(t.total_meso)}　裝備成本 ${formatMeso(t.equipment_cost)}（${t.equipment_used} 件）` +
    `　總計 ${formatMeso(session.totalCost)}　星捲 ${t.scrolls_used}　強化 ${t.attempts} 次　破壞 ${t.destroys} 次`;
}

/** One row inside a panel block: label on the left, figure on the right. */
function panelRow(label, value, className = "") {
  return `<div class="sf-row"><span>${label}</span>` +
    `<span class="num ${className}">${value}</span></div>`;
}

/**
 * The star grid, five to a cluster and three clusters to a row, the way the
 * game lays it out. Slots run to the level's cap, so a 130 item shows fewer.
 */
function renderStarGrid() {
  if (session === null) {
    el["play-star-grid"].innerHTML = "";
    return;
  }
  const clusters = [];
  for (let base = 0; base < session.maxStar; base += 5) {
    const stars = [];
    for (let star = base + 1; star <= Math.min(base + 5, session.maxStar); star += 1) {
      stars.push(`<span class="sf-star${star <= session.star ? " on" : ""}">★</span>`);
    }
    clusters.push(`<span class="sf-cluster">${stars.join("")}</span>`);
  }
  el["play-star-grid"].innerHTML = clusters.join("");
}

/**
 * The odds and the fee for the attempt that is available right now.
 *
 * These are the published base figures. The game shows whatever is in effect
 * including any event bonus, so the two will not always agree - hence the note
 * in the markup rather than a silent difference.
 */
function renderNextAttempt() {
  const rates = el["play-rates"];
  const cost = el["play-cost"];

  if (session === null) {
    rates.innerHTML = panelRow("—", "—");
    cost.innerHTML = panelRow("—", "—");
    return;
  }
  if (session.destroyed) {
    rates.innerHTML = panelRow("裝備已破壞", "先修復才有下一次強化");
    cost.innerHTML = panelRow("修復費用", "見下方修復按鈕");
    return;
  }
  if (session.star >= session.maxStar) {
    rates.innerHTML = panelRow("已達等級上限", `${session.maxStar} 星`);
    cost.innerHTML = panelRow("—", "—");
    return;
  }

  const basis = rules.rateBasis();
  const [success, destroy, maintain] = rules.enhanceRates(session.star);
  const percent = (value) => `${((value / basis) * 100).toFixed(2)}%`;
  rates.innerHTML =
    panelRow("成功", percent(success), "ok-text") +
    panelRow("失敗（維持星數）", percent(maintain)) +
    panelRow("破壞", percent(destroy), "bad-text");

  const fee = rules.enhanceCost(session.level, session.star);
  cost.innerHTML =
    panelRow("本次強化", formatMeso(fee), "gold") +
    panelRow("", `${fee.toLocaleString("en-US")} 楓幣`, "muted");
}

function render() {
  const live = session !== null;
  el["play-name"].textContent = live
    ? session.equipmentName || `未指定裝備（${session.level} 等）`
    : "—";
  el["play-star"].textContent = live ? session.star : "-";

  const climbing = live && !session.destroyed && session.star < session.maxStar;
  el["play-next-star"].textContent = climbing ? session.star + 1 : "-";
  el["play-arrow"].style.visibility = climbing ? "visible" : "hidden";

  renderStarGrid();
  renderNextAttempt();

  el["play-total"].textContent = live ? formatMeso(session.totalCost) : "0.00億";
  el["play-subtotal"].textContent = live
    ? `等級 ${session.level}・上限 ${session.maxStar} 星`
    : "";

  el["play-flag"].hidden = !(live && session.destroyed);
  if (live && session.destroyed) {
    el["play-flag"].textContent = `裝備已破壞，留下 ${session.star} 星痕跡 - 先修復才能繼續。`;
  }

  el["play-enhance"].disabled = !live || !session.canEnhance;
  el["play-repair-full"].disabled = !live || !session.destroyed;
  el["play-repair-12"].disabled = !live || !session.destroyed;

  const scrolls = live ? session.availableScrolls() : [];
  const chosen = el["play-scroll-star"].value;
  el["play-scroll-star"].innerHTML = scrolls
    .map((star) => `<option value="${star}">${star} 星星捲　${formatMeso(rules.starScrollCost(star))}</option>`)
    .join("");
  if (scrolls.includes(Number(chosen))) {
    el["play-scroll-star"].value = chosen;
  }
  el["play-scroll-star"].disabled = scrolls.length === 0;
  el["play-scroll"].disabled = scrolls.length === 0;

  renderLog();
  renderBudgetHint();
}

function copyLog() {
  if (session === null || session.log.length === 0) return;
  const lines = session.log.map((entry) => {
    const outcome = entry.outcome === null ? "" : OUTCOME_LABEL[entry.outcome];
    const cost = entry.meso + entry.equipment_cost;
    return [
      String(entry.index).padStart(3),
      ACTION_LABEL[entry.action],
      `${entry.star_before} -> ${entry.star_after}`,
      outcome,
      formatMeso(cost),
      formatMeso(entry.total_cost_after),
    ].join("\t");
  });
  lines.push(el["play-summary"].textContent);
  navigator.clipboard.writeText(lines.join("\n")).then(
    () => { el["play-copy"].textContent = "已複製"; setTimeout(() => { el["play-copy"].textContent = "複製"; }, 1500); },
    (error) => showError(`複製失敗：${error.message}`)
  );
}

export function initPlay(loadedDatasets) {
  datasets = loadedDatasets;
  bind();
  fillSetup();

  el["play-equipment"].addEventListener("change", () => {
    syncLevelField();
    applyBudgetSuggestion();
  });
  el["play-level"].addEventListener("change", () => {
    el["play-start-star"].max = String(rules.maxTargetStar(chosenLevel()));
  });
  el["play-new"].addEventListener("click", newSession);
  el["play-enhance"].addEventListener("click", () => act(() => session.enhance()));
  el["play-scroll"].addEventListener("click", () =>
    act(() => session.useScroll(Number(el["play-scroll-star"].value)))
  );
  el["play-repair-full"].addEventListener("click", () =>
    act(() => session.repair(RepairPolicy.FULL))
  );
  el["play-repair-12"].addEventListener("click", () =>
    act(() => session.repair(RepairPolicy.TO_12))
  );
  el["auto-budget-run"].addEventListener("click", runBudget);
  el["auto-star-run"].addEventListener("click", runTarget);
  el["auto-budget-reset-run"].addEventListener("click", () => resetAndRun(runBudget));
  el["auto-star-reset-run"].addEventListener("click", () => resetAndRun(runTarget));
  el["auto-star-target"].addEventListener("change", applyBudgetSuggestion);
  el["play-copy"].addEventListener("click", copyLog);

  store.onChange(() => {
    fillSetup();
    render();
  });

  // The default equipment is only useful if the fuse arrives with it, so the
  // suggestion is applied once here rather than waiting for a change event.
  applyBudgetSuggestion();
  newSession();
}
