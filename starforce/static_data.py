"""Fixed data: the official MapleStory TW star force tables.

These only change when NEXON publishes a new balance patch. Anything that moves
with the market - star scroll prices, equipment prices - lives in
:mod:`starforce.volatile_data` instead.

Sources (V272, effective 2025-07-30):
    Enhancement rates and costs
        https://maplestory.beanfun.com/bulletin?bid=74681
    Equipment trace repair costs
        https://maplestory-event.beanfun.com/eventad/eventad?eventadid=17655

All values are transcribed verbatim from the announcements. One figure looks
like an anomaly but is exactly what the official table publishes and is kept
as-is:
    - level 140, 21 -> 22 (92,474,100) is dearer than 22 -> 23 (65,166,700)

The one exception is BREAKTHROUGH_SCROLLS, which is the list of scrolls sold
in game rather than a figure from either announcement above. It is fixed data
all the same - a patch is what changes which scrolls exist - so it belongs
here, but it has no announcement URL to check it against.

Level 130 is not carried at all. The announcement publishes no level 130 repair
column, so a destroyed 130 item has no knowable cost, and no equipment in the
catalogue is that level. Its enhancement table lived here until it was removed
as an unused path; git history has it if it is ever needed.
"""

from __future__ import annotations

# Probabilities are stored in basis points (1 / 10_000) so that every row sums
# to exactly 10_000 with integer arithmetic. Keys are the *current* star, i.e.
# key 15 describes the 15 -> 16 attempt.
#
#            current star: (success, destroy, maintain)
ENHANCE_RATES: dict[int, tuple[int, int, int]] = {
    0: (9500, 0, 500),
    1: (9000, 0, 1000),
    2: (8500, 0, 1500),
    3: (8500, 0, 1500),
    4: (8000, 0, 2000),
    5: (7500, 0, 2500),
    6: (7000, 0, 3000),
    7: (6500, 0, 3500),
    8: (6000, 0, 4000),
    9: (5500, 0, 4500),
    10: (5000, 0, 5000),
    11: (4500, 0, 5500),
    12: (4000, 0, 6000),
    13: (3500, 0, 6500),
    14: (3000, 0, 7000),
    15: (3000, 210, 6790),
    16: (3000, 210, 6790),
    17: (1500, 680, 7820),
    18: (1200, 820, 7980),
    19: (1000, 900, 8100),
    20: (3000, 1050, 5950),
    21: (2000, 1150, 6850),
    22: (1750, 1225, 7025),
    23: (850, 1800, 7350),
    24: (850, 1800, 7350),
    25: (800, 1800, 7400),
    26: (700, 1860, 7440),
    27: (500, 1900, 7600),
    28: (300, 1940, 7760),
    29: (100, 1980, 7920),
}

RATE_BASIS = 10_000

# Levels this project simulates. Levels 0-120 are not covered by the
# announcement ("please refer to the client"), and level 130 is excluded because
# the repair table has no column for it - see the module docstring.
SUPPORTED_LEVELS: tuple[int, ...] = (140, 150, 160, 200, 250)

# Meso cost of a single enhancement attempt, keyed by item level then by the
# *current* star.
ENHANCE_COST: dict[int, dict[int, int]] = {
    140: {
        0: 77_200,
        1: 153_400,
        2: 229_700,
        3: 305_900,
        4: 382_100,
        5: 458_300,
        6: 534_600,
        7: 610_800,
        8: 687_000,
        9: 763_200,
        10: 3_116_400,
        11: 7_166_500,
        12: 13_051_200,
        13: 21_729_500,
        14: 38_411_200,
        15: 39_138_900,
        16: 48_020_200,
        17: 61_127_200,
        18: 172_905_500,
        19: 297_882_700,
        20: 50_974_700,
        21: 92_474_100,
        22: 65_166_700,
        23: 73_102_200,
        24: 81_620_200,
        25: 90_737_500,
        26: 100_471_000,
        27: 110_837_000,
        28: 121_851_900,
        29: 133_531_800,
    },
    150: {
        0: 94_800,
        1: 188_500,
        2: 282_300,
        3: 376_000,
        4: 469_800,
        5: 563_500,
        6: 657_300,
        7: 751_000,
        8: 844_800,
        9: 938_500,
        10: 3_832_800,
        11: 8_814_200,
        12: 16_052_200,
        13: 26_726_100,
        14: 47_243_900,
        15: 48_139_000,
        16: 59_062_500,
        17: 75_183_500,
        18: 212_666_000,
        19: 366_382_500,
        20: 62_696_400,
        21: 113_738_800,
        22: 80_152_000,
        23: 89_912_300,
        24: 100_389_000,
        25: 111_603_000,
        26: 123_574_700,
        27: 136_324_400,
        28: 149_872_300,
        29: 164_238_100,
    },
    160: {
        0: 114_800,
        1: 228_600,
        2: 342_300,
        3: 456_100,
        4: 569_900,
        5: 683_700,
        6: 797_400,
        7: 911_200,
        8: 1_025_000,
        9: 1_138_800,
        10: 4_651_300,
        11: 10_697_000,
        12: 19_481_200,
        13: 32_435_400,
        14: 57_336_400,
        15: 58_422_700,
        16: 71_679_800,
        17: 91_244_700,
        18: 258_097_500,
        19: 444_652_400,
        20: 76_090_000,
        21: 138_036_600,
        22: 97_274_600,
        23: 109_120_000,
        24: 121_834_900,
        25: 135_444_400,
        26: 149_973_700,
        27: 165_447_100,
        28: 181_889_200,
        29: 199_324_000,
    },
    200: {
        0: 223_200,
        1: 445_400,
        2: 667_700,
        3: 889_900,
        4: 1_112_100,
        5: 1_334_300,
        6: 1_556_600,
        7: 1_778_800,
        8: 2_001_000,
        9: 2_223_200,
        10: 9_083_700,
        11: 20_891_500,
        12: 38_048_200,
        13: 63_349_500,
        14: 111_984_100,
        15: 114_105_800,
        16: 139_998_700,
        17: 178_211_400,
        18: 504_095_800,
        19: 868_460_800,
        20: 148_612_400,
        21: 269_601_800,
        22: 189_988_600,
        23: 213_124_000,
        24: 237_957_700,
        25: 264_539_000,
        26: 292_916_400,
        27: 323_138_000,
        28: 355_251_400,
        29: 389_303_700,
    },
    250: {
        0: 435_000,
        1: 869_100,
        2: 1_303_100,
        3: 1_737_100,
        4: 2_171_100,
        5: 2_605_200,
        6: 3_039_200,
        7: 3_473_200,
        8: 3_907_300,
        9: 4_341_300,
        10: 17_740_600,
        11: 40_802_800,
        12: 74_312_000,
        13: 123_728_500,
        14: 218_718_100,
        15: 222_861_900,
        16: 273_434_000,
        17: 348_068_200,
        18: 984_561_100,
        19: 1_696_211_500,
        20: 387_009_800,
        21: 438_804_400,
        22: 494_760_300,
        23: 555_008_800,
        24: 619_680_000,
        25: 688_902_000,
        26: 762_801_400,
        27: 841_503_600,
        28: 925_132_300,
        29: 1_013_810_000,
    },
}

