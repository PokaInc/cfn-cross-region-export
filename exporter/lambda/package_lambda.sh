#!/bin/bash

# Create a temporary directory
TEMP_DIR=`mktemp -d`

# Small workaround for MacOS users
cat >$TEMP_DIR/setup.cfg<<EOL
[install]
prefix=
EOL

# Install the dependencies
pip3 install -r exporter/lambda/requirements.txt -t $TEMP_DIR

# Add the actual code
cp exporter/lambda/cross_region_import_replication.py $TEMP_DIR

# Finally let's bundle this
pushd $TEMP_DIR
zip -r cross_region_import_replication.zip ./*
popd

# Copy the tmp file back to the dist directory so it can be uploaded
cp $TEMP_DIR/cross_region_import_replication.zip dist/
