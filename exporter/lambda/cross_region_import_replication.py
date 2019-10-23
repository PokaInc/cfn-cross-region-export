import hashlib
import json
import os
from uuid import uuid4

import boto3
import botocore
from raven import Client
from raven.transport import HTTPTransport

MAX_RESOURCES_PER_TEMPLATE = 200
RESSOURCE_BY_GROUP = 5


def lambda_handler(*_):
    try:
        _lambda_handler()
    except:
        # Using a the default transport does not work in a Lambda function.
        # Must use the HTTPTransport.
        Client(
            dsn=os.environ['SENTRY_DSN'],
            environment=os.environ['SENTRY_ENVIRONMENT'],
            transport=HTTPTransport
        ).captureException()
        # Must raise, otherwise the Lambda will be marked as successful, and the exception
        # will not be logged to CloudWatch logs.
        raise


def _lambda_handler():
    dynamodb_resource = boto3.resource('dynamodb')
    cross_stack_ref_table = dynamodb_resource.Table(os.environ['CROSS_STACK_REF_TABLE_NAME'])

    scan_response = cross_stack_ref_table.scan()
    cross_stack_references = scan_response['Items']

    while scan_response.get('LastEvaluatedKey'):
        scan_response = cross_stack_ref_table.scan(ExclusiveStartKey=scan_response['LastEvaluatedKey'])
        cross_stack_references.extend(scan_response['Items'])

    if cross_stack_references:
        number_of_chunk = len(cross_stack_references) / MAX_RESOURCES_PER_TEMPLATE
        max_group_size = int(max(min(RESSOURCE_BY_GROUP/number_of_chunk, RESSOURCE_BY_GROUP), 1))

        nested_template_urls = []
        for items in _chunks(cross_stack_references, MAX_RESOURCES_PER_TEMPLATE):
            nested_template_urls.append(_generate_nested_template(items, max_group_size))

        master_template_resources = {}
        for i, url in enumerate(nested_template_urls):
            master_template_resources[f"ParameterChunk{i}"] = {
                "Type": "AWS::CloudFormation::Stack",
                "Properties": {
                    "TemplateURL": url
                }
            }
    else:
        master_template_resources = {
            'PlaceHolderParameter': {
                'Type': 'AWS::SSM::Parameter',
                'Properties': {
                    'Value': {'Ref': "AWS::StackName"},
                    'Type': 'String'
                },
            }
        }

    master_template = {
        'AWSTemplateFormatVersion': '2010-09-09',
        'Description': 'Auto-generated templates to simulate the standard importation behaviour on other regions',
        'Resources': master_template_resources
    }

    cloudformation_client = boto3.client('cloudformation')

    _upload_template(os.environ['GENERATED_STACK_NAME'], json.dumps(master_template))
    template_url = _build_unsigned_url(os.environ['GENERATED_STACK_NAME'])

    try:
        cloudformation_client.update_stack(
            StackName=os.environ['GENERATED_STACK_NAME'],
            TemplateURL=template_url,
        )
    except botocore.exceptions.ClientError as e:
        message = e.response['Error']['Message']
        if 'does not exist' in message:
            cloudformation_client.create_stack(
                StackName=os.environ['GENERATED_STACK_NAME'],
                TemplateURL=template_url,
            )
        elif 'No updates are to be performed.' in message:
            print('No updates are to be performed.')
        else:
            raise


def _generate_hash(string_to_hash):
    return hashlib.sha224(string_to_hash.encode()).hexdigest()


def _upload_template(template_name, template_content):
    s3_resource = boto3.resource('s3')
    template_object = s3_resource.Object(os.environ['TEMPLATE_BUCKET'], template_name)
    template_object.put(Body=template_content.encode())


def _build_unsigned_url(template_name):
    s3_resource = boto3.resource('s3')
    template_object = s3_resource.Object(
        os.environ['TEMPLATE_BUCKET'],
        template_name
    )

    return '{host}/{bucket}/{key}'.format(
        host=template_object.meta.client.meta.endpoint_url,
        bucket=template_object.bucket_name,
        key=template_object.key,
    )


def _generate_nested_template(cross_stack_references, max_group_size):
    last_ref_id = None
    ssm_resources = {}
    resource_count = 0

    for ref in cross_stack_references:
        ref_id = _generate_hash(ref['CrossStackRefId'])
        ssm_resource = {
            'Type': 'AWS::SSM::Parameter',
            'Properties': {
                'Name': {'Fn::Sub': "${AWS::StackName}." + ref_id},
                'Description': f'Imported by {ref["ImporterStackId"]}.{ref["ImporterLogicalResourceId"]}.{ref["ImporterLabel"]}',
                'Value': {'Fn::ImportValue': ref['ExportName']},
                'Type': 'String'
            },
        }

        if last_ref_id:
            ssm_resource['DependsOn'] = last_ref_id  # Required to prevent SSM throttling exceptions

        ssm_resources[ref_id] = ssm_resource

        if resource_count % max_group_size == 0:
            last_ref_id = ref_id

        resource_count += 1

    imports_replication_template = {
        'AWSTemplateFormatVersion': '2010-09-09',
        'Resources': ssm_resources
    }

    template_name = f'{os.environ["GENERATED_STACK_NAME"]}.{uuid4()}'

    _upload_template(template_name, json.dumps(imports_replication_template))
    return _build_unsigned_url(template_name)


def _chunks(l, n):
    for i in range(0, len(l), n):
        yield l[i:i + n]
