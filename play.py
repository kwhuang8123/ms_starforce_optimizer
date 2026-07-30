"""Interactive entry point: run this file and drive the enhancement by hand.

Same shape as ``main.py`` - edit the SETTINGS block, or pass the same names as
``main()`` keywords - except this one reads commands instead of simulating a
whole climb. Every action is charged and logged as it happens; ``log`` prints
the whole record and ``q`` prints it one last time on the way out.

Amounts accept the shorthand used around this project: ``100e`` is 100億, and a
bare number means the same thing. Stars accept ``22c`` or a bare ``22``.

Commands
    e                       one enhancement attempt
    s <star>                buy and apply that star scroll, e.g. ``s 17c``
    b                       list the breakthrough scrolls usable right now
    b <cap> <percent>       use one, e.g. ``b 23 50`` for 突破23星50%
    r full | r 12           repair a destroyed item
    auto star <star>        climb to a star, with BUDGET_CAP as the fuse
    auto budget <meso> <star>   spend up to <meso> chasing <star>
    log                     the full action log and the totals
    status                  where the item stands right now
    help                    this list
    q                       quit
"""

from __future__ import annotations

from starforce import rules, static_data, volatile_data
from starforce.autorun import (
    AutoPolicy,
    AutoRunResult,
    StopReason,
    run_to_star,
    run_within_budget,
)
from starforce.engine import RepairPolicy
from starforce.session import Session
from starforce.units import YI, format_meso

# ---------------------------------------------------------------------------
# SETTINGS - edit these
# ---------------------------------------------------------------------------

#: Equipment name, alias, or digit variant, e.g. "頂培" or "永恆上4".
#: Its level and price come from data/volatile.json. Set to None to fall back
#: to LEVEL below and value the equipment repairs consume at zero.
EQUIPMENT: str | None = "頂培"

#: Item level, used only when EQUIPMENT is None.
LEVEL = 150

#: Where the item starts. 0 is a fresh item; nothing is charged to reach it.
START_STAR = 0

#: Seed for reproducible runs, or None to let the OS pick.
SEED: int | None = None

#: Fuse for ``auto star``: stop once the session's total cost would pass this.
#: Fill it from the sweep dataset - the p95 total cost for the same equipment
#: and target - so the ceiling reflects measured runs instead of a guess.
#: While it is None, ``auto star`` refuses to run.
BUDGET_CAP: int | None = None

#: Which repair an automatic run buys when the item is destroyed.
AUTO_REPAIR = RepairPolicy.FULL

#: The star scroll an automatic run uses: applied at the start when the item is
#: below it, and again after every 12 star repair. None to never scroll.
AUTO_SCROLL_STAR: int | None = None

# ---------------------------------------------------------------------------


def parse_meso(text: str) -> int:
    """Read ``100e``, ``100億`` or ``100`` as 100億 in raw meso."""
    cleaned = text.strip().replace(",", "").rstrip("eE億")
    try:
        amount = float(cleaned)
    except ValueError:
        raise ValueError(f"{text!r} is not an amount; write it like 100e") from None
    if amount <= 0:
        raise ValueError(f"an amount must be positive, got {text!r}")
    return round(amount * YI)


def parse_star(text: str) -> int:
    """Read ``22c``, ``22星`` or ``22`` as the star 22."""
    cleaned = text.strip().rstrip("cC星")
    try:
        return int(cleaned)
    except ValueError:
        raise ValueError(f"{text!r} is not a star; write it like 22c") from None


def parse_percent(text: str) -> int:
    """Read ``50`` or ``50%`` as the 5,000 basis points the rules speak in."""
    cleaned = text.strip().rstrip("%")
    try:
        percent = float(cleaned)
    except ValueError:
        raise ValueError(f"{text!r} is not a rate; write it like 50") from None
    return round(percent * static_data.RATE_BASIS / 100)


def describe_breakthrough(cap_star: int, success: int) -> str:
    """One listing line: how to type this scroll, and what it costs."""
    percent = success * 100 / static_data.RATE_BASIS
    command = f"b {cap_star} {percent:g}"
    return (
        f"  {command:<12}up to {cap_star} stars, {percent:g}% success, "
        f"{format_meso(rules.breakthrough_cost(cap_star, success))}"
    )


def build_session(
    equipment: str | None, level: int, start_star: int, seed: int | None
) -> Session:
    """A session for the catalogue equipment, or for a bare level."""
    if equipment is None:
        return Session(level=level, start_star=start_star, seed=seed)
    return Session.for_equipment(equipment, start_star=start_star, seed=seed)


def print_prices(session: Session) -> None:
    """Show the volatile prices this session depends on."""
    print(f"volatile prices from {volatile_data.SOURCE_PATH}")
    if session.equipment_name is None:
        print("  equipment  (none - repair equipment valued at 0)")
    else:
        print(
            f"  equipment  {session.equipment_name}  level {session.level}  "
            f"{format_meso(session.equipment_price)}"
        )
    if AUTO_SCROLL_STAR is not None:
        print(
            f"  {AUTO_SCROLL_STAR:>2} star scroll  "
            f"{format_meso(rules.star_scroll_cost(AUTO_SCROLL_STAR))}"
        )
    print()


