#!/usr/bin/env python3

import boto3
from botocore.exceptions import ClientError

#######################################
# Configuration
#######################################
ROLE_NAME = "MyReadOnlyRole"  # The name of the IAM role in each account.
PROFILE_NAME = "saml"         # The name of the local AWS CLI profile to use.


def main():
    """
    1. Create a session with the given profile.
    2. Dynamically fetch all AWS regions.
    3. Use AWS Organizations to list all accounts.
    4. For each account, assume ROLE_NAME.
    5. For each region, list RDS DB instances.
    """
    # Create a base session using the specified profile.
    base_session = boto3.Session(profile_name=PROFILE_NAME)

    # Step 1: Dynamically fetch all regions (commercial only)
    ec2_client = base_session.client("ec2", region_name="us-east-1")
    try:
        region_response = ec2_client.describe_regions(AllRegions=True)
        # Filter for regions that are available and opt-in is not required or has been opted in
        regions = [r["RegionName"] for r in region_response["Regions"] if r["OptInStatus"] in ("opt-in-not-required", "opted-in")]
    except ClientError as e:
        print(f"Error describing regions: {e}")
        regions = ["us-east-1"]  # fallback

    print("Discovered regions:")
    for region in regions:
        print(f" - {region}")

    # Step 2: AWS Organizations to list all accounts
    org_client = base_session.client("organizations", region_name="us-east-1")
    sts_client = base_session.client("sts", region_name="us-east-1")

    accounts = []
    paginator = org_client.get_paginator("list_accounts")
    for page in paginator.paginate():
        accounts.extend(page["Accounts"])

    # Step 3: Loop over each account and assume the read-only role
    for account in accounts:
        account_id = account["Id"]
        account_name = account["Name"]
        role_arn = f"arn:aws:iam::{account_id}:role/{ROLE_NAME}"

        print("\n===============================================================")
        print(f"Account: {account_name} ({account_id})")
        print(f"Role ARN: {role_arn}")

        try:
            response = sts_client.assume_role(
                RoleArn=role_arn,
                RoleSessionName="CrossAccountRDSList",
                DurationSeconds=3600
            )
            credentials = response["Credentials"]

            # 4. Create a session with the temporary creds
            assumed_session = boto3.Session(
                aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"]
            )

            # 5. Loop over each discovered region and list RDS instances
            for region in regions:
                rds_client = assumed_session.client("rds", region_name=region)
                print(f"\nListing RDS in region: {region}")
                try:
                    dbs = rds_client.describe_db_instances()
                    db_instances = dbs.get("DBInstances", [])

                    if not db_instances:
                        print("  No RDS instances found.")
                    else:
                        print("  RDS Instances:")
                        for db in db_instances:
                            db_id = db.get("DBInstanceIdentifier")
                            engine = db.get("Engine")
                            status = db.get("DBInstanceStatus")
                            print(f"    - ID: {db_id}, Engine: {engine}, Status: {status}")
                except ClientError as e:
                    print(f"  Error describing RDS in {region}: {e}")

        except ClientError as e:
            print(f"Failed to assume role in {account_name} ({account_id}): {e}")


if __name__ == "__main__":
    main()
