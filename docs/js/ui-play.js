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
import { equipmentIcon, iconOrText, iconTag, scrollIcon } from "./assets.js";
import { formatMeso, formatYi, parseMeso, parseStar, toYi } from "./format.js";

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

/**
 * A finished automatic run being played back, or null.
 *
 * The engine runs to completion in one go, so by the time there is anything to
 * show the session already holds the final state. Playback therefore reads the
 * panel out of the log entry at `index` rather than out of the session - every
 * figure it needs is on the entry. Nothing about the engine changes for this.
 *
 * While it is running every action is locked: letting the session move while
 * the display is deliberately behind is how the two get out of step.
 */
let replay = null;

/**
 * A star gained by hand, waiting for its pop. Playback carries the same thing
 * on the log entry it is showing; a live action has no entry to hang it on, and
 * it has to be cleared after one render or every later repaint - a price edit,
 * a tab switch - would replay the animation.
 */
let pendingPop = null;

const ANIMATION_KEY = "ms-starforce/animate";

//: Playback aims to finish inside this, however many entries there are.
const REPLAY_BUDGET_MS = 6000;
const REPLAY_MIN_STEP_MS = 40;
const REPLAY_MAX_STEP_MS = 400;

const el = {};

function bind() {
  for (const id of [
    "play-equipment", "play-owned",
    "play-new", "play-icon", "play-star", "play-star-grid",
    "play-next-star", "play-arrow", "play-rates", "play-cost", "play-total",
    "play-subtotal", "play-flag",
    "play-enhance", "play-scrolls", "play-repair-full",
    "play-repair-12", "play-error", "play-copy", "play-summary",
    "play-animate", "play-skip",
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

  el["play-equipment"].innerHTML = prices.equipment
    .map(
      (item) =>
        `<option value="${item.name}">${item.name}（Lv${item.level}・${formatMeso(item.price)}）</option>`
    )
    .join("");

  if (first) {
    const known = prices.equipment.some((item) => item.name === DEFAULT_EQUIPMENT);
    el["play-equipment"].value = known
      ? DEFAULT_EQUIPMENT
      : prices.equipment[0].name;
  } else {
    // Assigning a value no option carries leaves the select empty, which is
    // exactly the right answer when the chosen equipment has just been deleted.
    el["play-equipment"].value = chosen;
  }

  el["auto-scroll"].innerHTML =
    `<option value="">不使用</option>` +
    rules
      .starScrollStars()
      .map((star) => `<option value="${star}">${star} 星星捲</option>`)
      .join("");

  syncOwned();
}

/**
 * Where a fresh item starts: nothing, or the star an owned one is worth
 * modelling from.
 *
 * 22 is not a magic number here - it is the star the engine prices a rebuild
 * against, so it comes from the same table rather than being written twice. No
 * scroll reaches it, which is exactly why the option has to exist: without it
 * the "I already hold a 22 star item" case cannot be simulated at all.
 */
function startStar() {
  if (!el["play-owned"].checked) {
    return 0;
  }
  return rules.rebuildStar();
}

/** Hide the option on any level that cannot reach the rebuild star. */
function syncOwned() {
  const name = el["play-equipment"].value;
  if (name === "") {
    return;
  }
  const cap = rules.maxTargetStar(store.lookup(name).level);
  const reachable = rules.rebuildStar() <= cap;
  el["play-owned"].disabled = !reachable;
  if (!reachable) {
    el["play-owned"].checked = false;
  }
}

function showError(message) {
  el["play-error"].hidden = message === null;
  el["play-error"].textContent = message || "";
}

function newSession() {
  stopReplay(false);
  showError(null);
  el["auto-result"].hidden = true;
  try {
    const item = store.lookup(el["play-equipment"].value);
    session = new Session({
      level: item.level,
      startStar: startStar(),
      equipmentName: item.name,
      equipmentPrice: item.price,
    });
  } catch (error) {
    session = null;
    showError(error.message);
  }
  render();
}

/**
 * What the panel should be showing: the live session, or the frame of the
 * playback currently on screen.
 *
 * Everything comes off a single log entry. An item is destroyed only in the
 * instant after a destruction, and the entry that repairs it carries no
 * outcome, so `outcome === "destroy"` is the whole test.
 */
function view() {
  if (session === null) {
    return null;
  }
  if (replay === null) {
    return {
      star: session.star,
      destroyed: session.destroyed,
      total: session.totalCost,
      logCount: session.log.length,
      live: true,
      gained: pendingPop,
    };
  }
  const entry = replay.entries[replay.index];
  return {
    star: entry.star_after,
    destroyed: entry.outcome === "destroy",
    total: entry.total_cost_after,
    logCount: replay.firstEntry + replay.index + 1,
    live: false,
    entry,
  };
}

/** True unless the operator or the system has asked for no motion. */
function animationsOn() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return false;
  }
  return el["play-animate"].checked;
}

