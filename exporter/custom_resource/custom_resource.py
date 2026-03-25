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
    exit()


def _format_value(event, properties_key="ResourceProperties"):
    table_arn = event[properties_key]["TableArn"]
    return f"{CURRENT_REGION}|{table_arn}"


def _get_values():
    response = ssm_client.get_parameter(Name=SSM_PARAMETER_NAME)
    return response["Parameter"]["Value"].split(",")


def _save_values(values):
    if values:
        ssm_client.put_parameter(
            Name=SSM_PARAMETER_NAME,
            Value=",".join(values),
            Type="String",
            Overwrite=True,
        )
    else:
        ssm_client.delete_parameter(Name=SSM_PARAMETER_NAME)


@helper.create
def create(event, context):
    formatted_value = _format_value(event)

    try:
        values = _get_values()
        values.append(formatted_value)
    except ssm_client.exceptions.ParameterNotFound:
        values = [formatted_value]
    except Exception as e:
        logger.error(f"Error fetching parameter: {e}")
        raise

    _save_values(values)


@helper.update
def update(event, context):
    formatted_value = _format_value(event)
    old_formatted_value = _format_value(event, "OldResourceProperties")

    if old_formatted_value == formatted_value:
        return

    try:
        values = _get_values()
        values.remove(old_formatted_value)
        values.append(formatted_value)
    except Exception as e:
        logger.error(f"Error while updating parameter: {e}")
        raise

    _save_values(values)


@helper.delete
def delete(event, context):
    formatted_value = _format_value(event)

    try:
        values = _get_values()
        values.remove(formatted_value)
    except ssm_client.exceptions.ParameterNotFound:
        return
    except ValueError:
        return
    except Exception as e:
        logger.error(f"Error fetching parameter: {e}")
        raise

    _save_values(values)
