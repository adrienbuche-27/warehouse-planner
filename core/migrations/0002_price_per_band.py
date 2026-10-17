from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    """The price now depends on the vehicle length, per band.

    The old flat "prix par période" is removed rather than renamed: its value was a price for a
    whole vehicle, not for one band, so the new price per band has to be entered in Paramètres.
    Existing bookings keep the price they were created with.
    """

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="appsettings",
            name="price_per_period",
        ),
        migrations.AddField(
            model_name="appsettings",
            name="band_length_m",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("2.00"),
                help_text="Une tranche entamée est comptée entière : avec 2 m, 7,40 m = 4 tranches.",
                max_digits=5,
                validators=[
                    django.core.validators.MinValueValidator(
                        Decimal("0.10"), "Une tranche fait au moins 0,10 m."
                    )
                ],
                verbose_name="taille d'une tranche (m)",
            ),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="price_per_band",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Prix hors TVA d'une tranche pour une période. "
                "Prix d'une période = nombre de tranches × ce prix.",
                max_digits=10,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                verbose_name="prix par tranche et par période (HTVA)",
            ),
        ),
    ]
