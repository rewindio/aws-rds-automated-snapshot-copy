from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger

logger = Logger(child=True)

def get_snapshot_type(event):
    """
    Returns whether a snapshot is manual or automated.

    :param event: the raw cloudwatch event
    """ 

    if 'manual' in event['detail']['Message'].lower():
        return 'manual'

    return 'automated'

def is_snapshot_from_cluster(source_snapshot_arn):
    """
    Returns whether a snapshot was generated from a cluster (Aurora)
    or a "regular" RDS databases

    :param source_snapshot_arn: arn of the snapshot
    """ 

    if 'cluster' in source_snapshot_arn:
        return True

    return False

def get_db_for_snapshot(rds_client, snapshot_id, is_cluster):
    """
    Returns the RDS database name a given snapshot was taken from
    

    :param rds_client: a valid boto RDS client
    :param snapshot_id: The ID of the snapshot
    :param is_cluster: Boolean, whether the snapshot was from a cluster (Aurora)
    """ 

    db_name = None
    logger.debug("Getting db name for snapshot {}".format(snapshot_id))

    try:
        if is_cluster:
            response = rds_client.describe_db_cluster_snapshots(
                DBClusterSnapshotIdentifier=snapshot_id
            )

            if response and 'KmsKeyId' in response['DBClusterSnapshots'][0]:
                db_name = response['DBClusterSnapshots'][0]['DBClusterIdentifier']
        else:
            response = rds_client.describe_db_snapshots(
                DBSnapshotIdentifier=snapshot_id
            )

            if response:
                db_name = response['DBSnapshots'][0]['DBInstanceIdentifier']

    except ClientError as ex:
        logger.critical("Unable to describe snapshot : {}".format(ex.response['Error']['Code']))

    return db_name


def is_snapshot_encrypted(rds_client, snapshot_id, is_cluster):
    """
    Determine whether a snapshot is encrypted with KMS

    :param rds_client: a valid boto RDS client
    :param snapshotID: The ID of the snapshot
    :param is_cluster: Boolean, whether the snapshot was from a cluster (Aurora)
    """ 

    encrypted = False
    logger.debug("Checking if snapshot {} is encrypted".format(snapshot_id))

    try:
        if is_cluster:
            response = rds_client.describe_db_cluster_snapshots(
                DBClusterSnapshotIdentifier=snapshot_id
            )

            if response and 'KmsKeyId' in response['DBClusterSnapshots'][0]:
                encrypted = True
        else:
            response = rds_client.describe_db_snapshots(
                DBSnapshotIdentifier=snapshot_id
            )

            if response:
                encrypted = response['DBSnapshots'][0]['Encrypted']

    except ClientError as ex:
        logger.critical("Unable to describe snapshot : {}".format(ex.response['Error']['Code']))

    return encrypted

def copy_snapshot(rds_client, source_region, source_arn, dest_snapshot_id, kms_key_id, is_cluster):
    """
    Copies a given snapshot to a destination region

    :param rds_client: a valid boto RDS client
    :param source_region: The ID of the snapshot
    :param source_arn: arn of the source snapshot to copy
    :param dest_snapshot_id: The ID (name) of the snapshot at the destination (must be unique)
    :param kms_key_id: Optional KMS key ID to encrypt the destination snapshot with
    :param is_cluster: Boolean, whether the snapshot was from a cluster (Aurora)
    """ 

    status = False
    copy_args = {}

    logger.info("Copying snapshot {} to {}".format(source_arn,dest_snapshot_id))

    try:
        copy_args['SourceRegion'] = source_region
        copy_args['CopyTags'] = True

        if kms_key_id:
            copy_args['KmsKeyId'] = kms_key_id

        if is_cluster:
            copy_args['SourceDBClusterSnapshotIdentifier'] = source_arn
            copy_args['TargetDBClusterSnapshotIdentifier'] = dest_snapshot_id

            response = rds_client.copy_db_cluster_snapshot(**copy_args)
        else:
            copy_args['SourceDBSnapshotIdentifier'] = source_arn
            copy_args['TargetDBSnapshotIdentifier'] = dest_snapshot_id
        
            response = rds_client.copy_db_snapshot(**copy_args)

        logger.info("Snapshot copy initated")
        status = True
    except ClientError as ex:
        if ex.response['Error']['Code'] == 'DBSnapshotAlreadyExists':
            logger.info("Snapshot {} already exists".format(dest_snapshot_id))
        else:
            logger.critical("Unable to copy snapshot: {} ()".format(ex.response['Error']['Code'], ex.response['Error']['Message']))

    return status

def prune_snapshots(rds_client, db_name, num_snapshots_to_keep, is_cluster):
    """
    Prunes (removes) older snapshots from a region

    :param rds_client: a valid boto RDS client
    :param db_name: Name of the RDS database to prune snapshots for
    :param num_snapshots_to_keep: Number of snapshots to keep (any existing over this will be deleted)
    :param dest_snapshot_id: The ID (name) of the snapshot at the destination (must be unique)
    :param is_cluster: Boolean, whether the snapshot was from a cluster (Aurora)
    """ 

    status = True
    snapshot_list_key = None
    snapshot_id_key = None
    logger.debug("Pruning old snapshots")

    # List snapshots for the DB
    try:
        if is_cluster:
            snapshot_list_key = 'DBClusterSnapshots'
            snapshot_id_key = 'DBClusterSnapshotIdentifier'

            response = rds_client.describe_db_cluster_snapshots(
                DBClusterIdentifier = db_name
            )
        else:
            snapshot_list_key = 'DBSnapshots'
            snapshot_id_key = 'DBSnapshotIdentifier'

            response = rds_client.describe_db_snapshots(
                DBInstanceIdentifier = db_name
            )
    except ClientError as ex:
        logger.critical("Unable to describe snapshots : {}".format(ex.response['Error']['Code']))
        status = False

    if response and snapshot_list_key in response:
        snapshot_list = response[snapshot_list_key]

        # Any snapshots in progress will not yet have a create time so exclude them from pruning
        for idx, snapshot in enumerate(snapshot_list):
            if 'SnapshotCreateTime' not in snapshot:
                logger.info("Snapshot {} has no create time - will not consider for pruning".format(snapshot[snapshot_id_key]))
                del snapshot_list[idx]

        snapshot_list.sort(key=lambda x: x['SnapshotCreateTime'], reverse=True)

    # Only purge any snapshots outside our max number to keep
    for i in range(num_snapshots_to_keep,len(snapshot_list)):
        current_snapshot = snapshot_list[i]
        logger.info("Purging {} from {}".format(current_snapshot[snapshot_id_key], rds_client.meta.region_name))

        try:
            if is_cluster:
                 response = rds_client.delete_db_cluster_snapshot(
                    DBClusterSnapshotIdentifier = current_snapshot[snapshot_id_key]
                )
            else:
                response = rds_client.delete_db_snapshot(
                    DBSnapshotIdentifier = current_snapshot[snapshot_id_key]
                )
        except ClientError as ex:
            logger.critical("Unable to delete snapshot {} : {}".format(current_snapshot[snapshot_id_key], ex.response['Error']['Code']))
            status = False

    return status
