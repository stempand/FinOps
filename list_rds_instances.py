#!/usr/bin/env python3

import csv
import boto3
from botocore.exceptions import ClientError

ROLE_NAME = "MyReadOnlyRole"
PROFILE_NAME = "saml"
CSV_FILE = "accounts.csv"

def main():
    """ Demonstrates a fallback:
        1) Use global STS
        2) If region fails with InvalidClientTokenId, retry that region with region-specific STS
    """
    base_session = boto3.Session(profile_name=PROFILE_NAME)
    
    # 1. Get all active/opted-in regions
    ec2_client = base_session.client("ec2", region_name="us-east-1")
    try:
        region_response = ec2_client.describe_regions(AllRegions=True)
        regions = [
            r["RegionName"] for r in region_response["Regions"]
            if r["OptInStatus"] in ("opt-in-not-required", "opted-in")
        ]
    except ClientError as e:
        print(f"Error describing regions: {e}")
        regions = ["us-east-1"]
    
    print("Discovered regions:")
    for r in regions:
        print(f" - {r}")
    
    # 2. Read account IDs from CSV
    accounts = []
    with open(CSV_FILE, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            accounts.append({
                "Id": row["vendor_account_identifier"],
                "Name": row.get("account_name", row["vendor_account_identifier"])
            })
    
    # 3. Create a global STS client
    global_sts_client = base_session.client("sts")  # no region_name => global endpoint
    
    # Track failures for a second pass
    fallback_list = []  # will store tuples of (account_id, account_name, region)
    
    # 4. Attempt describing RDS in each region with global STS
    for acct in accounts:
        account_id = acct["Id"]
        account_name = acct["Name"]
        role_arn = f"arn:aws:iam::{account_id}:role/{ROLE_NAME}"
        
        print("\n===============================================================")
        print(f"Account: {account_name} ({account_id})")
        print(f"Role ARN: {role_arn}")
        
        try:
            # Assume role with global STS
            resp = global_sts_client.assume_role(
                RoleArn=role_arn,
                RoleSessionName="CrossAccountRDSListGlobalSTS",
                DurationSeconds=3600
            )
            creds = resp["Credentials"]
            
            # Temporary session for the global STS token
            assumed_session = boto3.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"]
            )
            
            # Describe RDS in each region
            for region in regions:
                print(f"\nListing RDS in region: {region} (global STS)")
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
                    err_code = e.response["Error"]["Code"]
                    if err_code == "InvalidClientTokenId":
                        print(f"  InvalidClientTokenId in {region}. Will retry with regional STS.")
                        fallback_list.append((account_id, account_name, region))
                    else:
                        print(f"  Error describing RDS in {region}: {e}")
        
        except ClientError as e:
            print(f"Failed to assume role (global STS) in {account_name} ({account_id}): {e}")
    
    # 5. Second pass: for each (account_id, region) that failed, try region-specific STS
    if fallback_list:
        print("\n======== Second Pass: Retrying with region-specific STS ========\n")
        
        for (account_id, account_name, region) in fallback_list:
            role_arn = f"arn:aws:iam::{account_id}:role/{ROLE_NAME}"
            print(f"Retrying {account_name} ({account_id}) in region {region} with region-specific STS.")
            
            # Create region-specific STS client
            regional_sts_client = base_session.client("sts", region_name=region)
            try:
                # Assume the same role, but through the region's STS endpoint
                resp = regional_sts_client.assume_role(
                    RoleArn=role_arn,
                    RoleSessionName="CrossAccountRDSListRegionalSTS",
                    DurationSeconds=3600
                )
                creds = resp["Credentials"]
                
                # Create a new session with the region-specific STS credentials
                assumed_session = boto3.Session(
                    aws_access_key_id=creds["AccessKeyId"],
                    aws_secret_access_key=creds["SecretAccessKey"],
                    aws_session_token=creds["SessionToken"]
                )
                
                rds_client = assumed_session.client("rds", region_name=region)
                print(f"Listing RDS in region: {region} (regional STS)")
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
                    print(f"  Still received error describing RDS in {region}: {e}")
            
            except ClientError as e:
                print(f"Failed to assume role (regional STS) in {account_name} ({account_id} / {region}): {e}")


if __name__ == \"__main__\":
    main()
