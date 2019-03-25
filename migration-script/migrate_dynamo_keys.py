import os

import boto3
import re

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

OLD_NAMING_REGEX = re.compile(r'^(.*)\|(.*)\|(.*)\|(.*)$')


def main():
    table_info = _extract_region_and_resource_name(os.environ['CROSS_STACK_REF_TABLE_ARN'])
    migrated = 0

    dynamodb_resource = boto3.resource('dynamodb', region_name=table_info['region'])
    cross_stack_ref_table = dynamodb_resource.Table(table_info['name'])

    scan_response = cross_stack_ref_table.scan()
    cross_stack_items = [cross_ref_id for cross_ref_id in scan_response['Items']]

    while scan_response.get('LastEvaluatedKey'):  # This loop manage pagination of results
        scan_response = cross_stack_ref_table.scan(ExclusiveStartKey=scan_response['LastEvaluatedKey'])
        cross_stack_items.extend([cross_ref_id['CrossStackRefId'] for cross_ref_id in scan_response['Items']])

    for item in cross_stack_items:
        match = OLD_NAMING_REGEX.match(item['CrossStackRefId'])
        if match:
            physical_resource_id = _get_physical_resource_id(match.group(2), match.group(3))
            export_name = match.group(1)
            new_name = f'{physical_resource_id}|{export_name}'
            old_name = item['CrossStackRefId']
            item['CrossStackRefId'] = new_name

            try:
                print(f'Creating new item : {new_name} ')
                cross_stack_ref_table.put_item(
                    Item=item,
                    ConditionExpression=Attr('CrossStackRefId').ne(new_name)
                )
            except ClientError as e:
                if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                    print(f'\033[1;31;40m{new_name} already exist, not updating it')
            else:
                print(f'Deleting old item : {old_name} ')
                cross_stack_ref_table.delete_item(
                    Key={'CrossStackRefId': old_name},
                    ConditionExpression=Attr('CrossStackRefId').eq(old_name)
                )
                migrated += 1
    print(f'\033[1;32;40mItem migrated : {migrated}')


def _get_physical_resource_id(arn, logical_id):
    stack_info = _extract_region_and_resource_name(arn)
    cf_resource = boto3.resource('cloudformation', region_name=stack_info['region'])
    return cf_resource.StackResource(stack_info['name'], logical_id).physical_resource_id


def _extract_region_and_resource_name(arn):
    resource_name = arn.split('/')[1]
    resource_region = arn.split(':')[3]
    return {'name': resource_name, 'region': resource_region}


if __name__ == '__main__':
    main()
