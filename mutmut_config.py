"""Configuration for mutmut mutation testing framework."""


def pre_mutation(context):
    """Skip files that shouldn't be mutated."""
    if context.filename.endswith("__init__.py"):
        context.skip = True
    elif "alembic" in context.filename:
        context.skip = True
    elif "migrations" in context.filename:
        context.skip = True
    # Skip gateway_service.py due to Python 3.11+ except* syntax not supported by mutmut parser
    elif "gateway_service.py" in context.filename:
        context.skip = True


def post_mutation(context):
    """Any post-mutation processing."""
    pass