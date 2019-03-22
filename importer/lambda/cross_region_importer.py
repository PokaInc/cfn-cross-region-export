import json
import os
import uuid
from collections import namedtuple

import boto3
import requests
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from tenacity import retry, retry_if_exception_type, wait_random_exponential

RESOURCE_TYPE = 'Custom::CrossRegionImporter'
SUCCESS = "SUCCESS"
FAILED = "FAILED"
FAILED_PHYSICAL_RESOURCE_ID = "FAILED_PHYSICAL_RESOURCE_ID"

ImporterContext = namedtuple(
    'ImporterContext',
    [
        'stack_id',
        'logical_resource_id',
    ]
)


class TableInfo(object):
    def __init__(self, table_arn):
        self.table_name = table_arn.split('/')[1]
        self.target_region = table_arn.split(':')[3]


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
    print("Received event: " + json.dumps(event))

    resource_type = event['ResourceType']
    if resource_type != RESOURCE_TYPE:
        raise ValueError(f'Unexpected resource_type: {resource_type}. Use "{RESOURCE_TYPE}"')

    request_type = event['RequestType']
    physical_resource_id = None
    resource_properties = event['ResourceProperties']
    requested_exports = resource_properties.get('Exports', {})

    importer_context = ImporterContext(stack_id=event['StackId'], logical_resource_id=event['LogicalResourceId'])
    table_info = TableInfo(os.environ['CROSS_STACK_REF_TABLE_ARN'])

    response_data = {}

    if request_type in ['Create', 'Update']:
        physical_resource_id = str(uuid.uuid4())
        response_data = _create_new_cross_stack_references(
            requested_exports,
            importer_context,
            table_info,
            physical_resource_id
        )

    elif request_type == 'Delete':
        physical_resource_id = event['PhysicalResourceId']
        _delete_cross_stack_references(requested_exports, importer_context, table_info, physical_resource_id)

    else:
        print('Request type is {request_type}, doing nothing.'.format(request_type=request_type))

    send(
        event,
        context,
        response_status=SUCCESS,
        response_data=response_data,
        physical_resource_id=physical_resource_id,
    )


def _create_new_cross_stack_references(requested_exports, importer_context, table_info, physical_resource_id):
    exports = _get_cloudformation_exports(table_info.target_region)

    try:
        response_data = {
            label: exports[export_name]['Value'] for label, export_name in requested_exports.items()
        }
    except KeyError as e:
        raise ExportNotFoundError(e.args[0])

    dynamodb_resource = boto3.resource('dynamodb', region_name=table_info.target_region)
    cross_stack_ref_table = dynamodb_resource.Table(table_info.table_name)

    for label, export_name in requested_exports.items():
        cross_stack_ref_id = f'{physical_resource_id}|{export_name}'
        print(f'Adding cross-stack ref: {cross_stack_ref_id}')
        cross_stack_ref_table.put_item(
            Item={
                'CrossStackRefId': cross_stack_ref_id,
                'ImporterStackId': importer_context.stack_id,
                'ImporterLogicalResourceId': importer_context.logical_resource_id,
                'ImporterLabel': label,
                'ExporterStackId': exports[export_name]['ExportingStackId'],
                'ExportName': export_name,
            }
        )

    return response_data


def _delete_cross_stack_references(exports_to_remove, importer_context, table_info, physical_resource_id):
    dynamodb_resource = boto3.resource('dynamodb', region_name=table_info.target_region)
    cross_stack_ref_table = dynamodb_resource.Table(table_info.table_name)

    for label, export_name in exports_to_remove.items():
        cross_stack_ref_id = f'{physical_resource_id}|{export_name}'
        print(f'Removing cross-stack ref: {cross_stack_ref_id}')
        try:
            cross_stack_ref_table.delete_item(
                Key={'CrossStackRefId': cross_stack_ref_id},
                ConditionExpression=Attr('CrossStackRefId').eq(cross_stack_ref_id),
            )
        except ClientError as e:
            if 'The conditional request failed' in str(e):
                print(f'{cross_stack_ref_id} was not found, scanning to get the key name')
                scan_response = cross_stack_ref_table.scan(
                    FilterExpression=
                    Key('ExportName').eq(export_name) &
                    Key('ImporterStackId').eq(importer_context.stack_id) &
                    Key('ImporterLabel').eq(label) &
                    Key('ImporterLogicalResourceId').eq(importer_context.logical_resource_id)
                )
                cross_stack_ref_ids = [
                    cross_ref_id['CrossStackRefId'] for cross_ref_id in scan_response['Items']
                    if cross_ref_id != cross_stack_ref_id
                ]

                while scan_response.get('LastEvaluatedKey'):  # This loop manage pagination of results
                    scan_response = cross_stack_ref_table.scan(ExclusiveStartKey=scan_response['LastEvaluatedKey'])
                    cross_stack_ref_ids.extend([cross_ref_id['CrossStackRefId'] for cross_ref_id in scan_response['Items']])

                for ref_id in cross_stack_ref_ids:
                    print(f'Deleting {ref_id}')
                    cross_stack_ref_table.delete_item(
                        Key={'CrossStackRefId': ref_id},
                        ConditionExpression=Attr('CrossStackRefId').eq(ref_id),
                    )
            else:
                raise


@retry(
    wait=wait_random_exponential(multiplier=1, max=30),
    retry=retry_if_exception_type(ClientError),
)
def _get_cloudformation_exports(target_region):
    cloudformation_client = boto3.client('cloudformation', region_name=target_region)
    paginator = cloudformation_client.get_paginator('list_exports')
    exports_page_iterator = paginator.paginate()
    exports = {
        export['Name']: {
            'Value': export['Value'],
            'ExportingStackId': export['ExportingStackId'],
        } for page in exports_page_iterator for export in page['Exports']
    }
    return exports


class ExportNotFoundError(Exception):
    def __init__(self, name):
        super(ExportNotFoundError, self).__init__(
            'Export: {name} not found in exports'.format(name=name))


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
    print("Response data: " + json_response_body)

    headers = {
        'content-type': '',
        'content-length': str(len(json_response_body))
    }

    requests.put(
        response_url,
        data=json_response_body,
        headers=headers
    )
