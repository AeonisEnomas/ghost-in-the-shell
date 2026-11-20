# The fine-tuned model

How the model that writes commands was trained and tested. The notebook is
`finetune/finetune.ipynb`, its records are in `finetune/records/`, and the
tests are in `evaluation/`.

## Summary

Qwen2.5-Coder-1.5B-Instruct was fine-tuned with QLoRA on 49,489 request and
command pairs. Against the same base model exported the same way, the
fine-tuned model is ahead on both test sets, by 4.1 points on app-style
requests and 2.9 points on the public NL2SH-ALFA benchmark. With test sets of
this size neither gap is statistically significant.

| | App requests (169) | NL2SH-ALFA (274) |
|---|---|---|
| Base model | 68.6% | 47.1% |
| Fine-tuned model | 72.8% | 50.0% |
| McNemar p | 0.34 | 0.41 |

## Training data

Four public datasets are pooled, each pinned to a commit:
[Bash Instruct III](https://huggingface.co/datasets/Frost2o24/bash-instruct-III-55k)
(single commands and pipelines, one answer per request),
[mecha-org/linux-command-dataset](https://huggingface.co/datasets/mecha-org/linux-command-dataset),
[aelhalili/bash-commands-dataset](https://huggingface.co/datasets/aelhalili/bash-commands-dataset)
and the training split of
[NL2SH-ALFA](https://huggingface.co/datasets/westenfelder/NL2SH-ALFA). The
last is the largest but is unverified, so the pool is filtered:

| Filter | Removed | Left |
|---|---|---|
| Format: one line, at most 200 characters, no unfilled placeholders | 904 | 80,659 |
| Machine-made "pick a random file" tasks | 4,447 | 76,212 |
| Request says "current directory", command searches `/` or `~` | 751 | 75,461 |
| Catastrophic commands (recursive delete of `/` or `~`, writes to disks, download piped to a shell) | 374 | 75,087 |
| Matches or nearly matches a test request or command | 536 | 74,551 |
| Duplicate requests | 4,654 | 69,897 |
| Invalid syntax (`bash -n`) | 37 | 69,860 |
| Tools with fewer than 20 examples that appear in one source only | 13,439 | 56,421 |
| Cap on any single tool (mostly `find`) | 5,795 | 50,626 |

That leaves 49,489 training pairs and 1,137 validation pairs. Validation
holds out whole commands, so paraphrases of one command never sit on both
sides. By source, the training set is 57% Bash Instruct III, 27% NL2SH-ALFA,
15% mecha-org and 1% aelhalili.

Ordinary `rm`, `sudo` and `shutdown` commands stay in the data: the model has
to be able to answer "delete app.log", and the app rates and previews every
command before it can run.

## Training

- QLoRA with [Unsloth](https://github.com/unslothai/unsloth): the base model in
  4-bit, rank-16 adapters on every attention and MLP projection, loss on the
  reply only.
- The system prompt is the one the app sends, so the model is trained on the
  exact format it is used with.
- Two epochs (6,188 steps of 16 pairs, 139 minutes on a Tesla T4), learning
  rate 2e-4 with linear decay, evaluated and checkpointed every 250 steps.
- Validation loss fell from 0.451 to 0.276. The lowest value was at the last
  step, which is the checkpoint that was exported.
- The fine-tuned model and the untouched base model were exported to GGUF
  `Q4_K_M` by the same code, so the two files differ only in their weights.

## Tests

Both tests judge a command by running it in a sandbox and comparing what it
did with reference commands, since many different commands are correct for the
same request.

**App requests** (`evaluation/app_requests/`). 169 short requests of the kind
the app is built for ("how many python files do I have here"), run in a fixed
sample folder. Written for this project and frozen before any output of the
fine-tuned model was seen; none matches a training request.

**NL2SH-ALFA** (`evaluation/nl2sh_alfa/`). The 300-prompt test split of a
public benchmark (Westenfelder et al., NAACL 2025), manually verified by its
authors. Its prompts are long specifications with explicit paths, so it is the
independent check, not a picture of typical use. 274 prompts can be scored by
execution. A stricter "clean" set of 241 also drops prompts whose second
reference is unstable and prompts where both references fail in this sandbox
(a missing tool, no network).

## Results

| Model | App requests | NL2SH-ALFA | NL2SH-ALFA, clean set |
|---|---|---|---|
| Fine-tuned | 72.8% | 50.0% | 49.4% |
| Base, same export | 68.6% | 47.1% | 46.1% |
| Base, Qwen's own GGUF | 72.2% | 43.8% | 42.7% |

| Fine-tuned compared with | Test | Only fine-tuned right | Only the other right | McNemar p |
|---|---|---|---|---|
| Base, same export | App requests | 23 | 16 | 0.337 |
| Base, same export | NL2SH-ALFA | 40 | 32 | 0.410 |
| Base, Qwen's own GGUF | App requests | 19 | 18 | 1.000 |
| Base, Qwen's own GGUF | NL2SH-ALFA | 39 | 22 | 0.040 |

1. **The fine-tuned model is ahead of the like-for-like base on both tests,
   and the gap is not significant on either.**
2. **How the base file was built matters as much as the fine-tuning.** The two
   base files hold the same model but differ by 3.6 points on app requests in
   one direction and 3.3 points on NL2SH-ALFA in the other. The significant
   gain over Qwen's own file on NL2SH-ALFA therefore mixes both effects.
3. **The gain on NL2SH-ALFA is on medium prompts** (39% to 54% on the clean
   set). Easy prompts slipped (73% to 69%) and hard ones did not improve (35%
   to 32%).
4. **The fine-tuned model always replies with a bare command.** The base
   wrapped 24% of its replies to app requests in code fences or extra text,
   which the scorer strips.
5. **Typical mistakes of the fine-tuned model** are in searching inside files:
   a missing field separator on CSV files, searching from `/` instead of the
   current folder, and using `locate`.

## Limitations

- **The test sets are small.** A difference under about 7 points on app
  requests, or 6 on NL2SH-ALFA, is within noise for a single comparison.
- **NL2SH-ALFA scores move by a prompt or two between days.** Some prompts
  depend on file ages or on the state of the machine, which is why references
  are rebuilt in every scoring session. The figures here are from one session.
- **Commands run with this machine's tools,** not the benchmark's official
  Ubuntu containers, so NL2SH-ALFA scores are not comparable with published
  numbers. Both models are scored the same way.
- **The app-request test was written by this project,** not collected from
  users.
- **Explanations were not tested here.** The app uses Qwen's own base GGUF
  for them.
- **The exported checkpoint was still improving slightly,** so a longer run
  might gain a little more.

## Reproducing

Fine-tuning: open `finetune/finetune.ipynb` in Colab with a T4 GPU and run all
cells. Testing, with llama.cpp and bubblewrap installed:

```
cd evaluation/app_requests && uv run python run.py
cd ../nl2sh_alfa && uv run python run.py
```

Saved answers in `results/answers/` are reused; delete them to ask the models
again.
