output "image" {
  value       = "${local.image}:latest"
  description = "Image Cloud Build pushes and the job runs."
}

output "job" {
  value       = google_cloud_run_v2_job.deezync.id
  description = "Cloud Run Job id."
}

output "scheduler" {
  value       = google_cloud_scheduler_job.deezync.id
  description = "Cloud Scheduler job id."
}
