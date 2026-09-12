"""Offline EELS practice simulator; no GUI or server is started on import."""
from .model import Config, MODEL_VERSION, TERMS, coefficients, polynomial, simulate

__all__ = ["Config", "MODEL_VERSION", "TERMS", "coefficients", "polynomial", "simulate"]
