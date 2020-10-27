# aws-rds-automated-snapshot-copy

Automatically copies RDS snapshots to a backup region when a new snapshot is created.  Handles both Aurora clusters and _regular_ RDS databases

## Acknowledgements

This solutoon builds on the [outstanding idea](https://www.geektopia.tech/post.php?blogpost=Automating_The_Cross_Region_Copy_Of_RDS_Snapshots) from [Geektopia](https://www.geektopia.tech/) to subscribe to an Eventbridge event indicating a snapshot has been triggered.

## Installing

Everything is packaged with [aws sam](https://aws.amazon.com/serverless/sam/).  You'll want to install to each region where RDS databases are running and producing snapshots.  Clone this repo and run:

```bash
sam build --use-container

sam deploy --stack-name rds-snapshot-copy \
           --s3-bucket <an existing bucket to store lambda sam apps in> \
           --region us-east-1 \
           --profile staging \
           --capabilities CAPABILITY_NAMED_IAM \
           --no-fail-on-empty-changeset \
           --parameter-overrides "DestinationRegion=us-east-2 \
                                  DestinationKMSAlias=aws/rds \
                                  NumberOfSnapshotsToKeep=3 \
                                  CopyManualSnapshots=yes \
                                  LogLevel=INFO
                                  "
```

Repeat the `sam deploy` for each region.

## Configuration

There are only a small number of configuration parameters that can be passed to the application

- DestinationRegion : Snapshots will be replicated to this region
- NumberOfSnapshotsToKeep : N number of _automated_ snapshots that were replicated to the destination region will be kept. Any over N will be deleted
- DestinationKMSAlias - Should a snapshot be encrypted at the source, this is the alias of a KMS key in the destination to re-encrypt the snapshot with (default: aws/rds)
- CopyManualSnapshots - If set to _yes_, manually created snapshots as well as RDS automated snapshots are copied
- LogLevel - logging level to apply (default: INFO)

## Local Dev

To run locally, create an env-vars file and an event file (see samples in local-dev) and then invoke sam locally with

```bash
sam build --use-container && sam local invoke "SnapshotCopy" -e event.json --env-vars env-vars.json --profile staging --region us-east-1
```
