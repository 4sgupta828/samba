# AWS Resource Shutdown Summary
**Account:** 911167909198  
**Date:** December 3, 2025

## Resources Successfully Deleted

### ✅ High-Cost Resources (from November invoice: $133.10)

1. **EKS Cluster: `oats-dev`** (us-west-2)
   - Status: DELETING (takes 10-15 minutes to complete)
   - Estimated monthly cost: ~$72.00
   - This was the biggest cost driver

2. **Elastic Load Balancers** (us-west-2)
   - 2 Classic Load Balancers deleted
   - Estimated monthly cost: ~$17.25

3. **NAT Gateway** (us-west-2)
   - NAT Gateway ID: `nat-06128f2f4d9bdb192`
   - Part of VPC costs: ~$10.81/month

4. **RDS Database Instance: `oatsdb`** (us-west-2)
   - PostgreSQL database (db.t4g.micro, 20GB)
   - Status: DELETING
   - No final snapshot created

### ✅ Additional Resources Cleaned Up

5. **ECR Repositories** (us-west-2)
   - `oats-backend-api` - deleted
   - `oats-ui` - deleted
   - `incident-analysis-system` - deleted
   - Estimated monthly cost: ~$0.13

6. **EC2 Instances**
   - None found running or stopped

7. **EBS Volumes & Snapshots**
   - No unattached volumes found
   - No snapshots found

8. **Elastic IPs**
   - No unattached Elastic IPs found

## Resources NOT Deleted (Low Cost or Domain-Related)

### ⚠️ Route 53 Hosted Zone
- **Hosted Zone:** `oatslab.ai` (Zone ID: Z03416671G6UHPI1YBPQT)
- **Monthly cost:** ~$0.51
- **Action:** Left intact - If you own this domain, you may want to keep it.
  - To delete: `aws route53 delete-hosted-zone --id Z03416671G6UHPI1YBPQT`
  - Note: Deleting the hosted zone will not delete your domain registration

### ⚠️ CloudFormation Stacks
- `eksctl-oats-dev-cluster` - Will be automatically cleaned up when EKS cluster deletion completes
- `eksctl-oats-dev-nodegroup-oats-nodes` - Will be automatically cleaned up when EKS cluster deletion completes

## Expected Cost Savings

Based on November 2025 invoice:
- **Previous monthly bill:** $133.10
- **After shutdown:** ~$0.51 (only Route 53)
- **Estimated monthly savings:** ~$132.59

## Next Steps

1. **Monitor deletions:** Check AWS Console to ensure all resources are fully deleted
   - EKS cluster deletion can take 10-15 minutes
   - RDS deletion can take a few minutes
   - CloudFormation stacks will auto-delete when dependencies are removed

2. **Route 53 decision:** Decide if you want to keep or delete the `oatslab.ai` hosted zone

3. **Verify billing:** Check your AWS billing dashboard in a few days to confirm charges have stopped

## Verification Commands

Run these commands to verify resource deletion:

```bash
# Check EKS clusters
aws eks list-clusters --region us-west-2

# Check load balancers
aws elb describe-load-balancers --region us-west-2
aws elbv2 describe-load-balancers --region us-west-2

# Check RDS instances
aws rds describe-db-instances --region us-west-2

# Check NAT gateways
aws ec2 describe-nat-gateways --region us-west-2 --filter 'Name=state,Values=pending,available'

# Check ECR repositories
aws ecr describe-repositories --region us-west-2
```

## Important Notes

- **EKS Cluster:** Still in DELETING status - this is normal and will complete automatically
- **CloudFormation Stacks:** Will remain until EKS cluster deletion completes, then will auto-delete
- **VPC Resources:** The VPC itself (`vpc-07351ea1429cf266b`) is still present but should have minimal/no cost if no resources are using it
- **Route 53:** Only costs $0.51/month - keep if you use the domain

