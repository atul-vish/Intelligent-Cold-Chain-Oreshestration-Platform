# Cold Chain Logistics Operations

## Sample - Standard Operating Procedure (SOP): Cold-Chain, Transit & Logistics Incident Management

**Version:** 2.0 \| **Effective Date:** October 2026 \|
**Confidentiality:** Internal Operations Only

---

## 1. Temperature Control & Spoilage Prevention (Cold-Chain)

All refrigerated fleet operations must maintain continuous IoT
temperature compliance to protect temperature-sensitive cargo and
prevent spoilage.

- **Fresh Perishables:** `IOT_TEMP_VAL_C` must remain between **0.0°C
  and 4.0°C** unless a shipment-specific handling instruction defines
  a different approved range.
- **Critical Temperature Breach:** If `IOT_TEMP_VAL_C` exceeds
  **4.0°C**, declare a **cold-chain breach** and initiate immediate
  mitigation.
- **Low-Temperature Exception:** Temperatures below the approved
  shipment range must also be treated as an exception and reviewed
  against the cargo-specific SOP.
- **Mitigation Protocol:** The dispatcher must immediately contact the
  driver and verify the refrigeration/auxiliary cooling unit. Confirm
  whether the temperature can be restored without compromising cargo
  integrity.
- **Extended Breach:** If the temperature remains outside the approved
  range and the shipment cannot be stabilized, escalate to the
  Logistics Manager and identify the nearest approved cold-storage
  facility.
- **Documentation:** Record the observed temperature, timestamp,
  vehicle/shipment reference, action taken, and final disposition.

---

## 2. Route Congestion & Diversion Tactics

Route and port congestion can materially affect delivery SLAs, product
quality, and refrigeration exposure.

- **Congestion Indicator:** Use `PRT_CNG_LVL` as the operational
  congestion indicator.
- **High Congestion Trigger:** If `PRT_CNG_LVL` exceeds **7.0**,
  standard routing should be suspended and the shipment reviewed for
  diversion.
- **Mitigation Protocol:** Do not allow a high-risk refrigerated
  shipment to remain unnecessarily idle in a severe congestion zone.
  Evaluate approved alternate routes, cross-docking locations, or
  cold-storage facilities.
- **ETA Impact:** Recalculate ETA and delay probability after any
  diversion.
- **Temperature Consideration:** Any route decision must account for
  remaining refrigeration endurance and expected temperature exposure.
- **Escalation:** If congestion is combined with a high-risk
  classification or significant delay probability, escalate to the
  Tier 2 Logistics Manager.

---

## 3. Risk Classification Triggers

Risk classification must combine the shipment's operational risk with
predicted delay and route conditions.

- **High-Risk Shipment:** Any shipment where
  `RISK_CLS_TXT = High Risk` requires enhanced operational monitoring.
- **High-Risk + Delay Trigger:** A **High Risk** shipment combined
  with `DELAY_PROB_DEC > 0.65` must be escalated to the **Tier 2
  Logistics Manager**.
- **Critical Combination:** High-risk classification combined with a
  temperature breach, severe congestion, or rapidly increasing delay
  probability should be treated as a priority incident.
- **Risk Reassessment:** Recalculate/review risk whenever material
  changes occur in temperature, route conditions, congestion, ETA, or
  cargo condition.
- **Human Validation:** AI-generated risk classifications are
  decision-support outputs and must be validated by an authorized
  operations user before irreversible operational action.

---

## 4. Delay Probability & SLA Protection

Delay probability must be used as an early-warning signal rather than as
a standalone operational decision.

- **Normal:** `DELAY_PROB_DEC <= 0.65` --- continue standard
  monitoring unless another incident trigger is present.
- **Elevated:** `DELAY_PROB_DEC > 0.65` --- review shipment status and
  expected ETA.
- **High-Risk Escalation:** `RISK_CLS_TXT = High Risk` AND
  `DELAY_PROB_DEC > 0.65` --- escalate to Tier 2 Logistics Manager.
- **Operational Review:** Where delay probability is elevated, review
  congestion, route risk, temperature status, and cargo condition
  before selecting mitigation.
- **Customer SLA:** If the predicted delay threatens an agreed
  customer SLA, initiate the applicable customer communication
  procedure.

---

## 5. Route Risk Monitoring

`RT_RSK_IDX` must be considered when evaluating route safety and
delivery reliability.

- **Route Risk Review:** A rising `RT_RSK_IDX` should trigger
  additional monitoring of the affected shipment.
- **Combined Risk:** Route risk should not be evaluated in isolation.
  Consider congestion, delay probability, temperature, and cargo
  condition together.
- **Diversion Decision:** If route conditions materially increase the
  probability of SLA failure or cargo exposure, evaluate an approved
  alternate route.
- **No Blind Rerouting:** The system must not automatically select an
  unapproved route solely from an AI recommendation.
- **Human Approval:** Major diversions must follow the customer's
  operational authorization policy.

---

## 6. Cargo Condition & Handling

Cargo condition must remain a first-class operational signal.

