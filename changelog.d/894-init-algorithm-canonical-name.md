Fixed
`init --algorithm` writes the registered algorithm name into the spec, so
`--algorithm GEPA` or `archive-selection` is saved as `gepa` /
`archive_selection` (matching `algorithms list` and `algorithms run`) instead
of the alias as typed (#894).
