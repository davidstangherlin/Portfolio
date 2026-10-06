"""ORM models mapping onto the tables created by `db/schema.sql`.

Always import models from this package (`from src.models import Company`),
not from the individual submodules directly - relationships between models
are declared as string references and only resolve once every module has
been imported into SQLAlchemy's mapper registry, which happens here.
"""

from src.models.base import Base
from src.models.company import Company
from src.models.daily_price import DailyPrice
from src.models.dividend_payment import DividendPayment
from src.models.etf import EtfMonthly, EtfPerformance
from src.models.financial_report import FinancialReport
from src.models.holding import Holding
from src.models.portfolio import Portfolio
from src.models.scenario import Scenario
from src.models.signal_snapshot import SignalSnapshot
from src.models.valuation_metric import ValuationMetric
from src.models.watchlist import Watchlist, WatchlistItem

__all__ = [
    "Base",
    "Company",
    "DailyPrice",
    "DividendPayment",
    "EtfMonthly",
    "EtfPerformance",
    "FinancialReport",
    "Holding",
    "Portfolio",
    "Scenario",
    "SignalSnapshot",
    "ValuationMetric",
    "Watchlist",
    "WatchlistItem",
]