- **Cargo Condition:** Use `CGO_COND_CD` to identify and track
  cargo-condition exceptions.
- **Condition Degradation:** Any deterioration in cargo condition must
  be reviewed together with temperature history and transit duration.
- **Temperature + Cargo Incident:** A cargo-condition exception
  combined with a temperature breach must be escalated for immediate
  operational review.
- **Handling:** Do not continue standard delivery handling when the
  cargo may have been compromised until an authorized operator
  determines the appropriate disposition.
- **Evidence:** Preserve the relevant sensor readings, timestamps,
  shipment identifiers, and operational decisions.

---

## 7. IoT Data Integrity & Sensor Exceptions

Operational decisions must be based on trustworthy data.

- **Source Data:** `SYS_INGEST_FLAG` must be reviewed when validating
  whether a record was successfully ingested.
- **Missing Data:** Missing or stale IoT measurements must not be
  treated as proof of safe operating conditions.
- **Sensor Anomaly:** Sudden impossible values, prolonged unchanged
  readings, or unexpected gaps should be flagged for investigation.
- **Fallback:** If sensor reliability is uncertain, use approved
  backup operational procedures and request manual verification from
  the driver or dispatcher.
- **Auditability:** Preserve the original source record; do not
  overwrite raw telemetry merely to resolve an anomaly.

---

## 8. Incident Priority Matrix

---

Priority Trigger Required Action

---

**P1 --- Critical** Temperature breach with Immediate dispatcher
potential cargo action + Tier 2
compromise; or multiple escalation
critical risk signals

**P2 --- High** High Risk + Tier 2 Logistics
`DELAY_PROB_DEC > 0.65`; Manager review
severe congestion;  
 significant route risk

**P3 --- Medium** Elevated delay Operations review and
probability, route-risk enhanced monitoring
increase, or non-critical  
 data anomaly

**P4 --- Low** Minor anomaly with no Record, monitor,
immediate cargo/SLA impact resolve through normal
workflow

---

> Priority may be increased when multiple conditions occur
> simultaneously.

---

## 9. Standard Incident Response Workflow

For every operational incident, follow:

```text
Detect
  ↓
Validate
  ↓
Classify Risk
  ↓
Assess Cargo / Temperature / Route Impact
  ↓
Select Mitigation
  ↓
Human Approval Where Required
  ↓
Execute Action
  ↓
Recalculate ETA / Risk
  ↓
Monitor Recovery
  ↓
Close & Document
```

### Step 1 --- Detect

Identify the triggering condition from IoT telemetry, logistics data,
operational users, or system-generated alerts.

### Step 2 --- Validate

Confirm that the signal is not caused by a data-ingestion, sensor, or
system error.

### Step 3 --- Classify

Determine the applicable priority and risk classification.

### Step 4 --- Assess

Evaluate:

- Temperature exposure
- Cargo condition
- Delay probability
- Route risk
- Congestion
- ETA/SLA impact

### Step 5 --- Mitigate

Select the least disruptive approved mitigation that protects cargo and
SLA performance.

### Step 6 --- Escalate

Escalate according to the priority matrix and customer escalation
policy.

### Step 7 --- Monitor

Continue monitoring until the triggering condition is resolved or
ownership is transferred.

### Step 8 --- Close

Record the incident, action taken, outcome, and any follow-up
requirement.

---

## 10. Dispatcher Response Protocol

When an incident is detected, the dispatcher must:

1.  Identify the shipment and vehicle.
2.  Verify the latest telemetry timestamp.
3.  Confirm temperature and cargo condition.
4.  Review delay probability.
5.  Review route/congestion risk.
6.  Contact the driver where operationally required.
7.  Select an approved mitigation.
8.  Escalate according to severity.
9.  Record the action.
10. Continue monitoring until recovery.

The dispatcher must not rely on a single AI-generated recommendation
without checking the underlying operational signals.

---

## 11. Cold-Storage Diversion Protocol

A refrigerated shipment may require diversion when continued transit
creates unacceptable cargo or SLA risk.

Diversion should be evaluated when:

- Temperature cannot be stabilized.
- Severe congestion creates excessive idle time.
- Predicted delay materially threatens cargo integrity or SLA.
- Route risk becomes unacceptable.
- Cargo condition begins to deteriorate.

Before diversion:

1.  Identify an approved cold-storage or cross-docking facility.
2.  Confirm capacity and operating availability.
3.  Estimate travel time to the facility.
4.  Compare against current route ETA.
5.  Confirm refrigeration requirements.
6.  Obtain required operational approval.
7.  Record the decision.

---

## 12. AI Decision-Support Rules

The platform may use AI/agentic workflows to analyze operational
information and recommend actions.

The AI layer must:

- Use available source data and approved SOP information.
- Clearly distinguish observations from predictions.
- Provide traceable reasoning/context where supported.
- Avoid inventing missing telemetry.
- Escalate uncertainty when data is insufficient.
- Avoid silently changing source-of-truth operational records.

### Human-in-the-Loop

Human validation is required for:

- Critical cargo decisions
- Major route diversions
- Disposal/rejection decisions
- Customer-impacting escalations
- Actions with irreversible operational consequences

---

## 13. Data Source Priority

When multiple signals are available, use the following principle:

```text
Raw Operational Data
        ↓
Validated Derived Metrics
        ↓
Business Rules / SOP
        ↓
AI Recommendation
        ↓
Authorized Human Decision
```

AI recommendations must not replace the underlying operational source of
truth.

---

## 14. Audit & Incident Documentation

Every P1/P2 incident must record:

- Incident ID
- Date/time detected
- Shipment/vehicle reference
- Trigger condition
- Latest telemetry
- Temperature status
- Cargo condition
- Delay probability
- Route/congestion status
- Risk classification
- Action taken
- Approver/escalation owner
- Final outcome
- Resolution timestamp

Example:

```text
Incident ID: INC-YYYYMMDD-XXXX
Priority: P2
Shipment:
Vehicle:
Detected At:
Trigger:
Temperature:
Delay Probability:
Risk Classification:
Route Risk:
Congestion:
Mitigation:
Escalated To:
Approved By:
Resolved At:
Final Outcome:
```

---

## 15. Communication Protocol

### Internal Operations

Communicate immediately for P1 and P2 incidents.

Communication should include:

```text
What happened?
Which shipment is affected?
What is the operational impact?
What action has been taken?
What is the current ETA/risk?
Who owns the next action?
```

### Customer Communication

Customer-facing communication must use approved channels and approved
messaging procedures.

Do not communicate unverified AI predictions as confirmed operational
facts.

---

## 16. Incident Closure Criteria

An incident can be closed when:

- The triggering condition is resolved or formally accepted.
- Cargo condition is confirmed or disposition is documented.
- Temperature is within the approved range where applicable.
- ETA/SLA impact is understood.
- Required escalation has been completed.
- All actions are documented.
- Follow-up actions are assigned.

If the issue is unresolved but operational ownership has transferred,
close the incident only after documenting the transfer and open action.

---

## 17. Post-Incident Review

P1 incidents require a post-incident review.

Review:

1.  What triggered the incident?
2.  Was the alert timely?
3.  Was the data accurate?
4.  Was the SOP followed?
5.  Was escalation timely?
6.  Was the mitigation effective?
7.  Was cargo protected?
8.  Was SLA impact minimized?
9.  Did the AI recommendation help or create risk?
10. What preventive action is required?

Corrective actions must be tracked to completion.

---

## 18. Operational Guardrails

The following rules are mandatory:

- Never ignore a confirmed cold-chain breach.
- Never treat missing telemetry as proof that cargo is safe.
- Never expose customer credentials or operational secrets.
- Never modify raw operational data to hide an incident.
- Never make a major irreversible decision solely from an AI
  recommendation.
- Never bypass required human escalation.
- Always preserve incident evidence.
- Always reassess risk after a material operational change.

---

## 19. Quick Reference --- Trigger Rules

```text
IF IOT_TEMP_VAL_C > 4.0°C
    → Cold-chain breach
    → Contact driver / verify cooling
    → Assess cold-storage diversion
    → Escalate if unresolved

IF PRT_CNG_LVL > 7.0
    → Severe congestion
    → Review route/diversion
    → Recalculate ETA and delay probability

IF RISK_CLS_TXT = "High Risk"
   AND DELAY_PROB_DEC > 0.65
    → Tier 2 Logistics Manager escalation

IF temperature breach
   AND cargo condition degradation
    → Priority operational review

IF telemetry is missing/stale
    → Do not assume safe conditions
    → Validate manually / investigate sensor

IF multiple risk signals occur together
    → Increase incident priority
    → Human operational review
```

---

## 20. FDE / System Integration Notes

The AI platform should consume this SOP as an operational policy source.

Recommended retrieval metadata:

```text
document_type: operational_sop
domain: cold_chain_logistics
version: 2.0
effective_date: 2026-10
confidentiality: internal
```

Recommended policy entities:

```text
temperature_threshold
congestion_threshold
delay_probability_threshold
risk_escalation_rule
cargo_condition_rule
incident_priority
mitigation_protocol
escalation_owner
```

When the SOP is updated, the indexed/retrieval copy must be versioned so
that the AI system does not combine obsolete and current policies
without an explicit policy-resolution strategy.

---

## 21. SOP Change Control

---

Version Effective Date Change Owner

---

1.0 Initial Initial Operations
operational SOP

2.0 October 2026 Cold-chain, Operations / FDE
congestion, risk,  
 delay and AI  
 decision-support  
 procedures

---

Any threshold change must be approved by the authorized
business/operations owner before being promoted to the production
knowledge base.

---

## 22. Approval

**Operations Owner:**
\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Logistics Manager:**
\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**FDE / Technical Owner:**
\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Effective Date:**
\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Review Date:**
\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Approved Version:**
\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

---

# Document End

**Cold Chain Logistics Operations --- Standard Operating Procedure
v2.0**
