from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger

logger = Logger(child=True)

def get_kms_id_from_alias(kms_client, key_alias):
    """
    retrieve the ID of a KMS key given the name of the key alias.

    :param kms_client: a valid boto client for KMS
    :param key_alias: name of the KMS key alias to lookup
    """ 

    key_id = None

    try:
        response = kms_client.describe_key(
            KeyId='alias/' + key_alias
        )

        if response:
            key_id = response['KeyMetadata']['KeyId']
    except ClientError as ex:
        logger.critical("Unable to find KMS key by alias: {}".format(ex.response['Error']['Code']))

    return key_id
    