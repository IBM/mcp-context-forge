# -*- coding: utf-8 -*-
"""Unit tests for UAID (Universal Agent ID) utilities.

Tests HCS-14 UAID parsing, validation, and generation logic.
"""

# Standard
import hashlib
import json

# Third-Party
import base58
import pytest

# First-Party
from mcpgateway.utils.uaid import (
    HOP_HEADER,
    _HOP_MAX,
    extract_routing_info,
    generate_uaid,
    is_uaid,
    parse_hop_count,
    parse_uaid,
    read_hop_count,
    stamp_hop,
    UaidComponents,
    validate_uaid,
)


class TestIsUaid:
    """Test UAID format detection."""

    def test_is_uaid_aid_method(self):
        """Test aid-based UAID detection."""
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        assert is_uaid(uaid) is True

    def test_is_uaid_did_method(self):
        """Test did-based UAID detection."""
        uaid = "uaid:did:z6MkhaXgBZDvotDkL5257;uid=0;proto=a2a;nativeId=agent.example.com"
        assert is_uaid(uaid) is True

    def test_is_not_uaid_uuid(self):
        """Test UUID is not detected as UAID."""
        uuid = "123e4567-e89b-12d3-a456-426614174000"
        assert is_uaid(uuid) is False

    def test_is_not_uaid_empty(self):
        """Test empty string is not UAID."""
        assert is_uaid("") is False

    def test_is_not_uaid_random_string(self):
        """Test random string is not UAID."""
        assert is_uaid("not-a-uaid") is False


class TestParseUaid:
    """Test UAID parsing."""

    def test_parse_uaid_aid_method(self):
        """Test parsing aid-based UAID."""
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        components = parse_uaid(uaid)

        assert isinstance(components, UaidComponents)
        assert components.method == "aid"
        assert components.hash_or_did == "9BjK3mP7xQv"
        assert components.uid == "0"
        assert components.registry == "context-forge"
        assert components.proto == "a2a"
        assert components.native_id == "agent.example.com"

    def test_parse_uaid_did_method(self):
        """Test parsing did-based UAID."""
        uaid = "uaid:did:z6MkhaXgBZDvotDkL5257;uid=0;proto=a2a;nativeId=agent.example.com"
        components = parse_uaid(uaid)

        assert isinstance(components, UaidComponents)
        assert components.method == "did"
        assert components.hash_or_did == "z6MkhaXgBZDvotDkL5257"
        assert components.uid == "0"
        assert components.registry is None  # did method doesn't require registry
        assert components.proto == "a2a"
        assert components.native_id == "agent.example.com"

    def test_parse_uaid_did_method_with_registry(self):
        """Test parsing did-based UAID with optional registry."""
        uaid = "uaid:did:z6MkhaXgBZDvotDkL5257;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        components = parse_uaid(uaid)

        assert components.method == "did"
        assert components.registry == "context-forge"

    def test_parse_uaid_invalid_format(self):
        """Test parsing invalid UAID format."""
        with pytest.raises(ValueError, match="Invalid UAID format"):
            parse_uaid("not-a-uaid")

    @pytest.mark.parametrize(
        "injected",
        [
            "\n",  # LF — primary log-injection vector
            "\r",  # CR
            "\r\n",  # CRLF
            "\x00",  # NUL
            "\t",  # horizontal tab (also rejected per HCS-14 printable-field rule)
            "\x7f",  # DEL
        ],
        ids=["lf", "cr", "crlf", "nul", "tab", "del"],
    )
    def test_parse_uaid_rejects_ascii_control_characters(self, injected):
        """Control characters turn UAIDs into log-injection vectors; the
        parser must reject them wholesale before any downstream formatting.
        Rust's `parse_uaid` enforces the same contract in
        `crates/a2a_runtime/src/uaid.rs` — this parity is security-critical.
        Without the check a malicious UAID carrying CRLF could forge log
        lines or HTTP headers downstream."""
        uaid = f"uaid:aid:HASH{injected};uid=0;registry=cf;proto=a2a;nativeId=agent.example.com"
        with pytest.raises(ValueError, match="ASCII control characters"):
            parse_uaid(uaid)

    def test_parse_uaid_missing_method(self):
        """Test parsing UAID with missing method (too few colons)."""
        with pytest.raises(ValueError, match="Invalid UAID format: must start with 'uaid:aid:' or 'uaid:did:'"):
            parse_uaid("uaid:9BjK3mP7xQv;uid=0")

    def test_parse_uaid_invalid_method(self):
        """Test parsing UAID with invalid method (not aid or did)."""
        with pytest.raises(ValueError, match="Invalid UAID format: must start with 'uaid:aid:' or 'uaid:did:'"):
            parse_uaid("uaid:xyz:9BjK3mP7xQv;uid=0;proto=a2a;nativeId=agent.example.com")

    def test_parse_uaid_missing_uid(self):
        """Test parsing UAID with missing uid parameter."""
        with pytest.raises(ValueError, match="missing required 'uid' parameter"):
            parse_uaid("uaid:aid:9BjK3mP7xQv;registry=context-forge;proto=a2a;nativeId=agent.example.com")

    def test_parse_uaid_missing_proto(self):
        """Test parsing UAID with missing proto parameter."""
        with pytest.raises(ValueError, match="missing required 'proto' parameter"):
            parse_uaid("uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;nativeId=agent.example.com")

    def test_parse_uaid_missing_native_id(self):
        """Test parsing UAID with missing nativeId parameter."""
        with pytest.raises(ValueError, match="missing required 'nativeId' parameter"):
            parse_uaid("uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a")

    def test_parse_uaid_aid_missing_registry(self):
        """Test parsing aid UAID with missing registry (required for aid method)."""
        with pytest.raises(ValueError, match="'registry' parameter required for aid method"):
            parse_uaid("uaid:aid:9BjK3mP7xQv;uid=0;proto=a2a;nativeId=agent.example.com")

    def test_parse_uaid_no_semicolons(self):
        """Test parsing UAID with no semicolons (no parameters)."""
        with pytest.raises(ValueError, match="Invalid UAID format: expected hash/did and parameters"):
            parse_uaid("uaid:aid:9BjK3mP7xQv")

    def test_parse_uaid_invalid_parameter_format(self):
        """Test parsing UAID with parameter not in key=value format."""
        with pytest.raises(ValueError, match="Invalid UAID parameter: expected 'key=value' format"):
            parse_uaid("uaid:aid:9BjK3mP7xQv;uid=0;invalidparam;proto=a2a;nativeId=agent.example.com")


