# Project-wide French formats, overriding Django's defaults for "fr" / "fr-be".
# Only the values defined here are overridden; everything else comes from Django.
# See https://docs.djangoproject.com/en/5.2/topics/i18n/formatting/

# Dates are always displayed as dd/mm/yyyy.
DATE_FORMAT = "d/m/Y"
DATETIME_FORMAT = "d/m/Y H:i"

# Accept dd/mm/yyyy typed by users, and yyyy-mm-dd sent by <input type="date">.
DATE_INPUT_FORMATS = [
    "%d/%m/%Y",
    "%d/%m/%y",
    "%Y-%m-%d",
]
