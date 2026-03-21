#!/usr/bin/env python3
"""
Script to systematically shutdown all AWS resources to reduce billing.
This script identifies and shuts down resources based on the AWS invoice.
"""

import subprocess
import json
import sys
from typing import List, Dict, Any

def run_aws_command(cmd: str) -> Dict[str, Any]:
    """Run an AWS CLI command and return parsed JSON output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, check=True
        )
        if result.stdout.strip():
            return json.loads(result.stdout)
        return {}
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {cmd}")
        print(f"Error: {e.stderr}")
        return {}
    except json.JSONDecodeError:
        return {}

def get_all_regions() -> List[str]:
    """Get all AWS regions."""
    result = run_aws_command("aws ec2 describe-regions --query 'Regions[].RegionName' --output json")
    return result if isinstance(result, list) else []

def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")

def handle_ec2_instances():
    """Terminate all EC2 instances."""
    print_section("EC2 INSTANCES")
    regions = get_all_regions()
    
    total_terminated = 0
    for region in regions:
        cmd = f"aws ec2 describe-instances --region {region} --query 'Reservations[].Instances[].[InstanceId,State.Name,Tags[?Key==`Name`].Value|[0]]' --output json"
        instances = run_aws_command(cmd)
        
        if isinstance(instances, list) and instances:
            running_instances = [inst for inst in instances if inst and inst[1] in ['running', 'pending', 'stopping', 'stopped']]
            if running_instances:
                print(f"Region: {region}")
                for instance in running_instances:
                    instance_id = instance[0]
                    state = instance[1]
                    name = instance[2] if len(instance) > 2 and instance[2] else "N/A"
                    print(f"  - {instance_id} ({name}) - State: {state}")
                    
                    if state != 'terminated':
                        terminate_cmd = f"aws ec2 terminate-instances --region {region} --instance-ids {instance_id}"
                        print(f"    → Terminating...")
                        subprocess.run(terminate_cmd, shell=True)
                        total_terminated += 1
        elif instances:
            # Handle different response format
            print(f"Region {region}: Unexpected response format")
    
    print(f"\nTotal EC2 instances terminated: {total_terminated}")

def handle_eks_clusters():
    """Delete all EKS clusters."""
    print_section("EKS CLUSTERS (BIGGEST COST)")
    regions = get_all_regions()
    
    total_deleted = 0
    for region in regions:
        cmd = f"aws eks list-clusters --region {region} --output json"
        result = run_aws_command(cmd)
        
        clusters = result.get("clusters", []) if isinstance(result, dict) else []
        if clusters:
            print(f"Region: {region}")
            for cluster_name in clusters:
                print(f"  - {cluster_name}")
                delete_cmd = f"aws eks delete-cluster --region {region} --name {cluster_name}"
                print(f"    → Deleting cluster (this may take 10-15 minutes)...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
    
    print(f"\nTotal EKS clusters deleted: {total_deleted}")

def handle_load_balancers():
    """Delete all load balancers (ELB and ALB)."""
    print_section("ELASTIC LOAD BALANCERS")
    regions = get_all_regions()
    
    total_deleted = 0
    
    # Classic Load Balancers
    for region in regions:
        cmd = f"aws elb describe-load-balancers --region {region} --query 'LoadBalancerDescriptions[].LoadBalancerName' --output json"
        elbs = run_aws_command(cmd)
        
        if isinstance(elbs, list) and elbs:
            print(f"Region: {region} (Classic ELB)")
            for elb_name in elbs:
                print(f"  - {elb_name}")
                delete_cmd = f"aws elb delete-load-balancer --region {region} --load-balancer-name {elb_name}"
                print(f"    → Deleting...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
    
    # Application and Network Load Balancers
    for region in regions:
        cmd = f"aws elbv2 describe-load-balancers --region {region} --query 'LoadBalancers[].LoadBalancerArn' --output json"
        albs = run_aws_command(cmd)
        
        if isinstance(albs, list) and albs:
            print(f"Region: {region} (ALB/NLB)")
            for alb_arn in albs:
                print(f"  - {alb_arn}")
                delete_cmd = f"aws elbv2 delete-load-balancer --region {region} --load-balancer-arn {alb_arn}"
                print(f"    → Deleting...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
    
    print(f"\nTotal load balancers deleted: {total_deleted}")

def handle_nat_gateways():
    """Delete all NAT gateways."""
    print_section("NAT GATEWAYS")
    regions = get_all_regions()
    
    total_deleted = 0
    for region in regions:
        cmd = f"aws ec2 describe-nat-gateways --region {region} --filter 'Name=state,Values=pending,available' --query 'NatGateways[].NatGatewayId' --output json"
        nat_gws = run_aws_command(cmd)
        
        if isinstance(nat_gws, list) and nat_gws:
            print(f"Region: {region}")
            for nat_gw_id in nat_gws:
                print(f"  - {nat_gw_id}")
                delete_cmd = f"aws ec2 delete-nat-gateway --region {region} --nat-gateway-id {nat_gw_id}"
                print(f"    → Deleting...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
    
    print(f"\nTotal NAT gateways deleted: {total_deleted}")

def handle_ebs_volumes():
    """Delete all unattached EBS volumes."""
    print_section("EBS VOLUMES (Unattached)")
    regions = get_all_regions()
    
    total_deleted = 0
    for region in regions:
        cmd = f"aws ec2 describe-volumes --region {region} --filters Name=status,Values=available --query 'Volumes[].VolumeId' --output json"
        volumes = run_aws_command(cmd)
        
        if isinstance(volumes, list) and volumes:
            print(f"Region: {region}")
            for volume_id in volumes:
                print(f"  - {volume_id}")
                delete_cmd = f"aws ec2 delete-volume --region {region} --volume-id {volume_id}"
                print(f"    → Deleting...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
    
    print(f"\nTotal unattached EBS volumes deleted: {total_deleted}")

def handle_snapshots():
    """Delete all EBS snapshots."""
    print_section("EBS SNAPSHOTS")
    regions = get_all_regions()
    
    total_deleted = 0
    for region in regions:
        cmd = f"aws ec2 describe-snapshots --region {region} --owner-ids self --query 'Snapshots[].SnapshotId' --output json"
        snapshots = run_aws_command(cmd)
        
        if isinstance(snapshots, list) and snapshots:
            print(f"Region: {region}")
            for snapshot_id in snapshots:
                print(f"  - {snapshot_id}")
                delete_cmd = f"aws ec2 delete-snapshot --region {region} --snapshot-id {snapshot_id}"
                print(f"    → Deleting...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
    
    print(f"\nTotal snapshots deleted: {total_deleted}")

def handle_elastic_ips():
    """Release unattached Elastic IPs."""
    print_section("ELASTIC IPs (Unattached)")
    regions = get_all_regions()
    
    total_released = 0
    for region in regions:
        cmd = f"aws ec2 describe-addresses --region {region} --query 'Addresses[?AssociationId==null].AllocationId' --output json"
        eips = run_aws_command(cmd)
        
        if isinstance(eips, list) and eips:
            print(f"Region: {region}")
            for eip_allocation_id in eips:
                print(f"  - {eip_allocation_id}")
                release_cmd = f"aws ec2 release-address --region {region} --allocation-id {eip_allocation_id}"
                print(f"    → Releasing...")
                subprocess.run(release_cmd, shell=True)
                total_released += 1
    
    print(f"\nTotal Elastic IPs released: {total_released}")

def handle_route53_hosted_zones():
    """List Route 53 hosted zones (user should review before deletion)."""
    print_section("ROUTE 53 HOSTED ZONES")
    cmd = "aws route53 list-hosted-zones --query 'HostedZones[].[Id,Name]' --output json"
    zones = run_aws_command(cmd)
    
    if isinstance(zones, list) and zones:
        print("Hosted Zones found (Review before deletion):")
        for zone in zones:
            zone_id = zone[0].split('/')[-1] if '/' in zone[0] else zone[0]
            zone_name = zone[1] if len(zone) > 1 else "N/A"
            print(f"  - {zone_name} ({zone_id})")
            print(f"    To delete: aws route53 delete-hosted-zone --id {zone_id}")
    else:
        print("No hosted zones found.")

def handle_ecr_repositories():
    """Delete all ECR repositories."""
    print_section("ECR REPOSITORIES")
    regions = get_all_regions()
    
    total_deleted = 0
    for region in regions:
        cmd = f"aws ecr describe-repositories --region {region} --query 'repositories[].repositoryName' --output json"
        repos = run_aws_command(cmd)
        
        if isinstance(repos, list) and repos:
            print(f"Region: {region}")
            for repo_name in repos:
                print(f"  - {repo_name}")
                delete_cmd = f"aws ecr delete-repository --region {region} --repository-name {repo_name} --force"
                print(f"    → Deleting...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
    
    print(f"\nTotal ECR repositories deleted: {total_deleted}")

def handle_rds_instances():
    """Delete all RDS instances."""
    print_section("RDS DATABASE INSTANCES")
    regions = get_all_regions()
    
    total_deleted = 0
    for region in regions:
        cmd = f"aws rds describe-db-instances --region {region} --query 'DBInstances[].DBInstanceIdentifier' --output json"
        instances = run_aws_command(cmd)
        
        if isinstance(instances, list) and instances:
            print(f"Region: {region}")
            for db_id in instances:
                print(f"  - {db_id}")
                delete_cmd = f"aws rds delete-db-instance --region {region} --db-instance-identifier {db_id} --skip-final-snapshot"
                print(f"    → Deleting (this may take several minutes)...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
    
    print(f"\nTotal RDS instances deleted: {total_deleted}")

def handle_elasticache_clusters():
    """Delete all ElastiCache clusters."""
    print_section("ELASTICACHE CLUSTERS")
    regions = get_all_regions()
    
    total_deleted = 0
    for region in regions:
        # Redis clusters
        cmd = f"aws elasticache describe-cache-clusters --region {region} --show-cache-node-info --query 'CacheClusters[].CacheClusterId' --output json"
        redis_clusters = run_aws_command(cmd)
        
        if isinstance(redis_clusters, list) and redis_clusters:
            print(f"Region: {region} (Redis)")
            for cluster_id in redis_clusters:
                print(f"  - {cluster_id}")
                delete_cmd = f"aws elasticache delete-cache-cluster --region {region} --cache-cluster-id {cluster_id}"
                print(f"    → Deleting...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
        
        # Replication groups (Redis cluster mode)
        cmd = f"aws elasticache describe-replication-groups --region {region} --query 'ReplicationGroups[].ReplicationGroupId' --output json"
        replication_groups = run_aws_command(cmd)
        
        if isinstance(replication_groups, list) and replication_groups:
            print(f"Region: {region} (Replication Groups)")
            for rg_id in replication_groups:
                print(f"  - {rg_id}")
                delete_cmd = f"aws elasticache delete-replication-group --region {region} --replication-group-id {rg_id}"
                print(f"    → Deleting...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
    
    print(f"\nTotal ElastiCache clusters deleted: {total_deleted}")

def handle_ecs_clusters():
    """Delete all ECS clusters."""
    print_section("ECS CLUSTERS")
    regions = get_all_regions()
    
    total_deleted = 0
    for region in regions:
        cmd = f"aws ecs list-clusters --region {region} --query 'clusterArns[]' --output json"
        clusters = run_aws_command(cmd)
        
        if isinstance(clusters, list) and clusters:
            print(f"Region: {region}")
            for cluster_arn in clusters:
                cluster_name = cluster_arn.split('/')[-1]
                print(f"  - {cluster_name}")
                
                # Stop all tasks first
                stop_cmd = f"aws ecs list-tasks --region {region} --cluster {cluster_name} --query 'taskArns[]' --output json"
                tasks = run_aws_command(stop_cmd)
                if isinstance(tasks, list) and tasks:
                    for task_arn in tasks:
                        subprocess.run(f"aws ecs stop-task --region {region} --cluster {cluster_name} --task {task_arn}", shell=True)
                
                # Delete cluster
                delete_cmd = f"aws ecs delete-cluster --region {region} --cluster {cluster_name}"
                print(f"    → Deleting...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
    
    print(f"\nTotal ECS clusters deleted: {total_deleted}")

def handle_s3_buckets():
    """Delete all S3 buckets."""
    print_section("S3 BUCKETS")
    
    cmd = "aws s3api list-buckets --query 'Buckets[].Name' --output json"
    buckets = run_aws_command(cmd)
    
    total_deleted = 0
    if isinstance(buckets, list) and buckets:
        for bucket_name in buckets:
            print(f"  - {bucket_name}")
            # Empty bucket first
            empty_cmd = f"aws s3 rm s3://{bucket_name} --recursive"
            print(f"    → Emptying bucket...")
            subprocess.run(empty_cmd, shell=True)
            
            # Delete bucket
            delete_cmd = f"aws s3api delete-bucket --bucket {bucket_name}"
            print(f"    → Deleting bucket...")
            # Get region first
            try:
                region_cmd = f"aws s3api get-bucket-location --bucket {bucket_name} --query 'LocationConstraint' --output text"
                region_result = subprocess.run(region_cmd, shell=True, capture_output=True, text=True)
                region = region_result.stdout.strip() or 'us-east-1'
                if region == 'None':
                    region = 'us-east-1'
                delete_cmd = f"aws s3api delete-bucket --bucket {bucket_name} --region {region}"
            except:
                pass
            subprocess.run(delete_cmd, shell=True)
            total_deleted += 1
    
    print(f"\nTotal S3 buckets deleted: {total_deleted}")

def handle_cloudformation_stacks():
    """Delete all CloudFormation stacks."""
    print_section("CLOUDFORMATION STACKS")
    regions = get_all_regions()
    
    total_deleted = 0
    for region in regions:
        cmd = f"aws cloudformation list-stacks --region {region} --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE ROLLBACK_COMPLETE UPDATE_ROLLBACK_COMPLETE --query 'StackSummaries[].StackName' --output json"
        stacks = run_aws_command(cmd)
        
        if isinstance(stacks, list) and stacks:
            print(f"Region: {region}")
            for stack_name in stacks:
                print(f"  - {stack_name}")
                delete_cmd = f"aws cloudformation delete-stack --region {region} --stack-name {stack_name}"
                print(f"    → Deleting stack...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
    
    print(f"\nTotal CloudFormation stacks deleted: {total_deleted}")

def handle_vpcs():
    """Delete all VPCs and their dependencies."""
    print_section("VPCs AND DEPENDENCIES")
    regions = get_all_regions()
    
    total_deleted = 0
    for region in regions:
        # Get all VPCs (excluding default VPC)
        cmd = f"aws ec2 describe-vpcs --region {region} --filters 'Name=isDefault,Values=false' --query 'Vpcs[].VpcId' --output json"
        vpcs = run_aws_command(cmd)
        
        if isinstance(vpcs, list) and vpcs:
            print(f"Region: {region}")
            for vpc_id in vpcs:
                print(f"  Processing VPC: {vpc_id}")
                
                # Delete Internet Gateways
                igw_cmd = f"aws ec2 describe-internet-gateways --region {region} --filters 'Name=attachment.vpc-id,Values={vpc_id}' --query 'InternetGateways[].InternetGatewayId' --output json"
                igws = run_aws_command(igw_cmd)
                if isinstance(igws, list) and igws:
                    for igw_id in igws:
                        # Detach first
                        subprocess.run(f"aws ec2 detach-internet-gateway --region {region} --internet-gateway-id {igw_id} --vpc-id {vpc_id}", shell=True, capture_output=True)
                        # Then delete
                        subprocess.run(f"aws ec2 delete-internet-gateway --region {region} --internet-gateway-id {igw_id}", shell=True, capture_output=True)
                        print(f"    → Deleted Internet Gateway: {igw_id}")
                
                # Delete NAT Gateways (already handled, but double-check)
                nat_cmd = f"aws ec2 describe-nat-gateways --region {region} --filter 'Name=vpc-id,Values={vpc_id}' --filter 'Name=state,Values=pending,available' --query 'NatGateways[].NatGatewayId' --output json"
                nats = run_aws_command(nat_cmd)
                if isinstance(nats, list) and nats:
                    for nat_id in nats:
                        subprocess.run(f"aws ec2 delete-nat-gateway --region {region} --nat-gateway-id {nat_id}", shell=True, capture_output=True)
                        print(f"    → Deleted NAT Gateway: {nat_id}")
                
                # Delete VPC Endpoints
                endpoint_cmd = f"aws ec2 describe-vpc-endpoints --region {region} --filters 'Name=vpc-id,Values={vpc_id}' --query 'VpcEndpoints[].VpcEndpointId' --output json"
                endpoints = run_aws_command(endpoint_cmd)
                if isinstance(endpoints, list) and endpoints:
                    for endpoint_id in endpoints:
                        subprocess.run(f"aws ec2 delete-vpc-endpoint --region {region} --vpc-endpoint-id {endpoint_id}", shell=True, capture_output=True)
                        print(f"    → Deleted VPC Endpoint: {endpoint_id}")
                
                # Delete Subnets
                subnet_cmd = f"aws ec2 describe-subnets --region {region} --filters 'Name=vpc-id,Values={vpc_id}' --query 'Subnets[].SubnetId' --output json"
                subnets = run_aws_command(subnet_cmd)
                if isinstance(subnets, list) and subnets:
                    for subnet_id in subnets:
                        subprocess.run(f"aws ec2 delete-subnet --region {region} --subnet-id {subnet_id}", shell=True, capture_output=True)
                        print(f"    → Deleted Subnet: {subnet_id}")
                
                # Delete Route Tables (except main route table)
                rt_cmd = f"aws ec2 describe-route-tables --region {region} --filters 'Name=vpc-id,Values={vpc_id}' --query 'RouteTables[?!Associations[?Main]].RouteTableId' --output json"
                route_tables = run_aws_command(rt_cmd)
                if isinstance(route_tables, list) and route_tables:
                    for rt_id in route_tables:
                        subprocess.run(f"aws ec2 delete-route-table --region {region} --route-table-id {rt_id}", shell=True, capture_output=True)
                        print(f"    → Deleted Route Table: {rt_id}")
                
                # Delete Security Groups (except default)
                sg_cmd = f"aws ec2 describe-security-groups --region {region} --filters 'Name=vpc-id,Values={vpc_id}' 'Name=group-name,Values=!default' --query 'SecurityGroups[].GroupId' --output json"
                security_groups = run_aws_command(sg_cmd)
                if isinstance(security_groups, list) and security_groups:
                    for sg_id in security_groups:
                        subprocess.run(f"aws ec2 delete-security-group --region {region} --group-id {sg_id}", shell=True, capture_output=True)
                        print(f"    → Deleted Security Group: {sg_id}")
                
                # Delete Network ACLs (except default)
                nacl_cmd = f"aws ec2 describe-network-acls --region {region} --filters 'Name=vpc-id,Values={vpc_id}' 'Name=default,Values=false' --query 'NetworkAcls[].NetworkAclId' --output json"
                nacls = run_aws_command(nacl_cmd)
                if isinstance(nacls, list) and nacls:
                    for nacl_id in nacls:
                        subprocess.run(f"aws ec2 delete-network-acl --region {region} --network-acl-id {nacl_id}", shell=True, capture_output=True)
                        print(f"    → Deleted Network ACL: {nacl_id}")
                
                # Finally, delete the VPC
                delete_cmd = f"aws ec2 delete-vpc --region {region} --vpc-id {vpc_id}"
                print(f"    → Deleting VPC...")
                result = subprocess.run(delete_cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"    ✓ VPC {vpc_id} deleted")
                    total_deleted += 1
                else:
                    print(f"    ⚠ Could not delete VPC {vpc_id}: {result.stderr}")
                    print(f"    (May have dependencies - check manually)")
    
    print(f"\nTotal VPCs deleted: {total_deleted}")

def handle_cloudwatch_logs():
    """Delete all CloudWatch Log Groups."""
    print_section("CLOUDWATCH LOG GROUPS")
    regions = get_all_regions()
    
    total_deleted = 0
    for region in regions:
        cmd = f"aws logs describe-log-groups --region {region} --query 'logGroups[].logGroupName' --output json"
        log_groups = run_aws_command(cmd)
        
        if isinstance(log_groups, list) and log_groups:
            print(f"Region: {region}")
            for log_group_name in log_groups:
                print(f"  - {log_group_name}")
                delete_cmd = f"aws logs delete-log-group --region {region} --log-group-name {log_group_name}"
                print(f"    → Deleting...")
                subprocess.run(delete_cmd, shell=True)
                total_deleted += 1
    
    print(f"\nTotal CloudWatch log groups deleted: {total_deleted}")

def main():
    """Main function to shutdown all AWS resources."""
    print("="*60)
    print("  AWS RESOURCE SHUTDOWN SCRIPT")
    print("  COMPREHENSIVE CLEANUP - ALL RESOURCES")
    print("="*60)
    print("\nWARNING: This will DELETE/TERMINATE ALL AWS resources!")
    print("This includes:")
    print("  - EKS Clusters")
    print("  - EC2 Instances")
    print("  - RDS Databases")
    print("  - ElastiCache")
    print("  - ECS Clusters")
    print("  - Load Balancers")
    print("  - VPCs and all dependencies")
    print("  - NAT Gateways")
    print("  - S3 Buckets")
    print("  - CloudFormation Stacks")
    print("  - EBS Volumes & Snapshots")
    print("  - Elastic IPs")
    print("  - ECR Repositories")
    print("  - CloudWatch Logs")
    print("\nProceeding with shutdown...\n")
    
    # Handle resources in order of dependencies (delete resources that depend on VPCs first)
    # 1. Delete compute resources that depend on VPCs
    handle_eks_clusters()
    handle_ecs_clusters()
    handle_ec2_instances()
    
    # 2. Delete database and cache resources that depend on VPCs
    handle_rds_instances()
    handle_elasticache_clusters()
    
    # 3. Delete load balancers (depend on VPCs)
    handle_load_balancers()
    
    # 4. Delete NAT gateways (depend on VPCs)
    handle_nat_gateways()
    
    # 5. Delete VPCs and their dependencies (subnets, route tables, etc.)
    handle_vpcs()
    
    # 6. Delete storage resources
    handle_ebs_volumes()
    handle_snapshots()
    handle_s3_buckets()
    
    # 7. Delete networking resources
    handle_elastic_ips()
    
    # 8. Delete container registry
    handle_ecr_repositories()
    
    # 9. Delete infrastructure as code
    handle_cloudformation_stacks()
    
    # 10. Delete logs
    handle_cloudwatch_logs()
    
    # 11. Review Route 53 (low cost, may want to keep)
    handle_route53_hosted_zones()
    
    print_section("SUMMARY")
    print("Resource cleanup initiated.")
    print("\nImportant Notes:")
    print("- EKS clusters may take 10-15 minutes to fully delete")
    print("- RDS instances may take several minutes to delete")
    print("- VPCs with dependencies may need a second pass if some resources weren't deleted")
    print("- Review Route 53 hosted zones - only ~$0.51/month, you may want to keep them")
    print("- CloudFormation stacks may remain until dependent resources are deleted")
    print("\nNext Steps:")
    print("1. Wait 10-15 minutes for long-running deletions (EKS, RDS) to complete")
    print("2. Re-run this script if VPCs still exist (may need second pass)")
    print("3. Check AWS Console to verify all resources are cleaned up")
    print("4. Monitor AWS Billing Dashboard to confirm charges stop")
    print("\nTo verify cleanup, run:")
    print("  aws ec2 describe-vpcs --region us-west-2 --filters 'Name=isDefault,Values=false'")
    print("  aws eks list-clusters --region us-west-2")
    print("  aws rds describe-db-instances --region us-west-2")

if __name__ == "__main__":
    main()