class TestExtractRoutingInfo:
    """Test routing information extraction."""

    def test_extract_routing_info_aid(self):
        """Test extracting routing info from aid-based UAID."""
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        routing = extract_routing_info(uaid)

        assert routing["protocol"] == "a2a"
        assert routing["endpoint"] == "agent.example.com"
        assert routing["registry"] == "context-forge"

    def test_extract_routing_info_did(self):
        """Test extracting routing info from did-based UAID."""
        uaid = "uaid:did:z6MkhaXgBZDvotDkL5257;uid=0;proto=mcp;nativeId=mcp.example.com"
        routing = extract_routing_info(uaid)

        assert routing["protocol"] == "mcp"
        assert routing["endpoint"] == "mcp.example.com"
        assert routing["registry"] is None

    def test_extract_routing_info_different_protocols(self):
        """Test extracting routing info for different protocols."""
        protocols = ["a2a", "mcp", "rest", "grpc"]

        for proto in protocols:
            uaid = f"uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto={proto};nativeId=agent.example.com"
            routing = extract_routing_info(uaid)
            assert routing["protocol"] == proto


class TestGenerateUaid:
    """Test UAID generation."""

    def test_generate_uaid_basic(self):
        """Test basic UAID generation."""
        uaid = generate_uaid(
            registry="context-forge",
            name="Test Agent",
            version="1.0.0",
            protocol="a2a",
            native_id="agent.example.com",
            skills=[0, 17],
        )

        assert is_uaid(uaid)
        assert "uaid:aid:" in uaid
        assert "uid=0" in uaid
        assert "registry=context-forge" in uaid
        assert "proto=a2a" in uaid
        assert "nativeId=agent.example.com" in uaid

    def test_generate_uaid_deterministic(self):
        """Test UAID generation is deterministic for same inputs."""
        uaid1 = generate_uaid(
            registry="context-forge",
            name="Test Agent",
            version="1.0.0",
            protocol="a2a",
            native_id="agent.example.com",
            skills=[0, 17],
        )

        uaid2 = generate_uaid(
            registry="context-forge",
            name="Test Agent",
            version="1.0.0",
            protocol="a2a",
            native_id="agent.example.com",
            skills=[0, 17],
        )

        assert uaid1 == uaid2

    def test_generate_uaid_skills_order_independent(self):
        """Test UAID generation is independent of skills order."""
        uaid1 = generate_uaid(
            registry="context-forge",
            name="Test Agent",
            version="1.0.0",
            protocol="a2a",
            native_id="agent.example.com",
            skills=[0, 17, 5],
        )

        uaid2 = generate_uaid(
            registry="context-forge",
            name="Test Agent",
            version="1.0.0",
            protocol="a2a",
            native_id="agent.example.com",
            skills=[17, 5, 0],  # Different order
        )

        # Skills are sorted internally, so hash should be the same
        assert uaid1 == uaid2

    def test_generate_uaid_different_inputs_different_hash(self):
        """Test different inputs produce different UAIDs."""
        uaid1 = generate_uaid(
            registry="context-forge",
            name="Agent One",
            version="1.0.0",
            protocol="a2a",
            native_id="agent1.example.com",
            skills=[0],
        )

        uaid2 = generate_uaid(
            registry="context-forge",
            name="Agent Two",
            version="1.0.0",
            protocol="a2a",
            native_id="agent2.example.com",
            skills=[0],
        )

        # Different names should produce different hashes
        assert uaid1 != uaid2

        # Extract hashes to compare
        hash1 = uaid1.split(";")[0].split(":")[2]
        hash2 = uaid2.split(";")[0].split(":")[2]
        assert hash1 != hash2

    def test_generate_uaid_normalization(self):
        """Test UAID generation normalizes inputs."""
        # Trailing/leading spaces should be trimmed
        uaid1 = generate_uaid(
            registry="  context-forge  ",
            name="  Test Agent  ",
            version="  1.0.0  ",
            protocol="  A2A  ",  # Should be lowercased
            native_id="  agent.example.com  ",
            skills=[0],
        )

        uaid2 = generate_uaid(
            registry="context-forge",
            name="Test Agent",
            version="1.0.0",
            protocol="a2a",
            native_id="agent.example.com",
            skills=[0],
        )

        assert uaid1 == uaid2

    def test_generate_uaid_canonical_json(self):
        """Test UAID uses canonical JSON for hashing."""
        # Verify the canonical JSON structure matches HCS-14 spec
        canonical = {
            "name": "Test Agent",
            "nativeId": "agent.example.com",
            "protocol": "a2a",
            "registry": "context-forge",
            "skills": [0, 17],
            "version": "1.0.0",
        }

        canonical_json = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
        hash_bytes = hashlib.sha384(canonical_json.encode("utf-8")).digest()
        expected_hash = base58.b58encode(hash_bytes).decode("ascii")

        uaid = generate_uaid(
            registry="context-forge",
            name="Test Agent",
            version="1.0.0",
            protocol="a2a",
            native_id="agent.example.com",
            skills=[0, 17],
        )

        # Extract hash from UAID
        actual_hash = uaid.split(";")[0].split(":")[2]
        assert actual_hash == expected_hash

    def test_generate_uaid_custom_uid(self):
        """Test UAID generation with custom uid."""
        uaid = generate_uaid(
            registry="context-forge",
            name="Test Agent",
            version="1.0.0",
            protocol="a2a",
            native_id="agent.example.com",
            skills=[],
            uid="custom-uid",
        )

        assert "uid=custom-uid" in uaid

    def test_generate_uaid_empty_skills(self):
        """Test UAID generation with empty skills list."""
        uaid = generate_uaid(
            registry="context-forge",
            name="Test Agent",
            version="1.0.0",
            protocol="a2a",
            native_id="agent.example.com",
            skills=[],
        )

        assert is_uaid(uaid)
        components = parse_uaid(uaid)
        assert components.proto == "a2a"


