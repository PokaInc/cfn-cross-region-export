import os

import boto3
import re

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

OLD_NAMING_REGEX = re.compile(r'^(.*)\|(.*)\|(.*)\|(.*)$')


class TableInfo(object):
    def __init__(self, table_arn):
        self.table_name = table_arn.split('/')[1]
        self.target_region = table_arn.split(':')[3]


def _get_physical_resource_id(arn, logical_id):
    stack_name = arn.split('/')[1]
    stack_region = arn.split(':')[3]
    cf_resource = boto3.resource('cloudformation', region_name=stack_region)
    stack_resource = cf_resource.StackResource(stack_name, logical_id)
    return stack_resource.physical_resource_id


if __name__ == '__main__':
    table_info = TableInfo(os.environ['CROSS_STACK_REF_TABLE_ARN'])
    created = 0
    deleted = 0

    dynamodb_resource = boto3.resource('dynamodb', region_name=table_info.target_region)
    cross_stack_ref_table = dynamodb_resource.Table(table_info.table_name)

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
                created += 1
            except ClientError as e:
                if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                    print(f'\033[1;31;40m{new_name} already exist, not updating it')
            else:
                try:
                    print(f'Deleting old item : {old_name} ')
                    cross_stack_ref_table.delete_item(
                        Key={'CrossStackRefId': old_name},
                        ConditionExpression=Attr('CrossStackRefId').eq(old_name)
                    )
                    deleted += 1
                except ClientError as e:
                    if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                        print(f'\033[1;31;40m{old_name} does not exist, cannot delete it')
    print(f'\033[1;32;40mItem created : {created}\nItem deleted : {deleted}')
