from typing import Optional, Dict

class URLPluginResult:
    """
    Represents the result of a URL reputation check.

    Attributes:
        continue_processing: Whether the URL passed all checks.
        violation: Optional dictionary describing the violation if blocked.
    """
    continue_processing: bool
    violation: Optional[Dict[str, str]]


class URLReputationPlugin:
    """
    URLReputationPlugin evaluates URLs against a configurable reputation policy.

    Checks include:
    - Whitelist/blocked domains
    - Allowed/blocked URL patterns (regex)
    - Non-secure HTTP blocking
    - Heuristic checks (entropy, TLD, unicode safety)
    """
    continue_processing: bool
    violation: Optional[Dict[str, str]]

    def __init__(self, config: "URLReputationConfig") -> None:
        """
        Initialize the URLReputationPlugin with a configuration.

        Args:
            config: URLReputationConfig object containing whitelist, blocked patterns, etc.
        """

    def validate_url(self, url: str) -> URLPluginResult:
        """
        Validate a URL against the plugin's rules.

        Args:
            url: The URL to evaluate.

        Returns:
            URLPluginResult: Contains `continue_processing` flag and optional violation info.
        """
