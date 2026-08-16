{{/*
EasyOps Helm helpers.

命名策略：
- fullname：release 名 + nameOverride（标准 chart 开头），用于除固定 DNS 外的资源。
- 固定 Service 名（api/mysql/redis/prometheus）：EasyOps 依赖固定 DNS——
  nginx.conf proxy_pass http://api:8000、grafana datasource http://prometheus:9090、
  config.yaml MYSQL_HOST=mysql / REDIS_HOST=redis。本 Chart 明确不随 release 改名，
  覆盖 nameOverride 也不影响这些 Service 名（对齐 Kustomize 语义）。
*/}}

{{/* 标准命名函数 */}}
{{- define "easyops.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "easyops.fullname" -}}
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

{{/* Chart 命名空间 */}}
{{- define "easyops.namespace" -}}
{{- .Values.namespace.name | default "easyops" }}
{{- end }}

{{/* 公共标签 */}}
{{- define "easyops.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "easyops.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: easyops-platform
{{- end }}

{{/* 组件选择器标签（Deployment/Service 用） */}}
{{- define "easyops.selectorLabels" -}}
app.kubernetes.io/name: {{ include "easyops.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* 组件名：easyops-<component>（对齐 Kustomize 资源名） */}}
{{- define "easyops.component" -}}
{{- printf "%s-%s" (include "easyops.fullname" .) .component }}
{{- end }}

{{/* 镜像组合 */}}
{{- define "easyops.apiImage" -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- end }}
{{- define "easyops.webImage" -}}
{{- printf "%s:%s" .Values.image.webRepository .Values.image.tag }}
{{- end }}

{{/* 敏感 env（Secret 引用实现，create=false 时指向预建 Secret） */}}
{{- define "easyops.secretEnv" -}}
- name: MYSQL_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secret.existingSecretName | default "easyops-secrets" }}
      key: MYSQL_PASSWORD
- name: SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secret.existingSecretName | default "easyops-secrets" }}
      key: SECRET_KEY
{{- end }}

{{/* Secret 名称（create=true 时也使用 existingSecretName 生成，保持引用一致） */}}
{{- define "easyops.secretName" -}}
{{- .Values.secret.existingSecretName | default "easyops-secrets" }}
{{- end }}