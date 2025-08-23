SHELL := /bin/bash

.PHONY: help install deps run clean

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  help		Show this help message"
	@echo "  install	Create virtual environment and install dependencies"
	@echo "  deps		Compile pyproject.toml to requirements.txt"
	@echo "  run		Run the application"
	@echo "  clean		Remove virtual environment and compiled files"

install: .venv/pyvenv.cfg

.venv/pyvenv.cfg: pyproject.toml
	@uv venv
	@touch .venv/pyvenv.cfg
	@make deps
	@uv pip sync requirements.txt


deps:
	@echo "Compiling dependencies..."
	@uv pip compile pyproject.toml -o requirements.txt

run: install
	@echo "Starting application..."
	@uv run python main.py

clean:
	@rm -rf .venv
	@rm -f requirements.txt
