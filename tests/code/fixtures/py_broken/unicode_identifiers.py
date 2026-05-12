# Non-ASCII identifiers — valid Python, pins utf-8 round-trip
# through the parser wrapper.

café = 1
naïve_count = 2


def Δ_change(α: int, β: int) -> int:
    return β - α
