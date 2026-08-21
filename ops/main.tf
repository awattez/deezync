locals {
  image  = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.deezync.repository_id}/deezync"
  job_sa = "${data.google_project.current.number}-compute@developer.gserviceaccount.com"
  secrets = {
    es-url     = var.es_url
    es-api-key = var.es_api_key
    users-toml = var.users_toml
  }
}

data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "compute.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "deezync" {
  project       = var.project_id
  location      = var.region
  repository_id = "deezync"
  format        = "DOCKER"
  description   = "deezync Cloud Run Job images"

  depends_on = [google_project_service.services]
}

resource "google_artifact_registry_repository_iam_member" "cloudbuild" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.deezync.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = local.secrets
  project   = var.project_id
  secret_id = "deezync-${each.key}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret_version" "secrets" {
  for_each = local.secrets

  secret                 = google_secret_manager_secret.secrets[each.key].id
  secret_data_wo         = each.value
  secret_data_wo_version = parseint(substr(sha256(each.value), 0, 7), 16) + 1
}

resource "google_secret_manager_secret_iam_member" "job" {
  for_each = google_secret_manager_secret.secrets

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.job_sa}"
}

resource "terraform_data" "image" {
  triggers_replace = {
    image   = local.image
    owner   = var.source_owner
    name    = var.source_name
    ref     = var.source_ref
    rebuild = var.rebuild
    repo    = google_artifact_registry_repository.deezync.id
  }

  depends_on = [
    google_artifact_registry_repository_iam_member.cloudbuild,
  ]

  provisioner "local-exec" {
    command = <<-EOT
      gcloud builds submit --no-source \
        --project=${var.project_id} \
        --config=${path.module}/cloudbuild.yaml \
        --substitutions=_IMAGE=${local.image},_OWNER=${var.source_owner},_NAME=${var.source_name},_REF=${var.source_ref}
    EOT
  }
}

resource "google_cloud_run_v2_job" "deezync" {
  project             = var.project_id
  name                = "deezync"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = local.job_sa
      timeout         = "120s"
      max_retries     = 1

      volumes {
        name = "users"
        secret {
          secret = google_secret_manager_secret.secrets["users-toml"].secret_id
          items {
            path    = "users.toml"
            version = "latest"
          }
        }
      }

      containers {
        image = "${local.image}:latest"

        env {
          name = "ES_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets["es-url"].secret_id
              version = "latest"
            }
          }
        }

        env {
          name = "ES_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets["es-api-key"].secret_id
              version = "latest"
            }
          }
        }

        env {
          name  = "ES_INDEX"
          value = var.es_index
        }

        env {
          name  = "DEEZYNC_USERS_FILE"
          value = "/secrets/users.toml"
        }

        env {
          name  = "DEEZYNC_IMAGE_BUILD"
          value = terraform_data.image.id
        }

        volume_mounts {
          name       = "users"
          mount_path = "/secrets"
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.services,
    google_secret_manager_secret_version.secrets,
    google_secret_manager_secret_iam_member.job,
    terraform_data.image,
  ]
}

resource "google_cloud_run_v2_job_iam_member" "scheduler" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.deezync.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.job_sa}"
}

resource "google_service_account_iam_member" "scheduler_act_as" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${local.job_sa}"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"

  depends_on = [google_project_service.services]
}

resource "google_cloud_scheduler_job" "deezync" {
  project          = var.project_id
  name             = "deezync"
  region           = var.region
  schedule         = var.schedule
  time_zone        = var.time_zone
  attempt_deadline = "180s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.deezync.name}:run"

    oauth_token {
      service_account_email = local.job_sa
    }
  }

  retry_config {
    retry_count = 0
  }

  depends_on = [
    google_cloud_run_v2_job_iam_member.scheduler,
    google_service_account_iam_member.scheduler_act_as,
  ]
}
