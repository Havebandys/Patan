from __future__ import annotations
from datetime import date, timedelta
try:
    import holidays
except Exception:
    holidays = None

COMARB_CALENDAR_URL = "https://www.ca.gob.ar/servicios/calendario"


def _ar_holidays(year: int):
    if holidays is None:
        return set()
    try:
        return set(holidays.Argentina(years=[year]).keys())
    except Exception:
        return set()


def is_business_day(d: date, extra_holidays: set[date] | None = None) -> bool:
    extra_holidays = extra_holidays or set()
    return d.weekday() < 5 and d not in _ar_holidays(d.year) and d not in extra_holidays


def next_business_day(d: date, extra_holidays: set[date] | None = None) -> date:
    out = d
    while not is_business_day(out, extra_holidays):
        out += timedelta(days=1)
    return out


def proposed_notification_date(sent_date: date, extra_holidays: set[date] | None = None) -> date:
    """Primer martes o viernes estrictamente posterior al envío; si es inhábil, corre al hábil siguiente."""
    d = sent_date + timedelta(days=1)
    while d.weekday() not in (1, 4):  # martes=1, viernes=4
        d += timedelta(days=1)
    return next_business_day(d, extra_holidays)


def add_business_days(base: date, days: int, extra_holidays: set[date] | None = None) -> date:
    """Suma días hábiles a partir del día siguiente a la fecha base."""
    d = base
    count = 0
    while count < max(0, int(days)):
        d += timedelta(days=1)
        if is_business_day(d, extra_holidays):
            count += 1
    return d


def business_days_remaining(due: date, today: date | None = None, extra_holidays: set[date] | None = None) -> int:
    today = today or date.today()
    if due == today:
        return 0
    sign = 1 if due > today else -1
    a, b = (today, due) if due > today else (due, today)
    n = 0
    d = a
    while d < b:
        d += timedelta(days=1)
        if is_business_day(d, extra_holidays):
            n += 1
    return sign * n
