{{- /* --------------------------------------------------------------------
     Helper: mcp-stack.fullname
     -------------------------------------------------------------------- */}}
{{- define "mcp-stack.fullname" -}}
{{- if .Values.global.fullnameOverride }}
{{- .Values.global.fullnameOverride }}
{{- else -}}
{{- $name := default .Chart.Name .Values.global.nameOverride }}
{{- if contains $name .Release.Name }}
{{- printf "%s" .Release.Name }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name }}
{{- end }}

{{- end }}
{{- end }}

{{- /* Validate the fail-closed Praxis configuration contract. */}}
{{- define "mcp-stack.praxis.validate" -}}
{{- if .Values.praxis.enabled -}}
{{- if not (hasPrefix "https://" .Values.praxis.controlPlane.url) -}}
{{- fail "praxis.controlPlane.url must use https://" -}}
{{- end -}}
{{- if not (hasSuffix "/praxis/v1" .Values.praxis.controlPlane.url) -}}
{{- fail "praxis.controlPlane.url must end with /praxis/v1" -}}
{{- end -}}
{{- if or (empty .Values.praxis.controlPlane.caSecret.name) (empty .Values.praxis.controlPlane.caSecret.key) -}}
{{- fail "praxis.controlPlane.caSecret name and key are required" -}}
{{- end -}}
{{- if ne .Values.praxis.image.tag "ed46eb5" -}}
{{- fail "praxis.image.tag must be the Task 16 revision ed46eb5" -}}
{{- end -}}
{{- if ne .Values.praxis.storage.type "emptyDir" -}}
{{- fail "praxis.storage must use pod-local emptyDir" -}}
{{- end -}}
{{- if .Values.praxis.traffic.enabled -}}
{{- fail "praxis.traffic.enabled must remain false" -}}
{{- end -}}
{{- if lt (int .Values.praxis.terminationGracePeriodSeconds) 45 -}}
{{- fail "praxis.terminationGracePeriodSeconds must be at least 45" -}}
{{- end -}}
{{- if or (not .Values.praxis.podSecurityContext.runAsNonRoot) (eq (int .Values.praxis.podSecurityContext.runAsUser) 0) -}}
{{- fail "praxis.podSecurityContext.runAsUser must be non-root" -}}
{{- end -}}
{{- if empty .Values.praxis.replicas -}}
{{- fail "praxis.replicas must contain at least one server-issued identity" -}}
{{- end -}}
{{- $replicaIds := dict -}}
{{- $credentialRefs := dict -}}
{{- range .Values.praxis.replicas -}}
{{- if empty .replicaId -}}
{{- fail "praxis.replicas[].replicaId is required" -}}
{{- end -}}
{{- if hasKey $replicaIds .replicaId -}}
{{- fail (printf "duplicate Praxis replicaId: %s" .replicaId) -}}
{{- end -}}
{{- $_ := set $replicaIds .replicaId true -}}
{{- if or (empty .tokenSecret.name) (empty .tokenSecret.key) -}}
{{- fail (printf "praxis replica %s tokenSecret name and key are required" .replicaId) -}}
{{- end -}}
{{- if hasKey $credentialRefs .tokenSecret.name -}}
{{- fail "duplicate Praxis credential reference" -}}
{{- end -}}
{{- $_ := set $credentialRefs .tokenSecret.name true -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- /* --------------------------------------------------------------------
     Helper: mcp-stack.labels
     -------------------------------------------------------------------- */}}
{{- define "mcp-stack.labels" -}}
app.kubernetes.io/name: {{ include "mcp-stack.fullname" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- /* --------------------------------------------------------------------
     Helper: mcp-stack.serviceAccountName
     Returns the ServiceAccount name to use.
     If serviceAccount.create is true and name is empty, uses fullname.
     If serviceAccount.create is false, uses the provided name or "default".
     -------------------------------------------------------------------- */}}
{{- define "mcp-stack.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "mcp-stack.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- /* --------------------------------------------------------------------
     Helper: mcp-stack.postgresSecretName
     Returns the Secret name that the Postgres deployment should mount.
     If users set `postgres.existingSecret`, that name is used.
     Otherwise a release-scoped name is returned.
     -------------------------------------------------------------------- */}}
{{- define "mcp-stack.postgresSecretName" -}}
{{- if .Values.postgres.external.enabled }}
{{- .Values.postgres.external.existingSecret | default (printf "%s-postgres-external" (include "mcp-stack.fullname" .)) }}
{{- else if .Values.postgres.existingSecret }}
{{- .Values.postgres.existingSecret }}
{{- else }}
{{- printf "%s-postgres-secret" (include "mcp-stack.fullname" .) }}
{{- end }}
{{- end }}

{{- /* --------------------------------------------------------------------
     Helper: mcp-stack.redisSecretName
     Returns the Secret name for Redis authentication.
     If users set `redis.auth.existingSecret`, that name is used.
     Otherwise a release-scoped name is returned.
     -------------------------------------------------------------------- */}}
{{- define "mcp-stack.redisSecretName" -}}
{{- if .Values.redis.auth.existingSecret }}
{{- .Values.redis.auth.existingSecret }}
{{- else }}
{{- printf "%s-redis-secret" (include "mcp-stack.fullname" .) }}
{{- end }}
{{- end }}

{{- /* --------------------------------------------------------------------
     Helper: mcp-stack.pgadminSecretName
     Returns the Secret name for PgAdmin credentials.
     -------------------------------------------------------------------- */}}
{{- define "mcp-stack.pgadminSecretName" -}}
{{- if .Values.pgadmin.existingSecret }}
{{- .Values.pgadmin.existingSecret }}
{{- else }}
{{- printf "%s-pgadmin" (include "mcp-stack.fullname" .) }}
{{- end }}
{{- end }}

{{- /* --------------------------------------------------------------------
     Helper: helpers.renderProbe
     Renders a readiness or liveness probe from a shorthand values block.
     Supports "http", "tcp", and "exec".
     -------------------------------------------------------------------- */}}
{{- define "helpers.renderProbe" -}}
{{- $p := .probe -}}
{{- if eq $p.type "http" }}
httpGet:
  path: {{ $p.path }}
  port: {{ $p.port }}
  {{- if $p.scheme }}scheme: {{ $p.scheme }}{{ end }}
{{- else if eq $p.type "tcp" }}
tcpSocket:
  port: {{ $p.port }}
{{- else if eq $p.type "exec" }}
exec:
  command: {{ toYaml $p.command | nindent 4 }}
{{- end }}
initialDelaySeconds: {{ $p.initialDelaySeconds | default 0 }}
periodSeconds:       {{ $p.periodSeconds       | default 10 }}
timeoutSeconds:      {{ $p.timeoutSeconds      | default 1 }}
successThreshold:    {{ $p.successThreshold    | default 1 }}
failureThreshold:    {{ $p.failureThreshold    | default 3 }}
{{- end }}
