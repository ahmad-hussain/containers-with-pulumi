import pulumi
import pulumi_awsx as awsx
import pulumi_eks as eks
import pulumi_kubernetes as kubernetes

## Using the EKS template to create the cluster

# Get some values from the Pulumi configuration (or use defaults)
config = pulumi.Config()
min_cluster_size = config.get_float("minClusterSize", 3)
max_cluster_size = config.get_float("maxClusterSize", 6)
desired_cluster_size = config.get_float("desiredClusterSize", 3)
eks_node_instance_type = config.get("eksNodeInstanceType", "t3.medium")
vpc_network_cidr = config.get("vpcNetworkCidr", "10.0.0.0/16")

# Create a VPC for the EKS cluster
eks_vpc = awsx.ec2.Vpc("eks-vpc",
    enable_dns_hostnames=True,
    cidr_block=vpc_network_cidr)

# Create the EKS cluster
eks_cluster = eks.Cluster("eks-cluster",
    # Put the cluster in the new VPC created earlier
    vpc_id=eks_vpc.vpc_id,
    # Public subnets will be used for load balancers
    public_subnet_ids=eks_vpc.public_subnet_ids,
    # Private subnets will be used for cluster nodes
    private_subnet_ids=eks_vpc.private_subnet_ids,
    # Change configuration values to change any of the following settings
    instance_type=eks_node_instance_type,
    desired_capacity=desired_cluster_size,
    min_size=min_cluster_size,
    max_size=max_cluster_size,
    # Do not give worker nodes a public IP address
    node_associate_public_ip_address=False,
    # Uncomment the next two lines for private cluster (VPN access required)
    # endpoint_private_access=true,
    # endpoint_public_access=false
    tags={
    "Environment": "Prod",
    "Name": "ProdClusterEKS",
    "Project": pulumi.get_project(),
    "Owner": "SREs",
}
    )

# Export values to use elsewhere
pulumi.export("kubeconfig", eks_cluster.kubeconfig)
pulumi.export("vpcId", eks_vpc.vpc_id)

app_name = "weather-app"

cluster_provider = kubernetes.Provider("clusterProvider",
    kubeconfig=eks_cluster.kubeconfig,
    enable_server_side_apply=True)

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

##API deployment resource
apiDeployment = kubernetes.apps.v1.Deployment("api-deployment",
    metadata=kubernetes.meta.v1.ObjectMetaArgs(
        labels={
            "appClass": app_name,
            "name": "api",
        },
    ),
    spec=kubernetes.apps.v1.DeploymentSpecArgs(
        replicas=2,
        selector=kubernetes.meta.v1.LabelSelectorArgs(
            match_labels={
                "appClass": app_name,
                "name": "api",
                "tier": "backend",
                "track": "stable",
            },
        ),
        template=kubernetes.core.v1.PodTemplateSpecArgs(
            metadata=kubernetes.meta.v1.ObjectMetaArgs(
                labels={
                    "appClass": app_name,
                    "name": "api",
                    "tier": "backend",
                    "track": "stable",
                },
            ),
            spec=kubernetes.core.v1.PodSpecArgs(
                containers=[kubernetes.core.v1.ContainerArgs(
                    name=app_name,
                    image=apiImage.image_uri,
                    ports=[kubernetes.core.v1.ContainerPortArgs(
                        name="http",
                        container_port=80,
                    )],
                )],
            ),
        ),
    ),
    opts=pulumi.ResourceOptions(provider=cluster_provider))
##API service resource with load balancer
apiService = kubernetes.core.v1.Service("api-service",
    metadata=kubernetes.meta.v1.ObjectMetaArgs(
        labels={
            "appClass": app_name,
            "name": "api",
        },
    ),
    spec=kubernetes.core.v1.ServiceSpecArgs(
        selector={
            "appClass": app_name,
            "tier": "backend",
        },
        ports=[kubernetes.core.v1.ServicePortArgs(
            port=80,
            target_port="http",
            protocol="TCP",
        )],
    ),
    opts=pulumi.ResourceOptions(provider=cluster_provider))

##Web deployment resource
webDeployment = kubernetes.apps.v1.Deployment("web-deployment",
    metadata=kubernetes.meta.v1.ObjectMetaArgs(
        labels={
            "appClass": app_name,
            "name": "web"
        },
    ),
    spec=kubernetes.apps.v1.DeploymentSpecArgs(
        replicas=2,
        selector=kubernetes.meta.v1.LabelSelectorArgs(
            match_labels={
                "appClass": app_name,
                "tier": "frontend",
                "track": "stable",
            },
        ),
        template=kubernetes.core.v1.PodTemplateSpecArgs(
            metadata=kubernetes.meta.v1.ObjectMetaArgs(
                labels={
                    "appClass": app_name,
                    "tier": "frontend",
                    "track": "stable",
                },
            ),
            spec=kubernetes.core.v1.PodSpecArgs(
                containers=[kubernetes.core.v1.ContainerArgs(
                    name=app_name,
                    image=webImage.image_uri,
                    env=[{'name': "ApiAddress", 'value': "http://infraapi:5000/WeatherForecast"}],
                    ports=[kubernetes.core.v1.ContainerPortArgs(
                        name="http",
                        container_port=80,
                    )],
                )],
            ),
        ),
    ),
    opts=pulumi.ResourceOptions(provider=cluster_provider))

 ##Web service resource (which will be accessible through the load balancer endpoinnt)
service = kubernetes.core.v1.Service("service",
    metadata=kubernetes.meta.v1.ObjectMetaArgs(
        labels={
            "appClass": app_name,
            "name": "web"
        },
    ),
    spec=kubernetes.core.v1.ServiceSpecArgs(
        type="LoadBalancer",
        selector={
            "appClass": app_name,
            "tier": "frontend,"
        },
        ports=[kubernetes.core.v1.ServicePortArgs(
            port=80,
            target_port=80,
            protocol="TCP"
        )],
    ),
    opts=pulumi.ResourceOptions(provider=cluster_provider))
pulumi.export("url", service.status.load_balancer.ingress[0].hostname)