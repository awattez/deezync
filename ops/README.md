# Cloud Run Job

Builds [deezync](https://github.com/awattez/deezync) with Google Cloud Buildpacks,
stores Elasticsearch and Deezer credentials in Secret Manager, and runs a Cloud
Run Job every 30 minutes.

This directory is meant to live in a **private** repository (or to be applied
from a local clone of this one). `secrets.auto.tfvars` is gitignored either way.

Requires Terraform 1.11+, an authenticated `gcloud` (`gcloud auth application-default login`
and `gcloud auth login`), and a GCP project you can create Cloud Run / Cloud Build
resources in.

```bash
cp secrets.auto.tfvars.example secrets.auto.tfvars
# fill project_id, es_url, es_api_key, users_toml

terraform init
terraform apply
```

One apply enables the APIs, creates Artifact Registry and the secrets, builds
the image (Cloud Build clones the public repo), then creates the Job and the
Scheduler.

Rebuild the image after a deezync release:

```bash
terraform apply -var=rebuild=$(date +%s)
```

Rotate an ARL or the Elasticsearch key: edit `secrets.auto.tfvars` and apply
again. Secret versions use write-only attributes, so the values are not stored
in the Terraform state.
