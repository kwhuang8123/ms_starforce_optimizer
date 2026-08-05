/**
 * The cheat sheet: one line per equipment and target.
 *
 * Condensing a few hundred measured rows into eighteen conclusions throws
 * information away, so this tab says out loud where the conclusion is thin:
 *
 *   - When the best and second-best routes are within 1% of each other they are
 *     inside the sampling noise of a 50,000 trial run, so the winner would flip
 *     on a different seed. Those rows show the runner-up too.
 *   - The cheapest route is not always the most predictable one. A "stable"
 *     alternative is offered only when trading mean for tail is actually worth
 *     it, and the price of that trade is always shown.
 *   - The breakthrough policy each row follows was chosen against the sweep's
 *     prices. policy.js re-derives the cheapest one for the prices in effect
 *     now, and the table says so when the two have parted company.
 *
 * The mean is re-priced for whatever prices are in effect; percentiles are not,
 * because changing a price reorders the trials. Every column that depends on a
 * percentile is therefore labelled as belonging to the sweep's own prices.
 */

import * as rules from "./rules.js";
import * as store from "./prices-store.js";
import { rebuildBasis, repricedMean } from "./reprice.js";
import { describe, expectedTotal, optimalPolicy, sameEntries } from "./policy.js";
import { formatYi } from "./format.js";

const POLICY_LABEL = { full: "完整修復", to_12: "修復至 12 星" };

/**
 * How much cheaper a freshly derived policy has to be before the dataset is
 * called stale. The stored means are sampled and the derived one is exact, so
 * they disagree by a few tenths of a percent even when they agree perfectly;
 * 1% is comfortably outside that and matches the near-tie bar below.
 */
const POLICY_DRIFT = 0.01;

/** Within this, best and second-best are a coin flip rather than a ranking. */
const NEAR_TIE = 0.01;

/**
 * A stable alternative has to clear both bars: it must improve the tail by more
 * than it costs on the mean, and the improvement has to beat the noise floor.
 * Without the first bar the table would recommend paying 28% more to shave 2.4%
 * off p95, which is help nobody asked for.
 */
const MIN_P95_GAIN = 0.01;

/** What the query card opens on, matching the manual tab's default item. */
const DEFAULT_EQUIPMENT = "頂培";

let datasets = null;
const el = {};

function bind() {
  for (const id of [
    "best-meta",
    "best-reprice-note",
    "best-policy-note",
    "best-start",
    "ask-equipment",
    "ask-mode",
    "ask-target",
    "ask-answer",
  ]) {
    el[id] = document.getElementById(id);
  }
  el.scratch = document.querySelector("#best-scratch tbody");
  el.marginal = document.querySelector("#best-marginal tbody");
}

function routeLabel(row) {
  const base = `${row.start_star} 星起手・${POLICY_LABEL[row.repair_policy]}`;
  const entries = row.breakthrough_entries;
  if (!entries || entries.length === 0) {
    return base;
  }
  return `${base}<br><span class="muted">${describe({ entries })}</span>`;
}

/** Targets whose breakthrough policies the sweep actually explored. */
function exploredTargets(dataset) {
  return new Set(dataset.meta.breakthrough_targets || []);
}

/**
 * The cheapest policy at the prices in effect right now, derived rather than
 * looked up, across every start star and repair policy the dataset covers.
 *
 * This is the whole point of shipping the solver to the browser: the rows were
 * measured against a policy chosen at the sweep's prices, so once those prices
 * move the stored ranking can quietly stop being the answer. Re-deriving costs
 * nothing and catches it.
 */
