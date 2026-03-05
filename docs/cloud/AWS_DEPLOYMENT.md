# AWS Deployment Guide

This guide explains how to deploy the Real-Time Data Collection and Monitoring System on AWS.

## Architecture

- **EC2**: Backend and data generator services
- **RDS PostgreSQL**: Database with TimescaleDB extension
- **ElastiCache Redis**: Caching layer
- **ECS/EKS**: Container orchestration (optional)
- **CloudWatch**: Logging and monitoring
- **Application Load Balancer**: Load balancing

## Prerequisites

- AWS account
- AWS CLI configured
- Terraform (optional, for infrastructure as code)
- Docker and Docker Compose

## Deployment Steps

### 1. Database Setup (RDS)

```bash
# Create RDS PostgreSQL instance with TimescaleDB
aws rds create-db-instance \
  --db-instance-identifier sensor-db \
  --db-instance-class db.t3.medium \
  --engine postgres \
  --engine-version 15.4 \
  --master-username postgres \
  --master-user-password <password> \
  --allocated-storage 100 \
  --storage-type gp2 \
  --vpc-security-group-ids <security-group-id> \
  --db-subnet-group-name <subnet-group>
```

### 2. Redis Setup (ElastiCache)

```bash
# Create ElastiCache Redis cluster
aws elasticache create-cache-cluster \
  --cache-cluster-id sensor-redis \
  --cache-node-type cache.t3.micro \
  --engine redis \
  --num-cache-nodes 1 \
  --security-group-ids <security-group-id>
```

### 3. EC2 Instance Setup

```bash
# Launch EC2 instance
aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \
  --instance-type t3.medium \
  --key-name <key-pair> \
  --security-group-ids <security-group-id> \
  --subnet-id <subnet-id> \
  --user-data file://user-data.sh
```

### 4. Application Deployment

```bash
# SSH into EC2 instance
ssh -i <key.pem> ec2-user@<instance-ip>

# Clone repository
git clone <repository-url>
cd src

# Configure environment variables
cp .env.example .env
# Edit .env with AWS RDS and ElastiCache endpoints

# Start services
docker compose up -d
```

### 5. Load Balancer Setup

```bash
# Create Application Load Balancer
aws elbv2 create-load-balancer \
  --name sensor-alb \
  --subnets <subnet-ids> \
  --security-groups <security-group-id>

# Create target group
aws elbv2 create-target-group \
  --name sensor-backend \
  --protocol HTTP \
  --port 8000 \
  --vpc-id <vpc-id> \
  --health-check-path /health

# Register targets
aws elbv2 register-targets \
  --target-group-arn <target-group-arn> \
  --targets Id=<instance-id>
```

## Environment Variables

Update `.env` with AWS-specific values:

```bash
DB_HOST=<rds-endpoint>
DB_PORT=5432
REDIS_HOST=<elasticache-endpoint>
REDIS_PORT=6379
```

## Security Considerations

- Use AWS Secrets Manager for sensitive data
- Configure security groups properly
- Enable SSL/TLS for database connections
- Use IAM roles for service authentication
- Enable CloudWatch logging

## Monitoring

- CloudWatch Logs for application logs
- CloudWatch Metrics for system metrics
- CloudWatch Alarms for alerting
- Integrate Prometheus with CloudWatch

## Cost Optimization

- Use reserved instances for long-term deployments
- Use spot instances for non-critical workloads
- Enable auto-scaling based on load
- Use S3 for log archival

## Troubleshooting

- Check CloudWatch Logs for application errors
- Verify security group rules
- Check RDS connection limits
- Monitor ElastiCache memory usage
