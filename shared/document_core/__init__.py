"""
Shared canonical document normalization contracts and quality scoring helpers.
"""

from .models import (
    ArtifactPaths,
    NormalizedBlock,
    NormalizedChunk,
    NormalizedDocument,
    ParseReport,
    ParserAttempt,
)
from .quality import QualityResult, score_markdown_quality

