{{/*
Chart name, overridable. This is what lands in the `app.kubernetes.io/name`
label — the selector a Styrmin driver's component `identifier.label` matches on.
It is deliberately independent of `fullnameOverride`, so renaming resources for
the 63-character limit does not move the component identifier.
*/}}
{{- define "cisco-sdwan-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Fully qualified resource name.
*/}}
{{- define "cisco-sdwan-mcp.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "cisco-sdwan-mcp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "cisco-sdwan-mcp.labels" -}}
helm.sh/chart: {{ include "cisco-sdwan-mcp.chart" . }}
{{ include "cisco-sdwan-mcp.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "cisco-sdwan-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cisco-sdwan-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "cisco-sdwan-mcp.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "cisco-sdwan-mcp.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
Name of the Secret supplying SDWAN_PASSWORD: the operator-managed one when
`sdwan.existingSecret` is set, otherwise the chart-rendered fallback. Empty
when neither is configured, in which case no secret is referenced at all.
*/}}
{{- define "cisco-sdwan-mcp.secretName" -}}
{{- if .Values.sdwan.existingSecret -}}
{{- .Values.sdwan.existingSecret -}}
{{- else if .Values.sdwan.password -}}
{{- printf "%s-credentials" (include "cisco-sdwan-mcp.fullname" .) -}}
{{- end -}}
{{- end -}}
