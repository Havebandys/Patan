from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any


@dataclass
class ControlState:
    label: str
    icon: str
    reason: str
    days_without_activity: int | None
    objective_days: int | None
    elapsed_days: int | None
    objective_pct: float | None
    days_since_progress: int | None
    progress_overdue: bool
    objective_overdue: bool


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def objective_days(case: dict[str, Any], settings: dict[str, Any]) -> int:
    complexity = (case.get("complexity") or "ESTANDAR").upper()
    if complexity.startswith("COMP"):
        return int(settings["complex_objective_days"])
    return int(settings["standard_objective_days"])


def evaluate_case(case: dict[str, Any], settings: dict[str, Any], today: date | None = None) -> ControlState:
    today = today or date.today()

    registered = parse_date(case.get("date_registered")) or parse_date(case.get("date_assigned")) or parse_date(case.get("date_received"))
    last_activity = parse_date(case.get("last_movement")) or registered
    last_progress = parse_date(case.get("last_progress_report"))

    days_without_activity = (today - last_activity).days if last_activity else None
    obj_days = objective_days(case, settings)
    elapsed = (today - registered).days if registered else None
    pct = (elapsed / obj_days * 100.0) if elapsed is not None and obj_days else None
    days_since_progress = (today - last_progress).days if last_progress else (elapsed if elapsed is not None else None)

    progress_interval = int(settings["progress_interval_days"])
    progress_overdue = days_since_progress is not None and days_since_progress > progress_interval
    objective_overdue = elapsed is not None and elapsed > obj_days

    red_reasons: list[str] = []
    yellow_reasons: list[str] = []

    if days_without_activity is not None and days_without_activity > int(settings["red_inactivity_days"]):
        red_reasons.append(f"{days_without_activity} días sin actividad")
    if pct is not None and pct >= float(settings["red_deadline_pct"]):
        red_reasons.append(f"{pct:.0f}% del plazo objetivo consumido")
    if progress_overdue:
        red_reasons.append("informe de avance vencido")
    if objective_overdue:
        red_reasons.append("plazo objetivo vencido")

    if red_reasons:
        return ControlState("ROJO", "🔴", "; ".join(red_reasons), days_without_activity, obj_days, elapsed, pct, days_since_progress, progress_overdue, objective_overdue)

    if days_without_activity is not None and days_without_activity > int(settings["yellow_inactivity_days"]):
        yellow_reasons.append(f"{days_without_activity} días sin actividad")
    if pct is not None and pct >= float(settings["yellow_deadline_pct"]):
        yellow_reasons.append(f"{pct:.0f}% del plazo objetivo consumido")
    if days_since_progress is not None and days_since_progress > int(settings["yellow_progress_days"]):
        yellow_reasons.append(f"{days_since_progress} días desde el último informe")

    if yellow_reasons:
        return ControlState("AMARILLO", "🟡", "; ".join(yellow_reasons), days_without_activity, obj_days, elapsed, pct, days_since_progress, progress_overdue, objective_overdue)

    return ControlState("VERDE", "🟢", "Gestión dentro de parámetros", days_without_activity, obj_days, elapsed, pct, days_since_progress, progress_overdue, objective_overdue)


def business_day_deadline(start: date | None, business_days: int) -> date | None:
    if not start:
        return None
    d = start
    added = 0
    while added < business_days:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def case_hitos(case: dict[str, Any], settings: dict[str, Any]) -> dict[str, date | None]:
    assigned = parse_date(case.get("date_assigned"))
    registered = parse_date(case.get("date_registered")) or assigned
    obj = objective_days(case, settings)
    return {
        "analisis_preliminar": business_day_deadline(assigned, int(settings["preliminary_business_days"])),
        "primer_requerimiento": business_day_deadline(registered, int(settings["first_request_business_days"])),
        "plazo_objetivo": (registered + timedelta(days=obj)) if registered else None,
    }
