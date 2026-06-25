"""Three-signal remediation classifier: good_to_go / auto-tag / manual."""

from pdfscan.classify.apply import classify_rows
from pdfscan.classify.classifier import (
    Classification,
    Confidence,
    Label,
    classify_pdf,
)
from pdfscan.classify.profile import (
    DEFAULT_PROFILE,
    ClassificationProfile,
    load_classification_profile,
)

__all__ = [
    "Label",
    "Confidence",
    "Classification",
    "classify_pdf",
    "classify_rows",
    "ClassificationProfile",
    "load_classification_profile",
    "DEFAULT_PROFILE",
]
