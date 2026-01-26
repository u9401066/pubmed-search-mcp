"""
Mutation Testing Configuration for mutmut.

Mutation testing helps verify test quality by introducing bugs
and checking if tests catch them.
"""


def pre_mutation(context):
    """Called before each mutation."""
    # Skip mutation testing for certain patterns
    line = context.current_source_line.strip()

    # Don't mutate logging statements
    if "log." in line or "logger." in line or "print(" in line:
        context.skip = True

    # Don't mutate type hints
    if " -> " in line and ":" in line:
        context.skip = True

    # Don't mutate docstrings
    if line.startswith('"""') or line.startswith("'''"):
        context.skip = True

    # Don't mutate __init__.py imports
    if context.filename.endswith("__init__.py"):
        context.skip = True


def post_mutation(context):
    """Called after each mutation."""
    pass
