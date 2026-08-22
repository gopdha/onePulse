**OnePulse — DevOps Setup**

*Step 9 of 10 \| CI/CD Pipelines & Environments \| Ref: OnePulse PRD
v1.0*

This implements what Physical Architecture and Low-Level Design already
specified — Azure DevOps Pipelines, three environments, and the two
mandatory gates. No new design decisions are made here; every stage
below exists because a prior step required it.

# 1. Pipeline Structure

Every service uses the same stage sequence, defined once as a shared
template and referenced by each service's own pipeline — avoiding eleven
slightly-different, independently-drifting pipeline definitions.

|                        |                                            |                                                                                                                                                                                                    |
|------------------------|--------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Stage**              | **Runs When**                              | **Purpose**                                                                                                                                                                                        |
| Build & Unit Test      | Every commit                               | Lint, unit tests, container image build and push to Azure Container Registry.                                                                                                                      |
| Migration Verification | Only if the change touches schema          | See Section 2.1 — the gate that closes the proof of concept's real, repeated migration-drift incident.                                                                                             |
| Cost Regression Gate   | Only if the service calls a language model | See Section 2.2 — the gate that would have caught the proof of concept's real 10x cost anomaly before merge, not after.                                                                            |
| Deploy to Development  | On successful build                        | Automatic, no approval required.                                                                                                                                                                   |
| Deploy to Staging      | After Development succeeds                 | Automatic, no approval required.                                                                                                                                                                   |
| Deploy to Production   | After Staging succeeds                     | Requires a configured Azure DevOps environment approval — a human confirms promotion, matching this project's standing principle that nothing significant proceeds without an explicit checkpoint. |

  

# 2. The Two Mandatory Gates

## 2.1 Migration Verification

A migration tool reporting success is not, by itself, evidence a change
actually took effect — this exact gap caused two real, separate
incidents in the proof of concept. The gate re-queries the live database
directly after migrating:

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.11in 0.14in"><p>python
migrate.py --target $(targetEnvironment)</p>
<p>python verify_migration.py --target $(targetEnvironment)</p>
<p># verify_migration.py queries information_schema.columns (or</p>
<p># information_schema.table_constraints for a new CHECK
constraint)</p>
<p># directly against the live database, and fails the build if the</p>
<p># expected change is not actually present — the same technique
that</p>
<p># caught both real migration-drift incidents in the proof of
concept,</p>
<p># now a standing, automated gate rather than something discovered</p>
<p># by a failure downstream.</p></td>
</tr>
</tbody>
</table>

## 2.2 Cost Regression Gate

Applies only to services that call Microsoft Foundry. Each runs a fixed
reference scenario and compares real, measured cost against the last
known-good baseline:

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.11in 0.14in"><p>python
run_reference_scenario.py --service feature-investigation</p>
<p>python compare_cost_baseline.py --threshold-pct 20</p>
<p># Fails the build if real token or dollar cost on the fixed
reference</p>
<p># scenario exceeds the stored baseline by more than 20%. This is
the</p>
<p># gate that would have caught the proof of concept's real 10x
cost</p>
<p># anomaly at merge time, instead of on the system's first live
trace</p>
<p># weeks later.</p></td>
</tr>
</tbody>
</table>

# 3. Representative Pipeline Definition

