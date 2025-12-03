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

def main():
    """Main function to shutdown all AWS resources."""
    print("="*60)
    print("  AWS RESOURCE SHUTDOWN SCRIPT")
    print("  Account: 911167909198")
    print("="*60)
    print("\nWARNING: This will DELETE/TERMINATE all AWS resources!")
    print("Based on your invoice, the main costs are:")
    print("  - EKS Clusters: ~$72/month")
    print("  - EC2 Instances: ~$32.40/month")
    print("  - Load Balancers: ~$17.25/month")
    print("  - VPC/NAT Gateways: ~$10.81/month")
    print("\nProceeding with shutdown...\n")
    
    # Handle resources in order of cost impact
    handle_eks_clusters()
    handle_ec2_instances()
    handle_load_balancers()
    handle_nat_gateways()
    handle_ebs_volumes()
    handle_snapshots()
    handle_elastic_ips()
    handle_ecr_repositories()
    handle_route53_hosted_zones()
    
    print_section("SUMMARY")
    print("Resource cleanup initiated.")
    print("\nNote:")
    print("- EKS clusters may take 10-15 minutes to fully delete")
    print("- Some resources (like VPCs) may need manual cleanup if dependencies exist")
    print("- Review Route 53 hosted zones before deleting")
    print("- Check AWS Console to verify all resources are cleaned up")

if __name__ == "__main__":
    main()

