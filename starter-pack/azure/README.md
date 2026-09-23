# Azure components

**Read this first: most of this framework needs no Azure resources at all.**

The evaluation loop runs on Power Platform and your CI system. Azure enters in
exactly three places, and only one of them is required.

| Component | Required? | Why |
|---|---|---|
| **Microsoft Entra app registration** | **Yes** | The only way to get a token for the Power Platform API. See `SETUP.md` step 2. |
| Azure DevOps pipeline | Only if your ALM is in Azure DevOps | `azure-pipelines.yml` here is the equivalent of the GitHub release gate. |
| Azure Key Vault | Recommended at scale | Holds the client secret and the persona connection IDs instead of CI variables. |

Anything beyond this — Functions, Logic Apps, Container Apps — is not needed.
A scheduled GitHub Actions workflow or a Power Automate recurrence flow already
covers unattended execution, at no infrastructure cost.

## Key Vault, if you want it

Once you have more than a handful of personas and environments, the connection
IDs and secrets outgrow CI variables. The GitHub Actions path:

```yaml
- uses: azure/login@v2
  with:
    client-id: ${{ vars.AZURE_CLIENT_ID }}
    tenant-id: ${{ vars.PP_TENANT_ID }}
    subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}

- name: Load evaluation secrets
  uses: azure/get-keyvault-secrets@v1
  with:
    keyvault: kv-copilot-eval
    secrets: 'pp-client-secret, mcs-conn-representative, mcs-conn-manager'
```

Using `azure/login` with **federated credentials** (OIDC) removes the stored
client secret entirely — the preferred pattern for a long-lived pipeline.

## What to name things

| Resource | Suggested name |
|---|---|
| App registration | `sp-copilot-eval-runner` |
| Key Vault | `kv-copilot-eval` |
| Secret: client secret | `pp-client-secret` |
| Secret: persona connection | `mcs-conn-{persona}` |

## Sizing note

Evaluation runs are asynchronous and polled; the runner is idle most of its
wall-clock time. A standard hosted CI runner is more than sufficient — there is
no compute to size and no infrastructure to provision.