function liveOptimum(equipment, targetStar, startStars, prices) {
  const item = prices.equipment.find((entry) => entry.name === equipment);
  if (item === undefined) {
    return null;
  }
  let best = null;
  for (const startStar of startStars) {
    for (const repairPolicy of ["full", "to_12"]) {
      const options = {
        level: item.level,
        startStar,
        targetStar,
        equipmentPrice: item.price,
        repairPolicy,
      };
      let chosen;
      let total;
      try {
        chosen = optimalPolicy(options);
        total = expectedTotal(chosen, options);
      } catch (error) {
        // A start star the level cannot use, or a target past its cap. The
        // other combinations still answer the question.
        continue;
      }
      if (best === null || total < best.total) {
        best = { total, startStar, repairPolicy, policy: chosen };
      }
    }
  }
  return best;
}

function percentile(row, label) {
  return row.total_cost_percentiles[label];
}

/** Attach the mean at today's prices, dropping rows that cannot be worked out. */
function priced(rows, prices) {
  const basis = datasets.simulations
    ? rebuildBasis(datasets.simulations.results, prices)
    : new Map();
  return rows
    .map((row) => {
      const rebuild = basis.has(row.equipment) ? basis.get(row.equipment) : null;
      return { ...row, repriced: repricedMean(row, prices, rebuild) };
    })
    .filter((row) => row.repriced !== null);
}

function group(rows, keyOf) {
  const out = new Map();
  for (const row of rows) {
    const key = keyOf(row);
    if (!out.has(key)) {
      out.set(key, []);
    }
    out.get(key).push(row);
  }
  return out;
}

/**
 * Cheapest by mean; ties broken by p50; still tied and the order is left alone,
 * which means whatever order the generator wrote them in.
 */
function rank(candidates) {
  return [...candidates].sort((a, b) => {
    if (a.repriced !== b.repriced) {
      return a.repriced - b.repriced;
    }
    return percentile(a, "50") - percentile(b, "50");
  });
}

/** The stable alternative, or null when no candidate earns the recommendation. */
function stableAlternative(candidates, best) {
  let calmest = null;
  for (const row of candidates) {
    if (calmest === null || percentile(row, "95") < percentile(calmest, "95")) {
      calmest = row;
    }
  }
  if (calmest === null || calmest === best) {
    return null;
  }

  const meanCost = calmest.repriced / best.repriced - 1;
  const tailGain = 1 - percentile(calmest, "95") / percentile(best, "95");
  if (tailGain < MIN_P95_GAIN || tailGain <= meanCost) {
    return null;
  }
  return { row: calmest, meanCost, tailGain };
}

/** The scroll shortcut for a row, marked when it beats the measured route. */
function scrollCell(best) {
  const scroll = scrollShortcut(best.target_star);
  if (scroll === null) {
    return `<span class="muted">—</span>`;
  }
  const text = formatYi(scroll.price);
  if (scroll.price >= best.repriced) {
    return `<span class="muted">${text}</span>`;
  }
  return (
    `<span class="ok-text strong">${text}</span>` +
    `<br><span class="muted">省 ${((1 - scroll.price / best.repriced) * 100).toFixed(0)}%</span>`
  );
}

function nearTieCell(ordered) {
  if (ordered.length < 2) {
    return "—";
  }
  const gap = ordered[1].repriced / ordered[0].repriced - 1;
  const text = `${(gap * 100).toFixed(2)}%`;
  if (gap >= NEAR_TIE) {
    return text;
  }
  return (
    `<span class="bad-text">${text}</span>` +
    `<br><span class="muted">誤差內，等同 ${routeLabel(ordered[1])}</span>`
  );
}

/**
 * Buying the target's own star scroll and stopping there.
 *
 * A scroll sets an item straight to its star, so for any target a scroll exists
 * for, "buy that scroll" is a complete route: no attempts, no destruction, and
 * a cost that is simply the price - p50 and p95 both land on it.
 *
 * The sweep cannot express this. A SCROLL run buys its start_star scroll and
 * then climbs, and RunConfig requires the target to exceed the start, so a
 * zero-attempt route has no configuration to be. It does not need one: there is
 * nothing random about it, and comparing it is arithmetic rather than sampling.
 *
 * Priced from the live table, not the dataset snapshot, because the answer to
 * "should I just buy the scroll" moves with the scroll's price.
 *
 * Returns null when no scroll reaches the target - 21 stars and above.
 */
