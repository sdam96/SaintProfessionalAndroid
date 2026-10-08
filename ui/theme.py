"""Visual constants shared by every screen."""

import flet as ft

# Under this width the panes stack vertically; above it the line list and
# the totals sit side by side.
TABLET_BREAKPOINT = 800

# Field widths are fixed so a wrapping row collapses to one column on a
# phone and spreads into two or three on a tablet.
FIELD_WIDE = 300
FIELD_MED = 200
FIELD_NARROW = 140

# Empty space closing every scrolling screen. SafeArea depends on Android
# reporting the navigation-bar inset, and not every build does (it has
# been seen failing with three-button navigation), which left the last
# buttons under the bar. A fixed allowance taller than that bar (48 dp)
# lets them always scroll clear of it; where SafeArea does work it only
# adds blank space after the last control.
NAV_BAR_ALLOWANCE = 32

PRIMARY = ft.Colors.INDIGO_700
PRIMARY_DARK = ft.Colors.INDIGO_900
SURFACE = ft.Colors.INDIGO_50
ACCENT = ft.Colors.TEAL_600
DANGER = ft.Colors.RED_600
MUTED = ft.Colors.BLUE_GREY_600
BACKGROUND = ft.Colors.BLUE_GREY_50


def bottom_allowance() -> ft.Container:
    """The closing space described by NAV_BAR_ALLOWANCE."""
    return ft.Container(height=NAV_BAR_ALLOWANCE)