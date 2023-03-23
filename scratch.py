from pprint import pprint

import boto3
import botocore


S3_BUCKET = ""
conn = boto3.client('s3', aws_access_key_id="", aws_secret_access_key="", region_name="us-east-1")

# CRITICALLY IMPORTANT DETAIL: this deletes everything including the current file version.

def paginate_versions(prefix):
    """ We validate that the prefiex is exact, not a startswith """
    paginator = conn.get_paginator('list_object_versions')
    page_iterator: dict = paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix)
    
    for page in page_iterator:
        # pprint(page)
        # pprint(page.keys())
        # pprint(page['DeleteMarkers'])
        # pprint(page["Versions"])
        items = []
        
        if 'Versions' in page.keys():
            for item in page['Versions']:
                if item['Key'] == prefix:
                    items.append((item['Key'], item['VersionId']))
        if 'DeleteMarkers' in page.keys():
            for item in page['DeleteMarkers']:
                if item['Key'] == prefix:
                    items.append((item['Key'], item['VersionId']))
        
        yield items


def delete_file_versions_many(list_of_keys):
    for key in list_of_keys:
        try:
            print(f"doing key: {key}")
            delete_file_versions(key)
            print("\n\n")
        except botocore.exceptions.ClientError as e:
            # this error occurs when there is is no match, but also under
            #  ALL OTHER FAILURE MODES BECAUSE OF COURSE BOTO3 WORKS THAT WAY.
            assert "or did not validate against our published schema" in str(e)


def delete_file_versions(key: str):
    accumulator = 0
    for page, file_list in enumerate(paginate_versions(key)):
        accumulator += len(file_list)
        print((page, accumulator))
        objects = [{'Key': fp, "VersionId": version_id} for fp, version_id in file_list]
        
        delete_args = {
            "Bucket": "beiwe",
            "Delete": {
                'Objects': objects,
                'Quiet': False,
            },
        }
        pprint(delete_args)
        # conn.delete_objects(**delete_args)
