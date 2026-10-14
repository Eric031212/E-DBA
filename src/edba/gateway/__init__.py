"""A self-contained stand-in for the campus systems and the bank used in the course.

The v3 project talked to a lab server (``http://172.16.160.88:8001/hw/...``)
that no longer exists. This gateway serves the same contract with synthetic
data so E-DBA runs end to end anywhere. It is mounted at ``/gateway`` in dev
and can run on its own: ``uvicorn edba.gateway.app:app --port 8001``.
"""