function scrollShortcut(target) {
  if (!rules.starScrollStars().includes(target)) {
    return null;
  }
  return { star: target, price: rules.starScrollCost(target) };
}

// ---------------------------------------------------------------------------
// The query card: one equipment, one situation, one answer
// ---------------------------------------------------------------------------

/**
 * The situations the datasets can actually answer for.
 *
 * A from-scratch run buys its way in with a star scroll; an owned run starts
 * from an item that is already there. They live in different datasets with
 * different target ranges, so the situation picks the dataset as well as the
 * starting point - and only situations with rows behind them are offered.
 */
function situations() {
  const out = [];
  if (datasets.simulations) {
    out.push({ value: "scratch", label: "從零開始（買星捲起手）" });
  }
  if (datasets.marginal) {
    const stars = [
      ...new Set(datasets.marginal.results.map((row) => row.start_star)),
    ].sort((a, b) => a - b);
    for (const star of stars) {
      out.push({ value: `owned-${star}`, label: `已持有 ${star} 星` });
    }
  }
  return out;
}

/** The dataset and start-star filter a situation means. */
function situationOf(value) {
  if (value === "scratch") {
    return { dataset: datasets.simulations, startStar: null };
  }
  return {
    dataset: datasets.marginal,
    startStar: Number(value.slice("owned-".length)),
  };
}

function fillAsk() {
  const modes = situations();
  el["ask-mode"].innerHTML = modes
    .map((mode) => `<option value="${mode.value}">${mode.label}</option>`)
    .join("");

  // Equipment comes from the datasets rather than the price table: an item with
  // no rows behind it is a question this card cannot answer, and offering it
  // would only lead somewhere empty.
  const names = [];
  for (const dataset of [datasets.simulations, datasets.marginal]) {
    if (!dataset) continue;
    for (const row of dataset.results) {
      if (!names.includes(row.equipment)) {
        names.push(row.equipment);
      }
    }
  }
  el["ask-equipment"].innerHTML = names
    .map((name) => `<option value="${name}">${name}</option>`)
    .join("");
  el["ask-equipment"].value = names.includes(DEFAULT_EQUIPMENT)
    ? DEFAULT_EQUIPMENT
    : names[0];

  fillAskTargets();
}

/** Targets depend on the situation, so this runs again whenever it changes. */
function fillAskTargets() {
  const { dataset, startStar } = situationOf(el["ask-mode"].value);
  const chosen = el["ask-target"].value;
  const stars = dataset
    ? [
        ...new Set(
          dataset.results
            .filter((row) => startStar === null || row.start_star === startStar)
            .map((row) => row.target_star)
        ),
      ].sort((a, b) => a - b)
    : [];

  el["ask-target"].innerHTML = stars
    .map((star) => `<option value="${star}">${star} 星</option>`)
    .join("");
  // Keep the target across a situation change when it still exists, so moving
  // from "已持有 22 星" to "已持有 23 星" does not silently retarget.
  el["ask-target"].value = stars.map(String).includes(chosen)
    ? chosen
    : String(stars[0]);
}

function answerLine(label, value) {
  return `<div class="ask-line"><span>${label}</span><span>${value}</span></div>`;
}

