-include .env

IMPORTER_DIR=importer
IMPORTER_STACK_NAME?=`echo $(CROSS_STACK_REF_TABLE_ARN) | awk -F':' '{print $$4"-CrossRegionImporter"}'`
IMPORTER_SOURCE_TEMPLATE_PATH = $(IMPORTER_DIR)/cloudformation/cross-region-importer.yml
IMPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH = $(shell pwd)/dist/cross-region-importer.yml

EXPORTER_DIR=exporter
EXPORTER_STACK_NAME=CrossRegionExporter
EXPORTER_SOURCE_TEMPLATE_PATH = $(EXPORTER_DIR)/cloudformation/cross-region-exporter.yml
EXPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH = $(shell pwd)/dist/cross-region-exporter.yml

BUCKET_NAME=cfn-cross-region-export-`aws sts get-caller-identity --output text --query 'Account'`-$${AWS_DEFAULT_REGION:-`aws configure get region`}
VERSION = $(shell git describe --always --tags)
ALL_CATEGORIES = $(shell grep -E '^\[' Pipfile | grep -v '^\[\[' | grep -v -E '\[requires\]' | sed 's/\[//g' | sed 's/\]//g' | tr '\n' ' ')

# Check if variable has been defined, otherwise print custom error message
check_defined = \
	$(strip $(foreach 1,$1, \
		$(call __check_defined,$1,$(strip $(value 2)))))
__check_defined = \
	$(if $(value $1),, \
		$(error Undefined $1$(if $2, ($2))))

install:
	@pipenv install --categories "$(ALL_CATEGORIES)"

check-bucket:
	@aws s3api head-bucket --bucket $(BUCKET_NAME) &> /dev/null || aws s3 mb s3://$(BUCKET_NAME)

package-importer: check-bucket
	@./package_lambda.sh $(IMPORTER_DIR)/lambda cross_region_importer
	@sam package --template-file $(IMPORTER_SOURCE_TEMPLATE_PATH) --s3-bucket $(BUCKET_NAME) --s3-prefix cloudformation/$(IMPORTER_SOURCE_TEMPLATE_PATH).yml --output-template-file $(IMPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH)

deploy-importer: package-importer
	@./scripts/deploy_importer.sh

package-exporter: check-bucket
	@./package_lambda.sh exporter/lambda cross_region_import_replication
	@./package_lambda.sh exporter/custom_resource set_parameter
	@sam package --template-file $(EXPORTER_SOURCE_TEMPLATE_PATH) --s3-bucket $(BUCKET_NAME) --s3-prefix cloudformation/$(EXPORTER_SOURCE_TEMPLATE_PATH).yml --output-template-file $(EXPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH)

deploy-exporter: package-exporter
	$(call check_defined, SENTRY_DSN, Ex: make deploy-exporter SENTRY_DSN=https://...@sentry.io/... or set it in .env)
	$(call check_defined, SENTRY_ENV, Ex: make deploy-exporter SENTRY_ENV=dev or set it in .env)
	@sam deploy --template-file $(EXPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH) --stack-name $(EXPORTER_STACK_NAME) --capabilities CAPABILITY_IAM --parameter-overrides SentryDsn=$(SENTRY_DSN) SentryEnvironment=$(SENTRY_ENV) Version=$(VERSION)

check-deployed-version:
	@aws ssm get-parameters-by-path --path "/project-versions/cfn-cross-region-export/" --query "Parameters[*].[Name,Value]"

lock-requirements: requirements-custom-resource requirements-lambda

requirements-lambda:
	@pipenv requirements --categories packages > $(EXPORTER_DIR)/lambda/requirements.txt
	@pipenv requirements --categories packages > $(IMPORTER_DIR)/lambda/requirements.txt

requirements-custom-resource:
	@pipenv requirements --categories custom-resource > $(EXPORTER_DIR)/custom_resource/requirements.txt
