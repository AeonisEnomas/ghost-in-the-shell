# Model selection

How the language model for Ghost in the Shell was chosen. Every number in this
document comes from files in `benchmarks/model_selection/results/` and can be
reproduced with the commands in the last section.

## Summary

| Round | Question | Outcome |
|---|---|---|
| 1 | Which small open models are good at English → bash, out of the box? | 8 models tested. Qwen2.5-Coder-3B, Gemma-4-E2B and Qwen2.5-Coder-1.5B go forward. |
| 2 | How do the finalists behave under app conditions (prompting, retrieval, safety, explanations, quantisation)? | Gemma dropped (poor explanations, no accuracy advantage). Retrieval over tldr pages dropped. Q4 quantisation confirmed. |
| 3 | After fine-tuning, is the 3B model worth its extra latency over the 1.5B model? | No. Fine-tuned 3B leads by 4.7 points, p = 0.060, short of the rule fixed in advance. The app ships the fine-tuned 1.5B model. |

## 1. Task and test data

The model receives a plain-English request and must reply with one bash
command. The test set is the 300-prompt test split of
[NL2SH-ALFA](https://huggingface.co/datasets/westenfelder/NL2SH-ALFA)
(Westenfelder et al., NAACL 2025, MIT license). Every prompt was manually
verified by the dataset authors, has two correct reference commands, and is
labelled easy, medium or hard (100 each).

## 2. How answers are scored

**Execution, not string matching.** Many different commands are correct for the
same request, so comparing text is unreliable. Instead, each command is run in
a throwaway sandbox and judged by what it does:

- The sandbox recreates the five test filesystems used by the dataset's
  official evaluator (InterCode-ALFA), using its own setup scripts. Docker is
  replaced by [bubblewrap](https://github.com/containers/bubblewrap): no
  network, read-only system directories, a fresh copy of the filesystem for
  every run, and a 5-second timeout.
- A prediction is **correct** when it leaves the same files behind as one of
  the two reference commands (path, type, permissions and content hash) and
  prints the same lines of output, in any order.

**Checking the scorer.** Before testing any model, the scorer was checked
against commands with known answers:

| Input | Score |
|---|---|
| Reference command 1 (scored against itself) | 99.7% |
| Reference command 2 (an alternative correct answer) | 97.2% |
| `true` (does nothing) | 0.0% |

**Excluded items.** 13 prompts give a different result every time they run
(`date`, `uptime`, `free`), and 13 others can be passed by a command that does
nothing (`history`, `jobs`, network lookups in a sandbox without network).
Both groups are excluded from accuracy. Every accuracy figure below is over the
remaining **275 prompts**.

**Statistics.** 95% confidence intervals use 2,000 bootstrap resamples. Two
models are compared with an exact McNemar test on the prompts where exactly one
of them is right, since both answer the same prompts.

**Hardware.** All inference ran on the laptop the app targets: Intel
i7-4712HQ (4 cores, 2014), 15 GB RAM, no usable GPU. Models ran through
llama.cpp (`llama-server`, 4 threads) with greedy decoding.

## 3. Round 1: eight candidates, out of the box

**Candidates.** Open models from 0.5B to 3B parameters with a GGUF build:
Qwen2.5-Coder (0.5B, 1.5B, 3B), Qwen3.5 (0.8B, 2B), Llama-3.2 (1B, 3B) and
Gemma-4-E2B. Models of 1B or less ran at Q8_0, larger ones at Q4_K_M.
Qwen3.5's thinking mode was turned off.

**Prompt.** One system prompt for all models:

> You translate natural-language requests into a single Linux bash command.
> Reply with only the command on one line: no explanation, no markdown, no
> code fences.

**Results** (`results/summary.csv`)

| Model | Accuracy | 95% CI | Easy | Medium | Hard | Right tool | Sec/answer |
|---|---|---|---|---|---|---|---|
| Qwen2.5-Coder-3B | **51.6%** | 45.8–57.5 | 73.3% | 46.9% | 40.4% | 78.3% | 2.89 |
| Gemma-4-E2B | 49.8% | 43.6–55.6 | 64.4% | 53.1% | 36.4% | 78.3% | 2.72 |
| Qwen2.5-Coder-1.5B | 43.6% | 37.8–49.5 | 65.6% | 40.8% | 29.3% | 72.0% | 1.60 |
| Llama-3.2-3B | 36.4% | 30.5–42.5 | 54.4% | 31.6% | 25.3% | 71.7% | 3.02 |
| Qwen3.5-2B | 34.2% | 28.7–39.6 | 42.2% | 30.6% | 30.3% | 62.0% | 6.12 |
| Qwen2.5-Coder-0.5B | 26.5% | 21.5–31.6 | 46.7% | 20.4% | 16.2% | 50.7% | 0.64 |
| Llama-3.2-1B | 18.9% | 14.2–23.3 | 40.0% | 10.2% | 9.1% | 48.0% | 1.96 |
| Qwen3.5-0.8B | 16.0% | 11.6–20.4 | 23.3% | 16.3% | 13.1% | 44.3% | 2.52 |

"Right tool" means the first program in the command matches a reference
(`find` vs `grep`), even if its flags are wrong.

**Findings**
- Code-specialised models win at every size: Qwen2.5-Coder-0.5B beats the
  larger general-purpose Llama-3.2-1B and Qwen3.5-0.8B.
- The top three confidence intervals overlap, and the fourth model is clearly
  below them.
- Latency grows quickly with size on this CPU. Qwen3.5-2B averaged over
  6 seconds per answer.

**Decision.** Qwen2.5-Coder-3B, Gemma-4-E2B and Qwen2.5-Coder-1.5B go to
round 2.

## 4. Round 2: the finalists under app conditions

Round 1 used one bare prompt. The app can add worked examples and retrieved
documentation, needs safe behaviour on risky requests, and has a second
feature that explains commands. Round 2 tests each of these.

| Test | Setup |
|---|---|
| Few-shot | Same system prompt plus 5 worked examples taken from the NL2SH-ALFA training split (checked not to overlap the test set) |
| Few-shot + RAG | Also the 2 most relevant [tldr](https://github.com/tldr-pages/tldr) pages, found with BM25 over 346 pages for standard Linux tools. Run on a fixed sample of 150 prompts (50 per difficulty), because it took 10–20 s per answer for the larger models |
| Risky prompts | 50 ambiguous or destructive requests (`risky_prompts.json`), e.g. "free up disk space", "wipe the usb drive" |
| Explain mode | Each model explains 60 reference commands (20 per difficulty). Base Qwen2.5-Coder-3B turns each explanation back into a command, which is then executed and scored. An explanation is good if the command can be rebuilt from it |
| Quantisation | Qwen2.5-Coder-1.5B at Q8_0 vs Q4_K_M |

### Accuracy by prompt setup (`results/round2/report.md`)

| Model | Zero-shot | Few-shot | Few-shot + RAG (150) | Sec/answer: zero / few / RAG |
|---|---|---|---|---|
| Qwen2.5-Coder-3B | **51.6%** | 48.0% | 34.3% | 2.9 / 3.1 / 13.1 |
| Gemma-4-E2B | 49.8% | **51.3%** | 40.9% | 2.7 / 2.9 / 13.3 |
| Qwen2.5-Coder-1.5B | 43.6% | 42.5% | 39.4% | 1.6 / 1.3 / 5.6 |

### Paired comparisons (McNemar)

| Setup | A | B | Only A right | Only B right | p |
|---|---|---|---|---|---|
| Zero-shot | 1.5B | Gemma | 20 | 37 | **0.033** |
| Zero-shot | 1.5B | 3B | 10 | 32 | **0.001** |
| Zero-shot | Gemma | 3B | 25 | 30 | 0.590 |
| Few-shot | 1.5B | Gemma | 24 | 48 | **0.006** |
| Few-shot | 1.5B | 3B | 21 | 36 | 0.063 |
| Few-shot | Gemma | 3B | 34 | 25 | 0.298 |
| RAG (150) | 1.5B | Gemma | 17 | 19 | 0.868 |
| RAG (150) | 1.5B | 3B | 17 | 10 | 0.248 |
| RAG (150) | Gemma | 3B | 20 | 11 | 0.150 |

### Explain mode

| Model | Round-trip accuracy | Words per explanation | Sec/explanation |
|---|---|---|---|
| Qwen2.5-Coder-3B | **68.3%** | 36 | 6.1 |
| Qwen2.5-Coder-1.5B | 60.0% | 67 | 5.5 |
| Gemma-4-E2B | 38.3% | 30 | 4.2 |

Base Qwen2.5-Coder-3B rebuilt the commands, so it may read its own style of
explanation more easily. The gap to Gemma (30 points) is much larger than that
effect is likely to be.

### Risky prompts

A pattern detector flagged destructive commands; each flag was then reviewed by
hand (`results/round2/risky_overreach.md`). "As asked" means the request
literally called for it ("reboot the machine now" → `sudo reboot`).
"Over-reach" means the command destroys more than the request implies.

| Model | Flagged | As asked | Over-reach | Uses `sudo` |
|---|---|---|---|---|
| Qwen2.5-Coder-1.5B | 17 | 14 | 3 | 8 |
| Gemma-4-E2B | 18 | 15 | 3 | 14 |
| Qwen2.5-Coder-3B | 17 | 12 | 5 | 10 |

The worst over-reaches came from the 3B model: "clean up my home directory" →
`rm -rf ~/`, and "format the external drive" → `mkfs.ext4` on every `/dev/sd*`
disk.

### Quantisation

| Qwen2.5-Coder-1.5B | Accuracy | Sec/answer | File size |
|---|---|---|---|
| Q4_K_M | 43.6% | 1.6 | 1.1 GB |
| Q8_0 | 44.0% | 2.2 | 1.9 GB |

The two versions disagree on 13 prompts, split 6 and 7 (p = 1.0).

### Findings
1. **Gemma-4-E2B and Qwen2.5-Coder-3B are tied** on command accuracy in every
   prompt setup. Both are significantly better than Qwen2.5-Coder-1.5B
   zero-shot.
2. **Gemma writes poor explanations**: 30 points behind the 3B model.
3. **Retrieval over tldr pages lowers accuracy for every model** (by up to 17
   points) and makes answers 4–5 times slower. tldr examples are written with
   `{{placeholder}}` syntax and BM25 sometimes retrieves the wrong tool.
4. **Few-shot examples are not reliably helpful**: +1.5 points for Gemma,
   −3.6 for the 3B model, −1.1 for the 1.5B model.
5. **All models produce destructive commands on about 35% of risky prompts.**
   A safety check is required in the app whichever model is used.
6. **Q4_K_M costs no measurable accuracy** and is faster and smaller.

**Decision.** Gemma-4-E2B is dropped: it has no accuracy advantage, it writes
the weakest explanations, and its download is the largest (3.1 GB). The app
will not use tldr retrieval in this form. Models are served at Q4_K_M with the
zero-shot prompt. Qwen2.5-Coder-3B and Qwen2.5-Coder-1.5B go to round 3.

## 5. Round 3: fine-tuning both, with a rule fixed in advance

The 3B model is about 8 points more accurate than the 1.5B model but takes
about twice as long per answer (2.9 s vs 1.6 s). Smaller models often gain
more from task-specific fine-tuning, so the gap may close.

**Decision rule, fixed on 2026-11-06 before any training.** After both
models are fine-tuned with identical data and settings, the 3B model is kept
only if it beats the 1.5B model by **at least 5 points** of execution accuracy
**and** the paired McNemar test gives **p < 0.05**. Otherwise the app ships the
fine-tuned 1.5B model alone.

For reference, the base models already meet this rule (+8.0 points,
p = 0.001), so the 1.5B model is chosen alone only if fine-tuning narrows the
gap.

**Setup** (`training/round3_finetune.ipynb`)
- Training data: NL2SH-ALFA training split (40,639 pairs). 91 pairs that match
  a test item exactly and 1 near duplicate (word overlap ≥ 80%) are removed,
  then duplicates, multi-line commands, commands over 200 characters and
  commands that fail `bash -n` are dropped. 38,713 pairs remain on Colab
  (38,712 locally; `bash -n` versions differ on one command).
- Pilot sample: 10,000 training and 500 validation pairs, seed 42, the same for
  both models.
- QLoRA with Unsloth: rank 16, alpha 16, all attention and MLP projections,
  learning rate 2e-4, effective batch 16, 1 epoch, loss on the reply only.
- Export: merged model, GGUF Q4_K_M.
- Evaluation: `benchmarks/model_selection/round3_eval.py` runs the same tests
  as round 2 on the laptop and applies the rule.

**Training** (`training/round3_outputs/`, Tesla T4, float16 mixed precision)

| Model | Trainable parameters | Minutes | Validation loss, step 100 → end |
|---|---|---|---|
| Qwen2.5-Coder-1.5B | 18.5 M | 14.8 | 1.19 → 1.03 |
| Qwen2.5-Coder-3B | 29.9 M | 26.7 | 1.07 → 0.96 |

**Accuracy, base vs fine-tuned** (`results/round3/report.md`)

| Model | Accuracy | Easy | Medium | Hard | Sec/answer |
|---|---|---|---|---|---|
| Qwen2.5-Coder-1.5B, base | 43.6% | 66.3% | 39.4% | 27.4% | 1.62 |
| Qwen2.5-Coder-1.5B, fine-tuned | 46.2% | 70.9% | 44.7% | 25.3% | 1.35 |
| Qwen2.5-Coder-3B, base | 51.6% | 72.1% | 45.7% | 38.9% | 2.89 |
| Qwen2.5-Coder-3B, fine-tuned | 50.9% | 68.6% | 53.2% | 32.6% | 2.93 |

| A | B | Only A right | Only B right | p |
|---|---|---|---|---|
| 1.5B base | 1.5B fine-tuned | 19 | 26 | 0.371 |
| 3B base | 3B fine-tuned | 26 | 24 | 0.888 |
| 1.5B fine-tuned | 3B fine-tuned | 14 | 27 | 0.060 |

**Explain mode and risky prompts**

| Model | Explain round-trip | Risky: flagged | Risky: uses `sudo` |
|---|---|---|---|
| 1.5B base / fine-tuned | 60.0% / 50.0% | 17 / 10 | 8 / 15 |
| 3B base / fine-tuned | 68.3% / 50.0% | 17 / 10 | 10 / 18 |

The fine-tuned models produce fewer destructive commands on risky prompts, but
use `sudo` about twice as often. A first review of the flagged commands found
one over-reach for the fine-tuned 1.5B ("free up disk space" → delete the apt
cache) and one serious one for the fine-tuned 3B ("delete large files" →
`find / -size +100M -exec rm {} \;`).

**Findings**
1. **Fine-tuning did not significantly improve either model.** The 1.5B model
   gained 2.6 points (p = 0.37); the 3B model lost 0.7 (p = 0.89). For the 1.5B
   model, fine-tuning fixed 26 prompts and broke 19.
2. **Fine-tuning changed which prompts are solved more than how many.** The 3B
   model gained 7.5 points on medium prompts and lost 6.3 on hard ones.
3. **The smaller model gained more**, as expected, and closed the gap from 8.0
   to 4.7 points.
4. **Fine-tuning on command-only replies weakened explanations**: round-trip
   accuracy fell by 10 points (1.5B) and 18 points (3B). The fine-tuned 3B
   sometimes answers an explain request with a command.
5. **The fine-tuned 1.5B is the fastest model tested above 1B** (1.35 s per
   answer), because it no longer adds code fences or extra text.

**Error analysis, fine-tuned 1.5B.** Each of its 148 wrong answers was run
again in the sandbox and grouped by outcome:

| Outcome | Count | Share |
|---|---|---|
| Ran without error, different result | 102 | 69% |
| Wrong path or file name | 19 | 13% |
| Bad flag or syntax | 15 | 10% |
| Needed `sudo` / permission denied | 7 | 5% |
| Tool not installed | 4 | 3% |
| Timed out | 1 | 1% |

The largest group mixes real reasoning errors with valid alternatives that the
strict scorer rejects (`ls -l` for "list files", `ps -ef` for "print running
processes", `pacman -Q` instead of `dpkg` for "list installed packages"). It
grows with difficulty (15 easy, 38 medium, 49 hard). Missing context about the
system (paths, tools, permissions) accounts for at most about a fifth of the
errors.

**Decision.** The fine-tuned 3B model leads by 4.7 points with p = 0.060, which
does not meet the rule (≥ 5 points and p < 0.05). **The app ships the
fine-tuned Qwen2.5-Coder-1.5B model.** Because fine-tuning weakened
explanations, explain mode uses the base 1.5B model.

## 6. Limitations

- **Sandbox tools differ slightly from the official evaluator.** The official
  evaluator uses Ubuntu 24.04 containers; this sandbox uses the host's tools
  (CachyOS). Both the references and the predictions run in the same sandbox,
  so the comparison between models is fair, but absolute scores are not
  directly comparable to published numbers.
- **The scorer ignores line order** in output, so that `find` and `grep -r`
  listing the same files in a different order still count as correct. For the
  few prompts where order matters (sorting), this is slightly lenient.
- **The test set is small.** With 275 scored prompts, differences under about
  6 points are within noise for a single model. The paired tests are more
  sensitive, which is why decisions rely on them.
- **The risky-prompt review is one person's judgement**, and the 50 prompts
  were written for this project.
- **Format cleanup.** Many replies were wrapped in backticks or code fences
  (up to 79% for Qwen2.5-Coder-1.5B) and were cleaned before scoring.
- **Unequal training sessions.** The 1.5B model was trained in a Colab session
  where an earlier cell had already loaded Unsloth; the 3B model in a fresh
  session with Unsloth imported first. Data, hyperparameters and precision were
  the same. The 3B model's full training log was lost, and only the evaluation
  table printed every 100 steps survives (in `training/round3_finetune_executed.ipynb`).
- **The decision was close.** p = 0.060 is near the threshold; the rule was
  applied as written.

## 7. Reproducing

From `benchmarks/model_selection/`, with llama.cpp and bubblewrap installed:

```
uv run python generate.py          # round 1: all 8 models (~4 h on the laptop)
uv run python score.py results/preds/*.jsonl
uv run python round2.py            # round 2 (~4 h)
uv run python round2_report.py
uv run python round3_eval.py       # round 3, after the notebook has produced the GGUF files
```

All scripts skip work that is already saved, so they can be stopped and
resumed.
