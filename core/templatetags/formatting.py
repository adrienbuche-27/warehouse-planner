"""Template filters. Usage: {% load formatting %} then {{ invoice.total_incl_vat|money }}."""

from django import template

from core.formatting import format_money

register = template.Library()


@register.filter
def money(amount):
    return format_money(amount)
