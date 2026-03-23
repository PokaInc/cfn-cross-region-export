from crhelper import CfnResource

helper = CfnResource(boto_level="WARNING")

try:
    import os
    import logging
    import boto3

    TARGET_REGION = "us-east-1"
    CURRENT_REGION = os.environ["AWS_REGION"]
    SSM_PARAMETER_NAME = "/cfn-cross-region-exporter/table-arns"

    logger = logging.getLogger()
    ssm_client = boto3.client("ssm", region_name=TARGET_REGION)

except Exception as e:
    helper.init_failure(e)


@helper.create
def create(event, context):
    resource_properties = event["ResourceProperties"]
    table_arn = resource_properties["TableArn"]
    formatted_value = f"{CURRENT_REGION}|{table_arn}"

    try:
        response = ssm_client.get_parameter(Name=SSM_PARAMETER_NAME)
        values = response["Parameter"]["Value"].split(",")
        values.append(formatted_value)
    except ssm_client.exceptions.ParameterNotFound:
        values = [formatted_value]
    except Exception as e:
        logger.error(f"Error fetching parameter: {e}")
        raise

    ssm_client.put_parameter(
        Name=SSM_PARAMETER_NAME,
        Value=",".join(values),
        Type="String",
        Overwrite=True,
    )


@helper.update
def update(event, context):
    resource_properties = event["ResourceProperties"]
    table_arn = resource_properties["TableArn"]
    formatted_value = f"{CURRENT_REGION}|{table_arn}"

    old_resource_properties = event["OldResourceProperties"]
    old_table_arn = old_resource_properties["TableArn"]
    old_formatted_value = f"{CURRENT_REGION}|{old_table_arn}"

    if old_formatted_value == formatted_value:
        return

    try:
        response = ssm_client.get_parameter(Name=SSM_PARAMETER_NAME)
        values = response["Parameter"]["Value"].split(",")
        values.remove(old_formatted_value)
        values.append(formatted_value)
    except Exception as e:
        logger.error(f"Error while updating parameter: {e}")
        raise

    ssm_client.put_parameter(
        Name=SSM_PARAMETER_NAME,
        Value=",".join(values),
        Type="String",
        Overwrite=True,
    )


@helper.delete
def delete(event, context):
    resource_properties = event["ResourceProperties"]
    table_arn = resource_properties["TableArn"]
    formatted_value = f"{CURRENT_REGION}|{table_arn}"

    try:
        response = ssm_client.get_parameter(Name=SSM_PARAMETER_NAME)
        values = response["Parameter"]["Value"].split(",")
        values.remove(formatted_value)
    except ssm_client.exceptions.ParameterNotFound:
        return
    except ValueError:
        return
    except Exception as e:
        logger.error(f"Error fetching parameter: {e}")
        raise

    if len(values) != 0:
        ssm_client.put_parameter(
            Name=SSM_PARAMETER_NAME,
            Value=",".join(values),
            Type="String",
            Overwrite=True,
        )
    else:
        ssm_client.delete_parameter(Name=SSM_PARAMETER_NAME)
