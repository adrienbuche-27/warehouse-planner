"""Helpers shared by several apps."""

from django.db import router
from django.db.models import Model
from django.db.models.deletion import Collector, ProtectedError, RestrictedError


def protected_objects(obj: Model) -> list[Model]:
    """Objects that prevent `obj` from being deleted (for example its bookings or invoices).

    Links that must block deletion are declared with on_delete=PROTECT on the model that
    points to `obj`. An empty list means `obj.delete()` will succeed.
    """
    collector = Collector(using=router.db_for_write(obj.__class__))
    try:
        collector.collect([obj])
    except ProtectedError as exc:
        return list(exc.protected_objects)
    except RestrictedError as exc:
        return list(exc.restricted_objects)
    return []
