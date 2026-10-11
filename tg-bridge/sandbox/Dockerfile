FROM python:3.12-slim
RUN pip install --no-cache-dir pandas==2.2.3 openpyxl==3.1.5 xlrd==2.0.1 numpy==2.1.3 pypdf==5.1.0
RUN useradd -m -u 1000 sandbox
USER sandbox
WORKDIR /data
