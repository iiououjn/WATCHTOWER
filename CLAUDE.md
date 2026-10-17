# Watchtower

## Run report
run N | job <id> | PASS | FAIL at F<n> | PENDING-SIGNOFF | OBJECTION | attempt k/max | tests N
cause: <one line>
evidence: <command or log path>
next: <one-line recommendation>
need: <owner action + exact command, or none>
Merge: "merged <sha> tag <tag>, <N> tests".
Sign-off requests include the evidence line and the diagnosis path.
Phase detail goes in the committed plan doc; the ledger is working notes only.
Never approve/reject sign-offs for the owner.
