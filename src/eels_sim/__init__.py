"""Offline EELS practice simulator; no GUI or server is started on import."""
from .model import Config, MAX_ORDER, MODEL_VERSION, POWERS, TERMS, coefficients, polynomial, simulate, terms_through

__all__ = ["Config", "MAX_ORDER", "MODEL_VERSION", "POWERS", "TERMS", "coefficients", "polynomial", "simulate", "terms_through"]
