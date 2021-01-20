import hashlib
import json
import os
from uuid import uuid4

import boto3
import botocore
import sentry_sdk
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration

sentry_sdk.init(integrations=[AwsLambdaIntegration(timeout_warning=True)])

MAX_OUTPUTS_PER_TEMPLATE = 200


def lambda_handler(*_):
    try:
        _lambda_handler()
    except:
        raise


def _lambda_handler():
    dynamodb_resource = boto3.resource("dynamodb")
    cross_stack_ref_table = dynamodb_resource.Table(os.environ["CROSS_STACK_REF_TABLE_NAME"])

    scan_response = cross_stack_ref_table.scan()
    cross_stack_references = scan_response["Items"]

    while scan_response.get("LastEvaluatedKey"):
        scan_response = cross_stack_ref_table.scan(ExclusiveStartKey=scan_response["LastEvaluatedKey"])
        cross_stack_references.extend(scan_response["Items"])

    if cross_stack_references:
        nested_template_urls = []
        for items in _chunks(cross_stack_references, MAX_OUTPUTS_PER_TEMPLATE):
            nested_template_urls.append(_generate_nested_template(items))

        master_template_resources = {}
        for i, url in enumerate(nested_template_urls):
            master_template_resources[f"Chunk{i}"] = {"Type": "AWS::CloudFormation::Stack", "Properties": {"TemplateURL": url}}
    else:
        master_template_resources = {
            "PlaceHolderResource": {
                "Type": "AWS::CloudFormation::WaitConditionHandle",
                "Properties": {},
            }
        }

    master_template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Auto-generated templates to simulate the standard importation behaviour on other regions",
        "Resources": master_template_resources,
    }

    cloudformation_client = boto3.client("cloudformation")

    _upload_template(os.environ["GENERATED_STACK_NAME"], json.dumps(master_template))
    template_url = _build_unsigned_url(os.environ["GENERATED_STACK_NAME"])

    try:
        cloudformation_client.update_stack(
            StackName=os.environ["GENERATED_STACK_NAME"],
            TemplateURL=template_url,
        )
    except botocore.exceptions.ClientError as e:
        message = e.response["Error"]["Message"]
        if "does not exist" in message:
            cloudformation_client.create_stack(
                StackName=os.environ["GENERATED_STACK_NAME"],
                TemplateURL=template_url,
            )
        elif "No updates are to be performed." in message:
            print("No updates are to be performed.")
        else:
            raise


def _generate_hash(string_to_hash):
    return hashlib.sha224(string_to_hash.encode()).hexdigest()


def _upload_template(template_name, template_content):
    s3_resource = boto3.resource("s3")
    template_object = s3_resource.Object(os.environ["TEMPLATE_BUCKET"], template_name)
    template_object.put(Body=template_content.encode())


def _build_unsigned_url(template_name):
    s3_resource = boto3.resource("s3")
    template_object = s3_resource.Object(os.environ["TEMPLATE_BUCKET"], template_name)

    return "{host}/{bucket}/{key}".format(
        host=template_object.meta.client.meta.endpoint_url,
        bucket=template_object.bucket_name,
        key=template_object.key,
    )


def _generate_nested_template(cross_stack_references):
    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": {
            "PlaceHolderResource": {"Type": "AWS::CloudFormation::WaitConditionHandle", "Properties": {}},
        },
        "Outputs": {},
    }

    for ref in cross_stack_references:
        ref_id = _generate_hash(ref["CrossStackRefId"])
        output = {
            "Value": {"Fn::ImportValue": ref["ExportName"]},
            "Description": f'Imported by {ref["ImporterStackId"]}.{ref["ImporterLogicalResourceId"]}.{ref["ImporterLabel"]}',
        }

        template["Outputs"][ref_id] = output

    template_name = f'{os.environ["GENERATED_STACK_NAME"]}.{uuid4()}'

    _upload_template(template_name, json.dumps(template))
    return _build_unsigned_url(template_name)


def _chunks(l, n):
    for i in range(0, len(l), n):
        yield l[i : i + n]
