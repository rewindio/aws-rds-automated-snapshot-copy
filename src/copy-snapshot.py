import json
import boto3
from botocore.exceptions import ClientError
import os
import sys
from aws_lambda_powertools import Logger
from rds_snapshot_helpers import *
from kms_helpers import *

logger = Logger()

@logger.inject_lambda_context(log_event=True)
def lambda_handler(event, context):
    """
    Copies an RDS snapshot to an anternate region.
    Prunes older snapshots from the destination region
    """

    #Manual snapshot created\",
    if 'created' not in event['detail']['Message'].lower():
        logger.info("Received event for a snapshot but the snapshot is not yet finished being created")
        return 0

    is_cluster = False
    source_region = event['region']
    dest_region = os.environ['DESTINATION_REGION']
    snapshots_to_keep = os.environ['NUM_SNAPSHOTS_TO_KEEP']
    copy_manual_snapshots = os.environ['COPY_MANUAL_SNAPSHOTS'].lower()

    # Can be manual or automated
    snapshot_type = get_snapshot_type(event)
    
    logger.info("Snapshot type: {}".format(snapshot_type))

    if ( snapshot_type == 'manual' and copy_manual_snapshots == 'yes') or (snapshot_type == 'automated'):

        # Various clients.  Defined in the handler because the region is  passed in the event
        rds_source = boto3.client('rds',region_name=source_region)
        rds_dest = boto3.client('rds',region_name=dest_region)
        kms_dest = boto3.client('kms', region_name=dest_region)

        source_snapshot_arn = event['detail']['SourceArn']
        source_snapshot_id = source_snapshot_arn.split('snapshot:',1)[1]

        logger.info("Source Snapshot ID: {}".format(source_snapshot_id))

        # Was this snapshot generated from an RDS cluster?
        is_cluster = is_snapshot_from_cluster(source_snapshot_arn)

        dest_snapshot_name = source_snapshot_id.replace(":","-") + "-" + snapshot_type + "-CRR"

        kms_key_id = None
        
        # Is the snapshot encrypted? If so we need a KMS key ID in the dest region
        if is_snapshot_encrypted(rds_source, source_snapshot_id, is_cluster):
            dest_kms_alias = os.environ['DESTINATION_KMS_ALIAS']
            logger.info("The snapshot is encrypted - will use KMS key {} to encrypt".format(dest_kms_alias))

            kms_key_id = get_kms_id_from_alias(kms_dest, dest_kms_alias)

            if kms_key_id:
                logger.debug("Destination KMS ID: {}".format(kms_key_id))
            else:
                logger.critical("No KMS key with alias {} found in region {}".format(dest_kms_alias,dest_region))
                return 1
        else:
            logger.info("Snapshot is not encrypted")

        # Copy the snapshot
        if copy_snapshot(rds_dest, source_region, source_snapshot_arn, dest_snapshot_name, kms_key_id, is_cluster):
            logger.info("Snapshot copy successfully initated")
        else:
            logger.critical("Snapshot copy failed to initate")
            return 1

        # PRUNE
        # There is a hole here in that we don't block for the new snapshot to be replicated
        # so we will remove an older snapshot before the newer one has finished replicating
        # In our case, this is "good enough" as we will keep many snapshots
        db_name = get_db_for_snapshot(rds_source, source_snapshot_id, is_cluster)

        if db_name:
            logger.info("Keeping {} snapshots in {} for {}".format(snapshots_to_keep, dest_region, db_name))
            if prune_snapshots(rds_dest, db_name, int(snapshots_to_keep), is_cluster):
                logger.info("Snapshots pruned in region {} for DB {}".format(dest_region, db_name))
            else:
                logger.critical("Error pruning snapshots")
                return 1
        else:
            logger.critical("Unable to determine DB name for snapshot - cannot prune")
            return 1
    else:
        print("Snapshot is type " + snapshot_type + " and COPY_MANUAL_SNAPSHOTS is " + os.environ['COPY_MANUAL_SNAPSHOTS'] + ". Exiting.")

    return 0