class TestValidateUaid:
    """Test UAID validation."""

    def test_validate_uaid_valid_aid(self):
        """Test validation of valid aid-based UAID."""
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        is_valid, error = validate_uaid(uaid)

        assert is_valid is True
        assert error is None

    def test_validate_uaid_valid_did(self):
        """Test validation of valid did-based UAID."""
        uaid = "uaid:did:z6MkhaXgBZDvotDkL5257;uid=0;proto=a2a;nativeId=agent.example.com"
        is_valid, error = validate_uaid(uaid)

        assert is_valid is True
        assert error is None

    def test_validate_uaid_invalid_format(self):
        """Test validation of invalid UAID format."""
        is_valid, error = validate_uaid("not-a-uaid")

        assert is_valid is False
        assert error is not None
        assert "Invalid UAID format" in error

    def test_validate_uaid_missing_parameter(self):
        """Test validation of UAID with missing parameter."""
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a"  # Missing nativeId
        is_valid, error = validate_uaid(uaid)

        assert is_valid is False
        assert error is not None
        assert "nativeId" in error


class TestUaidRoundTrip:
    """Test UAID generation and parsing round-trip."""

    def test_generate_and_parse_round_trip(self):
        """Test generating and parsing UAID round-trip."""
        # Generate UAID
        original_data = {
            "registry": "context-forge",
            "name": "Test Agent",
            "version": "1.0.0",
            "protocol": "a2a",
            "native_id": "agent.example.com",
            "skills": [0, 17, 5],
        }

        uaid = generate_uaid(**original_data)

        # Parse UAID
        components = parse_uaid(uaid)

        # Verify round-trip
        assert components.registry == original_data["registry"]
        assert components.proto == original_data["protocol"]
        assert components.native_id == original_data["native_id"]

        # Extract routing info
        routing = extract_routing_info(uaid)
        assert routing["protocol"] == original_data["protocol"]
        assert routing["endpoint"] == original_data["native_id"]
        assert routing["registry"] == original_data["registry"]


