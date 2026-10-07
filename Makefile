# PISI task runner. Run `make help` to see targets.
.PHONY: help run test lint install uninstall clean tail-log

help:  ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

run:  ## launch PISI
	./run.sh

test:  ## run the test suite (headless Qt)
	python3 -m pytest

lint:  ## lint with ruff (CI runs this too)
	@command -v ruff >/dev/null 2>&1 && ruff check companion scripts tests \
	  || echo "ruff not installed — skipping (pip install ruff to enable)"

install:  ## install the launcher + autostart entry
	./install.sh

uninstall:  ## remove the launcher + autostart entry
	./uninstall.sh

tail-log:  ## follow the runtime log
	tail -f ~/.local/share/desktop-companion/companion.log

clean:  ## remove caches and build cruft
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache
