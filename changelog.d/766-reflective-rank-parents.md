Fixed
ReflectiveFusion now ranks a synthesised union against its parent singles before the acceptance gate, so a merge that loses to a stronger parent cannot commit just because it still beats the seed (`trust_union=True` keeps the older cheap unranked path).
