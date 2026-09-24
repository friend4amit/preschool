"""Turning report rows into a file, without knowing what a response is.

These build a CSV into a string and hand it back. The view wraps it in an
`HttpResponse` and picks a filename; nothing here imports `django.http`, so the export
can be tested by reading the text rather than by parsing a response — and the same
function will serve a scheduled email attachment in a later phase without being
rewritten.

`\\r\\n` line endings, which is what `csv.writer` does by default and what RFC 4180
asks for. The school opens these in Excel, and Excel on Windows is the reason the
default is the right one.
"""

import csv
import io
from datetime import date as date_type

from apps.attendance.models import AttendanceStatus

# The mark that appears in a printed register. Single characters, because the register
# is a grid 31 columns wide and anything longer stops fitting on one sheet of A4.
REGISTER_MARKS = {
    AttendanceStatus.PRESENT: "P",
    AttendanceStatus.ABSENT: "A",
    AttendanceStatus.LATE: "L",
    AttendanceStatus.HALF_DAY: "H",
    AttendanceStatus.HOLIDAY: "—",
}


def _csv(header: list[str], rows) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def roster_csv(rows: list[dict]) -> str:
    """The student roster.

    Carries the primary guardian's name and phone, because the reason somebody exports
    a roster is to have the contact list off-line — a version without it just gets
    joined to another spreadsheet by hand. That makes this file personal data about
    children under the DPDP Act the moment it is downloaded, which is a matter for the
    school's own handling rules; what this code owes is that the rows were scoped
    before they got here. See `selectors.roster_rows`.
    """
    return _csv(
        ["Name", "Classroom", "Joined", "Guardian", "Relationship", "Phone"],
        (
            [
                row["student"].display_name,
                row["classroom"].name if row["classroom"] else "",
                row["joined_on"].isoformat() if row["joined_on"] else "",
                row["guardian"].full_name if row["guardian"] else "",
                row["relationship"],
                row["guardian"].phone if row["guardian"] else "",
            ]
            for row in rows
        ),
    )


def attendance_summary_csv(rows: list[dict], year: int, month: int) -> str:
    """One row per child: their days present, absent and the percentage for a month."""
    return _csv(
        [f"Attendance {year}-{month:02d}", "Present", "Absent", "Late", "Half day", "Rate %"],
        (
            [
                row["student"].display_name,
                row["present"],
                row["absent"],
                row["late"],
                row["half_day"],
                "" if row["rate"] is None else row["rate"],
            ]
            for row in rows
        ),
    )


def register_grid(rows: list[dict], days: list[date_type]) -> list[dict]:
    """The printable month register: a child per row, a day per column.

    Built here rather than in the template because a template that indexes a dict by
    a loop variable needs a filter to do it, and the filter is where this logic would
    actually live — one layer too high, and untestable without rendering HTML.
    """
    return [
        {
            "student": row["student"],
            "marks": [REGISTER_MARKS.get(row["by_day"].get(day), "") for day in days],
            "rate": row["rate"],
        }
        for row in rows
    ]