One real Azure Pipelines YAML, illustrating the full sequence for an
AI-calling, schema-touching service:

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.11in 0.14in"><p>trigger:</p>
<p>branches: { include: [ main ] }</p>
<p>paths: { include: [ services/feature-investigation/* ] }</p>
<p>variables:</p>
<p>- group: onepulse-common-secrets # Key Vault-linked; no literal
secrets in YAML</p>
<p>stages:</p>
<p>- stage: Build</p>
<p>jobs:</p>
<p>- job: LintAndUnitTest</p>
<p>steps:</p>
<p>- script: pytest -k "not live"</p>
<p>- task: Docker@2</p>
<p>inputs:</p>
<p>command: buildAndPush</p>
<p>containerRegistry: onepulse-acr-connection</p>
<p>repository: feature-investigation</p>
<p>tags: $(Build.BuildId)</p>
<p>- stage: MigrationVerification</p>
<p>condition: eq(variables['hasSchemaChange'], 'true')</p>
<p>jobs:</p>
<p>- job: VerifyMigrationApplied</p>
<p>steps:</p>
<p>- script: |</p>
<p>python migrate.py --target $(targetEnvironment)</p>
<p>python verify_migration.py --target $(targetEnvironment)</p>
<p>- stage: CostRegressionGate</p>
<p>jobs:</p>
<p>- job: CheckCostRegression</p>
<p>steps:</p>
<p>- script: |</p>
<p>python run_reference_scenario.py --service feature-investigation</p>
<p>python compare_cost_baseline.py --threshold-pct 20</p>
<p>- stage: DeployProduction</p>
<p>dependsOn: [ Build, MigrationVerification, CostRegressionGate ]</p>
<p>jobs:</p>
<p>- deployment: DeployToProduction</p>
<p>environment: onepulse-production # approval gate configured here</p>
<p>strategy:</p>
<p>runOnce:</p>
<p>deploy:</p>
<p>steps:</p>
<p>- task: KubernetesManifest@1</p>
<p>inputs: { action: deploy, namespace: onepulse-production }</p></td>
</tr>
</tbody>
</table>

  

# 4. Environments

|                 |                     |                 |                                         |
|-----------------|---------------------|-----------------|-----------------------------------------|
| **Environment** | **AKS Namespace**   | **Neon Branch** | **Approval Required**                   |
| Development     | onepulse-dev        | dev             | No                                      |
| Staging         | onepulse-staging    | staging         | No                                      |
| Production      | onepulse-production | main            | Yes — Azure DevOps environment approval |

Each Neon branch is a real, isolated copy of the schema — a migration is
proven safe in Development and Staging before ever touching Production's
branch, and the Migration Verification gate runs independently in every
environment it is promoted to, not just once.

# 5. Secrets & Identity

No pipeline references a literal secret value. The Azure DevOps service
connection to AKS uses workload identity federation, not a stored
credential. Application-level secrets (the Azure DevOps connector's own
credentials, database connection details) are referenced through a Key
Vault-linked variable group, resolved at deploy time — directly closing
the credential-exposure risk observed multiple times during interactive
development of the proof of concept.

  

# 6. Deferred Enhancement: Canary Rollout

Decided: not built for MVP. Production promotion remains all-or-nothing,
gated by human approval, for the current scale and risk profile. This is
a deliberate Now/Next/Later call, consistent with the same
prioritization discipline applied to the PRD — not an oversight, and not
silently dropped.

Concrete specification, so this can be built later without re-deriving
the reasoning:

|                        |                                                                                                                                                                                                                                                                             |
|------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Step**               | **Behavior**                                                                                                                                                                                                                                                                |
| 1\. Canary deploy      | New version deployed to one real tenant (or a fixed small traffic percentage), not all of Production.                                                                                                                                                                       |
| 2\. Observation window | A fixed period (for example, 30 minutes) where the canary slice is watched specifically for error rate, latency, and cost-per-cycle against baseline — reusing the same comparison logic already built for the pre-merge Cost Regression Gate, now applied to live traffic. |
| 3\. Automatic decision | If the canary stays healthy, expand to full Production automatically. If it regresses, roll back automatically — the canary tenant is reverted and full rollout never happens.                                                                                              |

The concrete motivation for building this eventually: the proof of
concept's real 10x cost anomaly, had it shipped to a genuine
multi-tenant Production system without a canary stage, would have spiked
every tenant's cost simultaneously rather than being caught on a single
canary tenant first. This is the specific failure mode this enhancement
exists to contain — worth building once real multi-tenant scale makes
that risk concrete, not before.
