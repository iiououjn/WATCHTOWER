from __future__ import annotations

from pathlib import Path

from watchtower.evidence import no_host_run
from watchtower.floors.f4_qa_deploy.releases import manifest_problems
from watchtower.tower.errors import AppRejected, NeedsOwner
from watchtower.tower.spec_steps import spec_text

OWNED_NOTE = ("Note: the tower wrote the web server; a local AI wrote store.py and its tests, tested only "
              "inside the sandbox. Read store.py before you approve it. store.py was asked to keep data in memory: "
              "it is likely lost when the app stops.\n")  # 7b (run 34): the spec may promise more
CODER_NOTE = ("Note: written by a local AI and tested only inside the sandbox — untested on your Mac. Read the "
              "code before you approve it.\n")
TESTS_NOTE = ("Note: the coder's own unit tests fail (advisory); the tower's start, QA and security checks "
              "passed.\n")


def deploy_line(job_id: str) -> str:
    return f"Deploy it isolated, with no internet: watchtower deploy {job_id}"


def release_answer(job_id: str, root: Path, files: list[str], owned: bool, tests_ok: bool) -> str:
    """What the owner reads when the app is ready. 8a (D-H1): never a host-run line; AI code runs only in Docker."""
    return (f"App ready in {root}\nFiles: {', '.join(files)}\n" + (OWNED_NOTE if owned else CODER_NOTE)
            + ("" if tests_ok else TESTS_NOTE) + deploy_line(job_id))


class SignoffSteps:
    """Lifecycle: final audit → CEO recommendation → owner sign-off → release (mixed into TowerPipeline, which owns
    `_approvals`, `_releases` and `_bus`). Nothing is released until the owner signs off; 8a (D-M1): --yes covers
    the spec only, never this step, whatever the CEO says."""

    def _signoff_request(self, data: dict) -> dict:
        return {"signoff_id": self._approvals.request(data["job_id"], "signoff", self._signoff_summary(data))}

    def _signoff_summary(self, data: dict) -> str:
        ceo = data.get("ceo") or {}
        after = f"After you approve: watchtower deploy {data['job_id']}  (isolated, no internet)"
        answer = no_host_run(data["answer"]).replace(deploy_line(data["job_id"]), after)  # release needs sign-off
        verdict = {True: "approve", False: "REJECT"}.get(ceo.get("approve"), "no clear view")
        spec = spec_text(data["spec"]) + "\n\n" if data.get("auto_approve") else ""  # the owner never saw it
        note = f" — {ceo['note']}" if ceo.get("note") else ""
        return (f"{answer}\n\n{spec}Evidence:\n{data['evidence']}\n\nCEO recommends: {verdict}{note}"
                + (f"\n{data['objection']}" if data.get("objection") else ""))

    def _signoff(self, data: dict) -> dict:
        signoff_id = data.get("signoff_id")
        if signoff_id is None:  # 8a: a checkpoint saved when --yes skipped the sign-off; the owner signs it now
            found = self._approvals.latest(data["job_id"], "signoff")
            signoff_id = found.id if found else self._approvals.request(data["job_id"], "signoff",
                                                                        self._signoff_summary(data))
        status = self._approvals.get(signoff_id).status
        if status == "rejected":
            raise AppRejected("app rejected by owner")
        if status != "approved":
            raise NeedsOwner(f"app awaiting your sign-off; review it, then: watchtower approve {data['job_id']}")
        if not data.get("manifest"):
            raise NeedsOwner("this job was checkpointed before release pinning; run it again with: watchtower run")
        problems = manifest_problems(Path(data["workspace"]), data["manifest"])
        if problems:  # what ships is exactly what passed QA and the gate, or nothing
            raise NeedsOwner("workspace changed after QA; nothing released: " + "; ".join(problems[:3])
                             + f". Restore those files, then: watchtower resume {data['job_id']}")
        if self._releases is not None:
            self._releases.record_manifest(data["job_id"], data["entry"], data["manifest"])
        self._bus.publish("app.released", {"entry": data["entry"], "files": len(data["files"])}, data["job_id"])
        return {"released": True, "answer": no_host_run(data["answer"])}  # a pre-8a checkpoint's answer too
