"""The Open-Meteo weather / daylight source (A4) — tech spec D7.

The only V1 source with no account and no credentials, which is exactly why it needs a
guard the others don't: Open-Meteo will happily answer for coordinates 0.0/0.0 (a spot in
the Gulf of Guinea) instead of refusing. `Settings.home_lat`/`home_lon` left at their
defaults therefore mean the source is **off**, never "somewhere".
"""

from .source import OpenMeteoSource

__all__ = ["OpenMeteoSource"]
