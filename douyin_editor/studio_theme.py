"""Shared colors and widget defaults for the desktop editing workspace."""
from copy import deepcopy
import customtkinter as ctk

COLORS = {
    "background": "#0B1120", "surface": "#111C2E", "raised": "#17243A",
    "input": "#0D1728", "border": "#26364E", "text": "#E8EEF8",
    "muted": "#94A6C0", "accent": "#528BFF", "accent_hover": "#4076E5",
    "success": "#39C6A3", "danger": "#F17883",
}


def apply_studio_theme():
    theme = deepcopy(ctk.ThemeManager.theme)
    def update(widget, **values):
        theme[widget].update(values)
    pair = lambda color: [color, color]
    update("CTk", fg_color=pair(COLORS["background"]))
    update("CTkFrame", corner_radius=12, border_color=pair(COLORS["border"]),
           fg_color=pair(COLORS["surface"]), top_fg_color=pair(COLORS["raised"]))
    update("CTkLabel", text_color=pair(COLORS["text"]))
    update("CTkButton", corner_radius=8, border_width=0,
           fg_color=pair(COLORS["accent"]), hover_color=pair(COLORS["accent_hover"]),
           text_color=pair("#FFFFFF"), text_color_disabled=pair("#6D7D96"))
    for widget in ("CTkEntry", "CTkComboBox", "CTkOptionMenu"):
        update(widget, corner_radius=8, fg_color=pair(COLORS["input"]),
               text_color=pair(COLORS["text"]))
    update("CTkEntry", border_color=pair(COLORS["border"]))
    update("CTkComboBox", border_color=pair(COLORS["border"]),
           button_color=pair(COLORS["raised"]), button_hover_color=pair("#263B5B"))
    update("CTkTextbox", corner_radius=8, border_width=1,
           border_color=pair(COLORS["border"]), fg_color=pair(COLORS["input"]),
           text_color=pair(COLORS["text"]))
    update("CTkSegmentedButton", corner_radius=8, fg_color=pair(COLORS["background"]),
           selected_color=pair("#294B7C"), selected_hover_color=pair("#335B91"),
           unselected_color=pair(COLORS["background"]), unselected_hover_color=pair(COLORS["raised"]),
           text_color=pair(COLORS["text"]))
    for widget in ("CTkSwitch", "CTkSlider", "CTkProgressBar"):
        update(widget, progress_color=pair(COLORS["accent"]))
    update("CTkCheckBox", fg_color=pair(COLORS["accent"]), hover_color=pair(COLORS["accent_hover"]),
           border_color=pair("#536782"), text_color=pair(COLORS["text"]))
    update("CTkSlider", button_color=pair(COLORS["accent"]), button_hover_color=pair(COLORS["accent_hover"]))
    update("CTkProgressBar", fg_color=pair(COLORS["raised"]))
    update("CTkScrollbar", button_color=pair("#334764"), button_hover_color=pair("#4A6182"))
    theme["CTkFont"].update(family="Segoe UI", size=13)
    ctk.ThemeManager.theme = theme
