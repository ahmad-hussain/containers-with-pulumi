## This is derived from the base tempalte for deploying to ECS with pulumi's aws crosswalk [https://www.pulumi.com/docs/clouds/aws/guides/]
import pulumi
from pulumi import Config, Output, export
import pulumi_aws as aws
import pulumi_awsx as awsx

config = Config()
container_port = config.get_int("containerPort", 80)
cpu = config.get_int("cpu", 512)
memory = config.get_int("memory", 128)

##All the overhead for cluster and load balancer creation is handled by the new aws crosswalk stuff!!!! don't have to define granular details for security groups and listeners etc etc if we don't need to

##Adding the requirements to deploy to ECS so it can be customised.

vpc = awsx.ec2.Vpc(
    "custom-vpc",
    cidr_block = "10.0.0.0/16",
    ##giving max number of addresses for the whole vpc to give room for future subnets and resources
    availability_zone_names = ["us-west-2a", "us-west-2b"],
    subnet_specs = [
        awsx.ec2.SubnetSpecArgs(
            type = awsx.ec2.SubnetType.PRIVATE,
            cidr_mask = 20,
        ),
        awsx.ec2.SubnetSpecArgs(
            type = awsx.ec2.SubnetType.PUBLIC,
            cidr_mask = 22,
        ),
    ],
    nat_gateways = awsx.ec2.NatGatewayConfigurationArgs(
        strategy = awsx.ec2.NatGatewayStrategy.ONE_PER_AZ
    ),
    tags={
    "Environment": "Prod",
    "Name": "ProdVPC",
    "ResourceType": "VPC",
    "Project": pulumi.get_project(),
    "Owner": "SREs",
    }
)

##secuirty group to allow the web UI to be accessed from anywhere with http
allow_all_http_inbound_sg = aws.ec2.SecurityGroup("allow-all-http",
    description="Allow TLS inbound traffic",
    vpc_id=vpc.vpc_id,
    ingress=[aws.ec2.SecurityGroupIngressArgs(
    description="allow HTTP access from anywhere",
    from_port=80,
    to_port=80,
    protocol="tcp",
    cidr_blocks=["0.0.0.0/0"],
    )],
    egress=[aws.ec2.SecurityGroupEgressArgs(
    from_port=0,
    to_port=0,
    protocol="-1",
    cidr_blocks=["0.0.0.0/0"],
    )],
    tags={
    "Environment": "Prod",
    "Name": "WeatherAppUISecruityGroup",
    "ResourceType": "SG",
    "Project": pulumi.get_project(),
    "Owner": "SREs",
    }
)

# An ECS cluster to deploy into
cluster = aws.ecs.Cluster("cluster", tags={
    "Environment": "Prod",
    "Name": "ProdClusterECS",
    "ResourceType": "ECScluster",
    "Project": pulumi.get_project(),
    "Owner": "SREs",
})

# An ALB to serve the container endpoint to the internet, specify the security group
loadbalancer = awsx.lb.ApplicationLoadBalancer("loadbalancer", security_groups = [allow_all_http_inbound_sg.id], tags={
    "Environment": "Prod",
    "Name": "WeatherLoadBalancer",
    "ResourceType": "ALB",
    "Project": pulumi.get_project(),
    "Owner": "SREs",
})

#ECR repositories to store our the web and api images
webRepo = awsx.ecr.Repository("web-repo", tags={
    "Environment": "Prod",
    "Name": "WeatherWebECR",
    "ResourceType": "ECRrepository",
    "Project": pulumi.get_project(),
    "Owner": "SREs",
})

apiRepo = awsx.ecr.Repository("api-repo", tags={
    "Environment": "Prod",
    "Name": "WeatherApiECR",
    "ResourceType": "ECRrepository",
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
    network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
        subnets=vpc.private_subnet_ids,
        security_groups=[allow_all_http_inbound_sg.id]
    ),
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
    "ResourceType": "ECSFargateService",
    "Project": pulumi.get_project(),
    "Owner": "SREs",
})

# The URL at which the container's HTTP endpoint will be available
export("url", Output.concat("http://", loadbalancer.load_balancer.dns_name))
