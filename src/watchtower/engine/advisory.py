"""Errors an advisory agent (HR, QA office, Build office, memo answers) may hit. Those roles add value but
are not required, so on these errors their step is skipped instead of pausing the whole job. A busy agent slot
(SchedulerBusy) is NOT one of them (8b): another job holds the model, so the step pauses rather than silently
running this job with fewer reviewers."""
from watchtower.engine.model_socket import BadModelOutput, LowMemory, ModelUnavailable

ADVISORY_ERRORS = (BadModelOutput, LowMemory, ModelUnavailable)
