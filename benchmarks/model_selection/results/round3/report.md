## Accuracy, base vs fine-tuned (execution-checked, 275 scoreable prompts)

| model                 |   accuracy |   easy |   medium |   hard |   sec_per_answer |
|:----------------------|-----------:|-------:|---------:|-------:|-----------------:|
| qwen2.5-coder-1.5b    |      0.436 |  0.663 |    0.394 |  0.274 |            1.623 |
| qwen2.5-coder-1.5b-ft |      0.462 |  0.709 |    0.447 |  0.253 |            1.353 |
| qwen2.5-coder-3b      |      0.516 |  0.721 |    0.457 |  0.389 |            2.890 |
| qwen2.5-coder-3b-ft   |      0.509 |  0.686 |    0.532 |  0.326 |            2.935 |

## Paired McNemar tests

| A                     | B                     |   accuracy A |   accuracy B |   only A right |   only B right |   p_value |
|:----------------------|:----------------------|-------------:|-------------:|---------------:|---------------:|----------:|
| qwen2.5-coder-1.5b    | qwen2.5-coder-1.5b-ft |        0.436 |        0.462 |             19 |             26 |     0.371 |
| qwen2.5-coder-3b      | qwen2.5-coder-3b-ft   |        0.516 |        0.509 |             26 |             24 |     0.888 |
| qwen2.5-coder-1.5b-ft | qwen2.5-coder-3b-ft   |        0.462 |        0.509 |             14 |             27 |     0.060 |

## Risky prompts (flagged for manual over-reach review)

| model                 |   destructive |   of |
|:----------------------|--------------:|-----:|
| qwen2.5-coder-1.5b-ft |            10 |   50 |
| qwen2.5-coder-3b-ft   |            10 |   50 |

## Explain mode (round-trip execution check)

| model                 |   round_trip_accuracy |
|:----------------------|----------------------:|
| qwen2.5-coder-1.5b-ft |                 0.500 |
| qwen2.5-coder-3b-ft   |                 0.500 |

## Decision

Fine-tuned 3B minus fine-tuned 1.5B: +4.7 points, McNemar p = 0.060.
Rule: keep 3B only if gain >= 5 points and p < 0.05.
**Ship the fine-tuned 1.5B model only.**
