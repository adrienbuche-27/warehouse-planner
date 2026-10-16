"""Server-side bar charts, drawn as inline SVG by templates/includes/bar_chart.html.

No JavaScript and no chart library: Python computes the geometry, the template draws it.
Each bar has a hover tooltip (SVG <title>) and the page shows the same numbers in a table.
"""

from dataclasses import dataclass, field
from decimal import Decimal

# Drawing area in SVG units (the SVG scales to the page width).
WIDTH = 640
HEIGHT = 220
LEFT = 56  # room for the y-axis labels
RIGHT = 8
TOP = 12
BOTTOM = 34  # room for the x-axis labels
GAP = 2  # space between two bars
RADIUS = 4  # rounded top of each bar


@dataclass
class Bar:
    label: str  # x-axis label
    value: Decimal
    tooltip: str
    table_label: str = ""  # first column of the "Voir les données" table
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    path: str = ""  # bar shape with rounded top corners
    center: float = 0


@dataclass
class Tick:
    y: float
    label: str


@dataclass
class ReferenceLine:
    y: float
    label: str


@dataclass
class BarChart:
    bars: list[Bar]
    ticks: list[Tick]
    reference_lines: list[ReferenceLine] = field(default_factory=list)
    width: int = WIDTH
    height: int = HEIGHT
    left: int = LEFT
    baseline: float = HEIGHT - BOTTOM
    right_edge: float = WIDTH - RIGHT


def _rounded_top_bar(x: float, y: float, width: float, height: float) -> str:
    """Path of a bar anchored on the baseline, with rounded top corners only."""
    radius = min(RADIUS, width / 2, height)
    bottom = y + height
    return (
        f"M{x:.1f},{bottom:.1f} "
        f"V{y + radius:.1f} "
        f"Q{x:.1f},{y:.1f} {x + radius:.1f},{y:.1f} "
        f"H{x + width - radius:.1f} "
        f"Q{x + width:.1f},{y:.1f} {x + width:.1f},{y + radius:.1f} "
        f"V{bottom:.1f} Z"
    )


def _nice_maximum(value: Decimal) -> Decimal:
    """Round the axis maximum up to 1, 2 or 5 × a power of ten (e.g. 1 234 -> 2 000)."""
    if value <= 0:
        return Decimal("1")
    magnitude = Decimal(10) ** (len(str(int(value))) - 1)
    for step in (1, 2, 5, 10):
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def bar_chart(
    bars: list[Bar],
    maximum: Decimal | None = None,
    tick_format=lambda v: f"{v:,.0f}".replace(",", " "),
    tick_count: int = 4,
    reference_lines: list[tuple[Decimal, str]] = (),
) -> BarChart:
    """Lay out `bars` (in order, left to right) on a common y-scale starting at 0."""
    plot_width = WIDTH - LEFT - RIGHT
    plot_height = HEIGHT - TOP - BOTTOM
    baseline = HEIGHT - BOTTOM
    top_value = maximum or _nice_maximum(max((bar.value for bar in bars), default=Decimal(0)))

    def y_of(value) -> float:
        return round(baseline - float(Decimal(value) / top_value) * plot_height, 1)

    slot = plot_width / max(len(bars), 1)
    for index, bar in enumerate(bars):
        bar.width = round(slot - GAP, 1)
        bar.x = round(LEFT + index * slot + GAP / 2, 1)
        bar.center = round(bar.x + bar.width / 2, 1)
        clamped = min(max(bar.value, Decimal(0)), top_value)
        bar.y = y_of(clamped)
        bar.height = round(baseline - bar.y, 1)
        bar.path = _rounded_top_bar(bar.x, bar.y, bar.width, bar.height) if bar.height > 0 else ""

    ticks = [
        Tick(y=y_of(top_value * i / tick_count), label=tick_format(top_value * i / tick_count))
        for i in range(tick_count + 1)
    ]
    lines = [ReferenceLine(y=y_of(value), label=label) for value, label in reference_lines]
    return BarChart(bars=bars, ticks=ticks, reference_lines=lines, baseline=baseline)
