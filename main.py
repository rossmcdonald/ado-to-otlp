#!/usr/bin/env python3
#
# This script fetches log data from Azure DevOps and forwards it to ServiceNow's Cloud
# Observability SaaS platform. Please see the link below for more information.
#
#    https://www.servicenow.com/products/observability.html
#
# NOTE: This script was created for testing purposes only. It is not a supported product
#       nor intended for production use cases at this time.
#
import os
import sys
import json
import requests
import time
from datetime import datetime, timezone
import dateutil.parser
from requests.auth import HTTPBasicAuth
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    PeriodicExportingMetricReader,
)
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter


print("Starting ado-to-otlp...")
print("Runtime information:", sys.version)

start_time = datetime.now(timezone.utc)

access_token = os.environ.get("ADO_ACCESS_TOKEN")
organization = os.environ.get("ADO_ORGANIZATION")
cloudobs_access_token = os.environ.get("CLOUDOBS_ACCESS_TOKEN")

if access_token is None:
    print("Please set ADO_ACCESS_TOKEN environment variable to valid Azure DevOps PAT")
    sys.exit(1)
if organization is None:
    print(
        "Please set AD_ORGANIZATION environment variable to valid Azure DevOps organization name"
    )
    sys.exit(1)
if cloudobs_access_token is None:
    print(
        "Please set CLOUDOBS_ACCESS_TOKEN environment variable to valid ServiceNow Cloud Observability access token"
    )
    print(
        "\n\tSee here for more information:",
        "https://docs.lightstep.com/docs/create-and-manage-access-tokens",
        "\n",
    )
    sys.exit(1)

ado_url = os.environ.get("ADO_URL")
if ado_url is None:
    ado_url = "https://dev.azure.com"
organization_url = f"{ado_url}/{organization}"
api_version = "7.2-preview.1"

metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(
        endpoint="https://ingest.lightstep.com",
        headers={"lightstep-access-token": cloudobs_access_token},
    )
)
provider = MeterProvider(metric_readers=[metric_reader])
metrics.set_meter_provider(provider)
meter = metrics.get_meter("ado.meter")

runs_counter = meter.create_counter(
    "ado.runs",
    description="The number of runs executed",
)
runs_time_taken_counter = meter.create_counter(
    "ado.runs_time_taken_ms",
    description="The time taken for each run in ms",
)

s = requests.Session()
s.auth = HTTPBasicAuth("", access_token)

logingest = requests.Session()
logingest.auth = HTTPBasicAuth("", cloudobs_access_token)

metricingest = requests.Session()
metricingest.auth = HTTPBasicAuth("", cloudobs_access_token)

projects = {}
history = {}


def list_projects(continuation_token=None):
    params = {"api-version": api_version}
    if continuation_token is not None:
        params["continuationToken"] = str(continuation_token)

    res = s.get(
        "/".join([organization_url, "_apis", "projects"]),
        params=params,
    )
    res.raise_for_status()
    return res.json()


def build_project_cache():
    print("Building project cache")
    list_projects_response = list_projects()
    while list_projects_response is not None:
        for project in list_projects_response.get("value", []):
            projects[project.get("name")] = project

        continuation_token = list_projects_response.get("continuation_token")
        if continuation_token is not None and continuation_token != "":
            list_projects_response = list_projects(
                continuation_token=continuation_token
            )
        else:
            list_projects_response = None
    print(f"Fetched {len(projects)} projects")


def list_pipelines(project: str, continuation_token: str = None):
    params = {"api-version": api_version}
    if continuation_token is not None:
        params["continuationToken"] = str(continuation_token)

    res = s.get(
        "/".join([organization_url, project, "_apis", "pipelines"]),
        params=params,
    )
    res.raise_for_status()
    return res.json()


def build_pipeline_cache():
    for project_name in projects:
        print("Building pipeline cache for project:", project_name)
        list_pipelines_response = list_pipelines(project_name)
        while list_pipelines_response is not None:
            if projects[project_name].get("pipelines") is None:
                projects[project_name]["pipelines"] = {}

            for pipeline in list_pipelines_response.get("value", []):
                projects[project_name]["pipelines"][pipeline.get("id")] = pipeline

            continuation_token = list_pipelines_response.get("continuation_token")
            if continuation_token is not None and continuation_token != "":
                list_pipelines_response = list_pipelines(
                    continuation_token=continuation_token
                )
            else:
                list_pipelines_response = None


def list_runs(project: str, pipeline: str, continuation_token: str = None):
    params = {"api-version": api_version}
    if continuation_token is not None:
        params["continuationToken"] = str(continuation_token)

    res = s.get(
        "/".join(
            [organization_url, project, "_apis", "pipelines", str(pipeline), "runs"]
        ),
        params=params,
    )
    res.raise_for_status()
    return res.json()


def get_run(project: str, pipeline: str, run: str):
    params = {"api-version": api_version}

    res = s.get(
        "/".join(
            [
                organization_url,
                project,
                "_apis",
                "pipelines",
                str(pipeline),
                "runs",
                str(run),
            ]
        ),
        params=params,
    )
    res.raise_for_status()
    return res.json()


def list_logs(project: str, pipeline: str, run: str, continuation_token: str = None):
    params = {"api-version": api_version}
    if continuation_token is not None:
        params["continuationToken"] = str(continuation_token)

    res = s.get(
        "/".join(
            [
                organization_url,
                project,
                "_apis",
                "pipelines",
                str(pipeline),
                "runs",
                str(run),
                "logs",
            ]
        ),
        params=params,
    )
    res.raise_for_status()
    return res.json()


