## Accuracy (274 scoreable prompts; 241 in the clean set)

Easy, medium and hard are over the clean set.

| model                     |   accuracy |   clean accuracy |   easy |   medium |   hard |
|:--------------------------|-----------:|-----------------:|-------:|---------:|-------:|
| base-r4                   |      0.464 |            0.452 |  0.726 |    0.391 |  0.326 |
| ft-r4                     |      0.500 |            0.494 |  0.694 |    0.540 |  0.315 |
| base (original Qwen file) |      0.431 |            0.419 |  0.710 |    0.379 |  0.261 |
| ft-r3                     |      0.467 |            0.465 |  0.806 |    0.425 |  0.272 |

## Paired McNemar tests

| A                         | B                         | set       |   accuracy A |   accuracy B |   only A right |   only B right |   p_value |
|:--------------------------|:--------------------------|:----------|-------------:|-------------:|---------------:|---------------:|----------:|
| base-r4                   | ft-r4                     | scoreable |        0.464 |        0.500 |             32 |             42 |     0.295 |
| base-r4                   | ft-r4                     | clean     |        0.452 |        0.494 |             27 |             37 |     0.260 |
| base (original Qwen file) | ft-r4                     | scoreable |        0.431 |        0.500 |             22 |             41 |     0.023 |
| base (original Qwen file) | ft-r4                     | clean     |        0.419 |        0.494 |             18 |             36 |     0.020 |
| ft-r3                     | ft-r4                     | scoreable |        0.467 |        0.500 |             21 |             30 |     0.262 |
| ft-r3                     | ft-r4                     | clean     |        0.465 |        0.494 |             17 |             24 |     0.349 |
| base-r4                   | base (original Qwen file) | scoreable |        0.464 |        0.431 |             18 |              9 |     0.122 |
| base-r4                   | base (original Qwen file) | clean     |        0.452 |        0.419 |             16 |              8 |     0.152 |