class TestUaidDoSProtection:
    """Test UAID DoS protection via length limits."""

    def test_parse_uaid_exceeds_max_length(self, monkeypatch):
        """Test UAID parsing rejects strings exceeding UAID_MAX_LENGTH."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "uaid_max_length", 2048)

        # Create UAID exceeding limit (3000 chars)
        long_uaid = "uaid:aid:" + "x" * 3000

        with pytest.raises(ValueError, match="exceeds maximum length of 2048"):
            parse_uaid(long_uaid)

    def test_parse_uaid_respects_configured_max_length(self, monkeypatch):
        """Test parsing respects UAID_MAX_LENGTH configuration.

        Note: In production, settings.uaid_max_length is enforced by Pydantic Field(le=2048)
        which prevents configuration exceeding the database column limit. This test uses
        monkeypatch to verify the validation logic, but in real deployments the Pydantic
        constraint would prevent misconfiguration at startup.
        """
        # First-Party
        from mcpgateway.config import settings

        # Set a lower limit for testing
        monkeypatch.setattr(settings, "uaid_max_length", 100)

        # Create a UAID longer than 100 characters
        long_uaid = "uaid:aid:" + "x" * 150

        with pytest.raises(ValueError, match="exceeds maximum length of 100"):
            parse_uaid(long_uaid)

    def test_parse_uaid_invalid_method_dos_context(self):
        """Test UAID parsing rejects invalid methods in DoS context."""
        # Edge case: malformed UAID with invalid method
        # Caught by is_uaid() check at line 104-105
        invalid_uaid = "uaid:invalid:hash123;uid=0;registry=test;proto=a2a;nativeId=example.com"

        with pytest.raises(ValueError, match="Invalid UAID format: must start with 'uaid:aid:' or 'uaid:did:'"):
            parse_uaid(invalid_uaid)

    def test_parse_uaid_too_short_dos_context(self):
        """Test UAID parsing rejects incomplete UAID strings in DoS context."""
        # Edge case: UAID missing hash and parameters
        # Caught by is_uaid() check at line 104-105
        short_uaid = "uaid:aid"  # Missing colon, hash, and parameters

        with pytest.raises(ValueError, match="Invalid UAID format: must start with 'uaid:aid:' or 'uaid:did:'"):
            parse_uaid(short_uaid)

    def test_parse_uaid_normal_config_length(self, monkeypatch):
        """Test UAID parsing uses settings when within DB limit (covers lines 84, 88)."""
        # First-Party
        from mcpgateway.config import settings

        # Set config to value within DB limit (normal case)
        monkeypatch.setattr(settings, "uaid_max_length", 1024)  # Within 2048 DB limit

        valid_uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=example.com"
        result = parse_uaid(valid_uaid)

        # Should succeed without warning
        assert result.method == "aid"
        assert result.registry == "context-forge"

    def test_parse_uaid_too_few_parts_after_is_uaid_bypass(self, monkeypatch):
        """Test UAID parsing with too few parts after colon split (covers line 104).

        This is a defensive check that should never be reached in normal operation
        since is_uaid() checks for proper format. We bypass is_uaid() via mocking
        to test the defensive code path.
        """
        # Mock is_uaid to return True to bypass the initial check
        monkeypatch.setattr("mcpgateway.utils.uaid.is_uaid", lambda x: True)

        # Create a malformed UAID that would pass is_uaid() if mocked but fails split check
        # When split with maxsplit=3, "uaid:x" gives ["uaid", "x"] which is < 3 parts
        malformed_uaid = "uaid:x"

        with pytest.raises(ValueError, match="Invalid UAID format: expected 'uaid:METHOD:...' format"):
            parse_uaid(malformed_uaid)

    def test_parse_uaid_invalid_method_after_is_uaid_bypass(self, monkeypatch):
        """Test UAID parsing with invalid method (covers line 108).

        This is a defensive check that should never be reached in normal operation
        since is_uaid() checks for 'uaid:aid:' or 'uaid:did:' prefix. We bypass
        is_uaid() via mocking to test the defensive code path.
        """
        # Mock is_uaid to return True to bypass the initial check
        monkeypatch.setattr("mcpgateway.utils.uaid.is_uaid", lambda x: True)

        # Create a malformed UAID with invalid method
        malformed_uaid = "uaid:invalid:hash;uid=0;registry=test;proto=a2a;nativeId=example.com"

        with pytest.raises(ValueError, match="Invalid UAID method: expected 'aid' or 'did'"):
            parse_uaid(malformed_uaid)


class TestHopCounter:
    """Tests for the federation-loop hop counter parse/stamp helpers.

    These are the security-critical API that both Python and Rust
    runtimes must agree on byte-for-byte — a lenient parser on one side
    creates a split-brain where an attacker-controlled intermediate can
    pad header values to reset the counter on one runtime but not the
    other.
    """

    def test_parse_hop_count_missing_returns_zero(self):
        assert parse_hop_count(None) == 0

    def test_parse_hop_count_empty_returns_zero(self):
        assert parse_hop_count("") == 0

    def test_parse_hop_count_plain_digits(self):
        assert parse_hop_count("0") == 0
        assert parse_hop_count("3") == 3
        assert parse_hop_count("999") == 999

    @pytest.mark.parametrize(
        "bad",
        [
            " 3",  # leading whitespace
            "3 ",  # trailing whitespace
            "+3",  # leading plus
            "-1",  # leading minus
            "3.0",  # decimal
            "0x10",  # hex
            "NaN",  # text
            "   5",  # tab
            "five",  # spelled-out
            "\uff11",  # fullwidth digit 1 (U+FF11) — str.isdigit()=True
            "\uff12\uff13",  # fullwidth "23"
            "\u0663",  # Arabic-Indic 3 (U+0663) — str.isdigit()=True
            "1\uff12",  # mixed ASCII + fullwidth
        ],
        ids=[
            "leading-space",
            "trailing-space",
            "leading-plus",
            "leading-minus",
            "decimal",
            "hex",
            "nan",
            "leading-tab",
            "spelled",
            "fullwidth-1",
            "fullwidth-23",
            "arabic-3",
            "mixed-ascii-fullwidth",
        ],
    )
    def test_parse_hop_count_rejects_malformed_to_zero(self, bad):
        """Strict parse: anything that is not pure ASCII digits → 0.

        Matches the Rust `parse_hop_count` in `crates/a2a_runtime/src/server.rs`
        (`bytes().all(|b| b.is_ascii_digit())`).  Python `str.isdigit()`
        alone is too permissive — it returns True for fullwidth,
        Arabic-Indic, and other Unicode digit characters that `int()`
        also parses.  Without the `raw.isascii()` gate an attacker
        could send `"１"` and have Python count it as hop 1 while Rust
        treats it as 0, defeating the federation guard.
        """
        assert parse_hop_count(bad) == 0

    def test_parse_hop_count_saturates_on_overflow(self):
        """Astronomical integers saturate to _HOP_MAX rather than
        silently falling back to 0 (the loop guard must fire)."""
        assert parse_hop_count("999999999999999999999") == _HOP_MAX
        assert parse_hop_count(str(_HOP_MAX + 1)) == _HOP_MAX

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("0,10", 10),  # coalesced, no spaces
            ("0, 10", 10),  # RFC 7230 OWS
            ("10, 0", 10),  # order-agnostic
            (" 10 , 0 ", 10),  # leading/trailing OWS on tokens
            ("\t3,\t7", 7),  # tab OWS (RFC 7230 §3.2.6)
            ("3,garbage,10", 10),  # garbage token ignored, good tokens counted
            ("garbage, 5", 5),  # bad token skipped; good one wins
            ("-1, 0", 0),  # both invalid/low; max=0 (first rejected, second valid)
            ("1, \uff12", 1),  # fullwidth digit rejected; ASCII 1 survives
            (",", 0),  # comma alone → empty tokens → 0
            ("3,", 3),  # trailing comma OK
            (",3", 3),  # leading comma OK
        ],
        ids=[
            "coalesced-no-space",
            "coalesced-ows",
            "reverse-order",
            "outer-ows",
            "tab-ows",
            "mid-garbage",
            "leading-garbage",
            "both-invalid-low",
            "unicode-fullwidth-skipped",
            "comma-only",
            "trailing-comma",
            "leading-comma",
        ],
    )
    def test_parse_hop_count_handles_coalesced_form(self, raw, expected):
        """RFC 7230 §3.2.2 combined-form duplicate headers.

        A proxy may legally combine `X-Hop: 0` and `X-Hop: 10` into
        `X-Hop: 0, 10`.  The parser must split on `,`, trim OWS per
        §3.2.6, apply the single-value strict rules per token, and
        return the MAX so a smuggled low value can't mask a real high
        one.  Malformed tokens inside the list are ignored (not
        fatal), because otherwise an attacker could pair a good hop
        with `garbage` to force the whole header to 0.
        """
        assert parse_hop_count(raw) == expected

    def test_read_hop_count_uses_canonical_header_name(self):
        assert read_hop_count({HOP_HEADER: "4"}) == 4
        assert read_hop_count({}) == 0

    def test_stamp_hop_increments_and_writes(self):
        headers: dict[str, str] = {}
        stamp_hop(headers, 2)
        assert headers[HOP_HEADER] == "3"

    def test_stamp_hop_saturates_near_ceiling(self):
        headers: dict[str, str] = {}
        stamp_hop(headers, _HOP_MAX)
        assert headers[HOP_HEADER] == str(_HOP_MAX)
        stamp_hop(headers, _HOP_MAX + 100)  # defensive: treat as at ceiling
        assert headers[HOP_HEADER] == str(_HOP_MAX)

    def test_read_hop_count_takes_max_across_case_variants(self):
        """Header smuggling defense: an attacker who sends multiple
        case variants with different values must not be able to pick
        the lowest via HashMap iteration order."""
        headers = {
            "X-Contextforge-UAID-Hop": "0",  # attacker-crafted low value
            "x-contextforge-uaid-hop": "10",  # real value
        }
        assert read_hop_count(headers) == 10

    def test_read_hop_count_takes_max_from_starlette_getlist(self):
        """With a starlette-style `getlist` API, all duplicate values
        are visible — take the max defensively."""

        class FakeHeaders:
            def __init__(self, values):
                self._values = values

            def getlist(self, name):
                if name == HOP_HEADER:
                    return list(self._values)
                return []

            def items(self):
                # Not exercised in this branch but satisfies the protocol.
                return []

        assert read_hop_count(FakeHeaders(["0", "7", "3"])) == 7
        assert read_hop_count(FakeHeaders([])) == 0

    def test_read_hop_count_handles_truthy_but_empty_iterable(self):
        """Regression guard: an object whose `getlist` returns a value
        that is truthy yet iterates to empty (MagicMock default, some
        Header proxy types) must not crash with `max([])`.  Previously
        the iterator was consumed after the truthiness check, then `max`
        raised `ValueError` — surfaced by unit tests that mock
        `request.headers` with a bare `MagicMock`.
        """

        class TruthyEmpty:
            """Truthy object whose iterator yields nothing — mimics a
            MagicMock passed in as a headers stand-in."""

            def __bool__(self):
                return True

            def __iter__(self):
                return iter(())

        class FakeHeaders:
            def getlist(self, name):
                # Returns a truthy-but-empty iterable to exercise the
                # fall-through branch.
                return TruthyEmpty()

        assert read_hop_count(FakeHeaders()) == 0
