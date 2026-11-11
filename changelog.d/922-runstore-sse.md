Added
The read-only run store streams a run's status and new rounds over Server-Sent
Events at `GET /api/runs/<id>/events`, with `Last-Event-ID` resume, so a host
panel or platform can follow a run without polling (#922).
