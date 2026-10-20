"""Locations for bundled resources and writable application data."""
import os
from pathlib import Path
import sys


def resource_root():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def data_dir():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / "EditVideoStudio"


def model_dir():
    if getattr(sys, "frozen", False):
        return data_dir() / "models"
    return Path(__file__).resolve().parent / "models"
