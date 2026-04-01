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
from .policy_metadata import infer_policy_metadata, infer_policy_metadata_from_record
from .quality import QualityResult, score_markdown_quality
