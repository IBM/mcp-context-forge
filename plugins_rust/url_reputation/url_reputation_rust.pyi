from typing import Optional, Dict, Set, List


class URLReputationPlugin:
    """
    URLReputationPlugin evaluates URLs against a configurable reputation policy.

    Checks include:
    - Whitelist/blocklist domain matching
    - Pattern-based URL filtering
    - Heuristic analysis (entropy, suspicious patterns)
    - HTTP/HTTPS enforcement
    """

    def __init__(self, config: URLReputationConfig) -> None:
        """
        Initialize the URLReputationPlugin with a configuration.

        Args:
            config: URLReputationConfig object containing whitelist, blocked patterns, etc.
        """
        ...

    def validate_url(self, url: str) -> URLPluginResult:
        """
        Validate a URL against the plugin's rules.

        Args:
            url: The URL to evaluate.

        Returns:
            URLPluginResult: Contains `continue_processing` flag and optional violation info.
        """
        ...
