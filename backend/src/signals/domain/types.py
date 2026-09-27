"""Shared enums and constants. Values are part of the data contract (stored in the DB)."""

from enum import StrEnum


class Direction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    OTHER = "other"


class Basis(StrEnum):
    FILED = "filed"
    EXECUTED = "executed"


class Horizon(StrEnum):
    M1 = "1m"
    M3 = "3m"
    M6 = "6m"
    M12 = "12m"


HORIZON_TRADING_DAYS: dict[Horizon, int] = {
    Horizon.M1: 21,
    Horizon.M3: 63,
    Horizon.M6: 126,
    Horizon.M12: 252,
}


class Window(StrEnum):
    YTD = "ytd"
    Y1 = "1y"
    Y3 = "3y"
    Y5 = "5y"


WINDOW_TRADING_DAYS: dict[Window, int] = {Window.Y1: 252, Window.Y3: 756, Window.Y5: 1260}


class Role(StrEnum):
    CEO = "CEO"
    CFO = "CFO"
    COO = "COO"
    PRESIDENT = "President"
    CHAIR = "Chair"
    GENERAL_COUNSEL = "General Counsel"
    OTHER_OFFICER = "Other officer"
    DIRECTOR = "Director"
    TEN_PCT_OWNER = "10% owner"
    OTHER = "Other"


ROLE_PRIORITY: tuple[Role, ...] = (
    Role.CEO,
    Role.CFO,
    Role.PRESIDENT,
    Role.COO,
    Role.CHAIR,
    Role.GENERAL_COUNSEL,
    Role.OTHER_OFFICER,
    Role.DIRECTOR,
    Role.TEN_PCT_OWNER,
    Role.OTHER,
)


class PlanFlag(StrEnum):
    FLAG = "flag"
    FOOTNOTE = "footnote"
    NONE = "none"


class ChangeType(StrEnum):
    NEW = "NEW"
    ADD = "ADD"
    TRIM = "TRIM"
    EXIT = "EXIT"
    SAME = "SAME"


class ProfileKind(StrEnum):
    INSIDER = "insider"
    FUND = "fund"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLabel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ParseStatus(StrEnum):
    PENDING = "pending"
    PARSED = "parsed"
    ERROR = "error"
    SKIPPED = "skipped"


class JobStatus(StrEnum):
    REQUESTED = "requested"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Sector(StrEnum):
    MATERIALS = "Materials"
    COMMUNICATION = "Communication Services"
    ENERGY = "Energy"
    FINANCIALS = "Financials"
    INDUSTRIALS = "Industrials"
    TECHNOLOGY = "Technology"
    STAPLES = "Consumer Staples"
    REAL_ESTATE = "Real Estate"
    UTILITIES = "Utilities"
    HEALTH_CARE = "Health Care"
    DISCRETIONARY = "Consumer Discretionary"


SECTOR_ETF: dict[Sector, str] = {
    Sector.MATERIALS: "XLB",
    Sector.COMMUNICATION: "XLC",
    Sector.ENERGY: "XLE",
    Sector.FINANCIALS: "XLF",
    Sector.INDUSTRIALS: "XLI",
    Sector.TECHNOLOGY: "XLK",
    Sector.STAPLES: "XLP",
    Sector.REAL_ESTATE: "XLRE",
    Sector.UTILITIES: "XLU",
    Sector.HEALTH_CARE: "XLV",
    Sector.DISCRETIONARY: "XLY",
}

BENCHMARK_SYMBOLS: tuple[str, ...] = ("SPY", "QQQ", *SECTOR_ETF.values())


class Badge(StrEnum):
    CLUSTER_BUY = "cluster_buy"
    LATE_FILING = "late_filing"
    FIRST_BUY_2Y = "first_buy_2y"
    DIP_BUY = "dip_buy"
    BIG_STAKE = "big_stake"
    FORM144_MATCHED = "form144_matched"
    TOP_EXEC = "top_exec"


INSIDER_FORMS = frozenset({"3", "3/A", "4", "4/A", "5", "5/A"})
FORM144_FORMS = frozenset({"144", "144/A"})
FUND_FORMS = frozenset({"13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A"})
STAKE_FORMS = frozenset({"SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A"})
TRACKED_FORMS = INSIDER_FORMS | FORM144_FORMS | FUND_FORMS | STAKE_FORMS

# Base form types polled on the live feed; "/A" variants match via the category term.
FEED_POLL_FORMS: tuple[str, ...] = (
    "3",
    "4",
    "5",
    "144",
    "13F-HR",
    "SCHEDULE 13D",
    "SCHEDULE 13G",
)

CODE_LABELS: dict[str, str] = {
    "P": "Open-market buy",
    "S": "Open-market sale",
    "A": "Grant/award",
    "M": "Option exercise",
    "X": "In-the-money exercise",
    "O": "Out-of-the-money exercise",
    "F": "Tax withholding",
    "G": "Gift",
    "C": "Conversion",
    "D": "Disposition to issuer",
    "E": "Short derivative expired",
    "H": "Long derivative expired",
    "I": "Discretionary transaction",
    "J": "Other",
    "L": "Small acquisition",
    "U": "Tender in change of control",
    "W": "Will or inheritance",
    "Z": "Voting trust",
}
