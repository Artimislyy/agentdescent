Fixed
GEPA no longer stores unused `conflict`/`promotion`/`screen` Policies as
attributes, so #807's orphan check fails closed instead of reporting them
as active (#839).
