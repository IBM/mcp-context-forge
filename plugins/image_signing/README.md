# Image Signing & Verification Plugin

Verifies container image signatures and SLSA attestations using Sigstore/Cosign before MCP server deployment. Supports keyless (OIDC), public key, and KMS-based signing workflows.

## Planned Hook Integration

- `runtime_pre_deploy` (pending framework support in #2216)

## Architecture

```
verify_image() pipeline:

  1. Gather trusted signers (YAML config + DB)
  2. CosignVerifier.verify()        → VerificationResult
  3. match_signer()                 → MatchResult
  4. CosignVerifier.verify_attestation() → AttestationResult (if configured)
  5. evaluate_policy()              → PolicyDecision
  6. Assemble SignatureVerificationResult
  7. Persist to DB
```

## Structure

- `image_signing.py`: Main plugin class and orchestration
- `config.py`: Configuration parsing (ImageSigningConfig, VerificationConfig, SlsaConfig)
- `types.py`: Core data models (VerificationResult, TrustedSigner, PolicyDecision, etc.)
- `errors.py`: Exception types (CosignNotFoundError, CosignTimeoutError, etc.)
- `cosign/`: Cosign CLI integration
  - `command_builder.py`: Builds cosign CLI arguments for keyless/public_key/KMS
  - `runner.py`: Async subprocess wrapper for cosign execution
  - `parser.py`: Parses cosign JSON output into domain types
  - `verifier.py`: High-level CosignVerifier class (verify + verify_attestation)
- `policy/`: Policy evaluation
  - `matcher.py`: Trusted signer matching (exact subject, regex, issuer)
  - `evaluator.py`: Policy decision engine (ENFORCE/AUDIT modes)
  - `slsa.py`: SLSA attestation level and builder validation
- `storage/`: Persistence layer
  - `models.py`: SQLAlchemy ORM models (TrustedSignerRecord, SignatureVerificationRecord)
  - `repository.py`: CRUD operations for signers and verification history

## Config

```yaml
- name: "ImageSigningPlugin"
  kind: "plugins.image_signing.image_signing.ImageSigningPlugin"
  description: "Verifies container image signatures and SLSA attestations"
  hooks: ["runtime_pre_deploy"]  # pending framework hook support (#2216)
  mode: "enforce"
  priority: 20
  config:
    mode: "enforce"  # enforce | audit
    verification:
      require_signature: true
      require_trusted_signer: true
      verify_transparency_log: true
    cosign:
      binary_path: "cosign"
      timeout: 30
    slsa:
      require_attestation: false
      minimum_level: 3
      trusted_builders:
        - "https://github.com/slsa-framework/slsa-github-generator"
    trusted_signers:
      - type: "keyless"
        oidc_issuer: "https://token.actions.githubusercontent.com"
        subject_regex: "https://github.com/myorg/.*"
      - type: "public_key"
        public_key: "-----BEGIN PUBLIC KEY-----\n..."
```

## Enforcement Modes

- **ENFORCE**: Blocks deployment if verification fails. Rules checked in order:
  1. `require_signature=True` and no signature found → block
  2. Signature found but invalid → block
  3. `require_trusted_signer=True` and no signer match → block
  4. `verify_transparency_log=True` and Rekor not verified → block
  5. `require_attestation=True` and SLSA check fails → block

- **AUDIT**: Never blocks. Logs violations and persists results for review.

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/image-signing/signers` | List trusted signers |
| POST | `/api/v1/image-signing/signers` | Create a trusted signer |
| GET | `/api/v1/image-signing/signers/{id}` | Get a signer |
| PATCH | `/api/v1/image-signing/signers/{id}` | Update a signer |
| DELETE | `/api/v1/image-signing/signers/{id}` | Delete a signer |
| GET | `/api/v1/image-signing/verifications` | Query verification history |
| POST | `/api/v1/image-signing/verify` | Trigger manual verification |

## Admin UI

Accessible via the **Extensions > Image Signing** sidebar entry. Provides:
- Dashboard with verification statistics (total, verified, blocked, signers count)
- Trusted Signers management (CRUD with type badges and status indicators)
- Verification History browser
- Manual Verify tool for ad-hoc image verification

## Dependencies

- **cosign**: Sigstore cosign CLI binary (v2+) must be available on PATH
- **SQLAlchemy**: Database persistence (SQLite default, PostgreSQL supported)
- **Alembic**: Requires migration `9b680492ec77_add_image_signing_tables`

## Testing

```bash
# Unit tests
python -m pytest tests/unit/plugins/test_image_signing/ -v

# Integration tests 
python -m pytest tests/integration/test_image_signing/ -v --with-integration
```

## Pending

- Hook integration: awaiting #2216 (Container Scanner) to add `runtime_pre_deploy` hook type to framework
- Current stub types (`AssessmentPostContainerScanPayload/Result`) will be replaced with framework-provided types
- Cross-plugin integration tests with Container Scanner plugin

## Design Decisions

- **Sync Session** (not AsyncSession): matches project's `create_engine` + `SessionLocal` pattern
- **Independent SQLAlchemy Base**: `storage/models.py` not coupled to `mcpgateway/db.py`
- **DB failures degrade gracefully**: if the database is unavailable, the plugin continues operating with config-defined signers only
- **`flush()` not `commit()`** in repository: caller manages transactions
- **`re.fullmatch`** for `subject_regex`: prevents partial match attacks