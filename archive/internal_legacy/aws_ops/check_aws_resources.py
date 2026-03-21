#!/usr/bin/env python3
"""Quick script to check what AWS resources exist across all regions."""

import subprocess
import json

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
        if result.stdout.strip():
            return json.loads(result.stdout)
        return {}
    except Exception as e:
        return {}

def get_regions():
    result = run_cmd("aws ec2 describe-regions --query 'Regions[].RegionName' --output json")
    return result if isinstance(result, list) else []

print("=" * 60)
print("  AWS RESOURCE INVENTORY CHECK")
print("=" * 60)
print()

regions = get_regions()
print(f"Checking {len(regions)} regions...\n")

found_resources = False

# Check EKS
print("EKS CLUSTERS:")
for region in regions:
    result = run_cmd(f"aws eks list-clusters --region {region} --output json")
    clusters = result.get("clusters", []) if isinstance(result, dict) else []
    if clusters:
        print(f"  {region}: {clusters}")
        found_resources = True
if not found_resources:
    print("  None found")
print()

# Check EC2
found_resources = False
print("EC2 INSTANCES:")
for region in regions:
    result = run_cmd(f"aws ec2 describe-instances --region {region} --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output json")
    if isinstance(result, list) and result:
        print(f"  {region}: {len(result)} instances")
        for inst in result[:3]:  # Show first 3
            print(f"    - {inst[0]}: {inst[1]}")
        found_resources = True
if not found_resources:
    print("  None found")
print()

# Check RDS
found_resources = False
print("RDS INSTANCES:")
for region in regions:
    result = run_cmd(f"aws rds describe-db-instances --region {region} --query 'DBInstances[].DBInstanceIdentifier' --output json")
    if isinstance(result, list) and result:
        print(f"  {region}: {result}")
        found_resources = True
if not found_resources:
    print("  None found")
print()

# Check NAT Gateways
found_resources = False
print("NAT GATEWAYS:")
for region in regions:
    result = run_cmd(f"aws ec2 describe-nat-gateways --region {region} --filter 'Name=state,Values=pending,available' --query 'NatGateways[].NatGatewayId' --output json")
    if isinstance(result, list) and result:
        print(f"  {region}: {result}")
        found_resources = True
if not found_resources:
    print("  None found")
print()

# Check Load Balancers
found_resources = False
print("LOAD BALANCERS (ALB/NLB):")
for region in regions:
    result = run_cmd(f"aws elbv2 describe-load-balancers --region {region} --query 'LoadBalancers[].LoadBalancerName' --output json")
    if isinstance(result, list) and result:
        print(f"  {region}: {result}")
        found_resources = True
if not found_resources:
    print("  None found")
print()

# Check Route 53 (global)
print("ROUTE 53 HOSTED ZONES:")
result = run_cmd("aws route53 list-hosted-zones --query 'HostedZones[].[Name,Id]' --output json")
if isinstance(result, list) and result:
    for zone in result:
        print(f"  {zone[0]} ({zone[1]})")
else:
    print("  None found")
print()

# Check VPCs (non-default)
found_resources = False
print("VPCs (non-default):")
for region in regions:
    result = run_cmd(f"aws ec2 describe-vpcs --region {region} --filters 'Name=isDefault,Values=false' --query 'Vpcs[].VpcId' --output json")
    if isinstance(result, list) and result:
        print(f"  {region}: {result}")
        found_resources = True
if not found_resources:
    print("  None found")
print()

print("=" * 60)
print("Inventory complete!")
print("=" * 60)

