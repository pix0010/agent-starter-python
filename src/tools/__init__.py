# Делает удобным импорт тулзов: from tools import lookup_weather
from .weather import lookup_weather

__all__ = ["lookup_weather"]