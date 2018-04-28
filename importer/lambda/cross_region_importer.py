import json
import os
import uuid
from collections import namedtuple

import boto3
from botocore.vendored import requests
from cfn_get_export_value import get_export_value

RESOURCE_TYPE = 'Custom::CrossRegionImporter'
SUCCESS = "SUCCESS"
FAILED = "FAILED"
FAILED_PHYSICAL_RESOURCE_ID = "FAILED_PHYSICAL_RESOURCE_ID"

CrossStackReference = namedtuple(
    'CrossStackReference',
    [
        'cross_stack_ref_id',
        'importer_stack_id',
        'importer_logical_resource_id',
        'export_name',
        'export_value',
    ]
)


def lambda_handler(event, context):
    try:
        _lambda_handler(event, context)
    except Exception as e:
        send(
            event,
            context,
            response_status=FAILED if event['RequestType'] != 'Delete' else SUCCESS,
            # Do not fail on delete to avoid rollback failure
            response_data=None,
            physical_resource_id=event.get('PhysicalResourceId', FAILED_PHYSICAL_RESOURCE_ID),
            reason=str(e)
        )
        raise


def _lambda_handler(event, context):
    print("Received event: " + json.dumps(event, indent=2))

    resource_type = event['ResourceType']
    request_type = event['RequestType']
    stack_id = event['StackId']
    logical_resource_id = event['LogicalResourceId']
    physical_resource_id = event.get('PhysicalResourceId', str(uuid.uuid4()))
    resource_properties = event['ResourceProperties']
    export_names = resource_properties['ExportNames'].split(',')

    table_arn = os.environ['CROSS_STACK_REF_TABLE_ARN']
    target_region_name = table_arn.split(':')[3]
    table_name = table_arn.split('/')[1]
    target_region_boto3_session = boto3.Session(region_name=target_region_name)

    response_data = {}

    if resource_type != RESOURCE_TYPE:
        raise ValueError(f'Unexpected resource_type: {resource_type}. Use "{RESOURCE_TYPE}"')

    if request_type == 'Create':
        cross_stack_references = []
        for export_name in export_names:
            export_value = get_export_value(export_name, session=target_region_boto3_session)
            cross_stack_references.append(CrossStackReference(
                cross_stack_ref_id=f'{export_name}|{stack_id}|{logical_resource_id}',
                importer_stack_id=stack_id,
                importer_logical_resource_id=logical_resource_id,
                export_name=export_name,
                export_value=export_value,
            ))
            response_data[export_name] = export_value

        for cross_stack_reference in cross_stack_references:
            dynamodb_resource = target_region_boto3_session.resource('dynamodb')
            cross_stack_ref_table = dynamodb_resource.Table(table_name)
            print(f'Adding cross-stack ref: {cross_stack_reference.cross_stack_ref_id}')
            cross_stack_ref_table.put_item(
                Item={
                    'CrossStackRefId': cross_stack_reference.cross_stack_ref_id,
                    'ImporterStackId': cross_stack_reference.importer_stack_id,
                    'ImporterLogicalResourceId': cross_stack_reference.importer_logical_resource_id,
                    'ExportName': cross_stack_reference.export_name,
                    'ExportValue': cross_stack_reference.export_value,
                    'Replicated': False,
                }
            )

    elif request_type == 'Update':
        old_export_names = set(event['OldResourceProperties']['ExportNames'].split(','))
        current_export_names = set(export_names)

        export_names_to_remove = old_export_names - current_export_names
        export_names_to_add = current_export_names - old_export_names
        export_names_to_get = current_export_names & old_export_names

        cross_stack_references_to_add = []

        for export_name in export_names_to_add:
            export_value = get_export_value(export_name, session=target_region_boto3_session)
            cross_stack_references_to_add.append(CrossStackReference(
                cross_stack_ref_id=f'{export_name}|{stack_id}|{logical_resource_id}',
                importer_stack_id=stack_id,
                importer_logical_resource_id=logical_resource_id,
                export_name=export_name,
                export_value=export_value,
            ))
            response_data[export_name] = export_value

        dynamodb_resource = target_region_boto3_session.resource('dynamodb')
        cross_stack_ref_table = dynamodb_resource.Table(table_name)

        for export_name in export_names_to_get:
            cross_stack_reference = cross_stack_ref_table.get_item(
                Key={'CrossStackRefId': f'{export_name}|{stack_id}|{logical_resource_id}'},
                ConsistentRead=True,
            )['Item']
            response_data[cross_stack_reference['ExportName']] = cross_stack_reference['ExportValue']

        for cross_stack_reference in cross_stack_references_to_add:
            print(f'Adding cross-stack ref: {cross_stack_reference.cross_stack_ref_id}')
            cross_stack_ref_table.put_item(
                Item={
                    'CrossStackRefId': cross_stack_reference.cross_stack_ref_id,
                    'ImporterStackId': cross_stack_reference.importer_stack_id,
                    'ImporterLogicalResourceId': cross_stack_reference.importer_logical_resource_id,
                    'ExportName': cross_stack_reference.export_name,
                    'ExportValue': cross_stack_reference.export_value,
                    'Replicated': False,
                }
            )

        for export_name in export_names_to_remove:
            cross_stack_ref_id = f'{export_name}|{stack_id}|{logical_resource_id}'
            print(f'Removing cross-stack ref: {cross_stack_ref_id}')
            cross_stack_ref_table.delete_item(
                Key={'CrossStackRefId': cross_stack_ref_id},
            )

    elif request_type == 'Delete':
        dynamodb_resource = target_region_boto3_session.resource('dynamodb')
        cross_stack_ref_table = dynamodb_resource.Table(table_name)

        for export_name in export_names:
            cross_stack_ref_id = f'{export_name}|{stack_id}|{logical_resource_id}'
            print(f'Removing cross-stack ref: {cross_stack_ref_id}')
            cross_stack_ref_table.delete_item(
                Key={'CrossStackRefId': cross_stack_ref_id},
            )

    else:
        print('Request type is {request_type}, doing nothing.'.format(request_type=request_type))

    send(
        event,
        context,
        response_status=SUCCESS,
        response_data=response_data,
        physical_resource_id=physical_resource_id,
    )


def send(event, context, response_status, response_data, physical_resource_id, reason=None):
    response_url = event['ResponseURL']

    response_body = {
        'Status': response_status,
        'Reason': str(reason) if reason else 'See the details in CloudWatch Log Stream: ' + context.log_stream_name,
        'PhysicalResourceId': physical_resource_id,
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'Data': response_data,
    }

    json_response_body = json.dumps(response_body)

    headers = {
        'content-type': '',
        'content-length': str(len(json_response_body))
    }

    requests.put(
        response_url,
        data=json_response_body,
        headers=headers
    )
