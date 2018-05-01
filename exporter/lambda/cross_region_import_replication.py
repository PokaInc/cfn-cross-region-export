import hashlib
import json
import os

import boto3
import botocore
from raven import Client
from raven.transport import HTTPTransport


def lambda_handler(*_):
    try:
        _lambda_handler()
    except:
        # Using a the default transport does not work in a Lambda function.
        # Must use the HTTPTransport.
        Client(dsn=os.environ['SENTRY_DSN'], transport=HTTPTransport).captureException()
        # Must raise, otherwise the Lambda will be marked as successful, and the exception
        # will not be logged to CloudWatch logs.
        raise


def _lambda_handler():
    dynamodb_resource = boto3.resource('dynamodb')
    cross_stack_ref_table = dynamodb_resource.Table(os.environ['CROSS_STACK_REF_TABLE_NAME'])
    cross_stack_references = cross_stack_ref_table.scan()['Items']

    outputs = {
        _generate_hash(c['CrossStackRefId']): {
            'Description': f'Imported by {c["ImporterStackId"]}.{c["ImporterLogicalResourceId"]}',
            'Value': {'Fn::ImportValue': c['ExportName']},
        } for c in cross_stack_references
    }

    stack_outputs_digest = _generate_hash(json.dumps(outputs, sort_keys=True))

    imports_replication_template = {
        'AWSTemplateFormatVersion': '2010-09-09',
        'Description': 'Auto-generated Template to simulate the standard importation behaviour on other regions',
        'Resources': {
            'OutputsDigestParameter': {
                'Type': 'AWS::SSM::Parameter',
                'Properties': {
                    'Name': os.environ['STACK_OUTPUTS_DIGEST_SSM_PARAMETER_NAME'],
                    'Type': 'String',
                    'Value': str(stack_outputs_digest)
                }
            }
        },
        'Outputs': outputs
    }

    cloudformation_client = boto3.client('cloudformation')

    try:
        cloudformation_client.update_stack(
            StackName=os.environ['GENERATED_STACK_NAME'],
            TemplateBody=json.dumps(imports_replication_template),
        )
    except botocore.exceptions.ClientError as e:
        message = e.response['Error']['Message']
        if 'does not exist' in message:
            cloudformation_client.create_stack(
                StackName=os.environ['GENERATED_STACK_NAME'],
                TemplateBody=json.dumps(imports_replication_template),
            )
        elif 'No updates are to be performed.' in message:
            print('No updates are to be performed.')
        else:
            raise


def _generate_hash(string_to_hash):
    return hashlib.sha224(string_to_hash.encode()).hexdigest()