function renderAsk(prices) {
  const box = el["ask-answer"];
  const equipment = el["ask-equipment"].value;
  const target = Number(el["ask-target"].value);
  const mode = el["ask-mode"].value;
  const { dataset, startStar } = situationOf(mode);

  if (!dataset || equipment === "" || Number.isNaN(target)) {
    box.innerHTML = `<p class="muted">資料集尚未產生，沒有可以回答的內容。</p>`;
    return;
  }

  const candidates = priced(dataset.results, prices).filter(
    (row) =>
      row.equipment === equipment &&
      row.target_star === target &&
      (startStar === null || row.start_star === startStar)
  );

  if (candidates.length === 0) {
    // Either the sweep never covered this, or the equipment has been renamed or
    // deleted on the price page and its rows can no longer be re-priced.
    box.innerHTML =
      `<p class="banner warn">算不出這一組的現價成本。可能是資料集沒有「${equipment}」到 ` +
      `${target} 星的結果，或這件裝備已經從物價表移除。</p>`;
    return;
  }

  const ordered = rank(candidates);
  const best = ordered[0];
  const stable = stableAlternative(candidates, best);
  const explored = new Set(dataset.meta.breakthrough_targets || []);
  const scroll = scrollShortcut(target);
  const scrollWins = scroll !== null && scroll.price < best.repriced;

  // When a scroll reaches the target for less than the cheapest measured climb,
  // it is the answer - not a footnote to a dearer one. It also cannot go wrong,
  // so it has no distribution to show: the price is the p50 and the p95.
  const parts = scrollWins
    ? [
        `<div class="ask-head">
           <span class="ask-cost">${formatYi(scroll.price)}</span>
           <span class="muted">確定花費・現價</span>
         </div>`,
        `<div class="ask-route">直接買 ${scroll.star} 星星捲</div>`,
        answerLine(
          "風險",
          `<span class="ok-text">無</span>` +
            `<span class="muted">　一次強化都不做，不會破壞</span>`
        ),
        answerLine(
          "改用模擬出的最省路線",
          `${routeLabel(best)}<br><span class="muted">平均 ${formatYi(best.repriced)}，` +
            `貴 ${((best.repriced / scroll.price - 1) * 100).toFixed(1)}%</span>`
        ),
      ]
    : [
        `<div class="ask-head">
           <span class="ask-cost">${formatYi(best.repriced)}</span>
           <span class="muted">平均總成本・現價</span>
         </div>`,
        `<div class="ask-route">${routeLabel(best)}</div>`,
        answerLine(
          "p50 / p95<small>快照價</small>",
          `${formatYi(percentile(best, "50"))} / ${formatYi(percentile(best, "95"))}`
        ),
        answerLine("與次佳差距", nearTieCell(ordered)),
      ];

  // Everything below qualifies the measured climb. A winning scroll is cheaper
  // than that climb and cannot go wrong, so it dominates every alternative
  // those notes could point at - a stable variant, a policy the dataset has
  // not caught up with - and printing them anyway would bury the answer under
  // caveats about a route nobody should take.
  if (scrollWins) {
    box.innerHTML = parts.join("");
    return;
  }

  // "Should I just buy the scroll" deserves an answer even when it is no.
  if (scroll !== null) {
    parts.push(
      answerLine(
        `直接買 ${scroll.star} 星星捲`,
        `${formatYi(scroll.price)}<br><span class="muted">貴 ` +
          `${((scroll.price / best.repriced - 1) * 100).toFixed(1)}%，不划算</span>`
      )
    );
  }

  if (stable !== null) {
    parts.push(
      answerLine(
        "穩定解<small>快照價</small>",
        `${routeLabel(stable.row)}<br>` +
          `<span class="muted">平均多付 ${(stable.meanCost * 100).toFixed(1)}%、` +
          `p95 省 ${(stable.tailGain * 100).toFixed(1)}%</span>`
      )
    );
  }

  if (!explored.has(target)) {
    parts.push(
      `<p class="muted">這個目標尚未納入突破星捲，上面的走法只比較了強化與修復方式。</p>`
    );
  } else if (mode === "scratch") {
    const startStars = [
      ...new Set(dataset.results.map((row) => row.start_star)),
    ].sort((a, b) => a - b);
    const live = liveOptimum(equipment, target, startStars, prices);
    if (
      live !== null &&
      live.total < best.repriced * (1 - POLICY_DRIFT) &&
      !(
        live.startStar === best.start_star &&
        live.repairPolicy === best.repair_policy &&
        sameEntries(live.policy.entries, best.breakthrough_entries || [])
      )
    ) {
      parts.push(
        `<p class="banner warn">目前物價下有更便宜的走法：` +
          `${live.startStar} 星起手・${POLICY_LABEL[live.repairPolicy]}` +
          `（${describe(live.policy)}），平均約 ${formatYi(live.total)}，` +
          `再省 ${((1 - live.total / best.repriced) * 100).toFixed(1)}%。` +
          `這是用現價即時解出來的精確平均，沒有對應的 p50／p95 —— 要讓資料集跟上請重跑 sweep。</p>`
      );
    }
  }

  box.innerHTML = parts.join("");
}

