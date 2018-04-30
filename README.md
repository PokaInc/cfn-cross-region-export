# cfn-cross-region-export

### Exporter / Importer

The project is divided in 2 parts; the **Exporter** and the **Importer**. Only one **Exporter** stack is needed per 
region you want outputs to be imported from. The **Importer** stack on the other hand, need to be instantiated for each 
region you want to import outputs from.

Here's an example use-case:
Let's say you are creating some resources in the _ca-central-1_ region and you need to import values from the
_us-east-1_ and _eu-west-1_ regions. You'll need to first provision the **Exporter** stack in both _us-east-1_ and 
_eu-west-1_ region. You'll then have to provision 2 **Importer** stacks in the _ca-central-1_ region, each targeting a 
specific region.

### Installation

#### Exporter

Start by deploying the **Exporter**

```
export AWS_DEFAULT_REGION=<EXPORTER_REGION>
make deploy-exporter SENTRY_DSN=https://...@sentry.io/... 
```

#### Importer

You can find the `CROSS_STACK_REF_TABLE_ARN` in the output section of the **Exporter** stack we've just deployed.

```
export AWS_DEFAULT_REGION=<IMPORTER_REGION>
make deploy-importer CROSS_STACK_REF_TABLE_ARN=...
```

### Usage 

```
Resources: 
  Importer:
    Type: Custom::CrossRegionImporter
    Properties:
      ServiceToken: !ImportValue 'us-east-1:CrossRegionImporterServiceToken'
      ExportNames: 'xyz-export'
      
  TestImport:
    Type: "AWS::SSM::Parameter"
    Properties:
      Type: 'String'
      Value: !GetAtt 'Importer.xyz-export'

```
