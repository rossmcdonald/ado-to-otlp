# ado-to-otlp

Retrieve logs from Azure DevOps and forward them to ServiceNow Cloud Observability

## Running

This script requires:

- A recent version of python3 along with the python [requests library](https://requests.readthedocs.io/en/latest/).
- An [ADO Personal Access Token](https://learn.microsoft.com/en-us/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate?toc=%2Fazure%2Fdevops%2Forganizations%2Fsecurity%2Ftoc.json&view=azure-devops&tabs=Windows) with **Build (Read)** access, along with a target ADO organization.
- A ServiceNow Cloud Observability [access token](https://docs.lightstep.com/docs/create-and-manage-access-tokens).

To install all necessary dependencies, run:

```sh
# optional, but a good practice
python3 -m venv venv && source venv/bin/activate

# install dependencies
pip3 install -r requirements.txt
```

With the dependencies installed, set the necessary environment variables and run the script with:

```sh
# ADO PAT with build:read access
export ADO_ACCESS_TOKEN="XXXXX"
# ADO organization name, which can be retrieved from ADO URL: https://dev.azure.com/my_organization_name
export ADO_ORGANIZATION="my_organization_name"

# ServiceNow Cloud Observability access token
export CLOUDOBS_ACCESS_TOKEN="XXXXX"

python3 main.py
```

Once started, the script will connect to ADO and wait for pipeline runs that have executed **since the script was started**. Historical runs will not be fetched.
