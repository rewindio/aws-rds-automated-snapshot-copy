from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger

logger = Logger(child=True)

def get_snapshot_type(event):
    if 'manual' in event['detail']['Message'].lower():
        return 'manual'

    return 'automated'

def is_snapshot_from_cluster(sourceSnapshotARN):
    if 'cluster' in sourceSnapshotARN:
        return True

    return False

def is_snapshot_encrypted(rds_client, snapshotID, is_cluster):
    encrypted = False
    logger.debug("Checking if snapshot {} is encrypted".format(snapshotID))

    try:
        if is_cluster:
            response = rds_client.describe_db_cluster_snapshots(
                DBClusterSnapshotIdentifier=snapshotID
            )

            if response and 'KmsKeyId' in response['DBClusterSnapshots'][0]:
                encrypted = True
        else:
            response = rds_client.describe_db_snapshots(
                DBSnapshotIdentifier=snapshotID
            )

            if response:
                encrypted = response['DBSnapshots'][0]['Encrypted']

    except ClientError as ex:
        logger.critical("Unable to describe snapshot : {}".format(ex.response['Error']['Code']))

    return encrypted

def copy_snapshot(rds_client, source_region, source_arn, dest_snapshot_id, kms_key_id, is_cluster):
    status = False
    copy_args = {}

    logger.info("Copying snapshot {} to {}".format(source_arn,dest_snapshot_id))

    try:
        copy_args['SourceDBSnapshotIdentifier'] = source_arn
        copy_args['TargetDBSnapshotIdentifier'] = dest_snapshot_id
        copy_args['SourceRegion'] = source_region

        if kms_key_id:
            copy_args['KmsKeyId'] = kms_key_id

        response = rds_client.copy_db_snapshot(**copy_args)

        logger.info("Snapshot copy initated")
        status = True
    except ClientError as ex:
        if ex.response['Error']['Code'] == 'DBSnapshotAlreadyExists':
            logger.info("Snapshot {} already exists".format(dest_snapshot_id))
        else:
            logger.critical("Unable to copy snapshot: {}".format(ex.response['Error']['Code']))

    return status

def prune_snapshots():
    logger.info("Pruning old snapshots")
