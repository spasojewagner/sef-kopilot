# A measure is only as good as its labels: golden sets and the reference

An evaluation answers "how well does the system do its job?" with a number. Three things make
the number mean something.

**1. Labels that do not come from the system.** A golden set pairs each input with what the
system must give for it. If the expected answers were copied from the system's own output, the
measure is 100 % by construction and says nothing: the system agrees with itself. The labels
must come from somewhere else: the publisher of a document ("this example is valid"), the
person who made a test case ("this invoice has a wrong check digit in its PIB"), or a person
who read the answer ("this citation is relevant").

```
input ──► system ──► answer ─┐
                             ├─► compare ──► measure
input ──► label (elsewhere) ─┘
```

**2. A reference to disagree with.** Where a trusted implementation exists, run it on the
same inputs: the measure is then "do we give the same verdict?", over every input, not only the
labelled ones. For EN 16931 the reference is the published artefacts applied as published (the
schema, then CEN's Schematron); where SEF Kopilot deliberately differs (Serbian set-asides,
the calculation rules in Python), agreement shows the differences change no verdict.

**3. Every number names its cases.** "98.3 %" invites a shrug; "`faktura-sa-prilogom.xml`:
SRB-009 not reported" invites a fix. Here, the first run's miss was in the label, not the
validator: that example is not schema-valid, so no rule after the schema runs on it.

Two kinds of measure, two directions: a **share** (agreement, detection) should be high, a
**rate** (false accepts, false rejects) low. Which error is worse depends on the job: a false
accept lets an invoice through that SEF will refuse, so its threshold is 0.

A deterministic system allows thresholds of 100 % and 0 %: a miss is a defect. A language model
does not, so its thresholds (≥ 80 % repairs, ≥ 90 % relevant citations) leave room for its
variance, and its answers are recorded once and replayed, so that CI measures the same answers
every time.
