"""Step Functions waitForTaskToken target. Opens gate A: stores the token and the sha of the scope being approved."""
from common import audit, get_run, table


def handler(event, _ctx):
    run_id, gate, token = event["runId"], event["gate"], event["taskToken"]
    subject = get_run(run_id)["artifacts"]["intake"]
    table().put_item(Item={"PK": f"RUN#{run_id}", "SK": f"GATE#{gate}", "taskToken": token,
                           "sha": subject["sha"], "subjectKey": subject["key"]})
    audit(run_id, "system", "gate.opened", {"gate": gate, "sha": subject["sha"]})
