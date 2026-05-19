class ContextForgeConfigError(Exception):
    """
    Custom exception for configuration-related errors in ContextForge.

    This helps distinguish config issues from other runtime problems,
    allowing for more specific error handling and clearer user feedback.
    """
    pass