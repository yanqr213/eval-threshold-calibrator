class CalibrationError(Exception):
    """Base error raised for readable CLI failures."""


class ConfigError(CalibrationError):
    """Raised when configuration is invalid."""


class InputError(CalibrationError):
    """Raised when input files or records cannot be parsed."""
