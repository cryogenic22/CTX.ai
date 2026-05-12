# Intentionally broken Python — used by CP-002 tests to verify the
# parser surfaces warnings instead of crashing.
#
# DO NOT FIX. This file is not meant to be syntactically valid.

def broken(
    # missing closing paren and colon — tree-sitter will produce an
    # ERROR node here and continue parsing.

def survivor():
    """This function lives below the syntax error and should still be
    visible in the partial tree.
    """
    return 42
