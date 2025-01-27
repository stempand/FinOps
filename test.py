#!/usr/bin/env python3

import boto3
from botocore.exceptions import ClientError

# This script uses:
# 1. AWS Organizations to list all accounts.
# 2. STS to assume a read-only role in each account.
# 3. Lists RDS instances in each account.

# Prerequisites:
# - You must have permission to call Organizations API (for listing accounts)
# - You must have permission to assume the read-only role in each target account.
# - The read-only role name below must match the role in each account.
# - The default AWS CLI credentials/profile must have the authority to do #1 and #2.

ROLE_NAME = "MyReadOnlyRole"  # the name of the role that exists in each account


def main():
    org_client = boto3.client("organizations")
    sts_client = boto3.client("sts")

    # 1. Get list of all accounts in the AWS Organization
    accounts = []
    paginator = org_client.get_paginator("list_accounts")
    for page in paginator.paginate():
        accounts.extend(page["Accounts"])

    # 2. Loop over each account and assume the read-only role
    for account in accounts:
        account_id = account["Id"]
        account_name = account["Name"]
        role_arn = f"arn:aws:iam::{account_id}:role/{ROLE_NAME}"

        print(f"\n------------------------------")
        print(f"Account: {account_name} ({account_id})")
        print(f"Role ARN: {role_arn}")

        try:
            # Assume the cross-account role
            response = sts_client.assume_role(
                RoleArn=role_arn,
                RoleSessionName="CrossAccountRDSList",
                DurationSeconds=3600
            )

            credentials = response["Credentials"]

            # 3. Create a session with the temporary creds and list RDS instances
            assumed_session = boto3.Session(
                aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"]
            )

            rds_client = assumed_session.client("rds")

            # Describe all DB instances
            try:
                dbs = rds_client.describe_db_instances()
                db_instances = dbs.get("DBInstances", [])

                if not db_instances:
                    print("No RDS instances found.")
                else:
                    print("RDS Instances:")
                    for db in db_instances:
                        db_id = db.get("DBInstanceIdentifier")
                        engine = db.get("Engine")
                        status = db.get("DBInstanceStatus")
                        print(f"  - ID: {db_id}, Engine: {engine}, Status: {status}")

            except ClientError as e:
                print(f"Error describing DB instances: {e}")

        except ClientError as e:
            print(f"Failed to assume role in {account_name} ({account_id}): {e}")


if __name__ == "__main__":
    main()
