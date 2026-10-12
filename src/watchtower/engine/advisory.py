"""Errors an advisory agent (HR, QA office, Build office, memo answers) may hit. Those roles add value but
are not required, so on these errors their step is skipped instead of pausing the whole job."""
from watchtower.engine.model_socket import BadModelOutput, LowMemory, ModelUnavailable
from watchtower.engine.scheduler import SchedulerBusy

ADVISORY_ERRORS = (BadModelOutput, LowMemory, ModelUnavailable, SchedulerBusy)
