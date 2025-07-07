"""Textual TUI for inspecting and managing ECS services."""

from typing import TYPE_CHECKING

import boto3
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Log,
    Select,
)

from .regions import AWS_REGIONS

if TYPE_CHECKING:
    from mypy_boto3_ecs import ECSClient
    from mypy_boto3_logs import CloudWatchLogsClient

# Default clients used until the user selects another region
ecs_client: "ECSClient" = boto3.client("ecs", region_name="us-east-1")
logs_client: "CloudWatchLogsClient" = boto3.client("logs", region_name="us-east-1")


class ECSClusterItem(ListItem):
    """List item representing an ECS cluster."""

    def __init__(self, cluster_name: str, **kargs):
        super().__init__(Label(cluster_name), **kargs)
        self.cluster_name = cluster_name


class ECSServiceItem(ListItem):
    """List item representing an ECS service."""

    def __init__(self, service_name: str, **kargs):
        super().__init__(Label(service_name), **kargs)
        self.service_name = service_name


class RedeploytBtn(Button):
    """Button that triggers a redeploy of the selected service."""

    def __init__(self, label: str, **kargs):
        super().__init__(label, **kargs)
        self.cluster = ""
        self.service = ""

    def on_click(self) -> None:
        """Force a new deployment using the selected cluster and service."""
        ecs_client.update_service(
            cluster=self.cluster, service=self.service, forceNewDeployment=True
        )


class App(App):
    """Main Textual application."""

    CSS_PATH = "style.css"
    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("q", "quit", "Quit"),
    ]

    selected_cluster = reactive(None)
    selected_service = reactive(None)

    def compose(self) -> ComposeResult:
        """Compose the layout of the application."""
        yield Header()
        yield Horizontal(
            Vertical(
                ListView(ListItem(Label("Clusters")), id="clusters"),
                ListView(ListItem(Label("Services")), id="services"),
                id="panel",
            ),
            Vertical(
                Horizontal(
                    RedeploytBtn("Redeploy"),
                    Select([(line["name"], line["id"]) for line in AWS_REGIONS],prompt="Region"),
                    id="tools",
                ),
                Log(id="logs", highlight=True),
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load clusters when the app starts."""
        self.load_clusters()

    def load_clusters(self) -> None:
        """Fetch and display all ECS clusters in the selected region."""
        clusters = ecs_client.list_clusters()["clusterArns"]
        clusters_list = self.query_one("#clusters", ListView)
        clusters_list.clear()
        for cluster in clusters:
            clusters_list.append(ECSClusterItem(cluster.split("/")[-1]))

    def load_services(self) -> None:
        """Fetch and display services for the selected cluster."""
        if self.selected_cluster:
            services = ecs_client.list_services(cluster=self.selected_cluster)[
                "serviceArns"
            ]
            services_list = self.query_one("#services", ListView)
            services_list.clear()
            for service in services:
                services_list.append(ECSServiceItem(service.split("/")[-1]))

    @on(Select.Changed)
    def select_changed(self, event: Select.Changed) -> None:
        """Handle region selection changes by updating clients."""
        global ecs_client, logs_client
        val = str(event.value)
        self.title = val
        ecs_client = boto3.client("ecs", region_name=val)
        logs_client = boto3.client("logs", region_name=val)
        self.load_clusters()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Update state based on the selected cluster or service."""
        red_btn = self.query_one(RedeploytBtn)
        if isinstance(event.item, ECSClusterItem):
            self.selected_cluster = event.item.cluster_name
            red_btn.cluster = event.item.cluster_name
            self.load_services()
        elif isinstance(event.item, ECSServiceItem):
            self.selected_service = event.item.service_name
            red_btn.service = event.item.service_name
            self.load_logs()

    def get_log_group_name(self, cluster_name: str, service_name: str) -> str:
        """Return the CloudWatch log group for a service."""

        # Get the service details
        service = ecs_client.describe_services(
            cluster=cluster_name, services=[service_name]
        )["services"][0]

        # Get the task definition
        task_definition = ecs_client.describe_task_definition(
            taskDefinition=service["taskDefinition"]
        )["taskDefinition"]

        # Find the log configuration within the task definition
        for container_def in task_definition["containerDefinitions"]:
            if "logConfiguration" in container_def:
                log_config = container_def["logConfiguration"]
                if log_config["logDriver"] == "awslogs":
                    return log_config["options"]["awslogs-group"]

        return ""

    def load_logs(self) -> None:
        """Load CloudWatch logs for the selected service."""
        if self.selected_cluster and self.selected_service:
            log_widget = self.query_one("#logs", Log)
            log_widget.clear()

            log_group_name = self.get_log_group_name(
                self.selected_cluster, self.selected_service
            )

            if not log_group_name:
                log_widget.write("Could not find log group for this service.")
                return

            try:
                log_streams = logs_client.describe_log_streams(
                    logGroupName=log_group_name,
                    orderBy="LastEventTime",
                    descending=True,
                    limit=1,
                )["logStreams"]

                if log_streams:
                    latest_stream = log_streams[0]["logStreamName"]
                    events = logs_client.get_log_events(
                        logGroupName=log_group_name,
                        logStreamName=latest_stream,
                        limit=100,
                    )["events"]

                    for event in events:
                        log_widget.write_line(event["message"])
                else:
                    log_widget.write("No log streams found for this service.")
            except Exception as e:
                log_widget.write(f"Error fetching logs: {str(e)}")


if __name__ == "__main__":
    app = App()
    app.run()
