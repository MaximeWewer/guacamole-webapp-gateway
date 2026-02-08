{{/*
Expand the name of the chart.
*/}}
{{- define "guacamole-broker.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "guacamole-broker.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "guacamole-broker.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "guacamole-broker.labels" -}}
helm.sh/chart: {{ include "guacamole-broker.chart" . }}
{{ include "guacamole-broker.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "guacamole-broker.selectorLabels" -}}
app.kubernetes.io/name: {{ include "guacamole-broker.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "guacamole-broker.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "guacamole-broker.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Get the Guacamole password secret name
*/}}
{{- define "guacamole-broker.guacamoleSecretName" -}}
{{- if .Values.guacamole.existingSecret }}
{{- .Values.guacamole.existingSecret }}
{{- else }}
{{- include "guacamole-broker.fullname" . }}-guacamole
{{- end }}
{{- end }}

{{/*
Get the database password secret name
*/}}
{{- define "guacamole-broker.databaseSecretName" -}}
{{- if .Values.database.existingSecret }}
{{- .Values.database.existingSecret }}
{{- else }}
{{- include "guacamole-broker.fullname" . }}-database
{{- end }}
{{- end }}

{{/*
Get the Vault secret name
*/}}
{{- define "guacamole-broker.vaultSecretName" -}}
{{- if .Values.vault.existingSecret }}
{{- .Values.vault.existingSecret }}
{{- else }}
{{- include "guacamole-broker.fullname" . }}-vault
{{- end }}
{{- end }}

{{/*
Get the namespace for VNC pods
*/}}
{{- define "guacamole-broker.vncNamespace" -}}
{{- default .Release.Namespace .Values.orchestrator.namespace }}
{{- end }}
