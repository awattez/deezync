variable "project_id" {
  type        = string
  description = "GCP project that hosts the job."
}

variable "region" {
  type        = string
  description = "Region for Artifact Registry, Cloud Run, and Cloud Scheduler."
  default     = "europe-west1"
}

variable "es_url" {
  type        = string
  sensitive   = true
  description = "Elasticsearch URL (ES_URL)."

  validation {
    condition     = startswith(var.es_url, "https://") || startswith(var.es_url, "http://")
    error_message = "es_url must be an http(s) URL."
  }
}

variable "es_api_key" {
  type        = string
  sensitive   = true
  description = "Elasticsearch API key (ES_API_KEY)."

  validation {
    condition     = length(var.es_api_key) > 0
    error_message = "es_api_key is empty."
  }
}

variable "es_index" {
  type        = string
  description = "Destination index."
  default     = "deezer-history"
}

variable "users_toml" {
  type        = string
  sensitive   = true
  description = "Contents of users.toml (Deezer accounts)."

  validation {
    condition     = strcontains(var.users_toml, "[[accounts]]")
    error_message = "users_toml must contain an [[accounts]] block."
  }
}

variable "source_owner" {
  type        = string
  description = "GitHub owner of the public deezync repository."
  default     = "awattez"
}

variable "source_name" {
  type        = string
  description = "GitHub name of the public deezync repository."
  default     = "deezync"
}

variable "source_ref" {
  type        = string
  description = "Branch or tag Cloud Build clones."
  default     = "main"
}

variable "rebuild" {
  type        = number
  description = "Bump this to force a new image build."
  default     = 1
}

variable "schedule" {
  type        = string
  description = "Cloud Scheduler cron."
  default     = "*/30 * * * *"
}

variable "time_zone" {
  type        = string
  description = "Time zone for the schedule."
  default     = "Europe/Paris"
}
