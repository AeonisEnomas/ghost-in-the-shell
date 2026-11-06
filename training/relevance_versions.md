# Relevance classifier: versions

Both versions use the same model (TF-IDF word 1-2 grams + char 3-5 grams,
logistic regression), the same Dolly-15k negatives and the same split seed.
The handwritten evaluation sets (data/relevance/eval_*.txt) were never used
for training in either version.

| | v1 | v2 (shipped) |
|---|---|---|
| Handwritten training phrasings (shell / other) | 50 / 53 | 151 / 92 |
| Threshold (validation recall >= 0.99) | 0.544 | 0.510 |
| Test split accuracy | 99.3% | 99.2% |
| NL2SH-ALFA test prompts accepted (300) | 99.7% | 100.0% |
| Risky prompts accepted (50) | 94.0% | 98.0% |
| Handwritten shell tasks accepted (30) | 83.3% | 93.3% |
| Handwritten other requests rejected (30) | 86.7% | 90.0% |

v1 rejected casual questions about the system's state ("how much ram is this
machine using", "which folders are the largest here"), which are rare in the
formally worded NL2SH data. v2 adds 101 casual shell phrasings and 39 more
negatives (mostly coding questions in other languages and questions about the
model) to the training data. The evaluation sets were looked at once, after
v1, to diagnose the gap; their wording was not copied into training.
