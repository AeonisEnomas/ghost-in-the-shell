# Round 4 training records

Copied from the Colab output folder after training.

- `train.csv`, `val.csv`: the exact pairs the model was trained and validated
  on (columns: request, command, source dataset, tool).
- `data_manifest.json`: dataset revisions, how many pairs each filter removed,
  and a checksum of `train.csv`.
- `run_info.json`: settings and outcome of the training run.
- `log_history.csv`: training loss every 50 steps and validation loss every
  250.
- `versions.json`: package versions on the Colab machine.

The notebook's outputs were not saved, and the base-model export in the
committed notebook was corrected after the run: during the run it failed once
and was repeated with the model loaded in full precision, which is what the
notebook now does.