def print_result(result: AutoRunResult) -> None:
    """Report what an automatic run did and why it stopped."""
    for entry in result.entries:
        print(entry.describe())
    if result.stop_reason is StopReason.REACHED_TARGET:
        note = f"reached {result.star} stars"
    elif result.destroyed:
        note = (
            f"budget exhausted, and the {result.star} star trace is still "
            f"destroyed - it cannot afford a repair"
        )
    else:
        note = f"budget exhausted at {result.star} stars"
    print(f"  -> {note}; this run spent {format_meso(result.spent)}")


def handle(
    session: Session, policy: AutoPolicy, budget_cap: int | None, command: str
) -> bool:
    """Run one command. Returns False when the operator asked to quit."""
    # A byte order mark rides in on the first line when commands are piped in
    # on Windows, and would otherwise look like an unknown command.
    parts = command.replace("\ufeff", "").split()
    if not parts:
        return True

    verb, args = parts[0].lower(), parts[1:]

    if verb in ("q", "quit", "exit"):
        return False

    if verb in ("h", "help", "?"):
        print(__doc__)
    elif verb in ("e", "enhance"):
        print(session.enhance().describe())
    elif verb in ("s", "scroll"):
        if len(args) != 1:
            raise ValueError("scroll needs a star, e.g. 's 17c'")
        print(session.use_scroll(parse_star(args[0])).describe())
    elif verb in ("b", "break"):
        _handle_breakthrough(session, args)
    elif verb in ("r", "repair"):
        if len(args) != 1 or args[0] not in ("full", "12"):
            raise ValueError("repair needs a policy: 'r full' or 'r 12'")
        chosen = RepairPolicy.FULL if args[0] == "full" else RepairPolicy.TO_12
        print(session.repair(chosen).describe())
    elif verb == "auto":
        _handle_auto(session, policy, budget_cap, args)
    elif verb == "log":
        print(session.report())
    elif verb in ("status", "st"):
        print(session.headline())
    else:
        raise ValueError(f"unknown command {verb!r}; type 'help' for the list")

    return True


def _handle_breakthrough(session: Session, args: list[str]) -> None:
    """``b`` lists the scrolls that apply right now; ``b <cap> <percent>`` uses one."""
    if not args:
        if session.destroyed:
            print(f"  the {session.star} star trace has to be repaired first")
            return
        usable = rules.available_breakthroughs(session.star, session.level)
        if not usable:
            print(f"  no breakthrough scroll applies at {session.star} stars")
            return
        for cap_star, success in usable:
            print(describe_breakthrough(cap_star, success))
        return

    if len(args) != 2:
        raise ValueError(
            "breakthrough needs a cap and a rate, e.g. 'b 23 50'; "
            "type 'b' on its own to list what applies"
        )
    entry = session.use_breakthrough(parse_star(args[0]), parse_percent(args[1]))
    print(entry.describe())


def _handle_auto(
    session: Session, policy: AutoPolicy, budget_cap: int | None, args: list[str]
) -> None:
    """``auto star <star>`` or ``auto budget <meso> <star>``."""
    if not args:
        raise ValueError("auto needs a mode: 'auto star ...' or 'auto budget ...'")

    mode = args[0].lower()
    if mode == "star":
        if len(args) != 2:
            raise ValueError("auto star needs a target, e.g. 'auto star 22c'")
        if budget_cap is None:
            raise ValueError(
                "BUDGET_CAP is not set, so 'auto star' has no fuse and could run "
                "unbounded; fill it in play.py from the sweep's p95 total cost, "
                "or use 'auto budget <meso> <star>'"
            )
        target = parse_star(args[1])
        print(f"climbing to {target} stars, capped at {format_meso(budget_cap)}")
        print_result(run_to_star(session, target, budget_cap, policy))
    elif mode == "budget":
        if len(args) != 3:
            raise ValueError(
                "auto budget needs an amount and a target, e.g. "
                "'auto budget 100e 22c'"
            )
        budget = parse_meso(args[1])
        target = parse_star(args[2])
        print(f"chasing {target} stars with {format_meso(budget)}")
        print_result(run_within_budget(session, target, budget, policy))
    else:
        raise ValueError(f"unknown auto mode {mode!r}; use 'star' or 'budget'")


def main(
    equipment: str | None = EQUIPMENT,
    level: int = LEVEL,
    start_star: int = START_STAR,
    seed: int | None = SEED,
    budget_cap: int | None = BUDGET_CAP,
    auto_repair: RepairPolicy = AUTO_REPAIR,
    auto_scroll_star: int | None = AUTO_SCROLL_STAR,
) -> Session:
    """Read commands until the operator quits, then print the final log."""
    session = build_session(equipment, level, start_star, seed)
    policy = AutoPolicy(repair_policy=auto_repair, scroll_star=auto_scroll_star)

    print_prices(session)
    print(session.headline())
    print("type 'help' for the command list\n")

    while True:
        try:
            command = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        try:
            if not handle(session, policy, budget_cap, command):
                break
        except ValueError as error:
            # An operator typo or an illegal move: say what was wrong and let
            # them try again. Anything else is a bug and should surface.
            print(f"! {error}")

    print()
    print(session.report())
    return session


if __name__ == "__main__":
    main(
        equipment=EQUIPMENT,
        level=LEVEL,
        start_star=START_STAR,
        seed=SEED,
        budget_cap=BUDGET_CAP,
        auto_repair=AUTO_REPAIR,
        auto_scroll_star=AUTO_SCROLL_STAR,
    )
