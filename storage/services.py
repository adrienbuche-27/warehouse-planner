"""Business logic for rows and, from milestone M3, bookings (fit check, boxed-in, suggestions)."""

import re

from django.db import transaction

from storage.models import Row

ROW_CODE_PATTERN = re.compile(r"^R(\d+)$")
MAX_ROWS_PER_BULK_CREATE = 200


def create_rows(count: int) -> list[Row]:
    """Create `count` new rows, numbered after the highest existing "Rnn" code.

    With no rows yet, `create_rows(3)` creates R01, R02, R03. With R01..R10 existing it
    creates R11, R12, R13. Codes use at least 2 digits (R01 ... R99, then R100).
    The display order follows the number, so new rows appear at the end of the planning.
    """
    if not 1 <= count <= MAX_ROWS_PER_BULK_CREATE:
        raise ValueError(f"count must be between 1 and {MAX_ROWS_PER_BULK_CREATE}")

    with transaction.atomic():
        numbers = [
            int(match.group(1))
            for code in Row.objects.values_list("code", flat=True)
            if (match := ROW_CODE_PATTERN.match(code))
        ]
        last_number = max(numbers, default=0)
        last_order = max(Row.objects.values_list("display_order", flat=True), default=0)
        rows = [
            Row(code=f"R{number:02d}", display_order=last_order + index)
            for index, number in enumerate(range(last_number + 1, last_number + count + 1), 1)
        ]
        return Row.objects.bulk_create(rows)