def get_log(
    project: str, pipeline: str, run: str, log_id: str, continuation_token: str = None
):
    params = {"api-version": api_version, "$expand": "signedContent"}
    if continuation_token is not None:
        params["continuationToken"] = str(continuation_token)

    res = s.get(
        "/".join(
            [
                organization_url,
                project,
                "_apis",
                "pipelines",
                str(pipeline),
                "runs",
                str(run),
                "logs",
                str(log_id),
            ]
        ),
        params=params,
    )
    res.raise_for_status()
    return res.json()


def send_logs_payload(payload):
    logingest_res = logingest.post(
        "https://logingest.lightstep.com/_bulk",
        headers={"Content-Type": "application/json"},
        data="\n".join(payload),
    )
    logingest_res.raise_for_status()

    if logingest_res.json().get("errors") == True:
        raise Exception("Bad response:", logingest_res.text[:500])


def send_metrics_payload(payload):
    res = logingest.post("https://ingest.lightstep.com/v1/metrics", json=payload)
    res.raise_for_status()

    if res.json().get("errors") == True:
        raise Exception("Bad response:", res.text[:500])


build_project_cache()
build_pipeline_cache()
last_cache_update = datetime.now(timezone.utc)

print("Waiting for runs...")
while True:
    for project_name in projects:
        for pipeline in projects[project_name].get("pipelines", []):
            runs = list_runs(project_name, pipeline)
            for run in runs.get("value"):
                try:
                    run_url = run.get("url")

                    run_created_at = dateutil.parser.parse(run.get("createdDate"))

                    if start_time > run_created_at:
                        continue

                    if history.get(run_url) is not None:
                        continue

                    if run.get("state") != "completed":
                        continue

                    print("Fetching data for run:", run_url)
                    try:
                        run_data = get_run(project_name, pipeline, run.get("id"))

                        created = dateutil.parser.parse(run_data.get("createdDate"))
                        finished = dateutil.parser.parse(run_data.get("finishedDate"))
                        time_taken_ms = int((finished - created).total_seconds()) * 1e6

                        attributes = {
                            "run.state": str(run.get("state")),
                            "run.result": str(run.get("result")),
                            "run.name": str(run.get("name")),
                            "run.project": str(project_name),
                            "run.organization": str(organization),
                            "run.pipeline.name": str(
                                run_data.get("pipeline", {}).get("name")
                            ),
                            "run.pipeline.folder": str(
                                run_data.get("pipeline", {}).get("folder")
                            ),
                            "run.pipeline.revision": str(
                                run_data.get("pipeline", {}).get("revision")
                            ),
                        }

                        runs_counter.add(1, attributes)
                        runs_time_taken_counter.add(time_taken_ms, attributes)

                    except Exception as e:
                        print(
                            json.dumps(
                                {
                                    "message": "Encountered error while generating metrics for run",
                                    "run_url": run_url,
                                    "exception": str(e),
                                }
                            )
                        )

                    try:
                        payload = []
                        payload_size = 0

                        logs_result = list_logs(project_name, pipeline, run.get("id"))
                        for log in logs_result.get("logs"):
                            log_results = get_log(
                                project_name, pipeline, run.get("id"), log.get("id")
                            )
                            log_url = log_results.get("url")
                            log_url = log_results.get("signedContent", {}).get("url")

                            res = s.get(log_url)
                            res.raise_for_status()

                            log_lines = res.text.split("\n")
                            for line in log_lines:
                                line = line.strip()
                                if line == "":
                                    continue

                                line_content = {
                                    "organization": organization,
                                    "project": project_name,
                                    "body": line,
                                    "log.id": log_results.get("id"),
                                    "log.url": log_results.get("url"),
                                    "log.line_count": log_results.get("lineCount"),
                                    "run.url": run.get("_links", {})
                                    .get("web", {})
                                    .get("href"),
                                    "run.state": run.get("state"),
                                    "run.result": run.get("result"),
                                    "run.id": run.get("id"),
                                    "run.name": run.get("name"),
                                    "pipeline.name": run.get("pipeline", {}).get(
                                        "name"
                                    ),
                                    "pipeline.folder": run.get("pipeline", {}).get(
                                        "folder"
                                    ),
                                    "pipeline.revision": run.get("pipeline", {}).get(
                                        "revision"
                                    ),
                                    "pipeline.id": run.get("pipeline", {}).get("id"),
                                    "pipeline.url": run.get("_links", {}).get(
                                        "pipeline.web"
                                    ),
                                    "_ts": log_results.get("createdOn"),
                                }

                                action_line = (
                                    '{ "index" : { "_index" : "ado_pipeline_logs" } }'
                                )
                                json_line = json.dumps(line_content)
                                payload_size += len(json_line) + len(action_line)

                                payload.append(action_line)
                                payload.append(json_line)

                                if payload_size > (5 * 1024 * 1024):
                                    send_logs_payload(payload)

                                    payload = []
                                    payload_size = 0

                        if len(payload) > 0:
                            send_logs_payload(payload)

                        history[run_url] = True
                    except Exception as e:
                        print(
                            json.dumps(
                                {
                                    "message": "Encountered error while retrieving logs for run",
                                    "run_url": run_url,
                                    "log_url": log_url,
                                    "exception": str(e),
                                }
                            )
                        )
                        time.sleep(1)

                except Exception as e:
                    print(
                        json.dumps(
                            {
                                "message": "Encountered error on run",
                                "run_url": run_url,
                                "exception": str(e),
                            }
                        )
                    )

    time.sleep(30)

    if ((datetime.now(timezone.utc) - last_cache_update).seconds / 60) > 30:
        build_project_cache()
        build_pipeline_cache()