function renderScratch(prices) {
  const dataset = datasets.simulations;
  if (!dataset) {
    el.scratch.innerHTML = `<tr><td colspan="11">資料集尚未產生。</td></tr>`;
    return;
  }

  const groups = group(
    priced(dataset.results, prices),
    (row) => `${row.equipment} ${row.target_star}`
  );
  const explored = exploredTargets(dataset);
  const startStars = [
    ...new Set(dataset.results.map((row) => row.start_star)),
  ].sort((a, b) => a - b);
  const stale = [];

  const lines = [];
  for (const candidates of groups.values()) {
    const ordered = rank(candidates);
    const best = ordered[0];
    const stable = stableAlternative(candidates, best);

    if (explored.has(best.target_star)) {
      const live = liveOptimum(
        best.equipment, best.target_star, startStars, prices
      );
      if (
        live !== null &&
        live.total < best.repriced * (1 - POLICY_DRIFT) &&
        !(
          live.startStar === best.start_star &&
          live.repairPolicy === best.repair_policy &&
          sameEntries(live.policy.entries, best.breakthrough_entries || [])
        )
      ) {
        stale.push({ row: best, live });
      }
    }

    lines.push(`<tr>
      <td>${best.equipment}</td>
      <td class="num">${best.target_star} 星${
        explored.has(best.target_star)
          ? ""
          : `<br><span class="muted">未納入突破星捲</span>`
      }</td>
      <td>${routeLabel(best)}</td>
      <td class="num strong">${formatYi(best.repriced)}</td>
      <td class="num">${formatYi(percentile(best, "50"))}</td>
      <td class="num">${formatYi(percentile(best, "95"))}</td>
      <td class="num">${scrollCell(best)}</td>
      <td class="num">${nearTieCell(ordered)}</td>
      <td>${stable === null ? "—" : routeLabel(stable.row)}</td>
      <td class="num">${
        stable === null ? "—" : `+${(stable.meanCost * 100).toFixed(1)}%`
      }</td>
      <td class="num">${
        stable === null
          ? "—"
          : `<span class="ok-text">−${(stable.tailGain * 100).toFixed(1)}%</span>`
      }</td>
    </tr>`);
  }
  el.scratch.innerHTML = lines.join("");
  renderPolicyNote(stale);
}

/**
 * Say so when the current prices have moved the answer off the dataset.
 *
 * The stored means are still exact for the policies they measured - what has
 * gone stale is which policy is best. Nothing here overwrites the table: the
 * measured rows are real, and a derived figure has no percentiles to show
 * beside them, so this points at the gap rather than papering over it.
 */