/** Replay the outcome of a single hand-driven action. Never blocks. */
function flashOutcome(outcome) {
  if (outcome === null || !animationsOn()) {
    return;
  }
  const card = document.querySelector(".starforce");
  const className = `flash-${outcome}`;
  card.classList.remove("flash-success", "flash-maintain", "flash-destroy");
  // Force a reflow so re-clicking the same outcome restarts the animation.
  void card.offsetWidth;
  card.classList.add(className);
  window.setTimeout(() => card.classList.remove(className), 700);
}

function act(fn) {
  showError(null);
  const before = session === null ? 0 : session.log.length;
  try {
    fn();
  } catch (error) {
    showError(error.message);
  }

  // Only a hand-driven action lands exactly one entry; an automatic run adds
  // many and animates them itself.
  const single =
    session !== null && session.log.length === before + 1 && replay === null;
  const entry = single ? session.log[session.log.length - 1] : null;
  if (entry !== null && entry.outcome === "success" && animationsOn()) {
    pendingPop = entry.star_after;
  }

  render();
  pendingPop = null;

  if (entry !== null) {
    flashOutcome(entry.outcome);
  }
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

/**
 * Play a finished run back one entry at a time.
 *
 * The step is scaled so the whole thing lands inside REPLAY_BUDGET_MS: a ten
 * entry run plays slowly, a hundred and forty entry run fast-forwards, and
 * neither leaves the operator waiting. With animation off, or nothing to show,
 * it reports straight away exactly as before.
 */
function startReplay(result) {
  stopReplay(false);
  if (!animationsOn() || result.entries.length === 0) {
    reportAuto(result);
    render();
    return;
  }

  replay = {
    entries: result.entries,
    // entries is the tail of the log, so this is where the run began.
    firstEntry: session.log.length - result.entries.length,
    index: 0,
    result,
    timer: null,
  };

  const step = Math.min(
    REPLAY_MAX_STEP_MS,
    Math.max(REPLAY_MIN_STEP_MS, Math.round(REPLAY_BUDGET_MS / result.entries.length))
  );
  el["play-skip"].hidden = false;
  render();

  replay.timer = window.setInterval(() => {
    replay.index += 1;
    if (replay.index >= replay.entries.length) {
      stopReplay(true);
      return;
    }
    render();
  }, step);
}

/** End playback, whether it ran out or was skipped. Always clears the timer. */
function stopReplay(report) {
  if (replay === null) {
    return;
  }
  window.clearInterval(replay.timer);
  const { result } = replay;
  replay = null;
  el["play-skip"].hidden = true;
  if (report) {
    reportAuto(result);
  }
  render();
}

function runBudget() {
  act(() => {
    if (session === null) throw new Error("請先建立裝備");
    const budget = parseMeso(el["auto-budget"].value);
    const target = parseStar(el["auto-budget-target"].value);
    startReplay(runWithinBudget(session, target, budget, currentPolicy()));
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
    startReplay(runToStar(session, target, parseMeso(raw), currentPolicy()));
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

function renderLog(state) {
  // During playback the table grows a row at a time, so it stays in step with
  // the panel instead of showing the ending before the panel gets there.
  const rows = state === null ? [] : session.log.slice(0, state.logCount);
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
  if (!state.live) {
    // The session totals are already final, so quoting them here would run
    // ahead of the rows on screen. Show progress instead.
    el["play-summary"].textContent =
      `重播中　${replay.index + 1} / ${replay.entries.length} 筆`;
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
function renderStarGrid(state) {
  if (state === null) {
    el["play-star-grid"].innerHTML = "";
    return;
  }
  // The star just gained pops; during playback that is what carries the sense
  // of progress, since nothing else on the panel moves.
  const gained =
    state.entry !== undefined
      ? state.entry.outcome === "success"
        ? state.entry.star_after
        : null
      : state.gained;

  const clusters = [];
  for (let base = 0; base < session.maxStar; base += 5) {
    const stars = [];
    for (let star = base + 1; star <= Math.min(base + 5, session.maxStar); star += 1) {
      const classes =
        (star <= state.star ? "sf-star on" : "sf-star") +
        (star === gained ? " just-on" : "");
      stars.push(`<span class="${classes}">★</span>`);
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
function renderNextAttempt(state) {
  const rates = el["play-rates"];
  const cost = el["play-cost"];

  if (state === null) {
    rates.innerHTML = panelRow("—", "—");
    cost.innerHTML = panelRow("—", "—");
    return;
  }
  if (state.destroyed) {
    rates.innerHTML = panelRow("裝備已破壞", "先修復才有下一次強化");
    cost.innerHTML = panelRow("修復費用", "見下方修復按鈕");
    return;
  }
  if (state.star >= session.maxStar) {
    rates.innerHTML = panelRow("已達等級上限", `${session.maxStar} 星`);
    cost.innerHTML = panelRow("—", "—");
    return;
  }

  const basis = rules.rateBasis();
  const [success, destroy, maintain] = rules.enhanceRates(state.star);
  const percent = (value) => `${((value / basis) * 100).toFixed(2)}%`;
  rates.innerHTML =
    panelRow("成功", percent(success), "ok-text") +
    panelRow("失敗（維持星數）", percent(maintain)) +
    panelRow("破壞", percent(destroy), "bad-text");

  const fee = rules.enhanceCost(session.level, state.star);
  cost.innerHTML = panelRow(
    "費用",
    `${formatMeso(fee)}<span class="muted">　${fee.toLocaleString("en-US")} 楓幣</span>`,
    "gold"
  );
}

/**
 * The scrolls that would actually raise this item, one button each.
 *
 * A click spends immediately - there is no confirm step - so the star and the
 * price are on the face of every button. That is the only guard available when
 * a 20 star scroll costs 330億 and one click buys it.
 */
function renderScrolls(state) {
  // No buttons during playback: the session has already moved on, so anything
  // offered here would be acting on a state the screen is not showing.
  const stars = state === null || !state.live ? [] : session.availableScrolls();
  if (stars.length === 0) {
    el["play-scrolls"].innerHTML = "";
    return;
  }
  const icon = scrollIcon();
  el["play-scrolls"].innerHTML = stars
    .map((star) => {
      const price = rules.starScrollCost(star);
      // Without artwork the star reads as plain text; with it, the number sits
      // on the corner of the icon the way an item count does in game.
      const art = icon
        ? `<span class="sf-scroll-art">${iconTag(icon, "星捲", "sf-scroll-img")}` +
          `<span class="sf-scroll-star">${star}</span></span>`
        : `<span class="sf-scroll-star plain">${star} 星</span>`;
      // The compact form keeps the chip narrow enough that eleven of them wrap
      // into two rows on a phone rather than three; the full figure is one
      // hover away, and the log records it exactly either way.
      return `<button class="sf-scroll" data-star="${star}"
        title="${star} 星星捲，點下去直接花費 ${formatMeso(price)}">
        ${art}
        <span class="sf-scroll-price">${formatYi(price)}</span>
      </button>`;
    })
    .join("");
}

/** The item's artwork, or its name when there is none for it. */
function renderIcon() {
  if (session === null) {
    el["play-icon"].innerHTML = "";
    return;
  }
  const name = session.equipmentName;
  const label = name || `${session.level} 等`;
  el["play-icon"].innerHTML = iconOrText(
    equipmentIcon(name),
    label,
    "sf-icon-img",
    `<span class="sf-icon-text">${label}</span>`
  );
}

function render() {
  const state = view();
  const has = state !== null;
  const playing = replay !== null;

  // The name is the select itself now, so there is nothing to write here.
  renderIcon();
  el["play-star"].textContent = has ? state.star : "-";

  const climbing = has && !state.destroyed && state.star < session.maxStar;
  el["play-next-star"].textContent = climbing ? state.star + 1 : "-";
  el["play-arrow"].style.visibility = climbing ? "visible" : "hidden";

  renderStarGrid(state);
  renderNextAttempt(state);

  el["play-total"].textContent = has ? formatMeso(state.total) : "0.00億";
  el["play-subtotal"].textContent = has
    ? `等級 ${session.level}・上限 ${session.maxStar} 星`
    : "";

  el["play-flag"].hidden = !(has && state.destroyed);
  if (has && state.destroyed) {
    el["play-flag"].textContent = `裝備已破壞，留下 ${state.star} 星痕跡 - 先修復才能繼續。`;
  }

  // Nothing may act while playback is behind the session, or the two diverge.
  el["play-enhance"].disabled = playing || !has || !session.canEnhance;
  el["play-repair-full"].disabled = playing || !has || !session.destroyed;
  el["play-repair-12"].disabled = playing || !has || !session.destroyed;
  for (const id of [
    "play-new",
    "auto-budget-run",
    "auto-star-run",
    "auto-budget-reset-run",
    "auto-star-reset-run",
  ]) {
    el[id].disabled = playing;
  }

  renderScrolls(state);
  renderLog(state);
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

  // Equipment and the starting star are the only settings left, and neither can
  // be applied to an item already under way, so changing either starts a new one.
  el["play-equipment"].addEventListener("change", () => {
    syncOwned();
    applyBudgetSuggestion();
    newSession();
  });
  el["play-owned"].addEventListener("change", newSession);
  el["play-new"].addEventListener("click", newSession);
  el["play-enhance"].addEventListener("click", () => act(() => session.enhance()));
  // Delegated: the buttons are rebuilt on every render.
  el["play-scrolls"].addEventListener("click", (event) => {
    const button = event.target.closest("[data-star]");
    if (button !== null) {
      act(() => session.useScroll(Number(button.dataset.star)));
    }
  });
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
  el["play-skip"].addEventListener("click", () => stopReplay(true));

  el["play-animate"].checked =
    window.localStorage.getItem(ANIMATION_KEY) !== "off";
  el["play-animate"].addEventListener("change", () => {
    window.localStorage.setItem(
      ANIMATION_KEY,
      el["play-animate"].checked ? "on" : "off"
    );
    if (!el["play-animate"].checked) {
      stopReplay(true);
    }
  });

  store.onChange(() => {
    fillSetup();
    render();
  });

  // The default equipment is only useful if the fuse arrives with it, so the
  // suggestion is applied once here rather than waiting for a change event.
  applyBudgetSuggestion();
  newSession();
}
