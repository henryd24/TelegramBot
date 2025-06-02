CONDA_ENV=telegrambot

PYTHON_VERSION=3.11

REQUIREMENTS=requirements.txt

venv:
	@if [ ! -d ".venv" ]; then \
		echo "🔧 Creando entorno virtual .venv con Python $(PYTHON_VERSION)..."; \
		python$(PYTHON_VERSION) -m venv .venv; \
	else \
		echo "✅ Entorno virtual .venv ya existe."; \
	fi
	@echo "📢 Ejecuta: source .venv/bin/activate"

conda:
	@if ! conda info --envs | grep -q "^$(CONDA_ENV)\s"; then \
		echo "🔧 Creando entorno conda '$(CONDA_ENV)' con Python $(PYTHON_VERSION)..."; \
		conda create -n $(CONDA_ENV) python=$(PYTHON_VERSION) -y; \
	else \
		echo "✅ El entorno conda '$(CONDA_ENV)' ya existe."; \
	fi
	@echo "📢 Ejecuta: conda activate $(CONDA_ENV)"

install:
	@echo "📦 Instalando dependencias desde $(REQUIREMENTS)..."
	@.venv/bin/pip install -r $(REQUIREMENTS) || \
	( echo "⚠️  Activa el entorno antes de instalar: source .venv/bin/activate" && false )

clean:
	@echo "🧹 Eliminando entorno virtual .venv..."
	rm -rf .venv

clean-conda:
	@echo "🧹 Eliminando entorno conda $(CONDA_ENV)..."
	conda remove -n $(CONDA_ENV) --all -y

.PHONY: venv conda install clean clean-conda