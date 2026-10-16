PYTHON ?= python3

.PHONY: test golden examples repl clean

test:
	$(PYTHON) -m unittest discover -s tests -t tests

# Regenerate golden outputs after an intentional change; review with `git diff`.
golden:
	@for f in examples/*.lum; do bin/lumen "$$f" > "tests/golden/$$(basename "$$f" .lum).out"; done
	@echo "golden files updated"

examples:
	@for f in examples/*.lum; do echo "== $$f"; bin/lumen "$$f"; echo; done

repl:
	@bin/lumen

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
