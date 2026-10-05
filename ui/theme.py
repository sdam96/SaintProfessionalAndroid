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

PRIMARY = ft.Colors.INDIGO_700
PRIMARY_DARK = ft.Colors.INDIGO_900
SURFACE = ft.Colors.INDIGO_50
ACCENT = ft.Colors.TEAL_600
DANGER = ft.Colors.RED_600
MUTED = ft.Colors.BLUE_GREY_600
BACKGROUND = ft.Colors.BLUE_GREY_50