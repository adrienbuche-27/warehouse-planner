"""Template filters. Usage: {% load formatting %} then {{ amount|money }} or {{ length|metres }}."""

from django import template

from core.formatting import format_metres, format_metres_short, format_money

register = template.Library()


@register.filter
def money(amount):
    return format_money(amount)


@register.filter
def metres(value):
    return format_metres(value)


@register.filter
def metres_short(value):
    return format_metres_short(value)
