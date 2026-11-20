## Accuracy (274 scoreable prompts; 241 in the clean set)

Easy, medium and hard are over the clean set.

| model         |   accuracy |   clean accuracy |   easy |   medium |   hard |
|:--------------|-----------:|-----------------:|-------:|---------:|-------:|
| base          |      0.471 |            0.461 |  0.726 |    0.391 |  0.348 |
| finetuned     |      0.500 |            0.494 |  0.694 |    0.540 |  0.315 |
| base-original |      0.438 |            0.427 |  0.710 |    0.379 |  0.283 |

## Paired McNemar tests

| A             | B             | set       |   accuracy A |   accuracy B |   only A right |   only B right |   p_value |
|:--------------|:--------------|:----------|-------------:|-------------:|---------------:|---------------:|----------:|
| base          | finetuned     | scoreable |        0.471 |        0.500 |             32 |             40 |     0.410 |
| base          | finetuned     | clean     |        0.461 |        0.494 |             27 |             35 |     0.374 |
| base-original | finetuned     | scoreable |        0.438 |        0.500 |             22 |             39 |     0.040 |
| base-original | finetuned     | clean     |        0.427 |        0.494 |             18 |             34 |     0.036 |
| base          | base-original | scoreable |        0.471 |        0.438 |             18 |              9 |     0.122 |
| base          | base-original | clean     |        0.461 |        0.427 |             16 |              8 |     0.152 |
