## This is derived from the base tempalte for deploying to ECS with pulumi's aws crosswalk [https://www.pulumi.com/docs/clouds/aws/guides/]
import pulumi
from pulumi import Config, Output, export
import pulumi_aws as aws
import pulumi_awsx as awsx

config = Config()
container_port = config.get_int("containerPort", 80)
cpu = config.get_int("cpu", 512)
memory = config.get_int("memory", 128)

# An ECS cluster to deploy into
cluster = aws.ecs.Cluster("cluster", tags={
    "Environment": "Prod",
    "Name": "ProdClusterECS",
    "Project": pulumi.get_project(),
    "Owner": "SREs",
})

# An ALB to serve the container endpoint to the internet
loadbalancer = awsx.lb.ApplicationLoadBalancer("loadbalancer", tags={
    "Environment": "Prod",
    "Name": "WeatherLoadBalancer",
    "Project": pulumi.get_project(),
    "Owner": "SREs",
})

##All the overhead for cluster and load balancer creation is handled by the new aws crosswalk stuff!!!! don't have to define granular details for security groups and listeners etc etc if we don't need to

#ECR repositories to store our the web and api images
webRepo = awsx.ecr.Repository("web-repo", tags={
    "Environment": "Prod",
    "Name": "WeatherWebECR",
    "Project": pulumi.get_project(),
    "Owner": "SREs",
})

apiRepo = awsx.ecr.Repository("api-repo", tags={
    "Environment": "Prod",
    "Name": "WeatherApiECR",
    "Project": pulumi.get_project(),
    "Owner": "SREs",
})

# Build and publish our web and api container images from the respective folders to the ECR repository
webImage = awsx.ecr.Image(
    "web-image",
    repository_url=webRepo.url,
    path="../infra-web")

apiImage = awsx.ecr.Image(
    "api-image",
    repository_url=apiRepo.url,
    path="../infra-api")

webContainerTaskDefiniton = awsx.ecs.TaskDefinitionContainerDefinitionArgs(
    #"web-container",
    image=webImage.image_uri,
    cpu=cpu,
    memory=memory,
    essential=True,
    environment=[{'name': "ApiAddress", 'value': "http://infraapi:5000/WeatherForecast"}],
    port_mappings=[awsx.ecs.TaskDefinitionPortMappingArgs(
        container_port=80,
        host_port=80,
        protocol="tcp",
    )],
)

apiContainerTaskDefiniton = awsx.ecs.TaskDefinitionContainerDefinitionArgs(
    #"api-container",
    image=apiImage.image_uri,
    cpu=cpu,
    memory=memory,
    essential=True,
    port_mappings=[awsx.ecs.TaskDefinitionPortMappingArgs(
        container_port=5000,
        host_port=5000,
        protocol="tcp",
    )],
)


# Deploy an ECS Service on Fargate to host the application container
appService = awsx.ecs.FargateService(
    "app-service",
    cluster=cluster.arn,
    assign_public_ip=True,
    task_definition_args=awsx.ecs.FargateServiceTaskDefinitionArgs(
        containers=
        {
            "api-container": apiContainerTaskDefiniton,
            "web-container": webContainerTaskDefiniton,
        }
            ), 
    tags={
    "Environment": "Prod",
    "Name": "WeatherAppTaskDefiniton",
    "Project": pulumi.get_project(),
    "Owner": "SREs",
})

# The URL at which the container's HTTP endpoint will be available
export("url", Output.concat("http://", loadbalancer.load_balancer.dns_name))
