# Immutable Filter-Chain Delivery Examples

Operators do not hand-author or hot-reload a mutable Praxis pipeline. ContextForge renders each target's canonical
`praxis.yaml` and `cpex/*.yaml` files into an encrypted immutable generation. The launcher fetches that generation from the
machine API and activates it only after all validation stages pass.

## Initial activation

1. A platform administrator assigns representable platform/team servers to a target and requests rendering.
2. ContextForge captures source/policy epochs and a target fence, renders the archive, encrypts it, and uses pointer CAS to
   publish a desired activation for the frozen replica cohort.
3. Each eligible launcher polls `/praxis/v1/desired`, fetches `/praxis/v1/artifact` under the directive fence, verifies the
   archive and compatibility metadata, and atomically stages the generation.
4. The launcher reports `prepared`, validates the native pipeline, starts the candidate listener, proves a local policy
   denial, reports `canary_passed`, then reports `active`.
5. Reconciliation marks the rollout `verified` only after the complete nonempty cohort is active.

## Same-generation replacement

Replica registration or cohort churn can issue the already-known generation through a fresh rollout and directive. The
generation ID remains unchanged because content is unchanged. The rollout ID, directive ID, fence, cohort, report cursor,
and response ETag are new. This is activation convergence, not policy hot reload.

## Candidate failure and rollback

If parsing, compatibility, listener readiness, or local policy denial fails, the launcher stops the candidate and submits a
monotonic `failed` report. The control plane chooses a fresh retry, an eligible unexpired LKG rollback, or a stop directive.
Rollback is allowed only before the exact LKG deadline; at `now >= deadline` it fails closed to stop.

## Credential rotation

Register each replica independently. Issue a second JTI, update that replica's read-only mounted token, observe a successful
authenticated poll, then revoke the old JTI. At most two active JTIs overlap and replicas never share credentials.
