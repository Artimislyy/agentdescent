Fixed
When a GSM8K research port cannot fetch the dataset, the error now ends with
what to do next: `pip install pyarrow` (when that is why the parquet path
failed), set `HF_ENDPOINT` to a reachable mirror, or set
`AGENTDESCENT_GSM8K_SAMPLE=1` for the bundled offline sample (#870).
