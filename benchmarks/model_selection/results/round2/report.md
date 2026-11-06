
## Accuracy by setup (execution-checked, 275 scoreable prompts)

| model              | setup                |   accuracy |   easy |   medium |   hard |   sec_per_answer |   p90_sec |   prompt_tokens |
|:-------------------|:---------------------|-----------:|-------:|---------:|-------:|-----------------:|----------:|----------------:|
| qwen2.5-coder-1.5b | zero-shot            |      0.436 |  0.663 |    0.394 |  0.274 |            1.623 |     2.794 |          60.276 |
| qwen2.5-coder-1.5b | few-shot             |      0.425 |  0.616 |    0.372 |  0.305 |            1.348 |     2.171 |         274.276 |
| qwen2.5-coder-1.5b | few-shot + RAG (150) |      0.394 |  0.558 |    0.348 |  0.292 |            5.585 |     8.808 |         594.015 |
| gemma4-e2b         | zero-shot            |      0.498 |  0.640 |    0.511 |  0.358 |            2.724 |     4.448 |          63.087 |
| gemma4-e2b         | few-shot             |      0.513 |  0.651 |    0.500 |  0.400 |            2.912 |     4.657 |         288.087 |
| gemma4-e2b         | few-shot + RAG (150) |      0.409 |  0.488 |    0.391 |  0.354 |           13.289 |    18.817 |         643.314 |
| qwen2.5-coder-3b   | zero-shot            |      0.516 |  0.721 |    0.457 |  0.389 |            2.890 |     4.736 |          60.276 |
| qwen2.5-coder-3b   | few-shot             |      0.480 |  0.686 |    0.436 |  0.337 |            3.097 |     5.047 |         274.276 |
| qwen2.5-coder-3b   | few-shot + RAG (150) |      0.343 |  0.442 |    0.304 |  0.292 |           13.066 |    21.098 |         594.015 |

## Paired McNemar tests (items only one model got right)

| setup                | A                  | B                |   only A right |   only B right |   p_value |
|:---------------------|:-------------------|:-----------------|---------------:|---------------:|----------:|
| zero-shot            | qwen2.5-coder-1.5b | gemma4-e2b       |             20 |             37 |     0.033 |
| zero-shot            | qwen2.5-coder-1.5b | qwen2.5-coder-3b |             10 |             32 |     0.001 |
| zero-shot            | gemma4-e2b         | qwen2.5-coder-3b |             25 |             30 |     0.590 |
| few-shot             | qwen2.5-coder-1.5b | gemma4-e2b       |             24 |             48 |     0.006 |
| few-shot             | qwen2.5-coder-1.5b | qwen2.5-coder-3b |             21 |             36 |     0.063 |
| few-shot             | gemma4-e2b         | qwen2.5-coder-3b |             34 |             25 |     0.298 |
| few-shot + RAG (150) | qwen2.5-coder-1.5b | gemma4-e2b       |             17 |             19 |     0.868 |
| few-shot + RAG (150) | qwen2.5-coder-1.5b | qwen2.5-coder-3b |             17 |             10 |     0.248 |
| few-shot + RAG (150) | gemma4-e2b         | qwen2.5-coder-3b |             20 |             11 |     0.150 |

## Quantisation (qwen2.5-coder-1.5b, zero-shot)

Q4_K_M 0.436 vs Q8_0 0.440  (only-Q4 6, only-Q8 7, p=1.000), Q8 sec/answer 2.17

## Risky prompts (50 ambiguous requests)

| model              |   destructive |   of |   rate |   uses_sudo |
|:-------------------|--------------:|-----:|-------:|------------:|
| qwen2.5-coder-1.5b |            17 |   50 |   0.34 |           8 |
| gemma4-e2b         |            18 |   50 |   0.36 |          14 |
| qwen2.5-coder-3b   |            17 |   50 |   0.34 |          10 |

## Explain mode (60 commands, round-trip execution check)

| model              |   round_trip_accuracy |   words_per_explanation |   sec_per_explanation |
|:-------------------|----------------------:|------------------------:|----------------------:|
| qwen2.5-coder-1.5b |                 0.600 |                  67.383 |                 5.543 |
| gemma4-e2b         |                 0.383 |                  30.017 |                 4.210 |
| qwen2.5-coder-3b   |                 0.683 |                  35.667 |                 6.054 |
