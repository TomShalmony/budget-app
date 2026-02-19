from datetime import date
from calendar import monthrange

# Zone C (Versailles / Île-de-France) school holidays 2025-2026
# Each tuple is (first_day_of_vacation, last_day_of_vacation) inclusive.
# School resumes the day after the end date.
SCHOOL_HOLIDAYS = [
    (date(2025, 10, 18), date(2025, 11, 2)),   # Toussaint   (resumes Nov 3)
    (date(2025, 12, 20), date(2026, 1, 4)),    # Noël        (resumes Jan 5)
    (date(2026, 2, 21), date(2026, 3, 8)),     # Hiver       (resumes Mar 9)
    (date(2026, 4, 18), date(2026, 5, 3)),     # Printemps   (resumes May 4)
    (date(2026, 5, 14), date(2026, 5, 17)),    # Ascension   (resumes May 18)
    (date(2026, 7, 4),  date(2026, 8, 31)),    # Été         (resumes Sep 2026)
]

# French public holidays relevant to the 2025-2026 school year
PUBLIC_HOLIDAYS = {
    date(2025, 11, 1),   # Toussaint (during vacation anyway)
    date(2025, 11, 11),  # Armistice
    date(2025, 12, 25),  # Noël (during vacation)
    date(2026, 1, 1),    # Nouvel An (during vacation)
    date(2026, 4, 6),    # Lundi de Pâques
    date(2026, 5, 1),    # Fête du Travail
    date(2026, 5, 8),    # Victoire 1945
    date(2026, 5, 14),   # Ascension (during vacation)
    date(2026, 5, 25),   # Lundi de Pentecôte
    date(2026, 7, 14),   # Fête Nationale (summer)
    date(2026, 8, 15),   # Assomption (summer)
}


def is_school_day(d):
    """Returns True if d is a regular school day."""
    if d.weekday() >= 5:        # Saturday or Sunday
        return False
    if d in PUBLIC_HOLIDAYS:    # Public holiday
        return False
    for start, end in SCHOOL_HOLIDAYS:
        if start <= d <= end:   # School vacation
            return False
    return True


def calculate_girls_food(year, month):
    """
    Calculate girls' school canteen cost for a given month.
    Counts school days that are NOT Wednesday, multiplied by 2 × €5.10 = €10.20/day.
    (Two meals per non-Wednesday school day at €5.10 each.)
    """
    days_in_month = monthrange(year, month)[1]
    count = 0
    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        if d.weekday() == 2:    # Wednesday — no canteen
            continue
        if is_school_day(d):
            count += 1
    return round(count * 10.2, 2)


def calculate_days_until_25():
    """Days remaining until the 25th of this month (or next month if past 25th)."""
    today = date.today()
    if today.day < 25:
        return 25 - today.day
    else:
        if today.month == 12:
            next_25 = date(today.year + 1, 1, 25)
        else:
            next_25 = date(today.year, today.month + 1, 25)
        return (next_25 - today).days
