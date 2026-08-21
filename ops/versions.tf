terraform {
  required_version = ">= 1.11"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.14"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
