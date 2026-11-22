# Is a request a task for the shell? And does it try to instruct the model?

import re
from dataclasses import dataclass
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

INJECTION_PATTERNS = [
    r"\b(ignore|disregard|forget|override)\b[^.]{0,40}\b(instructions?|prompts?|rules|above|previous|everything)\b",
    r"\b(system|hidden|initial)\s+(prompt|instructions?|message)\b",
    r"\b(reply|respond|answer)\s+(only\s+|exactly\s+|just\s+)?(with|exactly|only|verbatim)\b",
    r"\b(output|print|say|return)\s+(exactly|verbatim)\b",
    r"\byou\s+are\s+now\b|\bact\s+as\b|\bpretend\s+(to\s+be|you)\b|\bfrom\s+now\s+on\b",
    r"\bnew\s+instructions?\b|\bdeveloper\s+mode\b|\bjailbreak\b|\bDAN\b",
    r"\brepeat\s+(everything|the\s+text|all)\b[^.]{0,20}\b(above|before)\b",
]
_INJECTION = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

_SMALL_TALK = re.compile(
    r"^(hi+|hello+|hey+|yo|sup|thanks?( you)?( so much)?|thank u|thx|ty|ok(ay)?|cool|nice|great|"
    r"bye|good ?bye|good (morning|afternoon|evening|night)|how are you|who are you|what are you)"
    r"[\s!.?]*$", re.IGNORECASE)


@dataclass(frozen=True)
class Relevance:
    on_topic: bool
    score: float
    injection_phrases: tuple[str, ...]


def injection_phrases(text: str) -> tuple[str, ...]:
    found = []
    for pattern in _INJECTION:
        found += [m.group(0) for m in pattern.finditer(text)]
    return tuple(dict.fromkeys(found))


def build_pipeline() -> Pipeline:
    features = FeatureUnion([
        ("words", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, lowercase=True)),
        ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3,
                                  sublinear_tf=True, lowercase=True)),
    ])
    return Pipeline([
        ("features", features),
        ("model", LogisticRegression(C=4.0, class_weight="balanced", max_iter=2000)),
    ])


class RelevanceChecker:

    # Loads the trained classifier and its decision threshold.
    def __init__(self, pipeline: Pipeline, threshold: float):
        self.pipeline = pipeline
        self.threshold = threshold

    @classmethod
    def load(cls, path: Path) -> "RelevanceChecker | None":
        if not path.is_file():
            return None
        bundle = joblib.load(path)
        return cls(bundle["pipeline"], bundle["threshold"])

    def check(self, request: str) -> Relevance:
        if _SMALL_TALK.match(request.strip()):
            return Relevance(False, 0.0, ())
        score = float(self.pipeline.predict_proba([request])[0][1])
        return Relevance(score >= self.threshold, score, injection_phrases(request))
