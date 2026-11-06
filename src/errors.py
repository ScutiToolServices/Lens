"""Stable public failures; messages never contain paths or engine diagnostics."""


class OCRError(Exception):
    code = "ocr_error"
    status = 400


class Rejected(OCRError):
    code = "invalid_image_or_regions"


class Missing(OCRError):
    code = "file_not_found"
    status = 404


class IdentityRequired(OCRError):
    code = "identity_required"
    status = 401


class QuotaExceeded(OCRError):
    code = "quota_exceeded"
    status = 413


class TooLarge(Rejected):
    code = "too_large"
    status = 413


class Unavailable(OCRError):
    code = "ocr_unavailable"
    status = 503


class Busy(Unavailable):
    code = "busy"
