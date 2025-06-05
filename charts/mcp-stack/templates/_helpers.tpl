{{- define "mcp-stack.fullname" -}}
{{- if .Values.global.fullnameOverride }}
{{ .Values.global.fullnameOverride }}
{{- else -}}
{{- $name := default .Chart.Name .Values.global.nameOverride }}
{{- if contains $name .Release.Name }}
{{- printf "%s" .Release.Name }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name }}
{{- end }}
{{- end }}
{{- end }}

{{- define "mcp-stack.labels" -}}
app.kubernetes.io/name: {{ include "mcp-stack.fullname" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
