"""Market calendar for Indian NSE sessions."""

from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from src.core.config import settings


# Timezone constants
IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


class MarketCalendar:
    """Handles NSE market hours and timezone conversions."""

    def __init__(self) -> None:
        self.pre_open = time(9, 0)
        self.open = time(9, 15)
        self.close = time(15, 30)
        self.post_close = time(15, 40)

    def now_ist(self) -> datetime:
        """Current time in IST."""
        return datetime.now(IST)

    def now_utc(self) -> datetime:
        """Current time in UTC."""
        return datetime.now(UTC)

    def to_ist(self, dt: datetime) -> datetime:
        """Convert any datetime to IST."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(IST)

    def to_utc(self, dt: datetime) -> datetime:
        """Convert any datetime to UTC."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(UTC)

    def is_market_open(self, dt: Optional[datetime] = None) -> bool:
        """Check if market is open (regular hours)."""
        if dt is None:
            dt = self.now_ist()
        else:
            dt = self.to_ist(dt)

        # Check weekday (Mon-Fri = 0-4)
        if dt.weekday() >= 5:
            return False

        current_time = dt.time()
        return self.open <= current_time <= self.close

    def is_pre_open(self, dt: Optional[datetime] = None) -> bool:
        """Check if in pre-open session."""
        if dt is None:
            dt = self.now_ist()
        else:
            dt = self.to_ist(dt)

        if dt.weekday() >= 5:
            return False

        current_time = dt.time()
        return self.pre_open <= current_time < self.open

    def is_post_close(self, dt: Optional[datetime] = None) -> bool:
        """Check if in post-close session."""
        if dt is None:
            dt = self.now_ist()
        else:
            dt = self.to_ist(dt)

        if dt.weekday() >= 5:
            return False

        current_time = dt.time()
        return self.close < current_time <= self.post_close

    def time_until_open(self, dt: Optional[datetime] = None) -> timedelta:
        """Time until next market open."""
        if dt is None:
            dt = self.now_ist()
        else:
            dt = self.to_ist(dt)

        next_open = datetime.combine(dt.date(), self.open, tzinfo=IST)
        if dt.time() >= self.open:
            # Market already opened today, next open is tomorrow
            next_open += timedelta(days=1)
            # Skip weekends
            while next_open.weekday() >= 5:
                next_open += timedelta(days=1)

        return next_open - dt

    def time_until_close(self, dt: Optional[datetime] = None) -> timedelta:
        """Time until market closes today."""
        if dt is None:
            dt = self.now_ist()
        else:
            dt = self.to_ist(dt)

        close_time = datetime.combine(dt.date(), self.close, tzinfo=IST)
        if dt > close_time:
            return timedelta(0)
        return close_time - dt

    def get_session_date(self, dt: Optional[datetime] = None) -> str:
        """Get the trading session date string (YYYYMMDD)."""
        if dt is None:
            dt = self.now_ist()
        else:
            dt = self.to_ist(dt)
        return dt.strftime("%Y%m%d")


# Singleton
market_calendar = MarketCalendar()