function renderPolicyNote(stale) {
  const note = el["best-policy-note"];
  if (stale.length === 0) {
    note.hidden = true;
    note.innerHTML = "";
    return;
  }
  const lines = stale
    .map(({ row, live }) => {
      const saving = 1 - live.total / row.repriced;
      return (
        `<li><strong>${row.equipment} ${row.target_star} 星</strong>：` +
        `改用 ${live.startStar} 星起手・${POLICY_LABEL[live.repairPolicy]}` +
        `（${describe(live.policy)}）平均約 ${formatYi(live.total)}，` +
        `比表上這列再省 ${(saving * 100).toFixed(1)}%</li>`
      );
    })
    .join("");
  note.hidden = false;
  note.innerHTML =
    `<strong>目前物價下，資料集挑出的最優解已經不是最優。</strong>` +
    `下面這 ${stale.length} 組有更便宜的走法，是用現價即時解出來的精確平均` +
    `（沒有對應的 p50／p95，因為那需要重跑 sweep）：<ul>${lines}</ul>` +
    `要讓整張表跟上，重跑 <code>sweep.py</code> 與 <code>build_site_data.py</code>。`;
}

function fillStartFilter() {
  const dataset = datasets.marginal;
  if (!dataset) {
    return;
  }
  const stars = [...new Set(dataset.results.map((row) => row.start_star))].sort(
    (a, b) => a - b
  );
  const chosen = el["best-start"].value;
  el["best-start"].innerHTML = stars
    .map((star) => `<option value="${star}">${star} 星</option>`)
    .join("");
  el["best-start"].value = stars.map(String).includes(chosen)
    ? chosen
    : String(stars[0]);
}

function renderMarginal(prices) {
  const dataset = datasets.marginal;
  if (!dataset) {
    el.marginal.innerHTML = `<tr><td colspan="7">資料集尚未產生。</td></tr>`;
    return;
  }

  const start = Number(el["best-start"].value);
  const rows = priced(dataset.results, prices).filter(
    (row) => row.start_star === start
  );
  const groups = group(rows, (row) => `${row.equipment} ${row.target_star}`);

  const lines = [];
  for (const candidates of groups.values()) {
    const ordered = rank(candidates);
    const best = ordered[0];
    lines.push(`<tr>
      <td>${best.equipment}</td>
      <td class="num">${best.target_star} 星</td>
      <td>${POLICY_LABEL[best.repair_policy]}</td>
      <td class="num strong">${formatYi(best.repriced)}</td>
      <td class="num">${formatYi(percentile(best, "50"))}</td>
      <td class="num">${formatYi(percentile(best, "95"))}</td>
      <td class="num">${nearTieCell(ordered)}</td>
    </tr>`);
  }
  el.marginal.innerHTML =
    lines.length === 0
      ? `<tr><td colspan="7">這個起始星數沒有資料。</td></tr>`
      : lines.join("");
}

function renderNotes() {
  const parts = [];
  for (const [label, dataset] of [
    ["從零開始", datasets.simulations],
    ["已持有", datasets.marginal],
  ]) {
    parts.push(
      dataset
        ? `${label} 產生於 ${dataset.meta.generated_at}，每組 ${dataset.meta.trials.toLocaleString(
            "en-US"
          )} 次，已完成目標 ${(dataset.meta.targets_completed || []).join("、")} 星`
        : `${label} 尚未產生`
    );
  }
  el["best-meta"].textContent = parts.join("　|　");

  const note = el["best-reprice-note"];
  note.hidden = !store.isModified();
  note.textContent =
    "「平均」已依目前的物價重新計算，但 p50、p95、以及據此挑出的穩定解仍是資料集自己那組價格下的結果 —— " +
    "分位數無法重新計價，因為換價格會改變每次試驗之間的排序。要讓它們跟上，請重跑 sweep.py 與 build_site_data.py。";
}

function render() {
  const prices = store.currentPrices();
  renderNotes();
  renderAsk(prices);
  renderScratch(prices);
  renderMarginal(prices);
}

export function initBest(loadedDatasets) {
  datasets = loadedDatasets;
  bind();
  fillStartFilter();
  fillAsk();

  el["best-start"].addEventListener("change", render);
  el["ask-mode"].addEventListener("change", () => {
    fillAskTargets();
    render();
  });
  for (const id of ["ask-equipment", "ask-target"]) {
    el[id].addEventListener("change", render);
  }

  store.onChange(render);
  render();
}
