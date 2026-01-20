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
     Otherwise the chart-managed default "postgres-secret" is returned.
     -------------------------------------------------------------------- */}}
{{- define "mcp-stack.postgresSecretName" -}}
{{- if .Values.postgres.external.enabled }}
{{- .Values.postgres.external.existingSecret | default (printf "%s-postgres-external" (include "mcp-stack.fullname" .)) }}
{{- else if .Values.postgres.existingSecret }}
{{- .Values.postgres.existingSecret }}
{{- else }}
postgres-secret
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
