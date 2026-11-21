# Thin wrapper: every target delegates to the cross-platform runner scripts/dev.py.
# Windows without make: run `uv run scripts/dev.py <target>` instead.
RUN := uv run scripts/dev.py

.PHONY: setup dev test lint verify format gen-client check-client e2e migrate seed demo-reset demo-check diagrams test-report report
setup dev test lint verify format gen-client check-client e2e migrate seed demo-reset demo-check diagrams test-report report:
	@$(RUN) $@
