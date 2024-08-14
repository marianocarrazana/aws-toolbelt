import boto3
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Label, ListItem, ListView, Log


class ECSClusterItem(ListItem):
    def __init__(self, cluster_name: str, **kargs):
        super().__init__(Label(cluster_name), **kargs)
        self.cluster_name = cluster_name


class ECSServiceItem(ListItem):
    def __init__(self, service_name: str, **kargs):
        super().__init__(Label(service_name), **kargs)
        self.service_name = service_name


class ECSApp(App):
    CSS_PATH = "style.css"
    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("q", "quit", "Quit"),
    ]

    selected_cluster = reactive(None)
    selected_service = reactive(None)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Vertical(
                ListView(ListItem(Label("Clusters")), id="clusters"),
                ListView(ListItem(Label("Services")), id="services"),
            ),
            Log(id="logs", highlight=True),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.load_clusters()

    def load_clusters(self) -> None:
        ecs_client = boto3.client("ecs")
        clusters = ecs_client.list_clusters()["clusterArns"]
        clusters_list = self.query_one("#clusters", ListView)
        clusters_list.clear()
        for cluster in clusters:
            clusters_list.append(ECSClusterItem(cluster.split("/")[-1]))

    def load_services(self) -> None:
        if self.selected_cluster:
            ecs_client = boto3.client("ecs")
            services = ecs_client.list_services(cluster=self.selected_cluster)[
                "serviceArns"
            ]
            services_list = self.query_one("#services", ListView)
            services_list.clear()
            for service in services:
                services_list.append(ECSServiceItem(service.split("/")[-1]))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, ECSClusterItem):
            self.selected_cluster = event.item.cluster_name
            self.load_services()
        elif isinstance(event.item, ECSServiceItem):
            self.selected_service = event.item.service_name
            self.load_logs()

    def get_log_group_name(self, cluster_name: str, service_name: str) -> str:
        ecs_client = boto3.client("ecs")

        # Get the service details
        service = ecs_client.describe_services(
            cluster=cluster_name, services=[service_name]
        )["services"][0]

        # Get the task definition
        task_definition = ecs_client.describe_task_definition(
            taskDefinition=service["taskDefinition"]
        )["taskDefinition"]

        # Find the log configuration
        for container_def in task_definition["containerDefinitions"]:
            if "logConfiguration" in container_def:
                log_config = container_def["logConfiguration"]
                if log_config["logDriver"] == "awslogs":
                    return log_config["options"]["awslogs-group"]

        return ""

    def load_logs(self) -> None:
        if self.selected_cluster and self.selected_service:
            logs_client = boto3.client("logs")
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
    app = ECSApp(watch_css=True)
    app.run()
