IMPORTER_STACK_NAME?=`echo $(CROSS_STACK_REF_TABLE_ARN) | awk -F':' '{print $$4"-CrossRegionImporter"}'`
IMPORTER_SOURCE_TEMPLATE_PATH = importer/cloudformation/cross-region-importer.yml
IMPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH = $(shell pwd)/dist/cross-region-importer.yml

EXPORTER_STACK_NAME=CrossRegionExporter
EXPORTER_SOURCE_TEMPLATE_PATH = exporter/cloudformation/cross-region-exporter.yml
EXPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH = $(shell pwd)/dist/cross-region-exporter.yml

BUCKET_NAME=cfn-cross-region-export-`aws sts get-caller-identity --output text --query 'Account'`-$${AWS_DEFAULT_REGION:-`aws configure get region`}

# Check if variable has been defined, otherwise print custom error message
check_defined = \
	$(strip $(foreach 1,$1, \
		$(call __check_defined,$1,$(strip $(value 2)))))
__check_defined = \
	$(if $(value $1),, \
		$(error Undefined $1$(if $2, ($2))))

check-bucket:
	@aws s3api head-bucket --bucket $(BUCKET_NAME) &> /dev/null || aws s3 mb s3://$(BUCKET_NAME)

package-importer: check-bucket
	@./package_lambda.sh importer/lambda cross_region_importer
	@aws cloudformation package --template-file $(IMPORTER_SOURCE_TEMPLATE_PATH) --s3-bucket $(BUCKET_NAME) --s3-prefix cloudformation/$(IMPORTER_SOURCE_TEMPLATE_PATH).yml --output-template-file $(IMPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH)

deploy-importer: package-importer
	$(call check_defined, CROSS_STACK_REF_TABLE_ARN, Ex: make generate-changelog CROSS_STACK_REF_TABLE_ARN=arn:aws:dynamodb:region:accountid:table/tablename)
	aws cloudformation deploy --template-file $(IMPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH) --stack-name $(IMPORTER_STACK_NAME) --capabilities CAPABILITY_IAM --parameter-overrides CrossStackRefTableArn=$(CROSS_STACK_REF_TABLE_ARN)


package-exporter: check-bucket
	@./package_lambda.sh exporter/lambda cross_region_import_replication
	@aws cloudformation package --template-file $(EXPORTER_SOURCE_TEMPLATE_PATH) --s3-bucket $(BUCKET_NAME) --s3-prefix cloudformation/$(EXPORTER_SOURCE_TEMPLATE_PATH).yml --output-template-file $(EXPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH)

deploy-exporter: package-exporter
	$(call check_defined, SENTRY_DSN, Ex: make deploy-exporter SENTRY_DSN=https://...@sentry.io/...)
	$(call check_defined, SENTRY_ENV, Ex: make deploy-exporter SENTRY_ENV=dev)
	aws cloudformation deploy --template-file $(EXPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH) --stack-name $(EXPORTER_STACK_NAME) --capabilities CAPABILITY_IAM --parameter-overrides SentryDsn=$(SENTRY_DSN) SentryEnvironment=$(SENTRY_ENV)
