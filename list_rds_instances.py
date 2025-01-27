#!/usr/bin/env python3

import csv
import boto3
from botocore.exceptions import ClientError

# Configuration
ROLE_NAME = "ADFS-ReadOnly"  # The name of the IAM role in each account
PROFILE_NAME = "saml"         # The name of the local AWS CLI profile to use
CSV_FILE = "accounts.csv"     # CSV file that has 'vendor_account_identifier' column


def main():
    """
    1. Create a base session with the given profile.
    2. Dynamically fetch all AWS regions.
    3. Read account IDs from a CSV file.
    4. For each account, assume ROLE_NAME.
    5. For each region, list RDS DB instances.
    """

    # 1. Create a base session using the specified profile
    base_session = boto3.Session(profile_name=PROFILE_NAME)

    # 2. Dynamically fetch all regions (commercial only)
    ec2_client = base_session.client("ec2", region_name="us-east-1")
    try:
        region_response = ec2_client.describe_regions(AllRegions=True)
        # Only keep regions that are available (opted-in or not required)
        regions = [
            r["RegionName"] for r in region_response["Regions"]
            if r["OptInStatus"] in ("opt-in-not-required", "opted-in")
        ]
    except ClientError as e:
        print(f"Error describing regions: {e}")
        regions = ["us-east-1"]  # fallback if error

    print("Discovered regions:")
    for region in regions:
        print(f" - {region}")

    # Create STS client from base session
    sts_client = base_session.client("sts", region_name="us-east-1")

    # 3. Read accounts from CSV
    accounts = []
    with open(CSV_FILE, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            accounts.append({
                "Id": row["vendor_account_identifier"],
                "Name": row.get("account_name", row["vendor_account_identifier"])
            })

    # 4. Loop over each account and assume ROLE_NAME
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

            # 5. Create a session with the temporary creds and list RDS in each region
            assumed_session = boto3.Session(
                aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"]
            )

            for region in regions:
                print(f"\nListing RDS in region: {region}")
                rds_client = assumed_session.client("rds", region_name=region)
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
