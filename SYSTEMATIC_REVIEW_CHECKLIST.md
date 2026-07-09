# Systematic Design Document Review Checklist

## Section-by-Section Review

### Section 5: AbstractTokenBackend Interface
- [ ] TokenRecord has team_id field
- [ ] store_tokens has (gateway_id, team_id, user_id, app_user_email, ...)
- [ ] get_user_token has (gateway_id, team_id, app_user_email, ...)
- [ ] get_token_info has (gateway_id, team_id, app_user_email)
- [ ] revoke_user_tokens has (gateway_id, team_id, app_user_email)
- [ ] cleanup_expired_tokens has NO team_id
- [ ] Class docstring mentions both gateway_id and team_id

### Section 6: TokenStorageService Façade
- [ ] Constructor has user_context parameter
- [ ] Has _get_team_id() helper method
- [ ] store_tokens delegates with team_id
- [ ] get_user_token delegates with team_id
- [ ] get_token_info delegates with team_id
- [ ] revoke_user_tokens delegates with team_id
- [ ] cleanup_expired_tokens delegates without team_id
- [ ] VaultTokenBackend example has correct parameter order

### Section 7: Vault Secret Schema
- [ ] Path pattern shows {team_id}/{server_id}/{email}
- [ ] Example paths have all three segments
- [ ] Secret payload includes team_id field
- [ ] All gateway_id references are UUIDs

### Section 7.5: DatabaseTokenBackend (Deferred)
- [ ] Interface methods accept team_id
- [ ] Documentation mentions team_id is ignored
- [ ] store_tokens example has correct parameter order
- [ ] get_user_token example has correct parameter order

### Section 8: Vault Authorization Endpoints
- [ ] /vault/callback mentions team_id extraction
- [ ] Method calls go through TokenStorageService
- [ ] All gateway_id references are UUIDs

### Section 15: End-to-End Flow
- [ ] All Vault paths have {team_id}/{server_id}/{email}
- [ ] All method calls go through façade
- [ ] All gateway_id values are UUIDs
- [ ] No direct backend method calls

### Section 18/19: Implementation Details
- [ ] Retry logic has correct parameter order
- [ ] All gateway_id in logs/metrics are UUIDs
- [ ] All method signatures match interface

### Cross-Document Consistency
- [ ] No "gw-" prefixed gateway IDs anywhere
- [ ] No paths missing team_id segment
- [ ] No direct VaultTokenBackend method calls
- [ ] All team_id mentions are consistent
