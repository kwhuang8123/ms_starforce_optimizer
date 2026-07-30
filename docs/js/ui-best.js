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

let datasets = null;
const el = {};

function bind() {
  for (const id of [
    "best-meta",
    "best-reprice-note",
    "best-policy-note",
    "best-start",
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

function renderScratch(prices) {
  const dataset = datasets.simulations;
  if (!dataset) {
    el.scratch.innerHTML = `<tr><td colspan="10">資料集尚未產生。</td></tr>`;
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
  renderScratch(prices);
  renderMarginal(prices);
}

export function initBest(loadedDatasets) {
  datasets = loadedDatasets;
  bind();
  fillStartFilter();
  el["best-start"].addEventListener("change", render);
  store.onChange(render);
  render();
}