# Full repair: meso cost keyed by item level then by the trace's star. Every
# supported level has a column here; that is precisely why 130 is not supported.
REPAIR_MESO: dict[int, dict[int, int]] = {
    140: {
        15: 149_000_000,
        16: 484_000_000,
        17: 896_000_000,
        18: 1_950_000_000,
        19: 3_790_000_000,
        20: 8_030_000_000,
        21: 10_100_000_000,
        22: 14_100_000_000,
    },
    150: {
        15: 183_000_000,
        16: 596_000_000,
        17: 1_110_000_000,
        18: 2_400_000_000,
        19: 4_660_000_000,
        20: 9_880_000_000,
        21: 12_400_000_000,
        22: 17_300_000_000,
    },
    160: {
        15: 222_000_000,
        16: 723_000_000,
        17: 1_340_000_000,
        18: 2_910_000_000,
        19: 5_650_000_000,
        20: 12_000_000_000,
        21: 15_000_000_000,
        22: 21_000_000_000,
    },
    200: {
        15: 433_000_000,
        16: 1_420_000_000,
        17: 2_620_000_000,
        18: 5_670_000_000,
        19: 11_100_000_000,
        20: 23_500_000_000,
        21: 29_200_000_000,
        22: 41_000_000_000,
    },
    250: {
        15: 846_000_000,
        16: 2_760_000_000,
        17: 5_100_000_000,
        18: 11_100_000_000,
        19: 21_600_000_000,
        20: 45_800_000_000,
        21: 57_100_000_000,
        22: 80_100_000_000,
    },
}

# Full repair: how many identical equipment pieces the repair consumes.
REPAIR_EQUIPMENT: dict[int, int] = {
    15: 1,
    16: 1,
    17: 1,
    18: 1,
    19: 2,
    20: 2,
    21: 3,
    22: 4,
}

# Star scroll: sets an item's star force directly to the scroll's star. Which
# scrolls exist is a fixed rule; what they cost is not, and lives in
# starforce.volatile_data. The 10 to 14 star scrolls were dropped: they all cost
# the same as each other, carry no destruction risk, and no strategy worth
# measuring starts below 15.
STAR_SCROLL_STARS: tuple[int, ...] = tuple(range(15, 21))

# Breakthrough scroll: one attempt at a single extra star. Success adds a star,
# failure leaves the item exactly where it was - there is no destruction, so
# nothing here touches the repair tables.
#
# Each scroll is identified by two things: the star it will not take an item
# past, and its success rate. A scroll may be used from any star as long as the
# extra star would not exceed its cap, so the 21 star scroll is spent at 20 and
# nowhere higher.
#
# Rates are in basis points, the same unit ENHANCE_RATES uses. That is also why
# the id below is built from basis points rather than from a percentage: a
# future scroll priced at a fraction of a percent would otherwise collide with
# an existing one. 21 and 22 stars only exist at 100%; 26 stars has no 100%
# version. Prices live in starforce.volatile_data.
#
#                            (cap star, success rate)
BREAKTHROUGH_SCROLLS: tuple[tuple[int, int], ...] = (
    (21, 10_000),
    (22, 10_000),
    (23, 3_000),
    (23, 5_000),
    (23, 10_000),
    (24, 3_000),
    (24, 5_000),
    (24, 10_000),
    (25, 3_000),
    (25, 5_000),
    (25, 10_000),
    (26, 3_000),
    (26, 5_000),
)


def breakthrough_id(cap_star: int, success: int) -> str:
    """Key for one breakthrough scroll, e.g. ``"23-3000"`` for 突破23星30%.

    Two numbers identify a scroll, and both JSON objects and DOM attributes
    need a single string. This is that string, defined once so the price file,
    the generated site data and the front end cannot drift apart.
    """
    return f"{cap_star}-{success}"
