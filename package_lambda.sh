#!/bin/bash

set -e

if [ $# -ne 2 ]
  then
    echo "Invalid number of arguments. Usage: package_lambda.sh <path_to_lambda_dir> <package_name>"
    exit 1
fi

LAMBDA_DIR=$1
PACKAGE_NAME=$2

# Enter lambda dir
pushd ${LAMBDA_DIR}

# Create a temporary directory
TEMP_DIR=`mktemp -d`

# Small workaround for MacOS users
cat >${TEMP_DIR}/setup.cfg<<EOL
[install]
prefix=
EOL

# Install the dependencies
pip3 install -r requirements.txt -t ${TEMP_DIR}

# Add the actual code
cp *.py ${TEMP_DIR}

# Exit lambda dir
popd

# Finally let's bundle this
pushd ${TEMP_DIR}
zip -r ${PACKAGE_NAME}.zip ./*
popd

# Copy the tmp file back to the dist directory so it can be uploaded
cp ${TEMP_DIR}/${PACKAGE_NAME}.zip dist/
