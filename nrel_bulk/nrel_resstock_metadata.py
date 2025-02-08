import os
import boto3
from botocore.client import Config
from botocore import UNSIGNED

s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
S3_BUCKET_NAME = "oedi-data-lake"

def download_s3_folder(bucket_name, s3_prefix, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket_name, Prefix=s3_prefix):
        if "Contents" in page:
            for obj in page["Contents"]:
                s3_key = obj["Key"]
                relative_path = os.path.relpath(s3_key, s3_prefix)
                local_path = os.path.join(output_dir, relative_path)
                local_dir = os.path.dirname(local_path)
                
                if not os.path.exists(local_dir):
                    os.makedirs(local_dir)
                
                if not os.path.exists(local_path):
                    try:
                        s3.download_file(Bucket=bucket_name, Key=s3_key, Filename=local_path)
                        print(f"Downloaded {s3_key} to {local_path}")
                    except Exception as e:
                        print(f"Error downloading {s3_key}: {e}")
                else:
                    print(f"File already exists: {local_path}. Skipping download.")

def download_metadata_and_results(output_base_dir="data", download_new_files=True):
    if not download_new_files:
        return {"message": "No new files needed."}
    
    s3_prefix = "nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2024/resstock_amy2018_release_2/metadata/"
    output_dir = os.path.join(output_base_dir, "metadata")
    
    print(f"Downloading all parquet files in metadata to: {output_dir}")
    
    download_s3_folder(S3_BUCKET_NAME, s3_prefix, output_dir)
    
    print("Download process completed.")
    return {"message": "Download completed for all parquet metadata files."}

download_metadata_and_results(output_base_dir="../data/nrel", download_new_files=True)
