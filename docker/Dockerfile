FROM python:3.12-slim-bookworm
RUN apt-get -o Acquire::Retries=5 update && apt-get -o Acquire::Retries=5 install -y --no-install-recommends libreoffice-writer libreoffice-impress libreoffice-calc poppler-utils fonts-noto-cjk fonts-dejavu-core curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir python-docx==1.2.0 openpyxl==3.1.5 pypdf==6.1.1 reportlab==4.4.4 pillow==11.3.0 pandas==2.3.3 python-pptx==1.0.2
RUN useradd --create-home --uid 1000 worker
USER worker
WORKDIR /task
CMD ["sleep", "infinity"]
